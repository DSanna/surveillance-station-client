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

"""Tests for the AAC-hbr (RFC 3640) helpers used by WebSocket audio muxing."""

from __future__ import annotations

import pytest

from surveillance.services.aac import adts_header, nearest_sample_rate, strip_au_header


def _parse_adts(header: bytes) -> tuple[int, int, int]:
    """Minimal local ADTS parser -- reads back what adts_header() wrote,
    to verify our own bit-packing round-trips correctly without needing
    ffmpeg or embedded real audio data."""
    freq_idx = (header[2] >> 2) & 0xF
    channels = ((header[2] & 0x1) << 2) | ((header[3] >> 6) & 0x3)
    frame_len = ((header[3] & 0x3) << 11) | (header[4] << 3) | ((header[5] >> 5) & 0x7)
    return freq_idx, channels, frame_len


class TestAdtsHeader:
    def test_round_trips_rate_and_length(self) -> None:
        freq_table = {8000: 11, 16000: 8, 44100: 4, 48000: 3}
        for rate, expected_idx in freq_table.items():
            header = adts_header(413, sample_rate=rate)
            freq_idx, ch, frame_len = _parse_adts(header)
            assert freq_idx == expected_idx
            assert ch == 2
            assert frame_len == 413 + 7

    def test_sync_word_and_length(self) -> None:
        header = adts_header(100, sample_rate=8000)
        assert len(header) == 7
        assert header[0] == 0xFF
        assert (header[1] & 0xF0) == 0xF0

    def test_rejects_a_frame_longer_than_the_length_field(self) -> None:
        """13 bits, header included. Past that the excess is dropped and the
        header describes a much shorter frame, which no reader can recover."""
        assert _parse_adts(adts_header(8184, sample_rate=16000))[2] == 8191
        with pytest.raises(ValueError, match="exceeds what an ADTS header"):
            adts_header(8185, sample_rate=16000)


class TestNearestSampleRate:
    def test_snaps_to_known_rates(self) -> None:
        assert nearest_sample_rate(1024 / 8000) == 8000
        assert nearest_sample_rate(1024 / 16000) == 16000
        assert nearest_sample_rate(1024 / 44100) == 44100

    def test_tolerates_jitter(self) -> None:
        # +-15ms jitter around the real ~128ms/8kHz interval, as observed
        # against a real camera -- must not snap to a neighboring rate.
        assert nearest_sample_rate(0.113) == 8000
        assert nearest_sample_rate(0.145) == 8000

    def test_non_positive_interval_has_a_safe_default(self) -> None:
        assert nearest_sample_rate(0) > 0
        assert nearest_sample_rate(-1) > 0


class TestStripAuHeader:
    def test_removes_leading_two_bytes(self) -> None:
        frame = b"\x00\x01\x02\x03\x04"
        assert strip_au_header(frame) == b"\x02\x03\x04"


class TestSampleRateDetectionRobustness:
    """The rate is taken from the median of real WebSocket arrival
    intervals, measured on the event loop that also serves every other
    camera, so one late frame must not decide the whole session's pitch."""

    @pytest.mark.parametrize("rate", [16000, 22050, 32000, 44100, 48000])
    def test_median_survives_a_scheduling_hiccup(self, rate: int) -> None:
        from statistics import median

        from surveillance.services.aac import nearest_sample_rate
        from surveillance.services.ws_bridge import _AAC_DETECTION_INTERVALS

        nominal = 1024 / rate
        intervals = [nominal] * (_AAC_DETECTION_INTERVALS - 1) + [nominal + 0.050]
        assert nearest_sample_rate(median(intervals)) == rate

    def test_enough_intervals_for_a_median(self) -> None:
        from surveillance.services.ws_bridge import _AAC_DETECTION_INTERVALS

        assert _AAC_DETECTION_INTERVALS >= 3
        assert _AAC_DETECTION_INTERVALS % 2 == 1  # a true middle sample
