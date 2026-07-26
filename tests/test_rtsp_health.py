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

"""Tests for the RTSP stream health monitor's stall/recover logic."""

from __future__ import annotations

from surveillance.ui.rtsp_health import RtspHealthMonitor


class _FakePlayer:
    def __init__(self, positions: list[float | None]) -> None:
        self._positions = positions
        self._i = 0
        self.play_calls = 0

    @property
    def time_pos(self) -> float | None:
        p = self._positions[min(self._i, len(self._positions) - 1)]
        self._i += 1
        return p

    def stop(self) -> None:
        pass

    def play(self, url: str, **kwargs: object) -> None:
        self.play_calls += 1


def _monitor(positions: list[float | None]) -> tuple[RtspHealthMonitor, _FakePlayer, list]:
    gave_up: list[str] = []
    recovered: list[bool] = []
    player = _FakePlayer(positions)
    mon = RtspHealthMonitor(
        player, "rtsp://cam/live", "Front", gave_up.append, lambda: recovered.append(True)
    )
    mon.stop()  # cancel the real GLib timer; we drive _check() manually
    return mon, player, [gave_up, recovered]


class TestRtspHealth:
    def test_recovers_after_a_stall_and_replay(self) -> None:
        """A stalled stream that is replayed and then advances from a low
        time_pos must be seen as recovered, not as a continued stall."""
        # baseline=10, advancing=11, then frozen at 11 (stall x3 -> replay),
        # replayed stream restarts low (2) then advances (3).
        mon, player, (gave_up, recovered) = _monitor([10.0, 11.0, 11.0, 11.0, 11.0, 2.0, 3.0])
        for _ in range(7):
            mon._check()
        assert player.play_calls >= 1, "should have retried on stall"
        assert not gave_up, f"should not give up on a recoverable stream: {gave_up}"
        assert recovered, "should report recovery once the replayed stream advances"

    def test_gives_up_when_replay_never_advances(self) -> None:
        """A stream frozen forever, even across replays, eventually gives up."""
        mon, _player, (gave_up, _recovered) = _monitor([5.0] + [5.0] * 20)
        for _ in range(20):
            if not mon._check():
                break
        assert gave_up, "a permanently frozen stream must give up"
