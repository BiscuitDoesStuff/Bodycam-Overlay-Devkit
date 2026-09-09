"""Bodycam control overlay -- a separate desktop window (NOT injected into the
game process), toggled with the Insert key. Requires the game to run in
windowed or borderless mode so this window can sit visually on top of it.

Run with:  python src/overlay_app.py
Requires the game to be running with the ClaudeBridge UE4SS mod loaded.
"""
import logging
import logging.handlers
import os
import socket
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import keyboard  # global hotkey
import pystray
from PIL import Image, ImageDraw

import game_api as api
import install_bridge
import ui_theme as ui
from ui_theme import PANEL, FG, MUTED, GOOD, BAD, PAD, PAD_SM

from ui_common import AsyncRunner
from tab_host import HostTab
from tab_loadout import LoadoutTab
from tab_speed import SpeedTab
from tab_saved_buttons import SavedButtonsTab
from tab_testing import TestingTab
from tab_console import ConsoleTab
from tab_plugins import PluginsTab
from tab_shell import ShellTab
from tab_about import AboutTab

# A --windowed PyInstaller build has no console: print() output (and, in some
# builds, an unhandled exception's default stderr traceback) goes nowhere.
# Log to a capped file instead so a crash/error is diagnosable after the fact.
_log_handler = logging.handlers.RotatingFileHandler(
    os.path.join(api._CONFIG_DIR, "overlay.log"), maxBytes=1_000_000, backupCount=2, encoding="utf-8")
_log_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
logging.getLogger().addHandler(_log_handler)
logging.getLogger().setLevel(logging.INFO)


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
        self.testing_tab = TestingTab(nb, self)
        self.console_tab = ConsoleTab(nb, self)
        self.plugins_tab = PluginsTab(nb, self)
        self.shell_tab = ShellTab(nb, self)
        self.about_tab = AboutTab(nb, self)
        nb.add(self.host_tab, text="Host / Create Match")
        nb.add(self.loadout_tab, text="Loadout Editor")
        nb.add(self.speed_tab, text="Game Speed")
        nb.add(self.saved_buttons_tab, text="Saved Command Buttons")
        nb.add(self.testing_tab, text="Testing")
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
