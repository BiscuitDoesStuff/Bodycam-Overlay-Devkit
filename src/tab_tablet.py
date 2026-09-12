"""Bodycam Tablet tab -- install/deploy/reapply controls for the Tablet Mod's
in-game "Mods" menu (F12). Deliberately thin: the 41 in-game settings stay
exclusively in that F12 menu, not mirrored here. See
dev/TABLET_MOD_INTEGRATION.md for the full integration story."""
import tkinter as tk
from tkinter import ttk, messagebox

import game_api as api
import install_bridge
import ui_theme as ui
from ui_theme import PAD, PAD_SM, PAD_LG


class TabletTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app

        ui.info_banner(
            self, title="Bodycam Tablet Mod",
            text="A separately-developed in-game mod menu (cheats, cosmetics, hosting/match "
                 "controls, loadout presets) reunited into this app -- see "
                 "dev/TABLET_MOD_INTEGRATION.md. Deploy it once, then press F12 in-game to open "
                 "its menu. Loadout saves made in that menu apply instantly through this app "
                 "(no extra click needed here).",
        ).pack(fill="x", padx=PAD, pady=(PAD, 0))

        deploy_row = ui.frame(self)
        deploy_row.pack(fill="x", padx=PAD, pady=PAD)
        ui.button(deploy_row, "Deploy / Update Tablet Mods", kind="good", command=self._deploy).pack(side="left")
        ui.button(deploy_row, "Reapply In-Game (F12 menu)", command=self._reapply).pack(
            side="left", padx=PAD_SM + 2)

        self.status_var = tk.StringVar(value="Not deployed yet -- press Deploy / Update Tablet Mods.")
        ui.label(self, textvariable=self.status_var, muted=True, wraplength=640, justify="left").pack(
            anchor="w", padx=PAD, pady=(0, PAD_LG))

        ui.info_banner(
            self, title="Catalog visibility reveal (advanced -- modifies game process memory)",
            text="Unlike everything else in this app, this reads and writes the live game "
                 "process's memory directly instead of running Lua inside the game's own "
                 "sandbox. Check first; only Reveal if you're comfortable with that.",
        ).pack(fill="x", padx=PAD, pady=(0, PAD))

        reveal_row = ui.frame(self)
        reveal_row.pack(fill="x", padx=PAD, pady=(0, PAD))
        ui.button(reveal_row, "Check Catalog Visibility", command=self._check_catalog).pack(side="left")
        ui.button(reveal_row, "Reveal Hidden Catalog Items", outline=True, command=self._reveal_catalog).pack(
            side="left", padx=PAD_SM + 2)

    def _deploy(self):
        def work():
            return install_bridge.deploy_tablet_mods()

        def done(path):
            self.status_var.set(f"Deployed to {path}. Press F12 in-game (or Reapply In-Game) to load it.")
            self.app.status("Tablet Mods deployed.")

        self.app.runner.run(work, done, self.app.on_error("Deploy failed"))

    def _reapply(self):
        def work():
            return api.reapply_tablet_mods()

        def done(result):
            self.status_var.set(str(result).strip())
            self.app.status("Tablet Mods reapplied in-game.")

        self.app.runner.run(work, done, self.app.on_error("Reapply failed"))

    def _check_catalog(self):
        def work():
            return api.reveal_catalog(apply=False)

        def done(result):
            n = result["hidden_found"]
            self.status_var.set(f"{n} hidden catalog row(s) found (read-only check, nothing changed).")
            self.app.status(f"Catalog check: {n} hidden row(s).")

        self.app.runner.run(work, done, self.app.on_error("Catalog check failed"))

    def _reveal_catalog(self):
        if not messagebox.askyesno(
                "Reveal hidden catalog items",
                "This reads and writes the live game process's memory directly (not sandboxed "
                "Lua). Only proceed if you understand that risk. Continue?"):
            return

        def work():
            return api.reveal_catalog(apply=True)

        def done(result):
            n = result["hidden_found"]
            self.status_var.set(f"Revealed {n} catalog row(s). See dev/TABLET_MOD_INTEGRATION.md.")
            self.app.status(f"Revealed {n} catalog row(s).")

        self.app.runner.run(work, done, self.app.on_error("Reveal failed"))
