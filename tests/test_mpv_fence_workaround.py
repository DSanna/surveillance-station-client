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

"""Tests for the libmpv 0.40/0.41 GL fence leak workaround (no GTK or libmpv required)."""

from __future__ import annotations

import ctypes

import pytest

from surveillance.ui import mpv_widget
from surveillance.ui.mpv_widget import (
    _NO_FENCE_SYNC,
    _NO_FENCE_SYNC_ADDR,
    _get_gl_proc_address_no_fences,
    _mpv_leaks_vsync_fences,
)


@pytest.mark.parametrize(
    ("version", "leaks"),
    [
        ("mpv 0.40.0", True),
        ("mpv 0.41.0", True),
        ("mpv v0.41.0-312-g1234abcd", True),
        ("mpv 0.39.0", False),
        ("mpv 0.42.0", False),
        ("mpv 1.0.0", False),
        ("", False),
        ("mpv git-unknown", False),
    ],
)
def test_only_the_leaking_releases_are_matched(version: str, leaks: bool) -> None:
    assert _mpv_leaks_vsync_fences(version) is leaks


def test_fence_sync_resolves_to_the_stub_and_the_rest_pass_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mpv_widget, "_get_gl_proc_address", lambda _ctx, name: len(name))
    assert _get_gl_proc_address_no_fences(ctypes.c_void_p(), b"glFenceSync") == _NO_FENCE_SYNC_ADDR
    assert _get_gl_proc_address_no_fences(ctypes.c_void_p(), b"glDeleteSync") == len(
        b"glDeleteSync"
    )


def test_stub_creates_no_fence() -> None:
    """mpv skips a null fence, which is the whole point."""
    assert _NO_FENCE_SYNC(0x9117, 0) is None  # GL_SYNC_GPU_COMMANDS_COMPLETE
