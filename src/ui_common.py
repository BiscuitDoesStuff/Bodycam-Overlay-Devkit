"""Shared dialogs, mixins, and small helpers used by two or more tab
modules -- split out of what used to be one large overlay_app.py so each
tab lives in its own file. Nothing in here is a tab itself.
"""
import json
import logging
import os
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox

import game_api as api
import ui_theme as ui
from ui_theme import BG, PANEL, MUTED, GOOD, BAD, PAD, PAD_SM, PAD_MD, PAD_ML, PAD_XS

# Small persisted "remember what I last picked" file -- Host tab restores its
# map/gamemode/cap/team/private/bots selections from this on the next launch
# instead of always resetting to the defaults. Lives alongside the app's other
# per-user files (families.json, snippets.json, ...) in the same config dir.
_UI_STATE_PATH = os.path.join(api._CONFIG_DIR, "ui_state.json")


def load_ui_state():
    try:
        with open(_UI_STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_ui_state(partial):
    state = load_ui_state()
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
FILTER_DEBOUNCE_MS = 120


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
                try:
                    if kind == "ok" and on_done:
                        on_done(payload)
                    elif kind == "err" and on_error:
                        on_error(payload)
                    elif kind == "err":
                        logging.error("Unhandled async error", exc_info=payload)
                except Exception:
                    # An exception here must not escape -- it would skip the
                    # after() below and silently stop delivering every later
                    # async result for the rest of the app's lifetime.
                    logging.exception("AsyncRunner on_done/on_error callback raised")
        except queue.Empty:
            pass
        finally:
            self.root.after(80, self._poll)


def save_cancel_row(parent, on_save, on_cancel, pady=PAD_ML):
    """The Save/Cancel button row shared by SaveButtonDialog below and
    SavedButtonsTab._recategorize's dialog."""
    row = ui.frame(parent)
    row.pack(pady=pady)
    ui.button(row, "Save", kind="accent", command=on_save).pack(side="left", padx=PAD_MD)
    ui.button(row, "Cancel", command=on_cancel).pack(side="left")
    return row


def PickerDialog(parent, title, items, on_pick):
    """A search-as-you-type scrollable list picker. Calls on_pick(value) and closes."""
    win = ui.toplevel(parent, title, geometry="420x480")
    all_items = sorted(items)
    filter_after_id = None

    search_var = tk.StringVar()
    entry = ui.entry(win, textvariable=search_var)
    entry.pack(fill="x", padx=PAD, pady=PAD)

    listbox = ui.listbox(win)
    listbox.pack(fill="both", expand=True, padx=PAD, pady=(0, PAD))

    def populate(items):
        listbox.delete(0, tk.END)
        for it in items:
            listbox.insert(tk.END, it)

    def pick(_evt=None):
        sel = listbox.curselection()
        # Enter with nothing explicitly selected picks the top filtered result --
        # the common "type to narrow it down, hit Enter" flow shouldn't require
        # also clicking or arrowing onto the one match left.
        if not sel and listbox.size() > 0:
            sel = (0,)
        if not sel:
            return
        value = listbox.get(sel[0])
        win.destroy()
        on_pick(value)

    def do_filter():
        nonlocal filter_after_id
        filter_after_id = None
        q = search_var.get().lower()
        populate([it for it in all_items if q in it.lower()])

    def on_keyrelease(_evt=None):
        nonlocal filter_after_id
        if filter_after_id is not None:
            win.after_cancel(filter_after_id)
        filter_after_id = win.after(FILTER_DEBOUNCE_MS, do_filter)

    entry.bind("<KeyRelease>", on_keyrelease)
    entry.bind("<Down>", lambda e: (listbox.focus_set(), listbox.selection_set(0)))
    entry.bind("<Return>", pick)
    entry.focus_set()
    listbox.bind("<Double-Button-1>", pick)

    populate(all_items)
    return win


def SaveButtonDialog(parent, on_save, categories=None, initial_category=""):
    """Prompts for a name and Run Once/Toggle when saving a console snippet as
    a reusable button. A toggle button renders as a checkbox and injects
    `local TOGGLE_ON = true/false` ahead of the snippet's own code on every
    click, so a single saved script (checking TOGGLE_ON itself) drives both
    states -- the same shape as the built-in bot-fill/explosive-bullets
    toggles, just authored by whoever wrote the snippet."""
    win = ui.toplevel(parent, "Save as Button")

    ui.label(win, text="Button name:").pack(anchor="w", padx=PAD_ML, pady=(PAD_ML, PAD_SM))
    name_var = tk.StringVar()
    entry = ui.entry(win, textvariable=name_var, width=32)
    entry.pack(padx=PAD_ML, fill="x")
    entry.focus_set()

    mode_var = tk.StringVar(value="run_once")
    ui.radiobutton(win, text="Run Once", variable=mode_var, value="run_once").pack(
        anchor="w", padx=PAD_ML, pady=(PAD_ML, 0))
    ui.radiobutton(win, text="Toggle (adds a checkbox; your code checks TOGGLE_ON)",
                   variable=mode_var, value="toggle").pack(anchor="w", padx=PAD_ML)

    ui.label(win, text="Category (optional -- buttons sharing one can all be run together, "
                        "in order, from a single 'Run All'):").pack(
        anchor="w", padx=PAD_ML, pady=(PAD_ML, PAD_SM))
    category_var = tk.StringVar(value=initial_category)
    cat_combo = ttk.Combobox(win, textvariable=category_var, values=list(categories or []), width=30)
    cat_combo.pack(padx=PAD_ML, fill="x")

    def save():
        name = name_var.get().strip()
        if not name:
            messagebox.showwarning("Name required", "Enter a button name.", parent=win)
            return
        win.destroy()
        on_save(name, mode_var.get(), category_var.get().strip())

    save_cancel_row(win, save, win.destroy)
    entry.bind("<Return>", lambda e: save())
    cat_combo.bind("<Return>", lambda e: save())
    return win


def render_label_or_separator(parent, spec):
    """Renders spec if it's a {"widget": "label"/"separator"} row -- shared by
    render_command_widgets() below and tab_plugins.py's PluginPreviewDialog,
    which otherwise render the "real" widget rows completely differently
    (one runnable, one a read-only code preview). Returns True if spec was
    handled here (caller should skip to the next spec), False otherwise."""
    kind = spec.get("widget", "button")
    if kind == "label":
        ui.label(parent, text=spec.get("label", ""), bold=True).pack(
            anchor="w", padx=PAD_MD, pady=(PAD_ML, PAD_XS))
        return True
    if kind == "separator":
        ttk.Separator(parent, orient="horizontal").pack(fill="x", padx=PAD_MD, pady=PAD_MD)
        return True
    return False


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
        if render_label_or_separator(parent, spec):
            continue

        label = spec.get("label", "?")
        code = spec.get("code", "")
        mode = spec.get("mode", "run_once")
        row = ui.frame(parent)
        row.pack(fill="x", padx=PAD_MD, pady=2)

        if selection_vars is not None:
            sel_var = tk.BooleanVar(value=False)
            ui.checkbutton(row, variable=sel_var).pack(side="left", padx=(0, PAD_MD))
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


def set_text(text_widget, s):
    """Replaces a disabled/read-only Text widget's whole content with `s`
    (toggles to normal to edit, then back to disabled) -- shared by
    HostTab's state/match-info boxes and ConsoleShellMixin's _clear_output
    below."""
    text_widget.configure(state="normal")
    text_widget.delete("1.0", tk.END)
    if s:
        text_widget.insert(tk.END, s)
    text_widget.configure(state="disabled")


class ConsoleShellMixin:
    """Shared history + output-log behavior for ConsoleTab and ShellTab --
    both bind Alt+Up/Alt+Down history and log to a colored Text widget the
    same way, so it lives here once instead of twice. Each subclass's
    __init__ still sets up self.history=[], self.hist_idx=0 before calling
    _build_input_row()/_build_output_area()."""

    def _build_input_row(self, height, default_text, extra_buttons=None):
        """The input Text box + button row shape ConsoleTab and ShellTab both
        use: Run (Ctrl+Enter), an optional extra_buttons(btn_row) hook right
        after it for whatever else that tab needs there (Console's Save-as-
        Button, Shell's timeout field), then Clear Output and the history hint."""
        self.input_box = ui.text(self, height=height)
        self.input_box.pack(fill="x", padx=PAD, pady=(PAD_XS, PAD_SM))
        self.input_box.insert("1.0", default_text)
        self._bind_history_keys()

        btn_row = ui.frame(self)
        btn_row.pack(fill="x", padx=PAD)
        ui.button(btn_row, "Run  (Ctrl+Enter)", kind="accent", command=self._run_from_input).pack(side="left")
        if extra_buttons:
            extra_buttons(btn_row)
        ui.button(btn_row, "Clear Output", command=self._clear_output).pack(side="left", padx=PAD_MD)
        ui.label(btn_row, text="Alt+Up/Down: history", muted=True).pack(side="right")

    def _build_output_area(self):
        ui.label(self, text="Output:").pack(anchor="w", padx=PAD, pady=(PAD, 0))
        out_frame = ui.frame(self)
        out_frame.pack(fill="both", expand=True, padx=PAD, pady=(PAD_XS, PAD))
        scrollbar = ui.scrollbar(out_frame)
        scrollbar.pack(side="right", fill="y")
        self.output_box = ui.text(out_frame, yscrollcommand=scrollbar.set, state="disabled")
        self.output_box.pack(fill="both", expand=True)
        scrollbar.config(command=self.output_box.yview)
        self.output_box.tag_configure("cmd", foreground=MUTED)
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
        set_text(self.output_box, "")

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




def make_scrollable(parent, panel=False):
    """Standard scrollable-frame pattern: a Canvas + inner Frame that grows
    with its contents and scrolls with a Scrollbar or the mouse wheel (bound
    only while the cursor is over this canvas, so it doesn't hijack scrolling
    on other tabs). Returns the inner frame to pack widgets into. Pass
    panel=True to use the PANEL background instead of BG (matches a
    panel=True parent frame, e.g. HostTab's right column)."""
    bg = PANEL if panel else BG
    canvas = tk.Canvas(parent, bg=bg, highlightthickness=0)
    vsb = ui.scrollbar(parent, orient="vertical", command=canvas.yview)
    inner = ui.frame(canvas, panel=panel)
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


