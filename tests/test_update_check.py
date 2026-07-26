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

from __future__ import annotations

import httpx
import pytest
import respx

from surveillance.services.update_check import _parse_version, get_latest_release, is_newer


class TestParseVersion:
    def test_plain(self) -> None:
        assert _parse_version("0.4.0") == (0, 4, 0)

    def test_v_prefix(self) -> None:
        assert _parse_version("v0.4.0") == (0, 4, 0)

    def test_suffix_dropped(self) -> None:
        assert _parse_version("0.4.0-rc1") == (0, 4, 0)

    def test_malformed_falls_back_to_empty(self) -> None:
        assert _parse_version("not-a-version") == ()


class TestIsNewer:
    def test_newer_patch(self) -> None:
        assert is_newer("v0.3.10", "0.3.9") is True

    def test_same_version(self) -> None:
        assert is_newer("v0.3.9", "0.3.9") is False

    def test_older_version(self) -> None:
        assert is_newer("v0.3.5", "0.3.9") is False

    def test_unparseable_remote_never_newer(self) -> None:
        assert is_newer("garbage", "0.3.9") is False


class TestGetLatestRelease:
    @pytest.mark.asyncio
    @respx.mock
    async def test_success(self) -> None:
        respx.get(
            "https://api.github.com/repos/renaudallard/surveillance-station-client/releases/latest",
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "tag_name": "v0.4.0",
                    "html_url": "https://github.com/renaudallard/surveillance-station-client/releases/tag/v0.4.0",
                },
            )
        )
        result = await get_latest_release()
        assert result == (
            "v0.4.0",
            "https://github.com/renaudallard/surveillance-station-client/releases/tag/v0.4.0",
        )

    @pytest.mark.asyncio
    @respx.mock
    async def test_network_failure_returns_none(self) -> None:
        respx.get(
            "https://api.github.com/repos/renaudallard/surveillance-station-client/releases/latest",
        ).mock(side_effect=httpx.ConnectError("no route"))
        assert await get_latest_release() is None

    @pytest.mark.asyncio
    @respx.mock
    async def test_http_error_returns_none(self) -> None:
        respx.get(
            "https://api.github.com/repos/renaudallard/surveillance-station-client/releases/latest",
        ).mock(return_value=httpx.Response(404))
        assert await get_latest_release() is None
