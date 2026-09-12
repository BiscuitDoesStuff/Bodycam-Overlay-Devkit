"""Host / Create Match tab."""
import tkinter as tk
from tkinter import ttk, messagebox

import game_api as api
import ui_theme as ui
from ui_theme import PANEL, FG, MUTED, BAD, PAD, PAD_SM, PAD_MD, PAD_XS
from ui_common import load_ui_state, save_ui_state, make_scrollable, FILTER_DEBOUNCE_MS, set_text


class HostTab(ttk.Frame):
    # Fixed iids for Treeview category rows -- distinct from any real map/mode
    # name (the \x00 prefix can't appear in one), so a selection is a category
    # iff it's one of these.
    CAT_PLAYLIST = "\x00cat_playlist"
    CAT_DEV = "\x00cat_dev"
    CAT_UNCONFIRMED_MAP = "\x00cat_unconfirmed_map"
    CAT_GM_WORKING = "\x00cat_gm_working"
    CAT_GM_UNTESTED = "\x00cat_gm_untested"
    CAT_GM_NO_CONTENT = "\x00cat_gm_no_content"
    CAT_GM_BROKEN = "\x00cat_gm_broken"
    _GM_CATEGORY_IIDS = (CAT_GM_WORKING, CAT_GM_UNTESTED, CAT_GM_NO_CONTENT, CAT_GM_BROKEN)

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.maps = api.list_maps()
        self.gamemodes = api.list_gamemodes()
        self.last_hosted = None  # dict remembered for Cycle
        self._map_filter_after_id = None

        left = ui.frame(self)
        left.pack(side="left", fill="both", expand=True, padx=PAD, pady=PAD)
        right_outer = ui.frame(self, panel=True, width=270)
        right_outer.pack(side="right", fill="y", padx=(0, PAD), pady=PAD)
        right_outer.pack_propagate(False)
        right = make_scrollable(right_outer, panel=True)

        ui.label(left, text="Map", bold=True).pack(anchor="w")

        filter_row = ui.frame(left)
        filter_row.pack(fill="x", pady=(PAD_SM, PAD_SM))
        # Plain text, not the U+1F50D magnifying-glass emoji -- that's outside
        # the Basic Multilingual Plane and renders as a box on Tk 8.6.
        ui.label(filter_row, text="Filter:", muted=True).pack(side="left")
        self.map_filter_var = tk.StringVar()
        filter_entry = ui.entry(filter_row, textvariable=self.map_filter_var)
        filter_entry.pack(side="left", fill="x", expand=True, padx=(PAD_XS, 0))
        filter_entry.bind("<KeyRelease>", self._on_map_filter_keyrelease)

        map_frame = ui.frame(left)
        map_frame.pack(fill="both", expand=True)
        map_scroll = ui.scrollbar(map_frame)
        map_scroll.pack(side="right", fill="y")
        self.map_tree = ui.treeview(map_frame, show="tree", selectmode="browse",
                                     height=9, yscrollcommand=map_scroll.set)
        self.map_tree.column("#0", stretch=True)
        self.map_tree.pack(side="left", fill="both", expand=True)
        map_scroll.config(command=self.map_tree.yview)
        self.map_tree.tag_configure("map_unconfirmed", foreground=MUTED)
        self.map_tree.bind("<Double-Button-1>", self._on_map_double_click)
        self.map_tree.bind("<Return>", self._on_map_double_click)
        self.map_tree.bind("<<TreeviewSelect>>", self._on_map_select)

        self.map_note_var = tk.StringVar()
        ui.label(left, textvariable=self.map_note_var, muted=True, wraplength=400,
                 justify="left").pack(anchor="w", fill="x", pady=(PAD_XS, 0))

        ui.label(left, text="Gamemode", bold=True).pack(anchor="w", pady=(PAD, 0))
        gm_frame = ui.frame(left)
        gm_frame.pack(fill="x", pady=(PAD_SM, 0))
        gm_scroll = ui.scrollbar(gm_frame)
        gm_scroll.pack(side="right", fill="y")
        self.gamemode_tree = ui.treeview(gm_frame, show="tree", selectmode="browse",
                                          height=5, yscrollcommand=gm_scroll.set)
        self.gamemode_tree.column("#0", stretch=True)
        self.gamemode_tree.pack(side="left", fill="x", expand=True)
        gm_scroll.config(command=self.gamemode_tree.yview)
        self.gamemode_tree.tag_configure("gm_working", foreground=FG)
        self.gamemode_tree.tag_configure("gm_untested", foreground=MUTED)
        self.gamemode_tree.tag_configure("gm_no_content", foreground=MUTED)
        self.gamemode_tree.tag_configure("gm_broken", foreground=MUTED)
        self.gamemode_tree.bind("<<TreeviewSelect>>", self._on_gamemode_select)
        self.gamemode_tree.bind("<Double-Button-1>", self._on_gamemode_double_click)

        self.gamemode_note_var = tk.StringVar()
        ui.label(left, textvariable=self.gamemode_note_var, muted=True, wraplength=400,
                 justify="left").pack(anchor="w", fill="x", pady=(PAD_XS, 0))

        row = ui.frame(left)
        row.pack(fill="x", pady=(PAD, 0))

        ui.label(row, text="Cap").grid(row=0, column=0, sticky="w")
        self.cap_var = tk.IntVar(value=7)
        ui.spinbox(row, from_=1, to=64, textvariable=self.cap_var, width=6).grid(
            row=0, column=1, sticky="w", padx=PAD_MD)

        ui.label(row, text="Team Cap").grid(row=1, column=0, sticky="w", pady=(PAD_MD, 0))
        self.team_var = tk.IntVar(value=1)
        self.team_spin = ui.spinbox(row, from_=1, to=32, textvariable=self.team_var, width=6)
        self.team_spin.grid(row=1, column=1, sticky="w", padx=PAD_MD, pady=(PAD_MD, 0))

        self.private_var = tk.BooleanVar(value=False)
        ui.checkbutton(row, text="Private", variable=self.private_var).grid(
            row=2, column=0, sticky="w", pady=(PAD_MD, 0))
        self.bots_var = tk.BooleanVar(value=True)
        ui.checkbutton(row, text="Bots", variable=self.bots_var).grid(
            row=2, column=1, sticky="w", pady=(PAD_MD, 0))

        row.columnconfigure(1, weight=1)

        ui.button(left, "Load Custom Match", kind="accent", command=self._load_match).pack(
            fill="x", pady=(PAD + 2, 0))
        # Persistent, not just a status-bar mention -- the status bar gets
        # overwritten by the very next thing that happens (a poll tick, any
        # other button), which would make the password unrecoverable.
        self.session_password_lbl = ui.label(left, text="", muted=True)
        self.session_password_lbl.pack(anchor="w", pady=(PAD_SM, 0))

        # right column: cycle + live state
        ui.label(right, text="Live State", bg=PANEL, bold=True).pack(anchor="w", padx=PAD, pady=(PAD, 0))
        self.state_box = ui.text(right, width=28, height=10, state="disabled")
        self.state_box.pack(padx=PAD, pady=(PAD_SM, PAD))

        ui.button(right, "Refresh State", command=self._refresh_state).pack(fill="x", padx=PAD)
        ui.button(right, "Reload Maps/Modes (from disk)", command=self._reload_config).pack(
            fill="x", padx=PAD, pady=(PAD_SM, 0))
        ui.button(right, "↻  Cycle Current Match", kind="accent", command=self._cycle).pack(
            fill="x", padx=PAD, pady=(PAD, 0))
        ui.button(right, "Force Round End", command=self._force_end).pack(
            fill="x", padx=PAD, pady=(PAD, PAD))

        ttk.Separator(right, orient="horizontal").pack(fill="x", padx=PAD, pady=(0, PAD))

        # Match Info -- read-only extras beyond Live State (match-started/ended,
        # lobby privacy, host-migration, server SteamID, your own team/K/D/
        # score/rank via GetPcInfo). Confirmed live 2026-09-07 -- see
        # get_match_info()'s docstring in game_api.py for exactly what was
        # tested. Most of these fields (everything except started/ended) only
        # return real data from the Lobby -- they're declared on the Lobby's
        # own gamemode class and don't exist on a per-match one, so seeing
        # them go blank/n/a once you're actually in a match is expected, not
        # broken.
        ui.label(right, text="Match Info", bg=PANEL, bold=True).pack(
            anchor="w", padx=PAD, pady=(0, 0))
        self.match_info_box = ui.text(right, width=28, height=10, state="disabled")
        self.match_info_box.pack(padx=PAD, pady=(PAD_SM, PAD_SM))
        ui.button(right, "Refresh Match Info", command=self._refresh_match_info).pack(fill="x", padx=PAD)

        ttk.Separator(right, orient="horizontal").pack(fill="x", padx=PAD, pady=PAD)

        # Roster -- connected players' names, read-only, via the base-engine
        # APlayerState:GetPlayerName() (safe to assume it exists on any UE
        # game), plus a per-connected-player team/K/D/score block (Lobby only)
        # via get_lobby_roster() -- see that function's docstring: it's
        # untested against real multiple players, shown by connection slot
        # rather than matched to the names above, since there's no safe way
        # to correlate the two lists without touching a field known to crash.
        self.roster_label_var = tk.StringVar(value="Roster")
        self.roster_label = ui.label(right, textvariable=self.roster_label_var, bg=PANEL, bold=True)
        self.roster_label.pack(anchor="w", padx=PAD, pady=(0, 0))
        self.roster_list = ui.listbox(right, width=28, height=6)
        self.roster_list.pack(padx=PAD, pady=(PAD_SM, PAD_SM))
        ui.button(right, "Refresh Roster", command=self._refresh_roster).pack(fill="x", padx=PAD, pady=(0, PAD))

        ttk.Separator(right, orient="horizontal").pack(fill="x", padx=PAD, pady=(0, PAD))

        ui.button(right, "Discover More Gamemodes...", command=self._discover_gamemodes).pack(
            fill="x", padx=PAD, pady=(0, PAD))

        ttk.Separator(right, orient="horizontal").pack(fill="x", padx=PAD, pady=(0, PAD))

        # Match Control -- found via the UE4SS SDK dump (2026-09-07), not
        # reflection guesswork: the game ships its own developer CheatManager
        # (pc.CheatManager, same object SpeedTab's Slomo already reaches) and
        # a real weather-forcing path (GameState.WeatherManagerComponent).
        # All confirmed live individually (see game_api.py's docstrings for
        # exactly what was independently observed vs. just "didn't error").
        # Every action here affects the whole match, not just you, so all of
        # them route through _guard_other_players the same as Load Custom
        # Match / Cycle / Force Round End.
        ui.label(right, text="Match Control", bg=PANEL, bold=True).pack(
            anchor="w", padx=PAD, pady=(0, 0))

        weather_row = ui.frame(right, panel=True)
        weather_row.pack(fill="x", padx=PAD, pady=(PAD_SM, PAD_SM))
        self.weather_var = tk.StringVar()
        self.weather_cb = ttk.Combobox(weather_row, textvariable=self.weather_var,
                                        state="readonly", width=14)
        self.weather_cb.pack(side="left", fill="x", expand=True)
        ui.button(weather_row, "Set Weather", command=self._set_weather).pack(
            side="left", padx=(PAD_SM, 0))
        ui.button(right, "Refresh Weather List", command=self._refresh_weather_list).pack(
            fill="x", padx=PAD)

        timer_row = ui.frame(right, panel=True)
        timer_row.pack(fill="x", padx=PAD, pady=(PAD, PAD_SM))
        ui.label(timer_row, text="Timer (s)", bg=PANEL).pack(side="left")
        self.game_timer_var = tk.IntVar(value=1)
        ui.spinbox(timer_row, from_=0, to=600, textvariable=self.game_timer_var, width=6).pack(
            side="left", padx=(PAD_SM, PAD_SM))
        ui.button(timer_row, "Set (Skip Pre-Match)", command=self._set_game_timer).pack(
            side="left", fill="x", expand=True)

        ui.button(right, "End Round", command=self._end_round).pack(
            fill="x", padx=PAD, pady=(PAD_SM, 0))

        end_match_row = ui.frame(right, panel=True)
        end_match_row.pack(fill="x", padx=PAD, pady=(PAD_SM, PAD))
        ui.button(end_match_row, "End Match: Win", command=lambda: self._end_match(True)).pack(
            side="left", fill="x", expand=True, padx=(0, PAD_SM // 2))
        ui.button(end_match_row, "End Match: Lose", command=lambda: self._end_match(False)).pack(
            side="left", fill="x", expand=True, padx=(PAD_SM // 2, 0))

        self._populate_map_tree()
        self._populate_gamemode_tree()
        self._apply_saved_state()
        # _refresh_weather_list()/_refresh_state() are game RPCs -- deferred to
        # App._poll_connection's first successful ping, not fired here (see its
        # comment: avoids a startup pile-up on bridge_client's request lock).

    def _populate_map_tree(self, filter_text=""):
        """Rebuilds the map tree under three real category rows (Playlist /
        Dev-Unreleased / Unconfirmed) instead of the old single flat list
        with a fake "--- non-playlist / dev maps ---" text row acting as a
        divider -- that row was itself a selectable listbox entry that
        _selected_map() had to special-case by string prefix. A category row
        here is a distinct, non-pickable tree node. Every map in maps.json is
        shown regardless of status=='unconfirmed' -- nothing about the game's
        own content is hidden, the category just tells you which ones haven't
        actually been reached live yet (see maps.json's own notes)."""
        self.map_tree.delete(*self.map_tree.get_children())
        q = filter_text.lower().strip()
        unconfirmed = sorted(n for n, i in self.maps.items() if i.get("status") == "unconfirmed")
        playlist = sorted(n for n, i in self.maps.items() if i["playlist"] and i.get("status") != "unconfirmed")
        dev = sorted(n for n, i in self.maps.items()
                     if not i["playlist"] and i.get("status") != "unconfirmed")
        if q:
            playlist = [n for n in playlist if q in n.lower()]
            dev = [n for n in dev if q in n.lower()]
            unconfirmed = [n for n in unconfirmed if q in n.lower()]

        self.map_tree.insert("", "end", iid=self.CAT_PLAYLIST, open=True, tags=("category",),
                              text=f"PLAYLIST MAPS  ({len(playlist)})")
        for n in playlist:
            self.map_tree.insert(self.CAT_PLAYLIST, "end", iid=n, text=n, tags=("map",))

        self.map_tree.insert("", "end", iid=self.CAT_DEV, open=True, tags=("category",),
                              text=f"DEV / UNRELEASED MAPS  ({len(dev)})")
        for n in dev:
            self.map_tree.insert(self.CAT_DEV, "end", iid=n, text=n, tags=("map",))

        if unconfirmed:
            self.map_tree.insert("", "end", iid=self.CAT_UNCONFIRMED_MAP, open=True, tags=("category",),
                                  text=f"UNCONFIRMED MAPS (guessed paths)  ({len(unconfirmed)})")
            for n in unconfirmed:
                self.map_tree.insert(self.CAT_UNCONFIRMED_MAP, "end", iid=n, text=n, tags=("map_unconfirmed",))

    def _on_map_filter_keyrelease(self, _evt=None):
        if self._map_filter_after_id is not None:
            self.after_cancel(self._map_filter_after_id)
        self._map_filter_after_id = self.after(FILTER_DEBOUNCE_MS, self._apply_map_filter)

    def _apply_map_filter(self):
        self._map_filter_after_id = None
        self._populate_map_tree(self.map_filter_var.get())

    def _on_map_double_click(self, _evt=None):
        iid = self.map_tree.focus()
        if not iid:
            return
        if iid in (self.CAT_PLAYLIST, self.CAT_DEV, self.CAT_UNCONFIRMED_MAP):
            self.map_tree.item(iid, open=not self.map_tree.item(iid, "open"))
            return
        self._load_match()

    def _on_map_select(self, _evt=None):
        name = self._selected_map()
        info = self.maps.get(name) if name else None
        note = info.get("note", "") if info else ""
        if info and info.get("status") == "unconfirmed":
            self.map_note_var.set("⚠ UNCONFIRMED PATH: " + (note or "never successfully reached live."))
        else:
            self.map_note_var.set(note)

    def _populate_gamemode_tree(self):
        """Groups every gamemode by its 'status' field (working / untested /
        no_content / broken) into real category rows, same pattern as
        _populate_map_tree. Every gamemode DT_GamemodeInfo/DT_GameModeData
        lists is shown regardless of status -- non-working ones aren't
        hidden, they're just visibly flagged (muted text + the note shown
        under the tree when selected) so nothing is silently presented as
        equivalent to the confirmed-working modes. 'no_content' is distinct
        from 'broken': it means the class/asset exists (LoadAsset +
        StaticFindObject resolves it) but hosting into it demonstrably never
        engages it as the active gamemode -- a leftover reference with no
        real playable content, not a bug in something that actually runs.
        'broken' is reserved for a mode that DOES engage but has an actual
        problem during play -- see gamemodes.json's own comment for the full
        definitions."""
        self.gamemode_tree.delete(*self.gamemode_tree.get_children())
        groups = {"working": [], "untested": [], "no_content": [], "broken": []}
        for name, info in self.gamemodes.items():
            groups.setdefault(info.get("status", "working"), []).append(name)
        for names in groups.values():
            names.sort()

        for status_key, cat_iid, label in (
            ("working", self.CAT_GM_WORKING, "WORKING"),
            ("untested", self.CAT_GM_UNTESTED, "UNTESTED"),
            ("no_content", self.CAT_GM_NO_CONTENT, "NO CONTENT (class exists, not implemented)"),
            ("broken", self.CAT_GM_BROKEN, "BROKEN"),
        ):
            names = groups.get(status_key, [])
            if not names:
                continue
            self.gamemode_tree.insert("", "end", iid=cat_iid, open=(status_key == "working"),
                                       tags=("category",), text=f"{label}  ({len(names)})")
            for name in names:
                self.gamemode_tree.insert(cat_iid, "end", iid=name, text=name,
                                           tags=(f"gm_{status_key}",))

    def _selected_gamemode(self):
        sel = self.gamemode_tree.selection()
        if not sel or sel[0] in self._GM_CATEGORY_IIDS:
            return None
        return sel[0]

    def _select_gamemode(self, name):
        """Selects `name` in the gamemode tree if it exists, expanding its
        category first (a collapsed category's children aren't selectable)."""
        if name not in self.gamemodes:
            return False
        parent = self.gamemode_tree.parent(name) if self.gamemode_tree.exists(name) else None
        if parent:
            self.gamemode_tree.item(parent, open=True)
        try:
            self.gamemode_tree.selection_set(name)
            self.gamemode_tree.see(name)
            return True
        except tk.TclError:
            return False

    def _on_gamemode_double_click(self, _evt=None):
        iid = self.gamemode_tree.focus()
        if not iid:
            return
        if iid in self._GM_CATEGORY_IIDS:
            self.gamemode_tree.item(iid, open=not self.gamemode_tree.item(iid, "open"))

    def _on_gamemode_select(self, _evt=None):
        name = self._selected_gamemode()
        if not name:
            self.gamemode_note_var.set("")
            return
        info = self.gamemodes[name]
        self.cap_var.set(info["default_cap"])
        self.team_var.set(info["default_team_size"])
        self.team_spin.configure(state="normal" if info["team_based"] else "disabled")
        status = info.get("status", "working")
        note = info.get("note", "")
        if status == "broken":
            self.gamemode_note_var.set("✗ BROKEN: " + (note or "confirmed not to work."))
        elif status == "no_content":
            self.gamemode_note_var.set("⊘ NO CONTENT: " + (note or "class exists but isn't wired up as a real mode."))
        elif status == "untested":
            self.gamemode_note_var.set("⚠ UNTESTED: " + (note or "class exists but never confirmed live."))
        else:
            self.gamemode_note_var.set(note)

    def _apply_saved_state(self):
        """Restores the last map/gamemode/cap/team/private/bots this tab was
        used with, so relaunching the overlay doesn't reset every field back
        to defaults. Written by _load_match() on every successful load; see
        load_ui_state()/save_ui_state() near the top of this file."""
        state = load_ui_state()
        mode = state.get("gamemode")
        if not (mode and self._select_gamemode(mode)):
            # nothing saved (or it's gone from gamemodes.json) -- fall back to
            # the first working mode rather than leaving the tree unselected.
            working = sorted(n for n, i in self.gamemodes.items() if i.get("status", "working") == "working")
            if working:
                self._select_gamemode(working[0])
        if "cap" in state:
            self.cap_var.set(state["cap"])
        if "team" in state:
            self.team_var.set(state["team"])
        if "private" in state:
            self.private_var.set(bool(state["private"]))
        if "bots" in state:
            self.bots_var.set(bool(state["bots"]))

        name = state.get("map")
        if name and name in self.maps:
            try:
                self.map_tree.selection_set(name)
                self.map_tree.see(name)
            except tk.TclError:
                pass  # map no longer exists in the current maps.json -- fine, just skip
            self.last_hosted = dict(map_path=self.maps[name]["path"],
                                     private=bool(state.get("private", False)),
                                     bots=bool(state.get("bots", True)))

    def _reload_config(self):
        api.reload_configs()
        self.maps = api.list_maps()
        self.gamemodes = api.list_gamemodes()

        self._populate_map_tree(self.map_filter_var.get())
        self._populate_gamemode_tree()
        self.app.status(f"Reloaded config: {len(self.maps)} maps, {len(self.gamemodes)} gamemodes")

    def _selected_map(self):
        sel = self.map_tree.selection()
        if not sel or sel[0] in (self.CAT_PLAYLIST, self.CAT_DEV, self.CAT_UNCONFIRMED_MAP):
            return None
        return sel[0]

    def _guard_other_players(self, action_label, on_proceed):
        """Checks the live roster before letting a disruptive action through
        (Load Custom Match / Cycle / Force Round End all route through this).
        Added 2026-09-07 after a near-miss: we almost ran gamemode-switch
        tests against a live match that turned out to have 5 real strangers
        in it, discovered only because the roster panel happened to be
        checked first. This does a FRESH roster read every time rather than
        trusting the passive Roster panel label, since that could be stale.

        Doesn't try to distinguish bots you spawned yourself from real other
        players -- no PlayerState property for that has been confirmed live
        (see get_player_roster()'s docstring). Erring toward one extra
        confirm click when it's actually just your own bots is the safe
        failure mode here; erring the other way is exactly what almost
        happened. If the roster can't even be read, fail safe by asking
        rather than silently proceeding."""
        def work():
            return api.get_player_roster()

        def done(roster):
            self._set_roster_label(len(roster))
            if len(roster) > 1:
                if messagebox.askyesno(
                        "Other players connected",
                        f"{len(roster)} players are currently connected:\n\n"
                        f"{', '.join(roster)}\n\n"
                        f"{action_label} will disrupt anyone else in this match "
                        "(or anyone else's bots -- there's no way yet to tell bots "
                        "from real players here). Continue?"):
                    on_proceed()
            else:
                on_proceed()

        def err(_e):
            if messagebox.askyesno(
                    "Couldn't check who's connected",
                    "Couldn't read the player roster, so there's no way to confirm "
                    f"you're alone right now.\n\n{action_label} anyway?"):
                on_proceed()

        self.app.runner.run(work, done, err)

    def _guard_then_run(self, guard_label, status_msg, work, done, err_label=None, refresh_delay=None):
        """Confirms via _guard_other_players, then runs work() through
        AsyncRunner -- collapses the proceed()/work()/done()/runner.run()
        wiring every disruptive action below otherwise repeats. Pass
        refresh_delay (ms) to schedule a Live State refresh after done()
        runs; err_label is forwarded to self.app.on_error()."""
        def proceed():
            self.app.status(status_msg)

            def _done(result):
                done(result)
                if refresh_delay is not None:
                    self.app.root.after(refresh_delay, self._refresh_state)

            self.app.runner.run(work, _done, self.app.on_error(err_label) if err_label else self.app.on_error())

        self._guard_other_players(guard_label, proceed)

    def _load_match(self):
        name = self._selected_map()
        if not name:
            messagebox.showwarning("No map selected", "Pick a map from the list first.")
            return
        mode_name = self._selected_gamemode()
        if not mode_name:
            messagebox.showwarning("No gamemode selected", "Pick a gamemode from the list first.")
            return
        mode_info = self.gamemodes[mode_name]
        status = mode_info.get("status", "working")
        if status != "working":
            note = mode_info.get("note", "no details recorded.")
            kind = {"broken": "BROKEN", "no_content": "NO CONTENT"}.get(status, "UNTESTED")
            if not messagebox.askyesno(
                    f"{kind} gamemode",
                    f"'{mode_name}' is marked {kind.lower()}:\n\n{note}\n\n"
                    "Load it anyway?"):
                return
        map_info = self.maps[name]
        if map_info.get("status") == "unconfirmed" and not messagebox.askyesno(
                "Unconfirmed map",
                f"'{name}'s path has never been confirmed to actually load:\n\n"
                f"{map_info.get('note', 'no details recorded.')}\n\nTry anyway?"):
            return
        map_path = map_info["path"]
        gm_class = mode_info["class"]
        cap = self.cap_var.get()
        team = self.team_var.get() if mode_info["team_based"] else None
        private = self.private_var.get()
        bots = self.bots_var.get()

        def done(result):
            self.last_hosted = dict(map_path=map_path, private=private, bots=bots)
            save_ui_state({"map": name, "gamemode": mode_name, "cap": cap,
                             "team": team or 1, "private": private, "bots": bots})
            self.session_password_lbl.configure(
                text=f"Session password: {api.SESSION_PASSWORD}" if private else "")
            self.app.status(f"Loaded {name}: {result}")

        self._guard_then_run(
            "Loading a custom match", f"Loading {name} ({mode_name})...",
            lambda: api.host_and_travel(map_path, gm_class, cap, team or 1, private, bots),
            done, err_label="ERROR loading match", refresh_delay=4000)

    def _refresh_state(self):
        def work():
            return api.get_live_state()

        def done(state):
            if not state.get("in_match"):
                body = "Not in a match\n(in Lobby / menu)"
            else:
                body = "".join(f"{k}: {state.get(k)}\n" for k in
                                ("mode_name", "phase", "count", "max", "team_size"))
            set_text(self.state_box, body)

        self.app.runner.run(work, done, self.app.on_error("state check failed"))

    def _cycle(self):
        fallback = self.last_hosted["map_path"] if self.last_hosted else None
        private = self.last_hosted["private"] if self.last_hosted else False
        bots = self.last_hosted["bots"] if self.last_hosted else True
        self._guard_then_run(
            "Cycling the current match", "Cycling current match...",
            lambda: api.cycle_match(fallback_map_path=fallback, private=private, bots=bots),
            lambda result: self.app.status(
                f"Cycled: {result['mode_name']} cap={result['cap']} team={result['team_size']}"),
            err_label="ERROR cycling", refresh_delay=4000)

    def _force_end(self):
        self._guard_then_run(
            "Forcing the round to end", "Forcing round end...",
            api.force_round_end,
            lambda result: self.app.status(f"Round end: {result}"),
            refresh_delay=2000)

    def _refresh_match_info(self):
        def work():
            return api.get_match_info()

        def done(info):
            if info is None:
                body = "Not in a match\n(in Lobby / menu)"
            else:
                body = "".join(f"{k}: {v}\n" for k, v in info.items())
            set_text(self.match_info_box, body)

        self.app.runner.run(work, done, self.app.on_error("match info check failed"))

    def _refresh_roster(self):
        def work():
            return api.get_player_roster(), api.get_lobby_roster()

        def done(result):
            names, lobby_info = result
            self.roster_list.delete(0, tk.END)
            if not names:
                self.roster_list.insert(tk.END, "(none found)")
            for n in names:
                self.roster_list.insert(tk.END, n)
            if lobby_info:
                # Untested with real multiple players as of this writing (see
                # get_lobby_roster()'s docstring) -- shown by connection index,
                # NOT matched up with the names above (no safe shared key to
                # correlate them without touching fields known to crash).
                self.roster_list.insert(tk.END, "--- Lobby team/K-D-S (by slot, unmatched to names) ---")
                for entry in lobby_info:
                    line = (f"#{entry.get('index', '?')}: team={entry.get('team', '?')} "
                            f"K={entry.get('kills', '?')} D={entry.get('deaths', '?')} "
                            f"S={entry.get('score', '?')}")
                    self.roster_list.insert(tk.END, line)
            self._set_roster_label(len(names))

        self.app.runner.run(work, done, self.app.on_error("roster check failed"))

    def _set_roster_label(self, count):
        """Passive ambient cue on the Roster header -- doesn't gate anything
        itself (that's _guard_other_players, checked fresh right before an
        actually disruptive action), just keeps you aware between actions."""
        if count > 1:
            self.roster_label_var.set(f"Roster — ⚠ {count} connected")
            self.roster_label.configure(fg=BAD)
        else:
            self.roster_label_var.set("Roster")
            self.roster_label.configure(fg=FG)

    def _refresh_weather_list(self):
        def work():
            return api.list_weather_presets()

        def done(names):
            self.weather_cb.configure(values=names)
            if names and not self.weather_var.get():
                self.weather_var.set(names[0])

        self.app.runner.run(work, done, self.app.on_error("weather list failed"))

    def _set_weather(self):
        name = self.weather_var.get()
        if not name:
            messagebox.showwarning("No weather selected", "Pick a weather preset first.")
            return
        self._guard_then_run(
            f"Changing the weather to {name}", f"Setting weather to {name}...",
            lambda: api.set_weather(name),
            lambda _result: self.app.status(f"Weather set to {name}"),
            err_label="ERROR setting weather")

    def _set_game_timer(self):
        seconds = self.game_timer_var.get()
        self._guard_then_run(
            f"Setting the round timer to {seconds}s", f"Setting round timer to {seconds}s...",
            lambda: api.set_game_timer(seconds),
            lambda _result: self.app.status(f"Round timer set to {seconds}s"),
            err_label="ERROR setting timer", refresh_delay=2000)

    def _end_round(self):
        self._guard_then_run(
            "Ending the current round", "Ending round (CheatEndRound)...",
            api.end_round,
            lambda _result: self.app.status("Round ended"),
            err_label="ERROR ending round", refresh_delay=3000)

    def _end_match(self, victory):
        label = "Win" if victory else "Lose"
        self._guard_then_run(
            f"Ending the match ({label})", f"Ending match ({label})...",
            lambda: api.end_match(victory),
            lambda _result: self.app.status(f"Match ended ({label})"),
            err_label="ERROR ending match", refresh_delay=3000)

    def _discover_gamemodes(self):
        """Probes for gamemode classes DT_GamemodeInfo/DT_GameModeData list
        (Zombie, Pit, Training, OnlyPistol) that aren't in gamemodes.json yet,
        via LoadAsset + StaticFindObject -- see api.discover_extra_gamemodes()'s
        docstring for why that's safe to run blind (it only loads a package,
        never constructs/spawns anything). A hit just means the class path is
        real; cap/team-size defaults below are guesses you should sanity-check
        in-game before relying on them."""
        self.app.status("Probing for undocumented gamemode classes (this can take a moment)...")

        def work():
            return api.discover_extra_gamemodes()

        def done(found):
            hits = {name: path for name, path in found.items() if path}
            if not hits:
                self.app.status("Discover Gamemodes: no additional classes resolved.")
                messagebox.showinfo(
                    "Discover Gamemodes",
                    "None of the candidate class paths resolved to a real class right now.\n\n"
                    "This can mean the mode genuinely isn't reachable, or its class simply "
                    "isn't loaded and LoadAsset's guessed path was wrong -- the actual folder "
                    "layout can only be confirmed by finding it live.")
                return
            self.app.status(f"Discover Gamemodes: found {len(hits)} -- {', '.join(hits)}")
            for name, class_path in hits.items():
                if name in self.gamemodes:
                    continue
                if messagebox.askyesno(
                        "Add gamemode?",
                        f"Found a class for '{name}':\n{class_path}\n\n"
                        "Add it to gamemodes.json with a default cap of 8 (non-team), "
                        "listed under UNTESTED? You can hand-edit team_based/cap/team_size/"
                        "status afterward in %LOCALAPPDATA%\\BodycamOverlay\\gamemodes.json -- "
                        "this hasn't been tested in an actual match yet."):
                    api.add_gamemode(name, class_path)
            self.gamemodes = api.list_gamemodes()
            self._populate_gamemode_tree()

        self.app.runner.run(work, done, self.app.on_error("gamemode discovery failed"))


