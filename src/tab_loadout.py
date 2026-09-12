"""Loadout Editor tab (Currency & Unlocks included)."""
import os
import tkinter as tk
from tkinter import ttk, messagebox

import game_api as api
import ui_theme as ui
from ui_theme import PANEL, INPUT, PAD, PAD_SM, PAD_LG, PAD_MD
from ui_common import PickerDialog


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
        self.loadout_cb.pack(side="left", padx=PAD_MD)
        self.loadout_cb.bind("<<ComboboxSelected>>", self._on_loadout_change)
        ui.button(top, "Refresh", command=self._refresh).pack(side="left", padx=PAD_MD)
        ui.button(top, "Set as Active Loadout", kind="accent", command=self._set_active).pack(
            side="left", padx=PAD_MD)
        ui.button(top, "Restore Backup...", command=self._restore_backup).pack(side="left", padx=PAD_MD)

        ui.info_banner(
            self, title="Currency & Unlocks",
            text="Both write directly to the live GameInstance, not the save file -- "
                 "no purchase or cheat-menu call involved. Currency is a temporary "
                 "boost, not a permanent grant: any value set above the real cap "
                 "(40,000) gets reset back to 40,000 by the next real currency update "
                 "(a match ending, a Steam Cloud sync, a restart) -- that's expected, "
                 "just re-set it when you want the boost back. Item unlocks reset the "
                 "same way -- confirmed by the app's maintainer: both unlock buttons' "
                 "effects clear on a game restart, same as currency, but work fine for "
                 "the rest of the session they're used in. Re-run whichever unlock "
                 "button you want after every restart. For a PERMANENT unlock instead: "
                 "boost currency above, then buy the item for real in the in-game Shop "
                 "-- a real purchase sticks even though the currency number itself "
                 "resets; only the unlock buttons' own writes don't. "
                 "\"Unlock All Items\" and \"Unlock Guns & Attachments\" spray the real "
                 "catalog id list extracted from the game's own shop data (item_catalog.json), "
                 "not a guessed range; ids that don't "
                 "correspond to a real item are harmless.",
        ).pack(fill="x", padx=PAD, pady=(PAD, 0))

        unlocks = ui.frame(self, panel=True)
        unlocks.pack(fill="x", padx=PAD, pady=(PAD_SM, PAD))

        cur_row = ui.frame(unlocks, panel=True)
        cur_row.pack(fill="x", padx=PAD_SM, pady=(PAD_SM, 2))
        ui.label(cur_row, text="Reissad Points:", bold=True, bg=PANEL).pack(side="left")
        self.currency_lbl = ui.label(cur_row, text="-", bg=INPUT, anchor="w", width=16)
        self.currency_lbl.pack(side="left", padx=PAD_MD, ipady=3)
        ui.button(cur_row, "Refresh", command=self._refresh_currency).pack(side="left")
        self.currency_var = tk.StringVar(value="1000000")
        ui.entry(cur_row, textvariable=self.currency_var, width=10).pack(side="left", padx=(PAD_LG, 2))
        ui.button(cur_row, "Set", kind="accent", command=self._set_currency).pack(side="left")

        unlock_row = ui.frame(unlocks, panel=True)
        unlock_row.pack(fill="x", padx=PAD_SM, pady=(2, PAD_SM))
        ui.button(unlock_row, "Unlock All Items...", kind="accent",
                  command=self._unlock_all_items).pack(side="left")
        ui.button(unlock_row, "Unlock Guns & Attachments...",
                  command=self._unlock_weapons).pack(side="left", padx=(PAD_MD, 0))

        unlock_row2 = ui.frame(unlocks, panel=True)
        unlock_row2.pack(fill="x", padx=PAD_SM, pady=(0, PAD_SM))
        ui.label(unlock_row2, text="Unlock item ID:", bg=PANEL).pack(side="left")
        self.unlock_id_var = tk.StringVar()
        ui.entry(unlock_row2, textvariable=self.unlock_id_var, width=8).pack(side="left", padx=(PAD_SM, 2))
        ui.button(unlock_row2, "Unlock", command=self._unlock_single_id).pack(side="left")

        self.body = ui.frame(self)
        self.body.pack(fill="both", expand=True, padx=PAD, pady=PAD)

        self._rows = {}
        self._build_rows()
        self._load_loadout_count()
        # _refresh_currency() is a game RPC -- deferred to App._poll_connection's
        # first successful ping (see its comment for why it's not fired here).

    def _build_rows(self):
        specs = [("operator", "Operator")] + [
            (f"slot{i}", f"Slot {i+1} ({self.CATEGORY_LABELS[self.SLOT_CATEGORY_HINT[i]]})") for i in range(5)
        ]
        for key, label in specs:
            row = ui.frame(self.body)
            row.pack(fill="x", pady=PAD_SM)
            ui.label(row, text=label, width=28, anchor="w").pack(side="left")
            val_lbl = ui.label(row, text="-", bg=INPUT, anchor="w", width=32)
            val_lbl.pack(side="left", padx=PAD_MD, ipady=3)
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
        win = ui.toplevel(self.app.root, "Choose category")
        ui.label(win, text="Slot category (default matches this slot, but you can pick any):"
                 ).pack(padx=PAD, pady=(PAD, PAD_SM))
        cat_var = tk.StringVar(value=default_category)
        for cat, label in self.CATEGORY_LABELS.items():
            ui.radiobutton(win, text=label, variable=cat_var, value=cat).pack(anchor="w", padx=PAD_LG)

        def next_step(_evt=None):
            win.destroy()
            self._pick_bundle(slot_idx, cat_var.get())

        ui.button(win, "Next →", kind="accent", command=next_step).pack(pady=PAD)
        win.bind("<Return>", next_step)

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

    def _refresh_currency(self):
        def work():
            return api.get_currency()

        def done(data):
            self.currency_lbl.configure(text=f'{data["balance"]:,} / {data["cap"]:,}')

        self.app.runner.run(work, done, self.app.on_error("currency read failed"))

    def _set_currency(self):
        try:
            amount = int(self.currency_var.get())
        except ValueError:
            messagebox.showerror("Invalid amount", "Enter a whole number.")
            return
        self.app.status(f"Setting Reissad Points to {amount:,}...")

        def work():
            return api.set_currency(amount)

        def done(data):
            self.currency_lbl.configure(text=f'{data["balance"]:,} / {data["cap"]:,}')
            self.app.status(f"Reissad Points set to {data['balance']:,} "
                             "(temporary -- resets to 40,000 on the next real currency update)")

        self.app.runner.run(work, done, self.app.on_error("set currency failed"))

    def _unlock_all_items(self):
        if not messagebox.askyesno(
                "Unlock All Items",
                "This adds every real item in the shop catalog (2131 ids, extracted "
                "from the game's own DT_NewShopItem data) to your live inventory "
                "ownership list. Confirmed: this resets on a game restart, "
                "same as the currency override -- re-run it each session you want "
                "it in. There's also no undo button for this in the UI.\n\n"
                "Proceed?"):
            return
        self.app.status("Unlocking all items...")

        def work():
            return api.unlock_all_items()

        def done(_result):
            self.app.status("Unlock sweep complete -- check the in-game Locker/Shop.")

        self.app.runner.run(work, done, self.app.on_error("unlock all failed"))

    def _unlock_weapons(self):
        if not messagebox.askyesno(
                "Unlock Guns & Attachments",
                "This adds exactly the weapon and attachment items (1507 ids, the "
                "game's own DT_WeaponSkins grouping in DT_NewShopItem -- weapons and "
                "their attachments/magazines together) to your live inventory "
                "ownership list, skipping operator skins, badges, and charms. "
                "Confirmed: this resets on a game restart, same as \"Unlock All "
                "Items\" -- re-run it each session you want it in.\n\n"
                "Proceed?"):
            return
        self.app.status("Unlocking guns & attachments...")

        def work():
            return api.unlock_weapons_and_attachments()

        def done(_result):
            self.app.status("Weapons/attachments unlock sweep complete -- check the in-game Locker/Shop.")

        self.app.runner.run(work, done, self.app.on_error("unlock weapons failed"))

    def _unlock_single_id(self):
        raw = self.unlock_id_var.get().strip()
        if not raw.isdigit():
            messagebox.showerror("Invalid ID", "Enter a whole number item ID.")
            return
        item_id = int(raw)
        self.app.status(f"Unlocking item ID {item_id}...")

        def work():
            return api.unlock_item(item_id)

        def done(_result):
            self.app.status(f"Item ID {item_id} unlocked -- check the in-game Locker/Shop.")

        self.app.runner.run(work, done, self.app.on_error("unlock failed"))


