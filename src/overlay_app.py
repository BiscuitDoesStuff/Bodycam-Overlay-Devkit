"""Bodycam control overlay -- a separate desktop window (NOT injected into the
game process), toggled with the Insert key. Requires the game to run in
windowed or borderless mode so this window can sit visually on top of it.

Run with:  python src/overlay_app.py
Requires the game to be running with the ClaudeBridge UE4SS mod loaded.
"""
import json
import logging
import logging.handlers
import os
import queue
import socket
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import keyboard  # global hotkey
import pystray
from PIL import Image, ImageDraw

import game_api as api
import shell_client
import install_bridge
import ui_theme as ui
from ui_theme import BG, PANEL, INPUT, FG, MUTED, ACCENT, GOOD, BAD, BORDER, CONSOLE_BG, PAD, PAD_SM, PAD_LG

# A --windowed PyInstaller build has no console: print() output (and, in some
# builds, an unhandled exception's default stderr traceback) goes nowhere.
# Log to a capped file instead so a crash/error is diagnosable after the fact.
_log_handler = logging.handlers.RotatingFileHandler(
    os.path.join(api._CONFIG_DIR, "overlay.log"), maxBytes=1_000_000, backupCount=2, encoding="utf-8")
_log_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
logging.getLogger().addHandler(_log_handler)
logging.getLogger().setLevel(logging.INFO)

# Small persisted "remember what I last picked" file -- Host tab restores its
# map/gamemode/cap/team/private/bots selections from this on the next launch
# instead of always resetting to the defaults. Lives alongside the app's other
# per-user files (families.json, snippets.json, ...) in the same config dir.
_UI_STATE_PATH = os.path.join(api._CONFIG_DIR, "ui_state.json")


def _load_ui_state():
    try:
        with open(_UI_STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_ui_state(partial):
    state = _load_ui_state()
    state.update(partial)
    try:
        with open(_UI_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except OSError:
        pass


# How long to wait, after the last keystroke, before a PickerDialog actually
# re-filters its list. Without this, filtering the ~2100-row shop-item catalog
# reruns a full scan + Listbox repopulate on every single keypress; a fast
# typist can queue up several of those before any of them finish.
_FILTER_DEBOUNCE_MS = 120


class AsyncRunner:
    """Runs blocking calls off the Tk main thread; delivers results back via after()."""

    def __init__(self, root):
        self.root = root
        self.q = queue.Queue()
        self._poll()

    def run(self, fn, on_done=None, on_error=None):
        def worker():
            try:
                result = fn()
                self.q.put(("ok", result, on_done, on_error))
            except Exception as e:  # noqa: BLE001
                self.q.put(("err", e, on_done, on_error))

        threading.Thread(target=worker, daemon=True).start()

    def _poll(self):
        try:
            while True:
                kind, payload, on_done, on_error = self.q.get_nowait()
                if kind == "ok" and on_done:
                    on_done(payload)
                elif kind == "err" and on_error:
                    on_error(payload)
                elif kind == "err":
                    logging.error("Unhandled async error", exc_info=payload)
        except queue.Empty:
            pass
        self.root.after(80, self._poll)


class PickerDialog(tk.Toplevel):
    """A search-as-you-type scrollable list picker. Calls on_pick(value) and closes."""

    def __init__(self, parent, title, items, on_pick):
        super().__init__(parent)
        self.title(title)
        self.configure(bg=BG)
        self.geometry("420x480")
        self.attributes("-topmost", True)
        self.on_pick = on_pick
        self.all_items = sorted(items)
        self._filter_after_id = None

        self.bind("<Escape>", lambda e: self.destroy())

        self.search_var = tk.StringVar()
        entry = ui.entry(self, textvariable=self.search_var)
        entry.pack(fill="x", padx=PAD, pady=PAD)
        entry.bind("<KeyRelease>", self._on_keyrelease)
        entry.bind("<Down>", lambda e: (self.listbox.focus_set(), self.listbox.selection_set(0)))
        entry.focus_set()

        self.listbox = ui.listbox(self)
        self.listbox.pack(fill="both", expand=True, padx=PAD, pady=(0, PAD))
        self.listbox.bind("<Double-Button-1>", self._pick)
        entry.bind("<Return>", self._pick)

        self._populate(self.all_items)

    def _pick(self, _evt=None):
        sel = self.listbox.curselection()
        # Enter with nothing explicitly selected picks the top filtered result --
        # the common "type to narrow it down, hit Enter" flow shouldn't require
        # also clicking or arrowing onto the one match left.
        if not sel and self.listbox.size() > 0:
            sel = (0,)
        if not sel:
            return
        value = self.listbox.get(sel[0])
        self.destroy()
        self.on_pick(value)

    def _populate(self, items):
        self.listbox.delete(0, tk.END)
        for it in items:
            self.listbox.insert(tk.END, it)

    def _on_keyrelease(self, _evt=None):
        if self._filter_after_id is not None:
            self.after_cancel(self._filter_after_id)
        self._filter_after_id = self.after(_FILTER_DEBOUNCE_MS, self._filter)

    def _filter(self):
        self._filter_after_id = None
        q = self.search_var.get().lower()
        self._populate([it for it in self.all_items if q in it.lower()])


class SaveButtonDialog(tk.Toplevel):
    """Prompts for a name and Run Once/Toggle when saving a console snippet as
    a reusable button. A toggle button renders as a checkbox and injects
    `local TOGGLE_ON = true/false` ahead of the snippet's own code on every
    click, so a single saved script (checking TOGGLE_ON itself) drives both
    states -- the same shape as the built-in bot-fill/explosive-bullets
    toggles, just authored by whoever wrote the snippet."""

    def __init__(self, parent, on_save, categories=None, initial_category=""):
        super().__init__(parent)
        self.title("Save as Button")
        self.configure(bg=BG)
        self.attributes("-topmost", True)
        self.on_save = on_save
        self.bind("<Escape>", lambda e: self.destroy())

        ui.label(self, text="Button name:").pack(anchor="w", padx=PAD_LG - 6, pady=(PAD_LG - 6, PAD_SM))
        self.name_var = tk.StringVar()
        entry = ui.entry(self, textvariable=self.name_var, width=32)
        entry.pack(padx=PAD_LG - 6, fill="x")
        entry.focus_set()

        self.mode_var = tk.StringVar(value="run_once")
        ui.radiobutton(self, text="Run Once", variable=self.mode_var, value="run_once").pack(
            anchor="w", padx=PAD_LG - 6, pady=(PAD_LG - 6, 0))
        ui.radiobutton(self, text="Toggle (adds a checkbox; your code checks TOGGLE_ON)",
                       variable=self.mode_var, value="toggle").pack(anchor="w", padx=PAD_LG - 6)

        ui.label(self, text="Category (optional -- buttons sharing one can all be run together, "
                             "in order, from a single 'Run All'):").pack(
            anchor="w", padx=PAD_LG - 6, pady=(PAD_LG - 6, PAD_SM))
        self.category_var = tk.StringVar(value=initial_category)
        cat_combo = ttk.Combobox(self, textvariable=self.category_var, values=list(categories or []), width=30)
        cat_combo.pack(padx=PAD_LG - 6, fill="x")

        btn_row = ui.frame(self)
        btn_row.pack(pady=PAD_LG - 6)
        ui.button(btn_row, "Save", kind="good", command=self._save).pack(side="left", padx=6)
        ui.button(btn_row, "Cancel", command=self.destroy).pack(side="left")
        entry.bind("<Return>", lambda e: self._save())
        cat_combo.bind("<Return>", lambda e: self._save())

    def _save(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("Name required", "Enter a button name.", parent=self)
            return
        self.destroy()
        self.on_save(name, self.mode_var.get(), self.category_var.get().strip())


def render_command_widgets(parent, app, widgets, on_delete=None, selection_vars=None,
                            on_recategorize=None, toggle_vars=None):
    """Renders a list of {"widget": "button"/"label"/"separator", ...} specs
    into `parent`, one per row -- shared by SavedButtonsTab and each Plugins
    sub-tab so a Plugin file and a Saved Command Buttons export are the same
    shape. Pass on_delete(label) to add a per-row delete button (used for
    Saved Command Buttons; plugins are removed as a whole file instead).
    Pass a dict as selection_vars to add a plain checkbox to the left of every
    button row -- filled in as {label: BooleanVar} so the caller can read back
    which rows are checked (used for Export Selected). Pass on_recategorize(spec)
    to add a per-row "Category..." button (Saved Command Buttons only -- a
    plugin file has no per-button category concept). Pass a dict as
    toggle_vars to have every toggle-mode row's on/off BooleanVar recorded
    into it as {label: BooleanVar}, so a caller can flip one's visible state
    (e.g. after force-running it as part of a category) without a full
    re-render, which would otherwise reset every toggle back to unchecked."""
    for spec in widgets:
        kind = spec.get("widget", "button")
        if kind == "label":
            ui.label(parent, text=spec.get("label", ""), bold=True).pack(
                anchor="w", padx=PAD_SM + 2, pady=(PAD_LG - 6, PAD_SM - 2))
            continue
        if kind == "separator":
            ttk.Separator(parent, orient="horizontal").pack(fill="x", padx=PAD_SM + 2, pady=PAD_SM + 2)
            continue

        label = spec.get("label", "?")
        code = spec.get("code", "")
        mode = spec.get("mode", "run_once")
        row = ui.frame(parent)
        row.pack(fill="x", padx=PAD_SM + 2, pady=2)

        if selection_vars is not None:
            sel_var = tk.BooleanVar(value=False)
            tk.Checkbutton(row, variable=sel_var, bg=BG, selectcolor=INPUT,
                           activebackground=BG, highlightthickness=0, bd=0,
                           ).pack(side="left", padx=(0, PAD_SM + 2))
            selection_vars[label] = sel_var

        var = tk.BooleanVar(value=False) if mode == "toggle" else None
        if var is not None and toggle_vars is not None:
            toggle_vars[label] = var

        def make_runner(code=code, mode=mode, label=label, var=var):
            def run():
                if mode == "toggle":
                    state = var.get()
                    prefixed = f"local TOGGLE_ON = {'true' if state else 'false'}\n{code}"
                else:
                    prefixed = code

                def work():
                    return api.run_raw_lua(prefixed)

                def done(result):
                    app.status(f"{label}: {result.strip() if result.strip() else 'OK'}")

                def err(e):
                    app.status(f"ERROR running {label}: {e}", bad=True)
                    if mode == "toggle":
                        var.set(not state)  # run failed -- the checkbox shouldn't have flipped

                app.runner.run(work, done, err)
            return run

        runner = make_runner()
        if mode == "toggle":
            ui.checkbutton(row, text=label, variable=var, command=runner, anchor="w").pack(
                side="left", fill="x", expand=True)
        else:
            ui.button(row, label, command=runner, anchor="w").pack(side="left", fill="x", expand=True)

        if on_delete:
            ui.button(row, "Delete", outline=True, command=lambda label=label: on_delete(label)
                      ).pack(side="right", padx=(PAD_SM, 0))
        if on_recategorize:
            ui.button(row, "Category...", command=lambda spec=spec: on_recategorize(spec)
                      ).pack(side="right", padx=(PAD_SM, 0))


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
        right = ui.frame(self, panel=True)
        right.pack(side="right", fill="y", padx=(0, PAD), pady=PAD)

        ui.label(left, text="Map", bold=True).pack(anchor="w")

        filter_row = ui.frame(left)
        filter_row.pack(fill="x", pady=(PAD_SM, PAD_SM))
        ui.label(filter_row, text="\U0001F50D", muted=True).pack(side="left")
        self.map_filter_var = tk.StringVar()
        filter_entry = ui.entry(filter_row, textvariable=self.map_filter_var)
        filter_entry.pack(side="left", fill="x", expand=True, padx=(PAD_SM - 2, 0))
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
                 justify="left").pack(anchor="w", fill="x", pady=(PAD_SM - 2, 0))

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
                 justify="left").pack(anchor="w", fill="x", pady=(PAD_SM - 2, 0))

        row = ui.frame(left)
        row.pack(fill="x", pady=(PAD, 0))

        ui.label(row, text="Cap").grid(row=0, column=0, sticky="w")
        self.cap_var = tk.IntVar(value=7)
        ui.spinbox(row, from_=1, to=64, textvariable=self.cap_var, width=6).grid(
            row=0, column=1, sticky="w", padx=PAD_SM + 2)

        ui.label(row, text="Team Cap").grid(row=1, column=0, sticky="w", pady=(PAD_SM + 2, 0))
        self.team_var = tk.IntVar(value=1)
        self.team_spin = ui.spinbox(row, from_=1, to=32, textvariable=self.team_var, width=6)
        self.team_spin.grid(row=1, column=1, sticky="w", padx=PAD_SM + 2, pady=(PAD_SM + 2, 0))

        self.private_var = tk.BooleanVar(value=False)
        ui.checkbutton(row, text="Private", variable=self.private_var).grid(
            row=2, column=0, sticky="w", pady=(PAD_SM + 2, 0))
        self.bots_var = tk.BooleanVar(value=True)
        ui.checkbutton(row, text="Bots", variable=self.bots_var).grid(
            row=2, column=1, sticky="w", pady=(PAD_SM + 2, 0))

        row.columnconfigure(1, weight=1)

        ui.button(left, "Load Custom Match", kind="accent", command=self._load_match).pack(
            fill="x", pady=(PAD + 2, 0))

        # right column: cycle + live state
        ui.label(right, text="Live State", bg=PANEL, bold=True).pack(anchor="w", padx=PAD, pady=(PAD, 0))
        self.state_box = ui.text(right, width=28, height=10, state="disabled")
        self.state_box.pack(padx=PAD, pady=(PAD_SM, PAD))

        ui.button(right, "Refresh State", command=self._refresh_state).pack(fill="x", padx=PAD)
        ui.button(right, "Reload Maps/Modes (from disk)", command=self._reload_config).pack(
            fill="x", padx=PAD, pady=(PAD_SM, 0))
        ui.button(right, "↻  Cycle Current Match", kind="good", command=self._cycle).pack(
            fill="x", padx=PAD, pady=(PAD, 0))
        ui.button(right, "Force Round End", command=self._force_end).pack(
            fill="x", padx=PAD, pady=(PAD, PAD))

        ttk.Separator(right, orient="horizontal").pack(fill="x", padx=PAD, pady=(0, PAD))

        # Match Info -- read-only extras beyond Live State (match-started/ended,
        # lobby privacy, host-migration, server SteamID). Confirmed live
        # 2026-09-07 -- see get_match_info()'s docstring in game_api.py for
        # exactly what was tested. server_steam_id reads empty until you're
        # actually hosting/in a session -- that's expected, not broken.
        ui.label(right, text="Match Info", bg=PANEL, bold=True).pack(
            anchor="w", padx=PAD, pady=(0, 0))
        self.match_info_box = ui.text(right, width=28, height=7, state="disabled")
        self.match_info_box.pack(padx=PAD, pady=(PAD_SM, PAD_SM))
        ui.button(right, "Refresh Match Info", command=self._refresh_match_info).pack(fill="x", padx=PAD)

        ttk.Separator(right, orient="horizontal").pack(fill="x", padx=PAD, pady=PAD)

        # Roster -- connected players' names, read-only, via the base-engine
        # APlayerState:GetPlayerName() (safe to assume it exists on any UE
        # game). Team assignment isn't shown: no PlayerState property for it
        # has been confirmed live yet.
        self.roster_label_var = tk.StringVar(value="Roster")
        self.roster_label = ui.label(right, textvariable=self.roster_label_var, bg=PANEL, bold=True)
        self.roster_label.pack(anchor="w", padx=PAD, pady=(0, 0))
        self.roster_list = ui.listbox(right, width=28, height=6)
        self.roster_list.pack(padx=PAD, pady=(PAD_SM, PAD_SM))
        ui.button(right, "Refresh Roster", command=self._refresh_roster).pack(fill="x", padx=PAD, pady=(0, PAD))

        ttk.Separator(right, orient="horizontal").pack(fill="x", padx=PAD, pady=(0, PAD))

        ui.button(right, "Discover More Gamemodes...", command=self._discover_gamemodes).pack(
            fill="x", padx=PAD, pady=(0, PAD))

        self._populate_map_tree()
        self._populate_gamemode_tree()
        self._apply_saved_state()
        self._refresh_state()

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

        self.map_tree.insert("", "end", iid=self.CAT_UNCONFIRMED_MAP, open=True, tags=("category",),
                              text=f"UNCONFIRMED MAPS (guessed paths)  ({len(unconfirmed)})")
        for n in unconfirmed:
            self.map_tree.insert(self.CAT_UNCONFIRMED_MAP, "end", iid=n, text=n, tags=("map_unconfirmed",))

    def _on_map_filter_keyrelease(self, _evt=None):
        if self._map_filter_after_id is not None:
            self.after_cancel(self._map_filter_after_id)
        self._map_filter_after_id = self.after(_FILTER_DEBOUNCE_MS, self._apply_map_filter)

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
        _load_ui_state()/_save_ui_state() near the top of this file."""
        state = _load_ui_state()
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

        def proceed():
            self.app.status(f"Loading {name} ({mode_name})...")

            def work():
                return api.host_and_travel(map_path, gm_class, cap, team or 1, private, bots)

            def done(result):
                self.last_hosted = dict(map_path=map_path, private=private, bots=bots)
                _save_ui_state({"map": name, "gamemode": mode_name, "cap": cap,
                                 "team": team or 1, "private": private, "bots": bots})
                self.app.status(f"Loaded {name}: {result}")
                self.app.root.after(4000, self._refresh_state)

            self.app.runner.run(work, done, self.app.on_error("ERROR loading match"))

        self._guard_other_players("Loading a custom match", proceed)

    def _refresh_state(self):
        def work():
            return api.get_live_state()

        def done(state):
            self.state_box.configure(state="normal")
            self.state_box.delete("1.0", tk.END)
            if not state.get("in_match"):
                self.state_box.insert(tk.END, "Not in a match\n(in Lobby / menu)")
            else:
                for k in ("mode_name", "phase", "count", "max", "team_size"):
                    self.state_box.insert(tk.END, f"{k}: {state.get(k)}\n")
            self.state_box.configure(state="disabled")

        self.app.runner.run(work, done, self.app.on_error("state check failed"))

    def _cycle(self):
        def proceed():
            fallback = self.last_hosted["map_path"] if self.last_hosted else None
            private = self.last_hosted["private"] if self.last_hosted else False
            bots = self.last_hosted["bots"] if self.last_hosted else True
            self.app.status("Cycling current match...")

            def work():
                return api.cycle_match(fallback_map_path=fallback, private=private, bots=bots)

            def done(result):
                self.app.status(f"Cycled: {result['mode_name']} cap={result['cap']} team={result['team_size']}")
                self.app.root.after(4000, self._refresh_state)

            self.app.runner.run(work, done, self.app.on_error("ERROR cycling"))

        self._guard_other_players("Cycling the current match", proceed)

    def _force_end(self):
        def proceed():
            self.app.status("Forcing round end...")

            def work():
                return api.force_round_end()

            def done(result):
                self.app.status(f"Round end: {result}")
                self.app.root.after(2000, self._refresh_state)

            self.app.runner.run(work, done, self.app.on_error())

        self._guard_other_players("Forcing the round to end", proceed)

    def _refresh_match_info(self):
        def work():
            return api.get_match_info()

        def done(info):
            self.match_info_box.configure(state="normal")
            self.match_info_box.delete("1.0", tk.END)
            if info is None:
                self.match_info_box.insert(tk.END, "Not in a match\n(in Lobby / menu)")
            else:
                for k, v in info.items():
                    self.match_info_box.insert(tk.END, f"{k}: {v}\n")
            self.match_info_box.configure(state="disabled")

        self.app.runner.run(work, done, self.app.on_error("match info check failed"))

    def _refresh_roster(self):
        def work():
            return api.get_player_roster()

        def done(names):
            self.roster_list.delete(0, tk.END)
            if not names:
                self.roster_list.insert(tk.END, "(none found)")
            for n in names:
                self.roster_list.insert(tk.END, n)
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


class LoadoutTab(ttk.Frame):
    CATEGORY_LABELS = {
        "primary": "Primary",
        "secondary": "Secondary (Pistols/Revolvers)",
        "melee": "Melee (Knives)",
        "lethal": "Lethal (Throwables)",
        "perk": "Perk (RC Cars / Drones)",
        "other": "Other",
    }
    SLOT_CATEGORY_HINT = ["primary", "secondary", "melee", "lethal", "perk"]

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.loadout_idx = 0

        top = ui.frame(self)
        top.pack(fill="x", padx=PAD, pady=PAD)
        ui.label(top, text="Edit Loadout").pack(side="left")
        self.loadout_var = tk.StringVar()
        self.loadout_cb = ttk.Combobox(top, textvariable=self.loadout_var, state="readonly", width=6)
        self.loadout_cb.pack(side="left", padx=PAD_SM + 2)
        self.loadout_cb.bind("<<ComboboxSelected>>", self._on_loadout_change)
        ui.button(top, "Refresh", command=self._refresh).pack(side="left", padx=PAD_SM + 2)
        ui.button(top, "Set as Active Loadout", kind="accent", command=self._set_active).pack(
            side="left", padx=PAD_SM + 2)
        ui.button(top, "Restore Backup...", command=self._restore_backup).pack(side="left", padx=PAD_SM + 2)

        self.body = ui.frame(self)
        self.body.pack(fill="both", expand=True, padx=PAD, pady=PAD)

        self._rows = {}
        self._build_rows()
        self._load_loadout_count()

    def _build_rows(self):
        specs = [("operator", "Operator")] + [
            (f"slot{i}", f"Slot {i+1} ({self.CATEGORY_LABELS[self.SLOT_CATEGORY_HINT[i]]})") for i in range(5)
        ]
        for key, label in specs:
            row = ui.frame(self.body)
            row.pack(fill="x", pady=PAD_SM)
            ui.label(row, text=label, width=28, anchor="w").pack(side="left")
            val_lbl = ui.label(row, text="-", bg=INPUT, anchor="w", width=32)
            val_lbl.pack(side="left", padx=PAD_SM + 2, ipady=3)
            btn = ui.button(row, "Change", command=lambda k=key: self._change(k))
            btn.pack(side="left")
            self._rows[key] = val_lbl

    def _load_loadout_count(self):
        def work():
            return api.loadout_count()

        def done(n):
            self.loadout_cb.configure(values=[str(i + 1) for i in range(n)])
            self.loadout_var.set("1")
            self._refresh()

        self.app.runner.run(work, done, self.app.on_error("loadout load failed"))

    def _on_loadout_change(self, _evt=None):
        self.loadout_idx = int(self.loadout_var.get()) - 1
        self._refresh()

    def _refresh(self):
        idx = self.loadout_idx

        def work():
            return api.dump_loadout(idx)

        def done(data):
            self._rows["operator"].configure(text=data["operator"] or "-")
            for i, s in enumerate(data["slots"]):
                self._rows[f"slot{i}"].configure(text=f'{s["weapon"]}  [{s["bundle"]}]')

        self.app.runner.run(work, done, self.app.on_error("refresh failed"))

    def _set_active(self):
        idx = self.loadout_idx
        self.app.status(f"Selecting Loadout {idx+1} as active...")

        def work():
            return api.select_active_loadout(idx)

        def done(result):
            self.app.status(f"Loadout {idx+1} active: {result}")

        self.app.runner.run(work, done, self.app.on_error())

    def _restore_backup(self):
        self.app.status("Loading backups...")

        def work():
            return api.list_backups()

        def done(backups):
            if not backups:
                messagebox.showinfo("No backups found", "No Loadout.sav backups exist yet.")
                return
            by_label = dict(backups)
            PickerDialog(self.app.root, "Choose backup to restore", list(by_label.keys()),
                         lambda label: self._confirm_restore(by_label[label]))

        self.app.runner.run(work, done, self.app.on_error("loading backups failed"))

    def _confirm_restore(self, path):
        if not messagebox.askyesno(
                "Restore backup",
                f"Restore Loadout.sav from this backup?\n\n{os.path.basename(path)}\n\n"
                "Your current save will itself be backed up first, so this is reversible."):
            return
        self.app.status("Restoring backup...")

        def work():
            return api.restore_backup(path)

        def done(_result):
            self.app.status("Backup restored -- reselect/cycle your loadout in-game to make it stick.")
            self._refresh()

        self.app.runner.run(work, done, self.app.on_error("restore failed"))

    def _change(self, key):
        if key == "operator":
            self.app.status("Loading operator list...")

            def work():
                return api.get_operators()

            def done(ops):
                self.app.status(f"{len(ops)} operators loaded")
                PickerDialog(self.app.root, "Choose Operator", ops, self._apply_operator)

            self.app.runner.run(work, done, self.app.on_error())
            return

        slot_idx = int(key.replace("slot", ""))
        hint_category = self.SLOT_CATEGORY_HINT[slot_idx]
        self._pick_category_then_item(slot_idx, hint_category)

    def _pick_category_then_item(self, slot_idx, default_category):
        win = tk.Toplevel(self.app.root)
        win.title("Choose category")
        win.configure(bg=BG)
        win.attributes("-topmost", True)
        win.bind("<Escape>", lambda e: win.destroy())
        ui.label(win, text="Slot category (default matches this slot, but you can pick any):"
                 ).pack(padx=PAD, pady=(PAD, PAD_SM))
        cat_var = tk.StringVar(value=default_category)
        for cat, label in self.CATEGORY_LABELS.items():
            ui.radiobutton(win, text=label, variable=cat_var, value=cat).pack(anchor="w", padx=PAD_LG)

        def next_step():
            win.destroy()
            self._pick_bundle(slot_idx, cat_var.get())

        ui.button(win, "Next →", kind="accent", command=next_step).pack(pady=PAD)

    def _pick_bundle(self, slot_idx, category):
        bundles = api.bundles_by_category(category)
        PickerDialog(self.app.root, "Choose Weapon Family", bundles,
                     lambda bundle: self._pick_variant(slot_idx, bundle))

    def _pick_variant(self, slot_idx, bundle):
        self.app.status(f"Loading {bundle} variants...")

        def work():
            return api.find_weapon_variants(bundle)

        def done(items):
            if not items:
                messagebox.showinfo("No items found", f"No live catalog items found for {bundle}.")
                return
            PickerDialog(self.app.root, f"Choose {bundle} skin", items,
                         lambda item: self._apply_slot(slot_idx, bundle, item))

        self.app.runner.run(work, done, self.app.on_error())

    def _apply_slot(self, slot_idx, bundle, item):
        idx = self.loadout_idx
        self.app.status(f"Setting Loadout {idx+1} slot {slot_idx+1} = {item}...")

        def work():
            return api.set_slot_weapon(idx, slot_idx, item, bundle_name=bundle)

        def done(_result):
            self.app.status(f"Loadout {idx+1} slot {slot_idx+1} -> {item}")
            self._refresh()

        self.app.runner.run(work, done, self.app.on_error())

    def _apply_operator(self, operator_name):
        idx = self.loadout_idx
        self.app.status(f"Setting Loadout {idx+1} operator = {operator_name}...")

        def work():
            return api.set_operator(idx, operator_name)

        def done(_result):
            self.app.status(f"Loadout {idx+1} operator -> {operator_name}")
            self._refresh()

        self.app.runner.run(work, done, self.app.on_error())


def run_cheat_snippet(app, snippet, on_extra_done=None):
    """Used by SpeedTab: run a snippet as `pc.<...>`, echo it into
    the Console tab's log either way, no appended `return` (a saved custom
    snippet might already end with its own, and Lua only allows one at the end
    of a block)."""
    app.status(f"Running: {snippet}")

    def work():
        return api.run_raw_lua("local pc = UEHelpers.GetPlayerController()\n" + snippet)

    def done(result):
        app.status(f"Ran: {snippet}")
        if hasattr(app, "console_tab"):
            app.console_tab._log(f">>> [cheat] {snippet}", "cmd")
            app.console_tab._log(result.strip() if result.strip() else "ok", "ok")
        if on_extra_done:
            on_extra_done(result)

    def err(e):
        app.status(f"ERROR: {e}", bad=True)
        if hasattr(app, "console_tab"):
            app.console_tab._log(f">>> [cheat] {snippet}", "cmd")
            app.console_tab._log(f"ERROR: {e}", "err")

    app.runner.run(work, done, err)


class SpeedTab(ttk.Frame):
    """Game-speed controls (Slomo), split out on their own."""

    PRESETS = [0.10, 0.25, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0]

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app

        ui.label(self, text="Game Speed (Slomo)", header=True).pack(anchor="w", padx=PAD, pady=(PAD, PAD_SM))

        preset_frame = ui.frame(self)
        preset_frame.pack(fill="x", padx=PAD, pady=PAD_SM)
        for val in self.PRESETS:
            label = "Normal (1x)" if val == 1.0 else f"{val}x"
            ui.button(preset_frame, label, width=10,
                      command=lambda v=val: self._set_speed(v)).pack(side="left", padx=3, pady=3)

        custom_frame = ui.frame(self)
        custom_frame.pack(fill="x", padx=PAD, pady=(PAD_LG, PAD_SM))
        ui.label(custom_frame, text="Custom:").pack(side="left")
        self.custom_var = tk.StringVar(value="1.0")
        ui.entry(custom_frame, textvariable=self.custom_var, width=8).pack(side="left", padx=PAD_SM + 2)
        ui.button(custom_frame, "Set", kind="accent", command=self._set_custom_speed).pack(side="left")

        self.current_lbl = ui.label(self, text="Current TimeDilation: unknown", muted=True)
        self.current_lbl.pack(anchor="w", padx=PAD, pady=(PAD_LG, 0))
        ui.button(self, "Refresh Current Speed", command=self._refresh_current).pack(
            anchor="w", padx=PAD, pady=(PAD_SM, 0))

        self._refresh_current()

    def _set_speed(self, value):
        run_cheat_snippet(self.app, f"pc.CheatManager:Slomo({value})",
                           on_extra_done=lambda _r: self._refresh_current())

    def _set_custom_speed(self):
        try:
            value = float(self.custom_var.get())
        except ValueError:
            messagebox.showwarning("Invalid value", "Enter a number, e.g. 0.5 or 2.0")
            return
        self._set_speed(value)

    def _refresh_current(self):
        def work():
            return api.run_raw_lua(
                "local ws=(FindAllOf('WorldSettings') or {})[1]\n"
                "local td='?'; pcall(function() td=tostring(ws.TimeDilation) end)\n"
                "return td"
            )

        def done(result):
            self.current_lbl.configure(text=f"Current TimeDilation: {result.strip()}")

        self.app.runner.run(work, done, lambda e: None)


class ConsoleShellMixin:
    """Shared history + output-log behavior for ConsoleTab and ShellTab --
    both bind Alt+Up/Alt+Down history and log to a colored Text widget the
    same way, so it lives here once instead of twice. Each subclass's
    __init__ still sets up self.history=[], self.hist_idx=0 and its own
    input_box before calling _build_output_area()/_bind_history_keys()."""

    def _build_output_area(self):
        ui.label(self, text="Output:").pack(anchor="w", padx=PAD, pady=(PAD, 0))
        out_frame = ui.frame(self)
        out_frame.pack(fill="both", expand=True, padx=PAD, pady=(PAD_SM - 2, PAD))
        scrollbar = ui.scrollbar(out_frame)
        scrollbar.pack(side="right", fill="y")
        self.output_box = ui.text(out_frame, yscrollcommand=scrollbar.set, state="disabled")
        self.output_box.pack(fill="both", expand=True)
        scrollbar.config(command=self.output_box.yview)
        self.output_box.tag_configure("cmd", foreground=ACCENT)
        self.output_box.tag_configure("err", foreground=BAD)
        self.output_box.tag_configure("ok", foreground=GOOD)

    def _bind_history_keys(self):
        self.input_box.bind("<Control-Return>", self._run_from_input)
        self.input_box.bind("<Alt-Up>", self._history_prev)
        self.input_box.bind("<Alt-Down>", self._history_next)

    def _log(self, text, tag=None):
        self.output_box.configure(state="normal")
        self.output_box.insert(tk.END, text + "\n", tag or ())
        self.output_box.see(tk.END)
        self.output_box.configure(state="disabled")

    def _clear_output(self):
        self.output_box.configure(state="normal")
        self.output_box.delete("1.0", tk.END)
        self.output_box.configure(state="disabled")

    def _history_prev(self, _evt=None):
        if not self.history:
            return "break"
        self.hist_idx = max(0, self.hist_idx - 1)
        self.input_box.delete("1.0", tk.END)
        self.input_box.insert("1.0", self.history[self.hist_idx])
        return "break"

    def _history_next(self, _evt=None):
        if not self.history:
            return "break"
        self.hist_idx = min(len(self.history), self.hist_idx + 1)
        self.input_box.delete("1.0", tk.END)
        if self.hist_idx < len(self.history):
            self.input_box.insert("1.0", self.history[self.hist_idx])
        return "break"


class ConsoleTab(ConsoleShellMixin, ttk.Frame):
    """Raw Lua console -- same bridge everything else uses, no training wheels."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.history = []
        self.hist_idx = 0

        ui.info_banner(
            self, title="Console — Lua inside the game",
            text="Runs directly on Bodycam's own Lua VM -- no sandbox, so a bad call can "
                 "crash the game. Globals: pawn(), props(obj), funcs(obj), count(className), "
                 "render(v), valid(o), UEHelpers, plus 'pc' (current PlayerController). "
                 "Alt+Up/Down replays this session's history; 'Save as Button' turns a working "
                 "snippet into a reusable button. Full reference: docs/DOCUMENTATION.md §1.",
        ).pack(fill="x", padx=PAD, pady=(PAD, 0))

        self.input_box = ui.text(self, height=6)
        self.input_box.pack(fill="x", padx=PAD, pady=(PAD_SM - 2, PAD_SM))
        self.input_box.insert("1.0", "return 1+1")
        self._bind_history_keys()

        btn_row = ui.frame(self)
        btn_row.pack(fill="x", padx=PAD)
        ui.button(btn_row, "Run  (Ctrl+Enter)", kind="accent", command=self._run_from_input).pack(side="left")
        ui.button(btn_row, "Save as Button...", kind="good", command=self._save_as_button).pack(
            side="left", padx=PAD_SM + 2)
        ui.button(btn_row, "Clear Output", command=self._clear_output).pack(side="left", padx=PAD_SM + 2)
        ui.label(btn_row, text="Alt+Up/Down: history", muted=True).pack(side="right")

        self._build_output_area()

    def _run_from_input(self, _evt=None):
        code = self.input_box.get("1.0", tk.END).strip()
        if not code:
            return "break"
        self.history.append(code)
        self.hist_idx = len(self.history)
        self._log(f">>> {code}", "cmd")
        # `pc` is just a local declaration -- safe to prepend to ANY payload,
        # including one that ends with the user's own `return`.
        self._execute("local pc = UEHelpers.GetPlayerController()\n" + code)
        return "break"  # swallow the Enter keypress in Ctrl+Enter binding

    def _save_as_button(self):
        code = self.input_box.get("1.0", tk.END).strip()
        if not code:
            messagebox.showwarning("Nothing to save", "The input box is empty.")
            return

        def on_save(name, mode, category):
            api.save_snippet(name, code, mode, category)
            if hasattr(self.app, "saved_buttons_tab"):
                self.app.saved_buttons_tab.refresh()
            cat_txt = f", category '{category}'" if category else ""
            self.app.status(f"Saved '{name}' ({mode}{cat_txt}) to Saved Command Buttons")

        SaveButtonDialog(self.app.root, on_save, categories=api.list_snippet_categories())

    def _execute(self, exec_code):
        self.app.status("Running Lua...")

        def work():
            return api.run_raw_lua(exec_code)

        def done(result):
            self._log(result if result.strip() else "(no output)", "ok")
            self.app.status("Ran Lua OK")

        def err(e):
            self._log(f"ERROR: {e}", "err")
            self.app.status("Lua error -- see console output", bad=True)

        self.app.runner.run(work, done, err)


def _make_scrollable(parent):
    """Standard scrollable-frame pattern: a Canvas + inner Frame that grows
    with its contents and scrolls with a Scrollbar or the mouse wheel (bound
    only while the cursor is over this canvas, so it doesn't hijack scrolling
    on other tabs). Returns the inner frame to pack widgets into."""
    canvas = tk.Canvas(parent, bg=BG, highlightthickness=0)
    vsb = ui.scrollbar(parent, orient="vertical", command=canvas.yview)
    inner = ui.frame(canvas)
    inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    win = canvas.create_window((0, 0), window=inner, anchor="nw")
    canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win, width=e.width))
    canvas.configure(yscrollcommand=vsb.set)
    canvas.pack(side="left", fill="both", expand=True)
    vsb.pack(side="right", fill="y")

    def _wheel(event):
        canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _wheel))
    canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))
    return inner


class SavedButtonsTab(ttk.Frame):
    """Buttons saved from the Console tab's 'Save as Button...' -- a
    scrollable, self-expanding list grouped by category, plus import/export
    so people can share a JSON file of their saved commands (the same widget
    shape a Plugin file uses, just without a plugin_name).

    Buttons sharing a category are rendered under one header with a "Run
    All" action that fires every button in that category once, in the same
    order they appear in the saved list (see game_api.save_snippet's
    docstring for why that order is what it is) -- one after another, not in
    parallel, since a later button in a group often assumes an earlier one
    already ran. A toggle-mode button run this way is always turned ON
    (TOGGLE_ON = true): "run all" reads as "activate everything in this
    group", not as flipping each one's current state."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.selection_vars = {}
        self.toggle_vars = {}

        toolbar = ui.frame(self)
        toolbar.pack(fill="x", padx=PAD, pady=PAD)
        ui.button(toolbar, "Import...", command=self._import).pack(side="left")
        ui.button(toolbar, "Export All...", command=self._export).pack(side="left", padx=PAD_SM + 2)
        ui.button(toolbar, "Export Selected...", command=self._export_selected).pack(side="left", padx=PAD_SM + 2)
        ui.label(toolbar, text="Save commands as buttons from the Console tab.", muted=True).pack(
            side="left", padx=PAD)

        self.inner = _make_scrollable(self)
        self.refresh()

    def refresh(self):
        for child in self.inner.winfo_children():
            child.destroy()
        self.selection_vars = {}
        self.toggle_vars = {}
        widgets = [w for w in api.list_snippets() if w.get("widget", "button") == "button"]
        if not widgets:
            ui.label(self.inner, text="No saved buttons yet -- use 'Save as Button...' in the Console tab.",
                     muted=True).pack(anchor="w", padx=PAD_SM + 2, pady=PAD)
            return

        groups = {}
        order = []
        for w in widgets:
            cat = w.get("category") or ""
            if cat not in groups:
                groups[cat] = []
                order.append(cat)
            groups[cat].append(w)
        # "General" (uncategorized) first if present, then named categories
        # in the order they were first seen in the saved list.
        ordered_cats = ([""] if "" in groups else []) + [c for c in order if c]

        for cat in ordered_cats:
            specs = groups[cat]
            header = ui.frame(self.inner)
            header.pack(fill="x", padx=PAD_SM + 2, pady=(PAD_LG - 6, PAD_SM - 2))
            ui.label(header, text=f'{cat or "General"}  ({len(specs)})', bold=True).pack(side="left")
            ui.button(header, "▶ Run All", command=lambda c=cat, s=list(specs): self._run_category(c, s)
                      ).pack(side="right")
            ttk.Separator(self.inner, orient="horizontal").pack(fill="x", padx=PAD_SM + 2, pady=(0, PAD_SM - 2))
            render_command_widgets(self.inner, self.app, specs, on_delete=self._delete,
                                    selection_vars=self.selection_vars,
                                    on_recategorize=self._recategorize, toggle_vars=self.toggle_vars)

    def _run_category(self, category, specs):
        cat_label = category or "General"
        self.app.status(f"Running category '{cat_label}' ({len(specs)} button(s))...")

        def work():
            results = []
            for spec in specs:
                label = spec.get("label", "?")
                mode = spec.get("mode", "run_once")
                code = spec.get("code", "")
                prefixed = f"local TOGGLE_ON = true\n{code}" if mode == "toggle" else code
                try:
                    result = api.run_raw_lua(prefixed)
                    results.append((label, mode, True, result))
                except Exception as e:  # noqa: BLE001
                    results.append((label, mode, False, str(e)))
                    break  # stop the sequence -- a later button may assume this one succeeded
            return results

        def done(results):
            for label, mode, success, _result in results:
                if success and mode == "toggle" and label in self.toggle_vars:
                    self.toggle_vars[label].set(True)
            ok = sum(1 for _, _, success, _ in results if success)
            failed = next((label for label, _, success, _ in results if not success), None)
            if failed:
                self.app.status(f"Category '{cat_label}': {ok}/{len(specs)} ran, stopped at '{failed}'", bad=True)
            else:
                self.app.status(f"Category '{cat_label}': all {ok} button(s) ran OK")

        self.app.runner.run(work, done, self.app.on_error(f"ERROR running category '{cat_label}'"))

    def _recategorize(self, spec):
        label = spec.get("label", "?")
        win = tk.Toplevel(self.app.root)
        win.title(f"Category for '{label}'")
        win.configure(bg=BG)
        win.attributes("-topmost", True)
        win.bind("<Escape>", lambda e: win.destroy())
        ui.label(win, text=f"Category for '{label}' -- pick an existing one or type a new one. "
                            "Leave blank for General.").pack(anchor="w", padx=PAD, pady=(PAD, PAD_SM))
        cat_var = tk.StringVar(value=spec.get("category", ""))
        combo = ttk.Combobox(win, textvariable=cat_var, values=api.list_snippet_categories(), width=30)
        combo.pack(padx=PAD, fill="x")
        combo.focus_set()

        def save():
            win.destroy()
            api.save_snippet(label, spec.get("code", ""), spec.get("mode", "run_once"), cat_var.get().strip())
            self.refresh()

        btn_row = ui.frame(win)
        btn_row.pack(pady=PAD)
        ui.button(btn_row, "Save", kind="accent", command=save).pack(side="left", padx=6)
        ui.button(btn_row, "Cancel", command=win.destroy).pack(side="left")
        combo.bind("<Return>", lambda e: save())

    def _export_selected(self):
        selected = [name for name, var in self.selection_vars.items() if var.get()]
        if not selected:
            messagebox.showinfo("Nothing selected", "Check the box next to at least one button first.")
            return
        path = filedialog.asksaveasfilename(title="Export selected buttons", defaultextension=".json",
                                             filetypes=[("JSON", "*.json")])
        if not path:
            return
        api.export_snippets(path, labels=selected)
        self.app.status(f"Exported {len(selected)} selected button(s) to {path}")

    def _delete(self, name):
        if messagebox.askyesno("Delete button", f"Delete saved button '{name}'?"):
            api.delete_snippet(name)
            self.refresh()

    def _import(self):
        path = filedialog.askopenfilename(title="Import buttons",
                                           filetypes=[("JSON", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            imported = api.import_snippets(path)
        except Exception as e:
            messagebox.showerror("Import failed", str(e))
            return
        existing = {w.get("label") for w in api.list_snippets()}
        added, skipped = 0, 0
        for w in imported:
            name = w.get("label", "?")
            if name in existing and not messagebox.askyesno(
                    "Overwrite?", f"'{name}' already exists. Overwrite it?"):
                skipped += 1
                continue
            api.save_snippet(name, w.get("code", ""), w.get("mode", "run_once"), w.get("category", ""))
            added += 1
        self.refresh()
        self.app.status(f"Imported {added} button(s), skipped {skipped}")

    def _export(self):
        path = filedialog.asksaveasfilename(title="Export buttons", defaultextension=".json",
                                             filetypes=[("JSON", "*.json")])
        if not path:
            return
        api.export_snippets(path)
        self.app.status(f"Exported buttons to {path}")


class PluginPreviewDialog(tk.Toplevel):
    """Shows a plugin's name and every button's label/mode/code before it's
    actually installed. Backs up the safety note in docs/DOCUMENTATION.md §3.7
    ("read a plugin's code before adding it") with something to actually
    read right here, instead of just a warning to go find the file yourself
    first."""

    def __init__(self, parent, plugin_name, widgets, on_confirm):
        super().__init__(parent)
        self.title(f"Preview: {plugin_name}")
        self.configure(bg=BG)
        self.geometry("560x480")
        self.attributes("-topmost", True)
        self.bind("<Escape>", lambda e: self.destroy())
        self.on_confirm = on_confirm

        ui.label(self, text=f"'{plugin_name}' -- {len(widgets)} widget(s). "
                             "Review the code below before adding it.",
                 wraplength=540, justify="left").pack(anchor="w", padx=PAD, pady=(PAD, PAD_SM))

        inner = _make_scrollable(self)
        if not widgets:
            ui.label(inner, text="(no widgets in this file)", muted=True).pack(
                anchor="w", padx=PAD_SM + 2, pady=PAD)
        for spec in widgets:
            kind = spec.get("widget", "button")
            if kind == "label":
                ui.label(inner, text=spec.get("label", ""), bold=True).pack(
                    anchor="w", padx=PAD_SM + 2, pady=(PAD_LG - 6, PAD_SM - 2))
                continue
            if kind == "separator":
                ttk.Separator(inner, orient="horizontal").pack(fill="x", padx=PAD_SM + 2, pady=PAD_SM + 2)
                continue
            code = spec.get("code", "")
            mode = spec.get("mode", "run_once")
            ui.label(inner, text=f'{spec.get("label", "?")}  [{mode}]', bold=True).pack(
                anchor="w", padx=PAD_SM + 2, pady=(PAD, 0))
            code_box = ui.text(inner, height=min(12, code.count("\n") + 2), wrap="none")
            code_box.insert("1.0", code)
            code_box.configure(state="disabled")
            code_box.pack(fill="x", padx=PAD_SM + 2, pady=(PAD_SM - 2, PAD_SM))

        btn_row = ui.frame(self)
        btn_row.pack(fill="x", padx=PAD, pady=PAD)
        ui.button(btn_row, "Add Plugin", kind="good", command=self._confirm).pack(side="left")
        ui.button(btn_row, "Cancel", command=self.destroy).pack(side="left", padx=PAD_SM + 2)

    def _confirm(self):
        self.destroy()
        self.on_confirm()


class PluginsTab(ttk.Frame):
    """Loads a JSON 'plugin' file -- same widget shape as Saved Command
    Buttons, plus a plugin_name and optional label/separator widgets for
    layout -- as its own sub-tab. Lets someone package a themed set of
    buttons (e.g. a 'Movement' plugin with Fly + Noclip toggles) as one
    shareable file, persisted the same way families.json/snippets.json are."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._tab_to_id = {}

        ui.info_banner(
            self, title="Plugins — shareable button packs",
            text="A plugin is a .json file bundling Console-tab buttons/toggles someone "
                 "packaged together (same format Saved Command Buttons exports use). "
                 "Installing one runs its code with full, unsandboxed game access -- always "
                 "read the preview before confirming. Full reference: docs/DOCUMENTATION.md §3.",
        ).pack(fill="x", padx=PAD, pady=(PAD, 0))

        toolbar = ui.frame(self)
        toolbar.pack(fill="x", padx=PAD, pady=PAD)
        ui.button(toolbar, "Add Plugin...", kind="good", command=self._add_plugin).pack(side="left")
        ui.button(toolbar, "Remove Selected Plugin", outline=True, command=self._remove_selected).pack(
            side="left", padx=PAD_SM + 2)

        self.inner_nb = ttk.Notebook(self)
        self.inner_nb.pack(fill="both", expand=True, padx=PAD, pady=(0, PAD))

        for plugin in api.list_plugins():
            self._add_tab(plugin)

    def _add_tab(self, plugin):
        frame = ui.frame(self.inner_nb)
        self.inner_nb.add(frame, text=plugin["plugin_name"])
        inner = _make_scrollable(frame)
        render_command_widgets(inner, self.app, plugin["widgets"])
        self._tab_to_id[str(frame)] = plugin["id"]
        self.inner_nb.select(frame)

    def _add_plugin(self):
        path = filedialog.askopenfilename(title="Add plugin",
                                           filetypes=[("JSON", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            plugin_name, data = api.preview_plugin(path)
        except Exception as e:
            messagebox.showerror("Invalid plugin", str(e))
            return

        def confirm():
            try:
                plugin = api.add_plugin(path)
            except Exception as e:
                messagebox.showerror("Invalid plugin", str(e))
                return
            self._add_tab(plugin)
            self.app.status(f"Loaded plugin '{plugin['plugin_name']}'")

        PluginPreviewDialog(self.app.root, plugin_name, data.get("widgets", []), confirm)

    def _remove_selected(self):
        sel = self.inner_nb.select()
        if not sel:
            messagebox.showinfo("No plugin selected", "Open a plugin tab first.")
            return
        plugin_id = self._tab_to_id.get(sel)
        name = self.inner_nb.tab(sel, "text")
        if not messagebox.askyesno("Remove plugin", f"Remove plugin '{name}'? This deletes its file."):
            return
        api.remove_plugin(plugin_id)
        self.inner_nb.forget(sel)
        self._tab_to_id.pop(sel, None)
        self.app.status(f"Removed plugin '{name}'")


class AboutTab(ttk.Frame):
    """Credits/license info -- see docs/DOCUMENTATION.md §5.6 for why this tab
    can't be made "tamper-proof" and what actually enforces attribution."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app

        ui.label(self, text="Bodycam Overlay", header=True).pack(anchor="w", padx=PAD_LG, pady=(PAD_LG + 4, 0))
        ui.label(self, text="A standalone desktop control panel for Bodycam -- not injected "
                             "into the game process.", muted=True, wraplength=600,
                 justify="left").pack(anchor="w", padx=PAD_LG, pady=(2, PAD_LG))

        ui.label(self, text="Created by clutch5.9", bold=True).pack(anchor="w", padx=PAD_LG, pady=(0, 2))
        ui.label(self, text="Licensed under the MIT License. See LICENSE in the project folder.",
                 muted=True).pack(anchor="w", padx=PAD_LG, pady=(0, PAD_LG))

        ui.label(self, text="Third-party components:", bold=True).pack(anchor="w", padx=PAD_LG, pady=(0, 2))
        ui.label(self, text="RE-UE4SS -- MIT License, Copyright (c) 2022 Narknon\n"
                             "(bundled under src/ue4ss_bundle/, see its own LICENSE file)",
                 muted=True, justify="left").pack(anchor="w", padx=PAD_LG, pady=(0, PAD_LG))

        ui.label(self, text="Docs: docs/DOCUMENTATION.md in the project folder explains the Console/"
                             "Shell tabs, the plugin format, and troubleshooting. "
                             "knowledge_base/CAPABILITIES.md covers what's actually in the game -- "
                             "content tables and what's confirmed safe vs. confirmed to crash.",
                 muted=True, wraplength=600, justify="left").pack(anchor="w", padx=PAD_LG)


class ShellTab(ConsoleShellMixin, ttk.Frame):
    """Runs arbitrary shell scripts locally via Git Bash -- see
    docs/DOCUMENTATION.md §2 for the full safety rationale (no sandboxing, by
    design)."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.history = []
        self.hist_idx = 0

        ui.info_banner(
            self, title="Shell — Bash on this PC",
            text="Runs on your computer via Git Bash, completely separate from the game -- "
                 "same unsandboxed access as a terminal you open yourself. Use it for local "
                 "files/automation, not for touching Bodycam (that's the Console tab's job). "
                 "Alt+Up/Down replays this session's history. Full reference: "
                 "docs/DOCUMENTATION.md §2.",
        ).pack(fill="x", padx=PAD, pady=(PAD, 0))

        self.input_box = ui.text(self, height=8)
        self.input_box.pack(fill="x", padx=PAD, pady=(PAD_SM - 2, PAD_SM))
        self.input_box.insert("1.0", "echo hello from bash\npwd")
        self._bind_history_keys()

        btn_row = ui.frame(self)
        btn_row.pack(fill="x", padx=PAD)
        ui.button(btn_row, "Run  (Ctrl+Enter)", kind="accent", command=self._run_from_input).pack(side="left")
        ui.label(btn_row, text="Timeout (s):").pack(side="left", padx=(PAD_LG, 2))
        self.timeout_var = tk.StringVar(value="60")
        ui.entry(btn_row, textvariable=self.timeout_var, width=6).pack(side="left")
        ui.button(btn_row, "Clear Output", command=self._clear_output).pack(side="left", padx=PAD_SM + 2)
        ui.label(btn_row, text="Alt+Up/Down: history", muted=True).pack(side="right")

        self._build_output_area()

    def _run_from_input(self, _evt=None):
        script = self.input_box.get("1.0", tk.END)
        if not script.strip():
            return "break"
        self.history.append(script)
        self.hist_idx = len(self.history)
        try:
            timeout = float(self.timeout_var.get())
        except ValueError:
            timeout = 60
        self._log(f">>> (running {len(script.splitlines())} line(s), timeout={timeout}s)", "cmd")
        self.app.status("Running shell script...")

        def work():
            return shell_client.run_shell(script, timeout=timeout)

        def done(result):
            if result["stdout"]:
                self._log(result["stdout"].rstrip(), "ok")
            if result["stderr"]:
                self._log(result["stderr"].rstrip(), "err")
            if not result["stdout"] and not result["stderr"]:
                self._log("(no output)")
            status = "TIMED OUT" if result["timed_out"] else f"exit code {result['returncode']}"
            self.app.status(f"Shell script finished: {status}")

        def err(e):
            self._log(f"ERROR: {e}", "err")
            self.app.status("Shell script failed to launch", bad=True)

        self.app.runner.run(work, done, err)
        return "break"


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Bodycam Overlay")
        self.root.geometry("840x760")
        self.root.minsize(680, 480)
        self.root.attributes("-topmost", True)
        self.root.protocol("WM_DELETE_WINDOW", self.hide)
        self.root.report_callback_exception = self._log_tk_exception

        ui.apply(self.root)

        self.runner = AsyncRunner(self.root)

        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=PAD_SM, pady=(PAD_SM, 0))
        self.host_tab = HostTab(nb, self)
        self.loadout_tab = LoadoutTab(nb, self)
        self.speed_tab = SpeedTab(nb, self)
        self.saved_buttons_tab = SavedButtonsTab(nb, self)
        self.console_tab = ConsoleTab(nb, self)
        self.plugins_tab = PluginsTab(nb, self)
        self.shell_tab = ShellTab(nb, self)
        self.about_tab = AboutTab(nb, self)
        nb.add(self.host_tab, text="Host / Create Match")
        nb.add(self.loadout_tab, text="Loadout Editor")
        nb.add(self.speed_tab, text="Game Speed")
        nb.add(self.saved_buttons_tab, text="Saved Command Buttons")
        nb.add(self.console_tab, text="Console")
        nb.add(self.plugins_tab, text="Plugins")
        nb.add(self.shell_tab, text="Shell")
        nb.add(self.about_tab, text="About")

        # Bottom status bar: one row, status text (left, expands) + a small
        # connection dot + label (right) -- replaces two separately-packed
        # full-width labels with a single denser bar.
        bottom = ui.frame(self.root, panel=True)
        bottom.pack(fill="x", side="bottom")
        ttk.Separator(bottom, orient="horizontal").pack(fill="x", side="top")

        self.status_var = tk.StringVar(value="Starting...")
        self.status_lbl = ui.label(bottom, textvariable=self.status_var, bg=PANEL, anchor="w")
        self.status_lbl.pack(fill="x", side="left", expand=True, padx=(PAD, PAD_SM), pady=PAD_SM + 1)

        conn_frame = ui.frame(bottom, panel=True)
        conn_frame.pack(side="right", padx=PAD, pady=PAD_SM)
        self.conn_dot = tk.Canvas(conn_frame, width=10, height=10, bg=PANEL, highlightthickness=0)
        self.conn_dot.pack(side="left", padx=(0, 6))
        self._conn_dot_id = self.conn_dot.create_oval(1, 1, 9, 9, fill=MUTED, outline="")
        self.conn_var = tk.StringVar(value="checking...")
        ui.label(conn_frame, textvariable=self.conn_var, bg=PANEL, muted=True).pack(side="left")

        keyboard.add_hotkey("insert", self.toggle)
        self.root.withdraw()
        self._start_tray_icon()
        self._run_setup_check()
        self.status("Press Insert to show/hide this window.")

    def _start_tray_icon(self):
        """A real taskbar/system-tray presence with a proper Exit option --
        see docs/DOCUMENTATION.md §5.6 for why the window itself only hides."""
        try:
            image = Image.open(os.path.join(api._HERE, "app_icon.ico")).convert("RGBA")
        except Exception:
            # fallback if app_icon.ico wasn't bundled -- a plain generated icon
            # beats a missing tray icon entirely
            image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)
            draw.ellipse((4, 4, 60, 60), fill=(91, 141, 238, 255))
            draw.text((20, 18), "B", fill=(255, 255, 255, 255))

        menu = pystray.Menu(
            pystray.MenuItem("Show/Hide (Insert)", lambda: self.toggle()),
            pystray.MenuItem("Exit", lambda: self.quit_app()),
        )
        self.tray_icon = pystray.Icon("BodycamOverlay", image, "Bodycam Overlay", menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def quit_app(self):
        """Actually terminates the app (the tray's Exit item). Uses os._exit
        rather than a normal mainloop return -- see docs/DOCUMENTATION.md §5.6."""
        try:
            self.tray_icon.stop()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass
        os._exit(0)

    def _run_setup_check(self):
        """Runs once at startup: makes sure ClaudeBridge (and, if it's already
        on this machine, the bundled UE4SS copy) is in place before the first
        connection poll. See install_bridge.py / docs/DOCUMENTATION.md §5.4."""
        def prompt_for_path():
            messagebox.showinfo(
                "Bodycam not found",
                "Couldn't auto-find your Bodycam install. Pick its Binaries\\Win64 folder next.")
            path = filedialog.askdirectory(title="Select Bodycam's Binaries\\Win64 folder")
            return path or None

        def work():
            return install_bridge.ensure_setup(prompt_for_path=prompt_for_path, on_status=self.status)

        def done(result):
            if result["reason"] == "needs_ue4ss":
                messagebox.showwarning(
                    "UE4SS not installed",
                    "UE4SS isn't installed in your Bodycam folder, and no bundled copy was "
                    "available to deploy. I've opened the official release page -- install it, "
                    "then restart this app.")
                self.status("Waiting on UE4SS install.", bad=True)
            elif result["reason"] == "not_found":
                self.status("Couldn't locate your Bodycam install.", bad=True)
            elif result["reason"] == "installed_ue4ss_and_bridge":
                messagebox.showinfo(
                    "Setup complete",
                    "Deployed UE4SS + ClaudeBridge. Fully restart Bodycam (not just Ctrl+R) "
                    "for it to load.")
                self.status("UE4SS + ClaudeBridge installed -- restart Bodycam.")
            elif result["reason"] == "installed_bridge":
                self.status("ClaudeBridge installed on top of existing UE4SS -- restart Bodycam if it's running.")
            self._poll_connection()

        def err(e):
            self.status(f"Setup check failed: {e}", bad=True)
            self._poll_connection()

        self.runner.run(work, done, err)

    def status(self, text, bad=False):
        self.status_var.set(text)
        self.status_lbl.configure(fg=BAD if bad else FG)

    def on_error(self, prefix="ERROR"):
        """Shorthand for the common AsyncRunner error handler: show the
        exception in the status bar with a prefix, e.g. as the third argument
        to self.runner.run(work, done, ...)."""
        return lambda e: self.status(f"{prefix}: {e}", bad=True)

    def _log_tk_exception(self, exc_type, exc_value, tb):
        """Replaces Tkinter's default callback-exception handler (which prints
        to stderr -- invisible in a --windowed build) so an exception raised
        directly in a widget command/binding still ends up in overlay.log."""
        logging.error("Unhandled Tk callback exception", exc_info=(exc_type, exc_value, tb))

    def _poll_connection(self):
        def work():
            return api.is_connected()

        def done(ok):
            self.conn_var.set("CONNECTED" if ok else "not responding")
            self.conn_dot.itemconfigure(self._conn_dot_id, fill=GOOD if ok else BAD)
            self.root.after(5000, self._poll_connection)

        self.runner.run(work, done, lambda e: self.root.after(5000, self._poll_connection))

    def toggle(self):
        self.root.after(0, self._toggle_ui)

    def _toggle_ui(self):
        if self.root.state() == "withdrawn":
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        else:
            self.root.withdraw()

    def hide(self):
        self.root.withdraw()

    def run(self):
        self.root.mainloop()


# Arbitrary fixed local port used purely as a single-instance lock -- binding
# it is the mutex. See docs/DOCUMENTATION.md §5.6 for what breaks without it.
_SINGLE_INSTANCE_PORT = 47821


def _acquire_single_instance_lock():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", _SINGLE_INSTANCE_PORT))
        s.listen(1)
        return s  # keep this alive for the process lifetime -- closing it releases the lock
    except OSError:
        s.close()
        return None


if __name__ == "__main__":
    _lock_socket = _acquire_single_instance_lock()
    if _lock_socket is None:
        import tkinter.messagebox as _mb
        _root = tk.Tk()
        _root.withdraw()
        _mb.showwarning(
            "Already running",
            "Bodycam Overlay is already running (check your system tray / taskbar, "
            "or press Insert). This copy will now close instead of opening a second, "
            "conflicting instance.")
        sys.exit(0)
    App().run()
