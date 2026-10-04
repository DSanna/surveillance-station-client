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

"""Tests for the login dialog's profile switching, driven on a stand-in:
a real LoginDialog needs a display."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from types import SimpleNamespace
from typing import Any

import pytest

from surveillance.config import ConnectionProfile
from surveillance.ui import login
from surveillance.ui.login import LoginDialog


class _Field:
    def __init__(self) -> None:
        self.value: Any = ""

    def set_text(self, value: str) -> None:
        self.value = value

    def set_active(self, value: bool) -> None:
        self.value = value


class _Combo:
    def __init__(self, active: str) -> None:
        self.active = active

    def get_active_id(self) -> str:
        return self.active


def _dialog(active: str) -> Any:
    profiles = {
        "home": ConnectionProfile("home", "192.168.1.10"),
        "office": ConnectionProfile("office", "office.example.com"),
    }
    dialog = SimpleNamespace(app=SimpleNamespace(config=SimpleNamespace(profiles=profiles)))
    for name in ("name", "host", "port", "user", "pass"):
        setattr(dialog, f"{name}_entry", _Field())
    dialog.https_check = _Field()
    dialog.verify_ssl_check = _Field()
    dialog.profile_combo = _Combo(active)
    return dialog


class TestProfileSwitch:
    @pytest.fixture
    def pending(self, monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, Callable[..., Any]]]:
        """run_async calls, held until the test runs them, the way the
        real callback lands a main-loop turn later."""
        calls: list[tuple[Any, Callable[..., Any]]] = []

        def _run_async(coro: Coroutine[Any, Any, Any], callback: Callable[..., Any]) -> None:
            calls.append((coro, callback))

        stored = {"home": ("alice", "alice-secret")}

        async def _get(name: str) -> tuple[str, str] | None:
            return stored.get(name)

        monkeypatch.setattr(login, "run_async", _run_async)
        monkeypatch.setattr(login, "get_credentials_async", _get)
        return calls

    @staticmethod
    def _flush(pending: list[tuple[Any, Callable[..., Any]]]) -> None:
        while pending:
            coro, callback = pending.pop(0)
            try:
                coro.send(None)
            except StopIteration as done:
                callback(done.value)

    def test_a_profile_with_nothing_stored_keeps_no_credentials(
        self, pending: list[tuple[Any, Callable[..., Any]]]
    ) -> None:
        dialog = _dialog("home")
        LoginDialog._on_profile_changed(dialog, dialog.profile_combo)
        self._flush(pending)
        assert dialog.pass_entry.value == "alice-secret"

        dialog.profile_combo.active = "office"
        LoginDialog._on_profile_changed(dialog, dialog.profile_combo)
        self._flush(pending)

        assert dialog.host_entry.value == "office.example.com"
        assert dialog.user_entry.value == ""
        assert dialog.pass_entry.value == ""

    def test_stored_credentials_still_fill_the_form(
        self, pending: list[tuple[Any, Callable[..., Any]]]
    ) -> None:
        dialog = _dialog("home")
        LoginDialog._on_profile_changed(dialog, dialog.profile_combo)
        self._flush(pending)
        assert (dialog.user_entry.value, dialog.pass_entry.value) == ("alice", "alice-secret")

    def test_a_new_profile_starts_from_the_defaults(
        self, pending: list[tuple[Any, Callable[..., Any]]]
    ) -> None:
        dialog = _dialog("home")
        dialog.app.config.profiles["home"] = ConnectionProfile(
            "home", "192.168.1.10", port=5000, https=False, verify_ssl=True
        )
        LoginDialog._on_profile_changed(dialog, dialog.profile_combo)
        self._flush(pending)
        assert (dialog.https_check.value, dialog.verify_ssl_check.value) == (False, True)

        dialog.profile_combo.active = "__new__"
        LoginDialog._on_profile_changed(dialog, dialog.profile_combo)
        assert dialog.port_entry.value == "5001"
        assert (dialog.https_check.value, dialog.verify_ssl_check.value) == (True, False)
