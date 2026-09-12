"""Saved Command Buttons tab."""
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import game_api as api
import ui_theme as ui
from ui_theme import PAD, PAD_SM, PAD_LG
from ui_common import make_scrollable, render_command_widgets, save_cancel_row


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

        self.inner = make_scrollable(self)
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
        for w in widgets:
            cat = w.get("category") or ""
            groups.setdefault(cat, []).append(w)
        # "General" (uncategorized) first if present, then named categories
        # in the order they were first seen in the saved list -- plain dict
        # insertion order (3.7+), no separate order-tracking list needed.
        ordered_cats = ([""] if "" in groups else []) + [c for c in groups if c]

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
        win = ui.toplevel(self.app.root, f"Category for '{label}'")
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

        save_cancel_row(win, save, win.destroy, pady=PAD)
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


