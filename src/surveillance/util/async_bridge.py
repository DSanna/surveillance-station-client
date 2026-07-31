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

"""Bridge between GTK4 main loop and asyncio.

Runs a dedicated asyncio event loop in a background thread.
Coroutines are submitted to it, and callbacks are dispatched
back to the GTK main thread via GLib.idle_add().
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
from collections.abc import Coroutine
from typing import Any, TypeVar

from gi.repository import GLib  # type: ignore[import-untyped]

log = logging.getLogger(__name__)

T = TypeVar("T")

_loop: asyncio.AbstractEventLoop | None = None
_thread: threading.Thread | None = None
_setup_lock = threading.Lock()


def setup_async() -> asyncio.AbstractEventLoop:
    """Start a background asyncio event loop thread.

    Called once at startup (from the GTK main thread), and again from
    get_loop() only if something reaches the loop before that.
    Returns the event loop (running in the background thread).
    """
    global _loop, _thread

    with _setup_lock:
        if _loop is not None:
            return _loop

        # The thread body takes the loop as an argument rather than reading
        # the global: the global is not assigned until start() returns, and
        # a second setup_async() in that window would leave both threads
        # calling run_forever() on the same loop.
        loop = asyncio.new_event_loop()

        def _run_loop(loop: asyncio.AbstractEventLoop) -> None:
            asyncio.set_event_loop(loop)
            loop.run_forever()

        _thread = threading.Thread(
            target=_run_loop, args=(loop,), daemon=True, name="asyncio-bridge"
        )
        _thread.start()
        _loop = loop
        return loop


def get_loop() -> asyncio.AbstractEventLoop:
    """Get the background asyncio event loop.

    Deliberately not gated on is_running(): the loop is not running yet for
    the moment between the thread starting and run_forever() being reached,
    and treating that as "no loop" used to build a second one. Nothing stops
    the loop once it exists, so having it is enough. Work submitted before
    it starts is queued by call_soon_threadsafe() and runs when it does.
    """
    return _loop if _loop is not None else setup_async()


def run_async(
    coro: Coroutine[Any, Any, T],
    callback: Any | None = None,
    error_callback: Any | None = None,
) -> concurrent.futures.Future[T]:
    """Submit an async coroutine to the background loop.

    The callback receives the result value on the GTK main thread.
    The error_callback receives the exception on the GTK main thread.
    """
    loop = get_loop()

    future = asyncio.run_coroutine_threadsafe(coro, loop)

    if callback or error_callback:

        def _on_done(f: concurrent.futures.Future[T]) -> None:
            # A cancelled future has no exception to ask for — .exception()
            # re-raises CancelledError instead of returning it, and this
            # runs on the loop thread where nothing would catch it.
            if f.cancelled():
                return
            exc = f.exception()
            if exc:
                if error_callback:
                    GLib.idle_add(error_callback, exc)
                else:
                    log.error("Async task failed: %s", exc)
            elif callback:
                GLib.idle_add(callback, f.result())

        future.add_done_callback(_on_done)

    return future
