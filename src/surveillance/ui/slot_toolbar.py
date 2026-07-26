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

"""Hover-revealed video toolbar for a Live View slot."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("GdkPixbuf", "2.0")

from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk  # type: ignore[import-untyped]

from surveillance.api.models import Camera, PtzPatrol, PtzPreset
from surveillance.ui.mpv_widget import MpvGLArea


class SlotToolbar(Gtk.Revealer):
    """Hover-revealed toolbar over a Live View slot's video.

    Mute/volume, push-to-talk placeholder, PTZ/Zoom/Focus/Preset/Patrol
    (shown only for PTZ-capable cameras), and Snapshot — slides up from
    the bottom of the video on hover, matching DSM's own Monitor Center.
    """

    def __init__(self, index: int, player: MpvGLArea) -> None:
        super().__init__()
        self.index = index
        self.player = player
        self.set_transition_type(Gtk.RevealerTransitionType.SLIDE_UP)
        self.set_valign(Gtk.Align.END)
        self.set_halign(Gtk.Align.START)
        self.set_reveal_child(False)

        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        toolbar.add_css_class("slot-toolbar")

        self._audio_playable = True
        self._mute_btn = Gtk.Button()
        self._mute_btn.add_css_class("flat")
        self._mute_btn.set_visible(False)  # shown in assign() only if the camera has audio
        self._mute_btn.connect("clicked", self._on_mute_clicked)
        toolbar.append(self._mute_btn)
        self.update_mute_icon()

        # Placeholder — push-to-talk two-way audio. Only shown for cameras
        # with a speaker (has_speaker); real implementation still needs OS
        # microphone capture plumbed into a press-and-hold gesture and the
        # actual DSM upload protocol reverse-engineered (see ToDo.md).
        self._mic_btn = Gtk.Button()
        self._mic_btn.add_css_class("flat")
        self._mic_btn.set_icon_name("audio-input-microphone-symbolic")
        self._mic_btn.set_sensitive(False)
        self._mic_btn.set_visible(False)  # shown in assign() only if the camera has a speaker
        self._mic_btn.set_tooltip_text("Push-to-talk — not yet implemented")
        toolbar.append(self._mic_btn)

        # PTZ pad — only shown for PTZ-capable cameras. Reuses
        # services.ptz.move() (v2, string-direction API) rather than
        # the newer v6/numeric-direction Move DSM's own web UI uses for
        # its "hover over the video, cursor becomes an arrow" click-to-pan
        # mode — confirmed live (network capture) that mode sends
        # direction as a number in steps of 8 (0/8/16/24 = right/up/
        # left/down seen so far), with corner arrows in between implying
        # it supports finer, possibly diagonal angles that v2's fixed
        # up/down/left/right/home strings can't express. Not needed here
        # since this is a discrete 4-button pad, not a free-angle one.
        self._ptz_btn = Gtk.Button()
        self._ptz_btn.add_css_class("flat")
        # No single stock icon reads as "pan/tilt" — overlay flip-
        # horizontal and flip-vertical's arrow glyphs to get a 4-way
        # arrow instead of picking an unrelated one (e.g. a gamepad).
        # Letting Gtk.Picture/Gtk.Overlay stretch a square icon into a
        # non-square box proved unreliable (the two arrows fought over
        # the Overlay's allocated size, squashing one another), so the
        # non-uniform stretch is instead baked directly into the pixel
        # data at load time via GdkPixbuf's preserve_aspect_ratio=False,
        # sidestepping GTK layout/measure() entirely for the distortion.
        icon_theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        base_size = 16
        stretch_size = int(base_size * 1.5)
        shrink_size = int(base_size * 0.5)

        def _stretched_icon_picture(name: str, width: int, height: int) -> Gtk.Picture:
            icon_file = icon_theme.lookup_icon(
                name,
                None,
                base_size,
                1,
                Gtk.TextDirection.NONE,
                Gtk.IconLookupFlags.PRELOAD,
            ).get_file()
            with open(icon_file.get_path(), encoding="utf-8") as f:
                svg_text = f.read()
            # Adwaita symbolic SVGs ship with a placeholder dark fill
            # (#2e3436) that GTK normally recolors to the current
            # foreground at render time (see .slot-toolbar button's
            # "color: #ccc" in style.css) — loading the raw file via
            # GdkPixbuf bypasses that recoloring, so patch the fill
            # directly before rasterizing or the icon is nearly
            # invisible against the toolbar's dark background.
            svg_text = svg_text.replace("#2e3436", "#cccccc")
            # SVG's default preserveAspectRatio ("xMidYMid meet") scales
            # uniformly to fit within width/height and letterboxes the
            # rest — GdkPixbuf.new_from_stream_at_scale's own
            # preserve_aspect_ratio=False argument does NOT override
            # that, so the non-uniform stretch was silently being
            # ignored. preserveAspectRatio="none" makes it actually
            # stretch to fill width/height exactly.
            svg_text = svg_text.replace("<svg ", '<svg preserveAspectRatio="none" ', 1)
            stream = Gio.MemoryInputStream.new_from_data(svg_text.encode("utf-8"))
            pixbuf = GdkPixbuf.Pixbuf.new_from_stream_at_scale(stream, width, height, False, None)
            picture = Gtk.Picture.new_for_pixbuf(pixbuf)
            picture.set_content_fit(Gtk.ContentFit.FILL)
            picture.set_size_request(width, height)
            picture.set_halign(Gtk.Align.CENTER)
            picture.set_valign(Gtk.Align.CENTER)
            return picture

        ptz_icon_overlay = Gtk.Overlay()
        # A Gtk.Overlay sizes itself from its *main* child (set_child), so
        # give it a neutral square spacer as the main child (sized to fit
        # both arrows) rather than either arrow, and add both arrows as
        # centered overlay children.
        ptz_icon_canvas = Gtk.Box()
        ptz_icon_canvas.set_size_request(stretch_size, stretch_size)
        ptz_icon_overlay.set_child(ptz_icon_canvas)
        ptz_icon_h = _stretched_icon_picture(
            "object-flip-horizontal-symbolic", stretch_size, shrink_size
        )
        ptz_icon_overlay.add_overlay(ptz_icon_h)
        ptz_icon_v = _stretched_icon_picture(
            "object-flip-vertical-symbolic", shrink_size, stretch_size
        )
        ptz_icon_overlay.add_overlay(ptz_icon_v)
        self._ptz_btn.set_child(ptz_icon_overlay)
        self._ptz_btn.set_visible(False)  # shown in assign() only if the camera is PTZ-capable
        self._ptz_btn.set_tooltip_text("Pan / Tilt")
        toolbar.append(self._ptz_btn)

        # Zoom — services.ptz.zoom() Start/Stop calls. plain zoom-in-symbolic
        # is just a "+" in a square, not a magnifying glass, so combine
        # system-search-symbolic (the actual magnifying glass, large) with
        # list-add-symbolic (a "+", small) overlaid on top of it — both
        # scaled uniformly (unlike the Pan/Tilt icon) so plain Gtk.Image
        # keeps automatic symbolic recoloring.
        self._zoom_btn = Gtk.Button()
        self._zoom_btn.add_css_class("flat")
        search_size = int(base_size * 1.5)
        plus_size = int(base_size * 0.5)
        zoom_icon_overlay = Gtk.Overlay()
        zoom_icon_canvas = Gtk.Box()
        zoom_icon_canvas.set_size_request(search_size, search_size)
        zoom_icon_overlay.set_child(zoom_icon_canvas)
        zoom_icon_search = Gtk.Image.new_from_icon_name("system-search-symbolic")
        zoom_icon_search.set_pixel_size(search_size)
        zoom_icon_search.set_halign(Gtk.Align.CENTER)
        zoom_icon_search.set_valign(Gtk.Align.CENTER)
        zoom_icon_overlay.add_overlay(zoom_icon_search)
        zoom_icon_plus = Gtk.Image.new_from_icon_name("list-add-symbolic")
        zoom_icon_plus.set_pixel_size(plus_size)
        zoom_icon_plus.set_halign(Gtk.Align.CENTER)
        zoom_icon_plus.set_valign(Gtk.Align.CENTER)
        # system-search-symbolic's lens circle is centered at (6.5, 6.5)
        # in its 16x16 viewBox, not (8, 8) — the handle sticking out to
        # the bottom-right pulls the icon's overall bounding box off from
        # the circle's true center. Nudge the "+" up-left to compensate
        # (margin_end/margin_bottom shift a centered widget by half the
        # margin amount, so use 2x the (0.5 - 6.5/16) offset fraction).
        plus_offset = round(search_size * (0.5 - 6.5 / 16) * 2)
        zoom_icon_plus.set_margin_end(plus_offset)
        zoom_icon_plus.set_margin_bottom(plus_offset)
        zoom_icon_overlay.add_overlay(zoom_icon_plus)
        self._zoom_btn.set_child(zoom_icon_overlay)
        self._zoom_btn.set_visible(False)  # shown in assign() only if the camera is PTZ-capable
        self._zoom_btn.set_tooltip_text("Zoom")
        toolbar.append(self._zoom_btn)

        # Focus — services.ptz.focus(), confirmed live against DSM's own
        # web UI (network capture): a distinct, newer PTZ API version.
        self._focus_btn = Gtk.Button()
        self._focus_btn.add_css_class("flat")
        self._focus_btn.set_icon_name("edit-select-all-symbolic")
        self._focus_btn.set_visible(False)  # shown in assign() only if the camera is PTZ-capable
        self._focus_btn.set_tooltip_text("Focus")
        toolbar.append(self._focus_btn)

        # Preset — jumps immediately on selection.
        self._preset_btn = Gtk.Button()
        self._preset_btn.add_css_class("flat")
        self._preset_btn.set_icon_name("starred-symbolic")
        self._preset_btn.set_visible(False)  # shown in assign() only if the camera is PTZ-capable
        self._preset_btn.set_tooltip_text("Preset")
        toolbar.append(self._preset_btn)

        # Patrol — needs an explicit Start button (unlike Preset): starting
        # a patrol is a bigger action than jumping to a fixed position.
        self._patrol_btn = Gtk.Button()
        self._patrol_btn.add_css_class("flat")
        self._patrol_btn.set_icon_name("media-playlist-repeat-symbolic")
        self._patrol_btn.set_visible(False)  # shown in assign() only if the camera is PTZ-capable
        self._patrol_btn.set_tooltip_text("Patrol")
        toolbar.append(self._patrol_btn)

        self._snapshot_btn = Gtk.Button()
        self._snapshot_btn.add_css_class("flat")
        self._snapshot_btn.set_icon_name("camera-photo-symbolic")
        self._snapshot_btn.set_tooltip_text("Take Snapshot")
        self._snapshot_btn.connect("clicked", lambda _btn: self._on_snapshot_clicked())
        toolbar.append(self._snapshot_btn)

        self.set_child(toolbar)

        # Volume popover — revealed on hovering the mute button specifically
        # (not the whole toolbar), matching DSM's own Monitor Center.
        self._volume_popover = Gtk.Popover()
        self._volume_popover.set_autohide(False)
        self._volume_popover.set_position(Gtk.PositionType.TOP)
        self._volume_popover.set_parent(self._mute_btn)
        self._volume_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self._volume_scale.set_size_request(100, -1)
        self._volume_scale.set_draw_value(False)
        self._volume_scale.set_value(50)
        self._volume_scale.connect("value-changed", self._on_volume_changed)
        self._volume_popover.set_child(self._volume_scale)

        # PTZ popover — 4 direction buttons (same Start/Stop press-release
        # pattern as Zoom/Focus below, calling services.ptz.move() — see
        # the comment where _ptz_btn is created for why v2/string rather
        # than the newer v6/numeric Move DSM's own hover-video mode uses)
        # plus a center Home button, single-click (direction="home", no
        # Start/Stop suffix).
        self._ptz_popover = Gtk.Popover()
        self._ptz_popover.set_autohide(False)
        self._ptz_popover.set_position(Gtk.PositionType.TOP)
        self._ptz_popover.set_parent(self._ptz_btn)
        ptz_pad = Gtk.Grid()
        ptz_pad.set_row_homogeneous(True)
        ptz_pad.set_column_homogeneous(True)
        ptz_pad.set_row_spacing(2)
        ptz_pad.set_column_spacing(2)
        ptz_pad.add_css_class("ptz-pad")
        for row, col, direction, icon in (
            (0, 1, "up", "go-up-symbolic"),
            (1, 0, "left", "go-previous-symbolic"),
            (1, 2, "right", "go-next-symbolic"),
            (2, 1, "down", "go-down-symbolic"),
        ):
            dir_btn = Gtk.Button()
            dir_btn.set_icon_name(icon)
            dir_gesture = Gtk.GestureClick()
            dir_gesture.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
            dir_gesture.connect("pressed", self._on_ptz_press, direction)
            dir_gesture.connect("released", self._on_ptz_release, direction)
            dir_btn.add_controller(dir_gesture)
            ptz_pad.attach(dir_btn, col, row, 1, 1)
        home_btn = Gtk.Button()
        home_btn.set_icon_name("go-home-symbolic")
        home_btn.set_tooltip_text("Home")
        # A plain "clicked" signal isn't reliable for a button living
        # inside this hover-managed popover (same root cause as the
        # direction buttons needing a capture-phase GestureClick — the
        # button's own default-phase click gesture can lose the sequence
        # to our hover handling), so this uses the same fix.
        home_gesture = Gtk.GestureClick()
        home_gesture.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        home_gesture.connect("released", self._on_ptz_home)
        home_btn.add_controller(home_gesture)
        ptz_pad.attach(home_btn, 1, 1, 1, 1)
        self._ptz_popover.set_child(ptz_pad)

        # Zoom popover — 2 buttons, Start/Stop press-release pattern
        # calling services.ptz.zoom() (text +/- labels).
        self._zoom_popover = Gtk.Popover()
        self._zoom_popover.set_autohide(False)
        self._zoom_popover.set_position(Gtk.PositionType.TOP)
        self._zoom_popover.set_parent(self._zoom_btn)
        zoom_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        zoom_out_btn = Gtk.Button(label="\u2212")
        zoom_out_btn.set_tooltip_text("Zoom Out")
        zoom_out_gesture = Gtk.GestureClick()
        zoom_out_gesture.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        zoom_out_gesture.connect("pressed", self._on_zoom_press, "out")
        zoom_out_gesture.connect("released", self._on_zoom_release, "out")
        zoom_out_btn.add_controller(zoom_out_gesture)
        zoom_box.append(zoom_out_btn)
        zoom_in_btn = Gtk.Button(label="+")
        zoom_in_btn.set_tooltip_text("Zoom In")
        zoom_in_gesture = Gtk.GestureClick()
        zoom_in_gesture.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        zoom_in_gesture.connect("pressed", self._on_zoom_press, "in")
        zoom_in_gesture.connect("released", self._on_zoom_release, "in")
        zoom_in_btn.add_controller(zoom_in_gesture)
        zoom_box.append(zoom_in_btn)
        self._zoom_popover.set_child(zoom_box)

        # Focus popover — same shape as Zoom's, calling services.ptz.focus().
        self._focus_popover = Gtk.Popover()
        self._focus_popover.set_autohide(False)
        self._focus_popover.set_position(Gtk.PositionType.TOP)
        self._focus_popover.set_parent(self._focus_btn)
        focus_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        focus_out_btn = Gtk.Button(label="\u2212")
        focus_out_btn.set_tooltip_text("Focus Out")
        focus_out_gesture = Gtk.GestureClick()
        focus_out_gesture.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        focus_out_gesture.connect("pressed", self._on_focus_press, "out")
        focus_out_gesture.connect("released", self._on_focus_release, "out")
        focus_out_btn.add_controller(focus_out_gesture)
        focus_box.append(focus_out_btn)
        focus_in_btn = Gtk.Button(label="+")
        focus_in_btn.set_tooltip_text("Focus In")
        focus_in_gesture = Gtk.GestureClick()
        focus_in_gesture.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        focus_in_gesture.connect("pressed", self._on_focus_press, "in")
        focus_in_gesture.connect("released", self._on_focus_release, "in")
        focus_in_btn.add_controller(focus_in_gesture)
        focus_box.append(focus_in_btn)
        self._focus_popover.set_child(focus_box)

        # Preset popover — a single dropdown, populated via set_presets()
        # once the camera's preset list has loaded (LiveView owns the API
        # call, same split as zoom/focus/PTZ). Selecting an entry jumps
        # immediately.
        self._preset_popover = Gtk.Popover()
        self._preset_popover.set_autohide(False)
        self._preset_popover.set_position(Gtk.PositionType.TOP)
        self._preset_popover.set_parent(self._preset_btn)
        self._preset_combo = Gtk.ComboBoxText()
        self._preset_combo.connect("changed", self._on_preset_changed)
        # Opening the combo's own dropdown list is a separate popup
        # surface, which fires a "leave" crossing on the parent popover's
        # motion controller (same class of gap the hover debounce already
        # handles between an icon and its popover) — without this, the
        # 200ms debounce tears the whole popover down before a selection
        # can be made. Cancel/re-arm the hide around the combo's own
        # popup-shown state so it survives the crossing.
        self._preset_combo.connect("notify::popup-shown", self._on_combo_popup_shown)
        # Selecting a preset is a one-shot "jump the camera there" command,
        # not a persistent setting — but Gtk.ComboBoxText's "changed" only
        # fires on an actual selection change, so re-picking the same
        # preset again (e.g. after someone nudged the camera manually) is
        # silently a no-op. Clearing the selection whenever the popover
        # closes means the next pick is always a real change, even if it's
        # the same preset as last time.
        self._preset_popover.connect("closed", lambda _p: self._preset_combo.set_active(-1))
        self._preset_popover.set_child(self._preset_combo)

        # Patrol popover — dropdown + explicit Start/Stop toggle button.
        self._patrol_popover = Gtk.Popover()
        self._patrol_popover.set_autohide(False)
        self._patrol_popover.set_position(Gtk.PositionType.TOP)
        self._patrol_popover.set_parent(self._patrol_btn)
        patrol_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self._patrol_combo = Gtk.ComboBoxText()
        self._patrol_combo.connect("notify::popup-shown", self._on_combo_popup_shown)
        self._patrol_combo.connect("changed", self._on_patrol_selection_changed)
        patrol_box.append(self._patrol_combo)
        self._patrol_start_btn = Gtk.Button(label="Start")
        self._patrol_start_btn.set_sensitive(False)  # enabled once a patrol is selected
        self._patrol_start_btn.connect("clicked", self._on_patrol_toggle_clicked)
        patrol_box.append(self._patrol_start_btn)
        self._patrol_popover.set_child(patrol_box)

        # One shared debounced hide, armed on leaving *any* of the video,
        # an icon, or its popover, and cancelled on entering *any* of
        # them — each popover renders in its own surface above its button
        # rather than as a normal child, so there's a gap between the two
        # a plain per-widget leave-hides-immediately would otherwise
        # collapse the whole toolbar in the middle of. Showing one popover
        # hides any other that's open, so only one is ever up at a time.
        self._toolbar_hide_id = 0
        # True while a zoom/focus button is actively pressed — suppresses
        # auto-hide so the popover can't get torn down mid-hold (which
        # silently drops the button's "released" signal, meaning the
        # matching Stop command never gets sent and the motor keeps
        # running server-side until manually stopped some other way).
        self._popover_button_held = False
        # True while a Preset/Patrol combo's own dropdown list is open —
        # see schedule_hide().
        self._combo_popup_open = False

        for icon_btn, popover in (
            (self._mute_btn, self._volume_popover),
            (self._ptz_btn, self._ptz_popover),
            (self._zoom_btn, self._zoom_popover),
            (self._focus_btn, self._focus_popover),
            (self._preset_btn, self._preset_popover),
            (self._patrol_btn, self._patrol_popover),
        ):
            icon_hover = Gtk.EventControllerMotion()
            icon_hover.connect("enter", lambda *_a, p=popover: self._show_only_popover(p))
            icon_hover.connect("leave", lambda *_a: self.schedule_hide())
            icon_btn.add_controller(icon_hover)

            popover_hover = Gtk.EventControllerMotion()
            popover_hover.connect("enter", lambda *_a: self.cancel_hide())
            popover_hover.connect("leave", lambda *_a: self.schedule_hide())
            popover.add_controller(popover_hover)

        self._snapshot_trigger: object = None
        self._volume_changed_callback: object = None
        self._mute_changed_callback: object = None
        self._zoom_callback: object = None
        self._focus_callback: object = None
        self._ptz_callback: object = None
        self._preset_callback: object = None
        # Patrol is run client-side (see PtzPatrol's docstring) by
        # repeatedly invoking _preset_callback through the patrol's own
        # preset sequence on a GLib timer — there's no separate
        # "patrol" callback/API call involved.
        self._patrols: list[PtzPatrol] = []
        self._patrol_running = False
        self._patrol_sequence: list[int] = []
        self._patrol_step = 0
        self._patrol_timer_id = 0

    def set_snapshot_trigger(self, callback: object) -> None:
        """Called once by the owning CameraSlot at construction — the
        toolbar's own Snapshot button just triggers whatever CameraSlot's
        right-click "Take Snapshot" menu item would (a shared code path,
        not toolbar-specific behavior itself)."""
        self._snapshot_trigger = callback

    def _on_snapshot_clicked(self) -> None:
        if self._snapshot_trigger and callable(self._snapshot_trigger):
            self._snapshot_trigger()

    def set_volume_changed_callback(self, callback: object) -> None:
        """Callback(slot_index, volume) — LiveView persists it per-camera;
        this class only owns applying it to the player itself."""
        self._volume_changed_callback = callback

    def set_saved_volume(self, volume: int) -> None:
        """Apply a persisted volume level without re-triggering the
        change callback that would just save the same value straight
        back."""
        self._volume_scale.handler_block_by_func(self._on_volume_changed)
        self._volume_scale.set_value(volume)
        self._volume_scale.handler_unblock_by_func(self._on_volume_changed)
        self.player.set_volume(volume)

    def set_mute_changed_callback(self, callback: object) -> None:
        """Callback(slot_index, muted) — LiveView persists it per-camera;
        this class only owns applying it to the player itself."""
        self._mute_changed_callback = callback

    def set_saved_mute(self, muted: bool) -> None:
        """Apply a persisted mute state — a camera becoming visible again
        restores its last manual mute choice, not a fixed default (unlike
        losing visibility, which always force-mutes — see clear() and
        LiveView's _apply_layout()/pause_streams())."""
        self.player.set_mute(muted)
        self.update_mute_icon()

    def set_audio_playable(self, playable: bool) -> None:
        """Whether the currently assigned camera's audio can actually reach
        the player right now — separate from whether it *has* audio at all
        (has_audio only gates the mute button's visibility). False for a
        WebSocket-protocol camera regardless of has_audio: the WebSocket
        bridge pipes raw video NAL units only (see ws_bridge.py's
        _extract_payload — no container to also carry an audio track
        through), so there's nothing mute/volume could ever control there.
        Ghosts the button rather than hiding it, with a tooltip pointing
        at the fix, so it isn't mistaken for "this camera has no mic"."""
        self._audio_playable = playable
        self._mute_btn.set_sensitive(playable)
        if playable:
            self.update_mute_icon()
        else:
            self._mute_btn.set_tooltip_text(
                "Audio isn't available over WebSocket (this camera's current "
                "protocol) — switch it to RTSP in camera settings to enable audio."
            )

    def update_mute_icon(self) -> None:
        if self.player.muted:
            self._mute_btn.set_icon_name("audio-volume-muted-symbolic")
            if self._audio_playable:
                self._mute_btn.set_tooltip_text("Unmute")
        else:
            self._mute_btn.set_icon_name("audio-volume-high-symbolic")
            if self._audio_playable:
                self._mute_btn.set_tooltip_text("Mute")

    def _on_mute_clicked(self, btn: Gtk.Button) -> None:
        muted = not self.player.muted
        self.player.set_mute(muted)
        self.update_mute_icon()
        if self._mute_changed_callback and callable(self._mute_changed_callback):
            self._mute_changed_callback(self.index, muted)

    def _on_volume_changed(self, scale: Gtk.Scale) -> None:
        volume = int(scale.get_value())
        self.player.set_volume(volume)
        if self._volume_changed_callback and callable(self._volume_changed_callback):
            self._volume_changed_callback(self.index, volume)

    def set_zoom_callback(self, callback: object) -> None:
        """Callback(slot_index, direction, move_type) — direction is "in"
        or "out", move_type is "Start" or "Stop"."""
        self._zoom_callback = callback

    def set_focus_callback(self, callback: object) -> None:
        """Callback(slot_index, control, move_type) — control is "in" or
        "out", move_type is "Start" or "Stop"."""
        self._focus_callback = callback

    def set_ptz_callback(self, callback: object) -> None:
        """Callback(slot_index, direction, move_type) — direction is "up",
        "down", "left", or "right", move_type is "Start" or "Stop"."""
        self._ptz_callback = callback

    def _on_ptz_press(
        self, gesture: Gtk.GestureClick, n_press: int, x: float, y: float, direction: str
    ) -> None:
        self._popover_button_held = True
        self.cancel_hide()
        if self._ptz_callback and callable(self._ptz_callback):
            self._ptz_callback(self.index, direction, "Start")

    def _on_ptz_release(
        self, gesture: Gtk.GestureClick, n_press: int, x: float, y: float, direction: str
    ) -> None:
        self._popover_button_held = False
        if self._ptz_callback and callable(self._ptz_callback):
            self._ptz_callback(self.index, direction, "Stop")

    def _on_ptz_home(self, gesture: Gtk.GestureClick, n_press: int, x: float, y: float) -> None:
        if self._ptz_callback and callable(self._ptz_callback):
            self._ptz_callback(self.index, "home", "")

    def _on_zoom_press(
        self, gesture: Gtk.GestureClick, n_press: int, x: float, y: float, direction: str
    ) -> None:
        self._popover_button_held = True
        self.cancel_hide()
        if self._zoom_callback and callable(self._zoom_callback):
            self._zoom_callback(self.index, direction, "Start")

    def _on_zoom_release(
        self, gesture: Gtk.GestureClick, n_press: int, x: float, y: float, direction: str
    ) -> None:
        self._popover_button_held = False
        if self._zoom_callback and callable(self._zoom_callback):
            self._zoom_callback(self.index, direction, "Stop")

    def _on_focus_press(
        self, gesture: Gtk.GestureClick, n_press: int, x: float, y: float, control: str
    ) -> None:
        self._popover_button_held = True
        self.cancel_hide()
        if self._focus_callback and callable(self._focus_callback):
            self._focus_callback(self.index, control, "Start")

    def _on_focus_release(
        self, gesture: Gtk.GestureClick, n_press: int, x: float, y: float, control: str
    ) -> None:
        self._popover_button_held = False
        if self._focus_callback and callable(self._focus_callback):
            self._focus_callback(self.index, control, "Stop")

    def set_preset_callback(self, callback: object) -> None:
        """Callback(slot_index, preset_id)."""
        self._preset_callback = callback

    def set_presets(self, presets: list[PtzPreset]) -> None:
        """Populate the Preset dropdown — LiveView owns the ptz.list_presets()
        call (same split as zoom/focus/PTZ) and pushes the result here."""
        self._preset_combo.remove_all()
        for p in presets:
            self._preset_combo.append(str(p.id), p.name)

    def set_patrols(self, patrols: list[PtzPatrol]) -> None:
        """Populate the Patrol dropdown — see set_presets()."""
        self._stop_patrol()
        self._patrols = patrols
        self._patrol_combo.remove_all()
        for p in patrols:
            self._patrol_combo.append(str(p.id), p.name)
        self._patrol_start_btn.set_sensitive(False)

    def _on_preset_changed(self, combo: Gtk.ComboBoxText) -> None:
        preset_id_str = combo.get_active_id()
        if not preset_id_str:
            return
        if self._preset_callback and callable(self._preset_callback):
            self._preset_callback(self.index, int(preset_id_str))

    def _on_patrol_selection_changed(self, combo: Gtk.ComboBoxText) -> None:
        self._patrol_start_btn.set_sensitive(combo.get_active_id() is not None)

    def _on_patrol_toggle_clicked(self, btn: Gtk.Button) -> None:
        if self._patrol_running:
            self._stop_patrol()
            return
        patrol_id_str = self._patrol_combo.get_active_id()
        if not patrol_id_str:
            return
        patrol = next((p for p in self._patrols if p.id == int(patrol_id_str)), None)
        if not patrol or not patrol.sequence:
            return
        self._start_patrol(patrol)

    def _start_patrol(self, patrol: PtzPatrol) -> None:
        self._patrol_running = True
        self._patrol_sequence = patrol.sequence
        self._patrol_step = 0
        self._patrol_start_btn.set_label("Stop")
        self._advance_patrol()  # move to the first position immediately
        self._patrol_timer_id = GLib.timeout_add_seconds(
            max(1, patrol.stay_time), self._advance_patrol
        )

    def _advance_patrol(self) -> bool:
        if not self._patrol_running or not self._patrol_sequence:
            return False
        preset_id = self._patrol_sequence[self._patrol_step]
        self._patrol_step = (self._patrol_step + 1) % len(self._patrol_sequence)
        if self._preset_callback and callable(self._preset_callback):
            self._preset_callback(self.index, preset_id)
        return True  # keep the GLib timer repeating

    def _stop_patrol(self) -> None:
        self._patrol_running = False
        if self._patrol_timer_id:
            GLib.source_remove(self._patrol_timer_id)
            self._patrol_timer_id = 0
        self._patrol_start_btn.set_label("Start")

    def _on_combo_popup_shown(self, combo: Gtk.ComboBoxText, pspec: object) -> None:
        self._combo_popup_open = combo.get_property("popup-shown")
        if self._combo_popup_open:
            self.cancel_hide()
        else:
            self.schedule_hide()

    def _all_popovers(self) -> tuple[Gtk.Popover, ...]:
        return (
            self._volume_popover,
            self._ptz_popover,
            self._zoom_popover,
            self._focus_popover,
            self._preset_popover,
            self._patrol_popover,
        )

    def _show_only_popover(self, popover: Gtk.Popover) -> None:
        self.cancel_hide()
        for other in self._all_popovers():
            if other is not popover:
                other.popdown()
        popover.popup()

    def cancel_hide(self) -> None:
        if self._toolbar_hide_id:
            GLib.source_remove(self._toolbar_hide_id)
            self._toolbar_hide_id = 0

    def schedule_hide(self) -> None:
        # Debounced rather than immediate: moving the pointer between the
        # video, an icon, and its popover (which renders in its own
        # surface, not as a normal child of either) is a leave/enter pair
        # on two different widgets each time, so hiding immediately on
        # any single leave would collapse things mid-transition.
        if self._popover_button_held:
            return  # re-armed in _on_{zoom,focus}_release once it isn't
        if self._combo_popup_open:
            # A ComboBoxText's own dropdown list is yet another separate
            # popup surface (below the popover, below the icon) — moving
            # the pointer onto it fires its own "leave" on the popover's
            # motion controller every time, not just once on open, so
            # this has to be a standing guard (re-armed on close in
            # _on_combo_popup_shown), not a one-shot cancel.
            return
        self.cancel_hide()
        self._toolbar_hide_id = GLib.timeout_add(200, self._hide_toolbar)

    def _hide_toolbar(self) -> bool:
        self.set_reveal_child(False)
        for popover in self._all_popovers():
            popover.popdown()
        self._toolbar_hide_id = 0
        return False  # one-shot

    def notify_video_hover_enter(self, has_camera: bool) -> None:
        """Called by the owning CameraSlot when the pointer enters the
        video area (not this toolbar itself)."""
        self.cancel_hide()
        self.set_reveal_child(has_camera)

    def notify_video_hover_leave(self) -> None:
        """Called by the owning CameraSlot when the pointer leaves the
        video area."""
        self.schedule_hide()

    def assign(self, camera: Camera) -> None:
        self._mute_btn.set_visible(camera.has_audio)
        self._mic_btn.set_visible(camera.has_speaker)
        self._ptz_btn.set_visible(camera.is_ptz)
        self._zoom_btn.set_visible(camera.is_ptz)
        self._focus_btn.set_visible(camera.is_ptz)
        self._preset_btn.set_visible(camera.is_ptz)
        self._patrol_btn.set_visible(camera.is_ptz)

    def clear(self) -> None:
        self.player.set_mute(True)
        self.update_mute_icon()
        self._mute_btn.set_visible(False)
        self._mic_btn.set_visible(False)
        self._ptz_btn.set_visible(False)
        self._zoom_btn.set_visible(False)
        self._focus_btn.set_visible(False)
        self._preset_btn.set_visible(False)
        self._patrol_btn.set_visible(False)
        self._preset_combo.remove_all()
        self._stop_patrol()  # cancels the GLib timer so it can't outlive this camera
        self._patrols = []
        self._patrol_combo.remove_all()
        self.cancel_hide()
        self._hide_toolbar()
