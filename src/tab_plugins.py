"""Plugins tab -- load a shareable JSON plugin file as its own sub-tab."""
import re
from tkinter import ttk, messagebox, filedialog

import game_api as api
import ui_theme as ui
from ui_theme import PAD, PAD_SM, RED, PAD_MD, PAD_XS
from ui_common import make_scrollable, render_command_widgets, render_label_or_separator

# Highlighted in the preview below since these are what actually make a
# plugin "arbitrary code on your PC", not just game access -- see main.lua's
# own os.execute()/io.open() usage for the mod-side equivalent. Not
# exhaustive (any os.*/io.* call can touch the filesystem/process, and Lua
# can obfuscate a call e.g. os["exec".."ute"]) -- a highlight here is a
# strong signal to read closely, not proof the rest of the code is safe.
_DANGEROUS_LUA = re.compile(r"\bos\.\w+|\bio\.\w+|\brequire\b|\bdofile\b|\bloadstring?\s*\(")


def PluginPreviewDialog(parent, plugin_name, widgets, on_confirm):
    """Shows a plugin's name and every button's label/mode/code before it's
    actually installed. Backs up the safety note in docs/DOCUMENTATION.md §4.7
    ("read a plugin's code before adding it") with something to actually
    read right here, instead of just a warning to go find the file yourself
    first."""
    win = ui.toplevel(parent, f"Preview: {plugin_name}", geometry="560x480")

    ui.label(win, text=f"'{plugin_name}' -- {len(widgets)} widget(s). "
                        "Review the code below before adding it -- red text flags an "
                        "obvious OS call, but that's a hint to read closely, not a full scan.",
             wraplength=540, justify="left").pack(anchor="w", padx=PAD, pady=(PAD, PAD_SM))

    inner = make_scrollable(win)
    if not widgets:
        ui.label(inner, text="(no widgets in this file)", muted=True).pack(
            anchor="w", padx=PAD_MD, pady=PAD)
    for spec in widgets:
        if render_label_or_separator(inner, spec):
            continue
        code = spec.get("code", "")
        mode = spec.get("mode", "run_once")
        ui.label(inner, text=f'{spec.get("label", "?")}  [{mode}]', bold=True).pack(
            anchor="w", padx=PAD_MD, pady=(PAD, 0))
        code_box = ui.text(inner, height=min(12, code.count("\n") + 2), wrap="none")
        code_box.insert("1.0", code)
        code_box.tag_configure("danger", foreground=RED)
        for m in _DANGEROUS_LUA.finditer(code):
            code_box.tag_add("danger", f"1.0+{m.start()}c", f"1.0+{m.end()}c")
        code_box.configure(state="disabled")
        code_box.pack(fill="x", padx=PAD_MD, pady=(PAD_XS, PAD_SM))

    def confirm():
        win.destroy()
        on_confirm()

    btn_row = ui.frame(win)
    btn_row.pack(fill="x", padx=PAD, pady=PAD)
    ui.button(btn_row, "Add Plugin", kind="accent", command=confirm).pack(side="left")
    ui.button(btn_row, "Cancel", command=win.destroy).pack(side="left", padx=PAD_MD)
    return win




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
                 "Installing one runs its code with no sandbox -- ClaudeBridge's Lua exposes "
                 "os.execute/io.popen, so this is arbitrary code on YOUR PC as well as the game, "
                 "not just game access. Always read the preview before confirming. Full "
                 "reference: docs/DOCUMENTATION.md §4.",
        ).pack(fill="x", padx=PAD, pady=(PAD, 0))

        toolbar = ui.frame(self)
        toolbar.pack(fill="x", padx=PAD, pady=PAD)
        ui.button(toolbar, "Add Plugin...", kind="accent", command=self._add_plugin).pack(side="left")
        ui.button(toolbar, "Remove Selected Plugin", outline=True, command=self._remove_selected).pack(
            side="left", padx=PAD_MD)

        self.inner_nb = ttk.Notebook(self)
        self.inner_nb.pack(fill="both", expand=True, padx=PAD, pady=(0, PAD))

        for plugin in api.list_plugins():
            self._add_tab(plugin)

    def _add_tab(self, plugin):
        frame = ui.frame(self.inner_nb)
        self.inner_nb.add(frame, text=plugin["plugin_name"])
        inner = make_scrollable(frame)
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


