# Copyright (c) 2026, Renaud Allard <renaud@allard.it>
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice,
#    this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.


"""Tests for the mpv playback profiles (no GTK or libmpv required)."""

from __future__ import annotations

from typing import Any

from surveillance.ui.mpv_widget import MpvGLArea


class _Recorder:
    """Stands in for the mpv handle, recording every option written."""

    def __init__(self) -> None:
        self.options: dict[str, Any] = {}

    def __setitem__(self, name: str, value: Any) -> None:
        self.options[name] = value


def _applied(*, low_latency: bool, muxed_audio: bool) -> dict[str, Any]:
    """The options one profile writes.

    _apply_playback_options only reads three attributes, so it runs
    against a stand-in rather than a real widget, which would need a GL
    context and libmpv.
    """

    class _Widget:
        def __init__(self) -> None:
            self._mpv = _Recorder()
            self._low_latency = low_latency
            self._muxed_audio = muxed_audio

    widget = _Widget()
    MpvGLArea._apply_playback_options(widget)  # type: ignore[arg-type]
    return widget._mpv.options


class TestPlaybackProfiles:
    def test_every_profile_writes_the_same_options(self) -> None:
        """A slot's widget is reused across protocol switches, so a
        profile that leaves an option unwritten inherits whatever the
        previous stream set. Each profile must state all of them."""
        muxed = _applied(low_latency=False, muxed_audio=True)
        low_latency = _applied(low_latency=True, muxed_audio=False)
        default = _applied(low_latency=False, muxed_audio=False)
        assert set(muxed) == set(low_latency) == set(default)

    def test_muxed_audio_wins_over_low_latency(self) -> None:
        """Documented precedence: a muxed-audio stream is a container,
        not raw NALs, so it must not get the raw-NAL profile."""
        both = _applied(low_latency=True, muxed_audio=True)
        assert both == _applied(low_latency=False, muxed_audio=True)

    def test_default_profile_does_not_cap_the_rtsp_buffer(self) -> None:
        """cache-secs raises the readahead above demuxer-readahead-secs
        whenever the cache is on, so the muxed profile's small value must
        not survive into an RTSP stream on the same widget."""
        default = _applied(low_latency=False, muxed_audio=False)
        muxed = _applied(low_latency=False, muxed_audio=True)
        assert default["cache-secs"] > muxed["cache-secs"]
