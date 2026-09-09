"""Plugins tab -- load a shareable JSON plugin file as its own sub-tab."""
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import game_api as api
import ui_theme as ui
from ui_theme import BG, PANEL, INPUT, FG, MUTED, ACCENT, GOOD, BAD, PAD, PAD_SM, PAD_LG
from ui_common import _make_scrollable, render_command_widgets


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


