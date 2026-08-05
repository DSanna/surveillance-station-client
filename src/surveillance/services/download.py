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

"""Shared validation and disk writing for downloaded media.

Recordings, time lapse recordings and snapshots all fetch bytes from DSM
and drop them on disk. They used to carry three copies of that, which had
drifted apart: only one checked for a JSON error body, and only one
removed the partial file when the write failed.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator
from pathlib import Path

log = logging.getLogger(__name__)

# Enough of the body to recognise an error page or a JSON error before
# any of it is written out.
_VALIDATE_HEAD_BYTES = 1024


def check_download_content(data: bytes, label: str) -> None:
    """Raise ValueError if *data* is an error response rather than media.

    Synology DSM may return:
    - An empty body when the session has expired and no redirect is possible.
    - An HTML login page (text/html) when the reverse proxy redirects instead
      of returning a JSON error.
    - A JSON error body when the content-type header was missed by the client.
    Any of these would silently produce a corrupt or empty file without this
    check. *label* names the item in the message the user sees.
    """
    if not data:
        raise ValueError(
            f"{label}: server returned an empty response. "
            "The session may have expired — try logging out and back in."
        )

    # Detect HTML responses (login redirect, DSM error page). Matched as a
    # prefix: an exact "<html>" comparison missed a root tag carrying any
    # attribute, so a doctype-less "<html lang=..>" login page was written
    # out as if it were the media file.
    stripped = data[:100].lstrip().lower()
    if stripped.startswith((b"<!doctype", b"<html")):
        raise ValueError(
            f"{label}: server returned an HTML page instead of a media file. "
            "This usually means the session expired or the request was rejected. "
            "Log out and log back in, then try again."
        )

    # Detect a bare JSON error that slipped past the content-type check.
    if stripped[:1] == b"{":
        try:
            obj = json.loads(data)
        except Exception:
            obj = None
        if isinstance(obj, dict) and not obj.get("success", True):
            code = obj.get("error", {}).get("code", 0)
            msg = obj.get("error", {}).get("message", "")
            raise ValueError(
                f"{label}: API returned error code {code}" + (f" — {msg}" if msg else "")
            )


async def stream_to_file(chunks: AsyncIterator[bytes], output_path: Path, label: str) -> Path:
    """Write a streamed download to disk as it arrives.

    Memory stays flat whatever the file size, so a multi-gigabyte
    recording no longer has to fit in RAM. The first bytes are validated
    before anything is written, and a partial file is removed if the
    transfer or the write fails part-way through.

    Writes run off the loop thread: one event loop serves the whole app,
    so blocking it on disk I/O would stall every live stream and poll.
    """
    await asyncio.to_thread(output_path.parent.mkdir, parents=True, exist_ok=True)

    head = bytearray()
    checked = False
    total = 0
    handle = await asyncio.to_thread(output_path.open, "wb")
    try:
        async for chunk in chunks:
            if not checked:
                head += chunk
                if len(head) < _VALIDATE_HEAD_BYTES:
                    continue
                check_download_content(bytes(head), label)
                checked = True
                pending = bytes(head)
                head.clear()
            else:
                pending = chunk
            total += len(pending)
            await asyncio.to_thread(handle.write, pending)

        if not checked:
            # The whole file was smaller than the validation window.
            check_download_content(bytes(head), label)
            total += len(head)
            await asyncio.to_thread(handle.write, bytes(head))
    except BaseException:
        await asyncio.to_thread(handle.close)
        with contextlib.suppress(OSError):
            output_path.unlink()
        raise

    await asyncio.to_thread(handle.close)
    log.info("%s downloaded: %s (%d bytes)", label, output_path, total)
    return output_path


async def write_download(data: bytes, output_path: Path, label: str) -> Path:
    """Validate *data* and write it to *output_path*.

    Runs off the loop thread: one event loop serves the whole app, so a
    multi-hundred-MB write here would stall every live stream and every
    poll until it finished. A partial file left by a failed write is
    removed, so the user never keeps a truncated or empty placeholder.
    """
    check_download_content(data, label)

    await asyncio.to_thread(output_path.parent.mkdir, parents=True, exist_ok=True)
    try:
        await asyncio.to_thread(output_path.write_bytes, data)
    except Exception:
        with contextlib.suppress(OSError):
            output_path.unlink()
        raise

    log.info("%s downloaded: %s (%d bytes)", label, output_path, len(data))
    return output_path
