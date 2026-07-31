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

"""AAC (MPEG4-GENERIC over RTP, RFC 3640 "AAC-hbr" mode) helpers for
WebSocket audio muxing (see ws_bridge.py).

DSM delivers each AAC access unit prefixed with a 2-byte RFC 3640
AU-header (13-bit size + 3-bit index) rather than a self-contained
ADTS frame -- confirmed against a real camera, and matching the
widely-documented "AAC-hbr" default (sizeLength=13, indexLength=3,
indexDeltaLength=3) most IP cameras use for RTP audio. ffmpeg can't
read the bare AU-header framing directly, so each frame needs that
header stripped and a synthesized ADTS header prepended instead, which
ffmpeg's plain "aac" demuxer auto-detects via the ADTS sync word.

This is the common-case transport only. A second camera model tested
alongside this one reported the same adoCodec but used different
framing entirely (no AU-header length in the 0-8 byte range decoded
cleanly) -- not something a small tweak covers, so audio for a camera
like that just won't decode correctly through this path yet.
"""

from __future__ import annotations

_AU_HEADER_LEN = 2  # 13-bit size + 3-bit index, the AAC-hbr default

# DSM doesn't expose the negotiated sample rate directly (adoExtra's
# encoding isn't known), but AAC-hbr's "constantDuration" default means
# every frame carries a fixed 1024 samples -- so timing alone, measured
# from real frame arrivals, is enough to determine the rate live,
# without a per-camera-model lookup table.
_SAMPLES_PER_FRAME = 1024
_STANDARD_SAMPLE_RATES = (8000, 11025, 12000, 16000, 22050, 24000, 32000, 44100, 48000)

# aac_frame_length is 13 bits and counts the header in.
_ADTS_MAX_FRAME_LEN = 0x1FFF

_ADTS_FREQ_INDEX = {
    96000: 0,
    88200: 1,
    64000: 2,
    48000: 3,
    44100: 4,
    32000: 5,
    24000: 6,
    22050: 7,
    16000: 8,
    12000: 9,
    11025: 10,
    8000: 11,
    7350: 12,
}


def strip_au_header(frame: bytes) -> bytes:
    """Remove the leading RFC 3640 AU-header, leaving the raw AAC frame."""
    return frame[_AU_HEADER_LEN:]


def nearest_sample_rate(interval_seconds: float) -> int:
    """Snap a measured inter-frame interval to the nearest standard AAC
    sample rate, assuming the standard 1024-sample AAC-hbr frame size."""
    if interval_seconds <= 0:
        return 16000
    measured = _SAMPLES_PER_FRAME / interval_seconds
    return min(_STANDARD_SAMPLE_RATES, key=lambda r: abs(r - measured))


def adts_header(payload_length: int, sample_rate: int) -> bytes:
    """Build a 7-byte ADTS header (no CRC, AAC-LC, stereo) for an AAC frame
    of *payload_length* bytes -- lets ffmpeg's plain "aac" demuxer read an
    otherwise-bare AAC stream via ADTS sync-word auto-detection.

    Raises ValueError past what the header can describe. A 1024-sample
    AAC-LC frame never comes anywhere near that, so this catches a caller
    feeding in something that is not one frame rather than a real camera,
    which matters because the alternative is a silently wrong length: the
    field is 13 bits and the excess would just be dropped.
    """
    freq_idx = _ADTS_FREQ_INDEX[sample_rate]
    profile_id = 1  # AAC-LC (object type 2) -> ADTS profile field = object_type - 1
    channels = 2
    frame_len = payload_length + 7
    if frame_len > _ADTS_MAX_FRAME_LEN:
        raise ValueError(
            f"AAC frame of {payload_length} bytes exceeds what an ADTS header can describe"
        )
    h = bytearray(7)
    h[0] = 0xFF
    h[1] = 0xF1
    h[2] = ((profile_id & 0x3) << 6) | ((freq_idx & 0xF) << 2) | ((channels >> 2) & 0x1)
    h[3] = ((channels & 0x3) << 6) | ((frame_len >> 11) & 0x3)
    h[4] = (frame_len >> 3) & 0xFF
    h[5] = ((frame_len & 0x7) << 5) | 0x1F
    h[6] = 0xFC
    return bytes(h)
