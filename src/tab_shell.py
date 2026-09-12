"""Shell tab -- runs raw Bash scripts on the local PC via Git Bash."""
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import ui_theme as ui
from ui_theme import BG, PANEL, INPUT, FG, MUTED, ACCENT, GOOD, BAD, PAD, PAD_SM, PAD_LG
import shell_client
from ui_common import ConsoleShellMixin


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


