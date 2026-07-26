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

"""Check GitHub Releases for a newer version of this app.

Unlike every other service module here, this doesn't talk to the NAS at
all — it's a plain, unauthenticated request to GitHub's public API, done
once per app launch. Failures (offline, rate-limited, no releases yet)
are expected and non-fatal: this is a best-effort background check, never
something that should interrupt startup or get retried aggressively.
"""

from __future__ import annotations

import logging

import httpx

log = logging.getLogger(__name__)

RELEASES_PAGE_URL = "https://github.com/renaudallard/surveillance-station-client/releases"
_RELEASES_API_URL = (
    "https://api.github.com/repos/renaudallard/surveillance-station-client/releases/latest"
)


def _parse_version(text: str) -> tuple[int, ...]:
    """Parse a version-ish string ("v0.4.0", "0.4.0-rc1") into a tuple of
    its leading numeric components, for simple tuple comparison. Anything
    once a non-digit is hit (a suffix like "-rc1", or a malformed string)
    is dropped rather than raising — this only ever feeds a > comparison,
    so an empty tuple is a safe "unknown, treat as not newer" fallback.
    """
    parts: list[int] = []
    for chunk in text.removeprefix("v").split("."):
        digits = ""
        for ch in chunk:
            if not ch.isdigit():
                break
            digits += ch
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def is_newer(remote_tag: str, current_version: str) -> bool:
    """True if remote_tag represents a version newer than current_version."""
    return _parse_version(remote_tag) > _parse_version(current_version)


async def get_latest_release() -> tuple[str, str] | None:
    """Return (tag_name, html_url) for the latest GitHub release, or None
    on any failure — this must never raise."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                _RELEASES_API_URL, headers={"Accept": "application/vnd.github+json"}
            )
            resp.raise_for_status()
            data = resp.json()
        # Inside the try: a response whose JSON body is not an object makes
        # data.get(...) raise, and this function must never raise.
        tag = data.get("tag_name") or ""
        html_url = data.get("html_url") or RELEASES_PAGE_URL
    except Exception as e:
        log.debug("Update check failed (non-fatal): %s", e)
        return None

    if not tag:
        return None
    return tag, html_url
