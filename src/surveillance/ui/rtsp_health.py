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

"""Health monitoring for plain RTSP live view streams.

A WebSocket stream is bridged through WebSocketBridge (see
services/ws_bridge.py), which already detects a dead connection and gives
up after repeated failures. A plain RTSP stream has no such bridge — mpv
talks to the camera directly — so nothing watches for the demuxer
silently dying mid-stream, which can leave a slot's mpv render context
permanently wedged on a single stale frame, with no way back (confirmed
by reproducing that exact failure mode this investigation).

This fills that gap for RTSP: watch mpv's own time_pos to confirm a
stream is actually advancing, retry play() on the same URL if it isn't,
and give up (report back) after too many failures in a row so a slot
doesn't sit silently wedged forever.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from gi.repository import GLib  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from surveillance.ui.mpv_widget import MpvGLArea

log = logging.getLogger(__name__)

_CHECK_INTERVAL_SECS = 5
_MAX_CONSECUTIVE_STALLS = 3


class RtspHealthMonitor:
    """Watches an MpvGLArea playing a plain RTSP URL and retries on stall."""

    def __init__(
        self,
        player: MpvGLArea,
        url: str,
        label: str,
        on_gave_up: Callable[[str], None],
        on_recovered: Callable[[], None] | None = None,
    ) -> None:
        self._player = player
        self._url = url
        self._label = label or url
        self._on_gave_up = on_gave_up
        self._on_recovered = on_recovered
        self._reported_recovered = False
        self._checks_done = 0
        self._last_time_pos: float | None = None
        self._consecutive_stalls = 0
        self._timer_id: int = GLib.timeout_add_seconds(_CHECK_INTERVAL_SECS, self._check)

    def stop(self) -> None:
        """Stop monitoring — the slot has moved on to something else."""
        if self._timer_id:
            GLib.source_remove(self._timer_id)
            self._timer_id = 0

    def _check(self) -> bool:
        self._checks_done += 1
        pos = self._player.time_pos

        if self._checks_done == 1:
            # First check is just a baseline: mpv may still be buffering the
            # initial connection, which normally takes a couple of seconds —
            # well under one check interval — so this doesn't count as a
            # stall regardless of what pos is yet.
            self._last_time_pos = pos
            return True

        advancing = pos is not None and (self._last_time_pos is None or pos > self._last_time_pos)
        self._last_time_pos = pos

        if advancing:
            self._consecutive_stalls = 0
            if not self._reported_recovered and self._on_recovered is not None:
                self._reported_recovered = True
                self._on_recovered()
            return True

        self._consecutive_stalls += 1
        if self._consecutive_stalls >= _MAX_CONSECUTIVE_STALLS:
            log.error(
                "RTSP stream for %s stalled (no progress for ~%ds) — giving up",
                self._label,
                _CHECK_INTERVAL_SECS * _MAX_CONSECUTIVE_STALLS,
            )
            self._timer_id = 0
            self._on_gave_up("stalled: no progress")
            return False

        log.warning(
            "RTSP stream for %s stalled — retrying play() (%d/%d)",
            self._label,
            self._consecutive_stalls,
            _MAX_CONSECUTIVE_STALLS,
        )
        self._player.stop()
        self._player.play(self._url)
        return True
