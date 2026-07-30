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

"""G.711 mu-law encoding for push-to-talk audio upload.

A small, dependency-free reimplementation of the one stdlib `audioop`
function push-to-talk needs (`lin2ulaw`) -- audioop is deprecated since
Python 3.12 and removed in 3.13. Rather than take on the `audioop-lts`
backport package for one function, this reimplements CPython's own
algorithm directly (Modules/audioop.c: audioop_lin2ulaw_impl ->
st_14linear2ulaw, itself derived from SoX's public-domain g711.c) --
verified bit-for-bit against an independent implementation of the same
algorithm across all 65536 possible 16-bit sample values (see
tests/test_services.py -- audioop itself cannot be used as the reference,
being absent from the very versions this module exists to serve).
"""

from __future__ import annotations

# CPython widens the sample into a 32-bit "sample * 65536" value and takes
# its top bits; net effect is an arithmetic right shift by 2, reducing the
# 16-bit sample to the 14-bit domain the mu-law encoder operates on.
_BIAS = 33  # 0x84 >> 2
_CLIP = 32635  # never actually reached for a valid 14-bit magnitude

# Segment (exponent) upper bounds -- smallest index i where value <= bound.
_SEG_UEND = (0x3F, 0x7F, 0xFF, 0x1FF, 0x3FF, 0x7FF, 0xFFF, 0x1FFF)


def _segment(value: int) -> int:
    for i, bound in enumerate(_SEG_UEND):
        if value <= bound:
            return i
    return len(_SEG_UEND)


def _encode_sample(sample: int) -> int:
    pcm = sample >> 2
    if pcm < 0:
        pcm = -pcm
        mask = 0x7F
    else:
        mask = 0xFF
    pcm = min(pcm, _CLIP)
    pcm += _BIAS
    seg = _segment(pcm)
    mantissa = (pcm >> (seg + 1)) & 0x0F
    uval = 0x7F if seg >= len(_SEG_UEND) else (seg << 4) | mantissa
    return (uval ^ mask) & 0xFF


def lin2ulaw(fragment: bytes) -> bytes:
    """Encode 16-bit signed little-endian PCM samples to G.711 mu-law bytes."""
    if len(fragment) % 2:
        raise ValueError("fragment length must be a multiple of 2")

    out = bytearray(len(fragment) // 2)
    for i in range(0, len(fragment), 2):
        sample = int.from_bytes(fragment[i : i + 2], "little", signed=True)
        out[i // 2] = _encode_sample(sample)
    return bytes(out)
