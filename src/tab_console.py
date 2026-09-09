"""Console tab -- raw Lua console into the live game process."""
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import game_api as api
import ui_theme as ui
from ui_theme import BG, PANEL, INPUT, FG, MUTED, ACCENT, GOOD, BAD, PAD, PAD_SM, PAD_LG
from ui_common import ConsoleShellMixin, SaveButtonDialog


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


