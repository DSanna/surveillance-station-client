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

"""About page: app version, update status, and licensing information.

Not to be confused with the Licenses page, which manages DSM/Surveillance
Station *camera* licenses — this is about the client application itself.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gtk  # type: ignore[import-untyped]

from surveillance import __version__
from surveillance.services.update_check import RELEASES_PAGE_URL

if TYPE_CHECKING:
    from surveillance.ui.window import MainWindow

# Embedded rather than read from the repo's LICENSE file at runtime: a
# regular (non-editable) install copies only the Python package itself,
# so a path built from __file__ would not reliably find a root-level
# LICENSE file once installed. Keep this in sync with LICENSE by hand.
_LICENSE_TEXT = """Copyright (c) 2026, Renaud Allard <renaud@allard.it>
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice,
   this list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
POSSIBILITY OF SUCH DAMAGE."""

_REPO_URL = "https://github.com/renaudallard/surveillance-station-client"


class AboutView(Gtk.Box):
    """App version, update-check status, and license text."""

    def __init__(self, window: MainWindow) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.window = window
        self.app = window.app
        self.set_margin_top(16)
        self.set_margin_bottom(16)
        self.set_margin_start(16)
        self.set_margin_end(16)

        # Update banner — populated/shown by on_page_shown(), since the
        # background check may not have completed yet when this widget
        # is first constructed.
        self.update_banner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.update_banner.add_css_class("update-banner")
        self.update_banner.set_visible(False)
        self.update_banner_label = Gtk.Label(label="")
        self.update_banner_label.set_xalign(0)
        self.update_banner_label.set_hexpand(True)
        self.update_banner.append(self.update_banner_label)
        self.update_banner_link = Gtk.LinkButton(uri=RELEASES_PAGE_URL, label="Download")
        self.update_banner.append(self.update_banner_link)
        self.append(self.update_banner)

        title = Gtk.Label(label="Surveillance Station Client")
        title.add_css_class("title-2")
        title.set_xalign(0)
        title.set_margin_top(8)
        self.append(title)

        version_label = Gtk.Label(label=f"Version {__version__}")
        version_label.add_css_class("dim-label")
        version_label.set_xalign(0)
        self.append(version_label)

        repo_link = Gtk.LinkButton(uri=f"{_REPO_URL}#quick-start", label="GitHub repository")
        repo_link.set_halign(Gtk.Align.START)
        repo_link.set_margin_top(4)
        self.append(repo_link)

        releases_link = Gtk.LinkButton(uri=RELEASES_PAGE_URL, label="Releases")
        releases_link.set_halign(Gtk.Align.START)
        self.append(releases_link)

        self.append(Gtk.Separator(margin_top=12, margin_bottom=12))

        license_heading = Gtk.Label(label="License (BSD-2-Clause)")
        license_heading.add_css_class("heading")
        license_heading.set_xalign(0)
        self.append(license_heading)

        license_label = Gtk.Label(label=_LICENSE_TEXT)
        license_label.add_css_class("dim-label")
        license_label.add_css_class("caption")
        license_label.set_xalign(0)
        license_label.set_wrap(True)
        license_label.set_margin_top(8)
        self.append(license_label)

    def on_page_shown(self) -> None:
        """Refresh the update banner and dismiss the nav indicator.

        Called every time this page becomes visible (see
        MainWindow.show_page) — matches the pattern other pages use to
        refresh on navigation. The banner reflects whether a newer version
        is actually available and stays visible on every visit for as long
        as that's true; only the nav dot is a one-time "you haven't looked
        at this yet" indicator, cleared the first time this page is shown.
        """
        release = self.app.latest_release
        if release:
            tag, url = release
            self.update_banner_label.set_label(f"New version available: {tag}")
            self.update_banner_link.set_uri(url)
            self.update_banner.set_visible(True)

            if tag != self.app.config.dismissed_update_version:
                self.app.config.dismissed_update_version = tag
                from surveillance.config import save_config

                save_config(self.app.config)
        else:
            self.update_banner.set_visible(False)

        self.window.sidebar.set_update_available(False)
        self.window.headerbar.set_update_available(False)
