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

"""Tests for RtspHealthMonitor's stall-detection logic.

_check() is called directly rather than through the real GLib timer, so
these run without a GLib main loop or a display.
"""

from __future__ import annotations

from surveillance.ui import rtsp_health
from surveillance.ui.rtsp_health import RtspHealthMonitor


class _FakePlayer:
    """Duck-types the bits of MpvGLArea the monitor touches."""

    def __init__(self) -> None:
        self.time_pos: float | None = None
        self.stop_calls = 0
        self.play_calls: list[str] = []

    def stop(self) -> None:
        self.stop_calls += 1

    def play(self, url: str, **kwargs: object) -> None:
        self.play_calls.append(url)


class TestRtspHealthMonitor:
    def test_first_check_is_baseline_only(self) -> None:
        player = _FakePlayer()
        gave_up: list[str] = []
        monitor = RtspHealthMonitor(player, "rtsp://cam", "Cam A", gave_up.append)
        try:
            assert monitor._check() is True
            assert player.stop_calls == 0
            assert gave_up == []
        finally:
            monitor.stop()

    def test_advancing_time_pos_never_retries(self) -> None:
        player = _FakePlayer()
        gave_up: list[str] = []
        monitor = RtspHealthMonitor(player, "rtsp://cam", "Cam A", gave_up.append)
        try:
            player.time_pos = 1.0
            monitor._check()  # baseline
            for pos in (2.0, 3.0, 4.0):
                player.time_pos = pos
                assert monitor._check() is True
            assert player.stop_calls == 0
            assert gave_up == []
        finally:
            monitor.stop()

    def test_stalled_time_pos_retries_then_gives_up(self) -> None:
        player = _FakePlayer()
        gave_up: list[str] = []
        monitor = RtspHealthMonitor(player, "rtsp://cam", "Cam A", gave_up.append)
        try:
            player.time_pos = 5.0
            monitor._check()  # baseline

            retries = rtsp_health._MAX_CONSECUTIVE_STALLS - 1
            for _ in range(retries):
                assert monitor._check() is True  # not enough stalls yet: retries

            assert player.stop_calls == retries
            assert player.play_calls == ["rtsp://cam"] * retries
            assert gave_up == []

            assert monitor._check() is False  # final stall: gives up
            assert gave_up == ["stalled: no progress"]
        finally:
            monitor.stop()

    def test_calls_on_recovered_once_when_advancing_resumes(self) -> None:
        player = _FakePlayer()
        recovered_calls = 0

        def _on_recovered() -> None:
            nonlocal recovered_calls
            recovered_calls += 1

        monitor = RtspHealthMonitor(
            player, "rtsp://cam", "Cam A", lambda _: None, on_recovered=_on_recovered
        )
        try:
            player.time_pos = 1.0
            monitor._check()  # baseline: never reports recovery
            assert recovered_calls == 0

            player.time_pos = 2.0
            monitor._check()  # first confirmed advance
            assert recovered_calls == 1

            player.time_pos = 3.0
            monitor._check()  # still advancing: not reported again
            assert recovered_calls == 1
        finally:
            monitor.stop()

    def test_none_time_pos_after_baseline_counts_as_stall(self) -> None:
        player = _FakePlayer()
        gave_up: list[str] = []
        monitor = RtspHealthMonitor(player, "rtsp://cam", "", gave_up.append)
        try:
            monitor._check()  # baseline, pos stays None throughout
            monitor._check()
            assert player.stop_calls == 1
        finally:
            monitor.stop()
