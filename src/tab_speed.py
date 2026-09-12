"""Game Speed tab: Slomo, Player Cheats, Perk/Gadget Cooldown."""
import math
import tkinter as tk
from tkinter import ttk, messagebox

import game_api as api
import ui_theme as ui
from ui_theme import PAD, PAD_SM, PAD_LG


class SpeedTab(ttk.Frame):
    """Game-speed controls (Slomo), split out on their own."""

    PRESETS = [0.10, 0.25, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0]

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._auto_clear_after_id = None

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

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=PAD, pady=(PAD_LG, PAD_SM))

        # Player Cheats -- the game's own developer CheatManager (found via
        # the UE4SS SDK dump, 2026-09-07), reached the exact same way Slomo
        # above already does: pc().CheatManager:SomeFunction(). Self-only, so
        # unlike Host tab's Match Control section these don't go through
        # _guard_other_players -- none of them force anything on anyone else.
        # See game_api.py's kill_self/set_invincible/set_infinite_ammo
        # docstrings for exactly what was independently confirmed live
        # vs. just "the call didn't error."
        ui.label(self, text="Player Cheats", header=True).pack(anchor="w", padx=PAD, pady=(0, PAD_SM))
        ui.info_banner(
            self, title="Kill Self / Invincible / Infinite Ammo confirmed NOT working",
            text="All three calls succeed with no error, but real-gameplay testing confirmed "
                 "they have no actual effect -- self didn't die, damage wasn't prevented, ammo "
                 "wasn't infinite. Left in the UI since they're harmless, not removed, but don't "
                 "expect anything to happen.",
        ).pack(fill="x", padx=PAD, pady=(0, PAD_SM))
        cheat_frame = ui.frame(self)
        cheat_frame.pack(fill="x", padx=PAD, pady=(0, PAD_SM))
        ui.button(cheat_frame, "Kill Self", outline=True, command=self._kill_self).pack(
            side="left", padx=(0, PAD_SM))
        ui.button(cheat_frame, "Invincible", command=self._set_invincible).pack(
            side="left", padx=(0, PAD_SM))
        ui.button(cheat_frame, "Infinite Ammo", command=self._set_infinite_ammo).pack(
            side="left", padx=(0, PAD_SM))

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=PAD, pady=(PAD_LG, PAD_SM))

        # Perk/Gadget Cooldown -- unlike the four cheats above, this one is
        # a real, confirmed-working Server RPC that actually does something.
        # It has to be re-applied for every new cooldown instance, not just
        # once, so Auto-Clear exists to do that on a timer instead of
        # needing a manual re-click after every gadget redeploy.
        ui.label(self, text="Perk / Gadget Cooldown", header=True).pack(anchor="w", padx=PAD, pady=(0, PAD_SM))
        ui.info_banner(
            self, title="Confirmed working -- must be reapplied per cooldown instance",
            text="Server RPC, not a plain CheatManager call -- confirmed live to clear an "
                 "in-progress gadget cooldown (tested against the FPV drone's 90s cooldown). "
                 "NOT a one-time toggle: it only clears whatever cooldown is running right now, "
                 "so it has to be called again every time a new cooldown starts (e.g. each "
                 "redeploy). Use Auto-Clear below instead of manually re-clicking after every use.",
        ).pack(fill="x", padx=PAD, pady=(0, PAD_SM))
        perk_frame = ui.frame(self)
        perk_frame.pack(fill="x", padx=PAD, pady=(0, PAD_SM))
        ui.button(perk_frame, "Clear Cooldown Now", kind="accent",
                  command=self._clear_perk_cooldown_once).pack(side="left", padx=(0, PAD_LG))
        self.auto_clear_var = tk.BooleanVar(value=False)
        ui.checkbutton(perk_frame, "Auto-Clear every", variable=self.auto_clear_var,
                        command=self._on_auto_clear_toggle).pack(side="left")
        self.auto_clear_interval_var = tk.StringVar(value="3")
        ui.entry(perk_frame, textvariable=self.auto_clear_interval_var, width=4).pack(
            side="left", padx=(PAD_SM - 2, 2))
        ui.label(perk_frame, text="sec").pack(side="left")
        self.auto_clear_status_lbl = ui.label(self, text="", muted=True)
        self.auto_clear_status_lbl.pack(anchor="w", padx=PAD, pady=(0, PAD_SM))

        # _refresh_current() is a game RPC -- deferred to App._poll_connection's
        # first successful ping (see its comment for why it's not fired here).

    def _run_cheat(self, status_msg, api_fn, done_msg, on_extra_done=None):
        """Collapses the status/work/done/runner.run shape every simple,
        no-argument self-only cheat button below shares -- api_fn is called
        with no args, done_msg replaces the status on success, errors go
        through self.app.on_error("ERROR"). on_extra_done, if given, also
        runs on success (e.g. _set_speed() refreshing the current-speed label)."""
        self.app.status(status_msg)

        def done(result):
            self.app.status(done_msg)
            if on_extra_done:
                on_extra_done(result)

        self.app.runner.run(api_fn, done, self.app.on_error("ERROR"))

    def _clear_perk_cooldown_once(self):
        self._run_cheat("Clearing perk/gadget cooldown...", api.disable_perk_cooldown,
                         "Perk/gadget cooldown cleared")

    def _cancel_auto_clear_timer(self):
        if self._auto_clear_after_id is not None:
            self.app.root.after_cancel(self._auto_clear_after_id)
            self._auto_clear_after_id = None

    def _on_auto_clear_toggle(self):
        # Cancel any pending tick before (re)starting -- toggling off then on
        # again before the next tick fires would otherwise leave the old
        # chain's already-queued after() alive alongside the new one, running
        # two independent tick chains (and so two disable_perk_cooldown calls
        # per interval) forever.
        self._cancel_auto_clear_timer()
        if self.auto_clear_var.get():
            self.auto_clear_status_lbl.configure(text="Auto-Clear running...")
            self._auto_clear_tick()
        else:
            self.auto_clear_status_lbl.configure(text="Auto-Clear stopped")

    def _auto_clear_tick(self):
        if not self.auto_clear_var.get():
            return

        def work():
            return api.disable_perk_cooldown()

        def done(_result):
            self.auto_clear_status_lbl.configure(text="Auto-Clear running (last call OK)")

        def err(e):
            self.auto_clear_status_lbl.configure(text=f"Auto-Clear running (last call failed: {e})")

        self.app.runner.run(work, done, err)

        try:
            interval_ms = max(1, int(float(self.auto_clear_interval_var.get()))) * 1000
        except ValueError:
            interval_ms = 3000
        self._auto_clear_after_id = self.app.root.after(interval_ms, self._auto_clear_tick)

    def _kill_self(self):
        self._run_cheat("Killing self...", api.kill_self, "Killed self")

    def _set_invincible(self):
        self._run_cheat("Toggling invincibility...", api.set_invincible,
                         "Invincibility toggled (not independently confirmed which state it's now in)")

    def _set_infinite_ammo(self):
        self._run_cheat("Toggling infinite ammo...", api.set_infinite_ammo,
                         "Infinite ammo toggled (not independently confirmed which state it's now in)")

    def _set_speed(self, value):
        self._run_cheat(f"Setting speed to {value}x...", lambda: api.set_slomo(value),
                         f"Speed set to {value}x", on_extra_done=lambda _r: self._refresh_current())

    def _set_custom_speed(self):
        try:
            value = float(self.custom_var.get())
        except ValueError:
            messagebox.showwarning("Invalid value", "Enter a number, e.g. 0.5 or 2.0")
            return
        # float() also accepts "inf"/"nan", and 0 freezes the game -- none of
        # those are a real speed, and Lua would just interpolate them as the
        # bare (nil) words inf/nan, producing a Slomo(nil) call.
        if not math.isfinite(value) or not (0.01 <= value <= 10):
            messagebox.showwarning("Invalid value", "Enter a number between 0.01 and 10, e.g. 0.5 or 2.0")
            return
        self._set_speed(value)

    def _refresh_current(self):
        def done(result):
            self.current_lbl.configure(text=f"Current TimeDilation: {result}")

        self.app.runner.run(api.get_time_dilation, done, lambda e: None)


