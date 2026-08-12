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

"""AAC helpers for WebSocket audio muxing (see ws_bridge.py).

DSM delivers each AAC frame behind a short prefix rather than as a
self-contained ADTS frame. ffmpeg's plain "aac" demuxer needs ADTS
framing, so each frame has that prefix stripped and a synthesized ADTS
header prepended, which the demuxer then finds via the sync word.

The prefix is the tail of an ADTS header, not the RFC 3640 AU-header
this code first assumed. For the one camera whose frames were captured
(3 bytes), adts_header() below reproduces all three exactly: they are
aac_frame_length's low 11 bits, adts_buffer_fullness 0x7FF, and one
raw_data_block per frame. Read as an RFC 3640 AU-header the same bytes
give an AU size of ~1600 for a ~420-byte frame and an AU index of 7
where the RFC requires 0, so that reading is excluded. Where the
leading ADTS bytes go is not established. Most likely the frame header
DSM sends covers them, the way it covers the 4-byte Annex B start code
for video (see _read_messages in ws_bridge.py). Confirming that needs
one full payload rather than the 12-byte prefixes captured so far:
((p[0] << 3) | (p[1] >> 5)) == len(p) + 4 holds if it does, and would
replace the measurement below with plain arithmetic.

Until then the prefix length is measured per camera (see
detect_frame_prefix_len) from frames buffered during startup, since
nothing DSM sends states it. That measurement cannot lean on ffmpeg
reporting a decode error: leaving one prefix byte unstripped makes its
decoder recover through an internal retry that drops the packet's own
timestamp without surfacing anything, which is what let WebSocket
reconnect gaps pass unnoticed until audio and video had drifted apart.
_aac_frames_look_valid in ws_bridge.py only checks that ffmpeg stays
quiet, so it cannot catch that by itself.

A second camera model reported the same adoCodec but used different
framing entirely, so audio for a camera like that falls back to
video-only.
"""

from __future__ import annotations

from collections.abc import Sequence

# DSM doesn't expose the negotiated sample rate directly (adoExtra's
# encoding isn't known), but every AAC-LC frame carries a fixed 1024
# samples, so timing alone, measured from real frame arrivals, is enough
# to determine the rate live, without a per-camera-model lookup table.
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


def strip_frame_prefix(frame: bytes, prefix_len: int) -> bytes:
    """Remove DSM's leading prefix, leaving the raw AAC frame."""
    return frame[prefix_len:]


# 2 is the shortest prefix seen in practice and 3 is the only other one,
# so the search starts at 2; a shorter candidate would be tested against
# real AAC payload bytes rather than prefix bytes, which proves nothing.
# The ceiling is arbitrary but generous, and matches the range already
# ruled out for the second camera model in the module docstring.
_PREFIX_MIN_LEN = 2
_PREFIX_MAX_LEN = 8

# AAC's raw_data_block starts with a 3-bit id_syn_ele naming the first
# syntax element; 0b111 is ID_END, meaning "no elements follow". A real,
# non-empty frame can never legitimately start with that.
_AAC_ELEMENT_ID_END = 0b111


def detect_frame_prefix_len(frames: Sequence[bytes]) -> int | None:
    """Work out how many leading bytes DSM puts in front of the raw AAC
    frame, from a handful of real (still prefixed) frames.

    This eliminates rather than confirms. A candidate whose first
    post-strip byte reads as AAC's "immediate end, zero elements"
    marker on any sample frame is provably wrong, since a real
    raw_data_block cannot start with it; every other candidate is
    merely not disproved, and the shortest survivor wins. That
    preference is what makes the answer right on the captured camera,
    not the test itself, so a wrong prefix length is still possible in
    principle and _aac_frames_look_valid stays the only real check.

    Frames too short to carry any candidate are dropped rather than
    allowed to veto one: a runt payload says nothing about the framing,
    and letting it rule every length out would cost the camera its
    audio for the whole session. Returns None if nothing usable is left
    or no candidate holds, so callers can fall back instead of guessing.
    """
    usable = [frame for frame in frames if len(frame) > _PREFIX_MAX_LEN]
    if not usable:
        return None
    for length in range(_PREFIX_MIN_LEN, _PREFIX_MAX_LEN + 1):
        if all((frame[length] >> 5) != _AAC_ELEMENT_ID_END for frame in usable):
            return length
    return None


def nearest_sample_rate(interval_seconds: float) -> int:
    """Snap a measured inter-frame interval to the nearest standard AAC
    sample rate, assuming AAC-LC's fixed 1024 samples per frame."""
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
