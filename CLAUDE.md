# CLAUDE.md

## What

External Tk control panel for **Bodycam** (UE5), not injected into the game
process — talks to a bundled UE4SS Lua mod via file-based RPC. Fork of
clutch5.9's original "Bodycam Overlay", MIT-licensed. Windows-only.

## Run / test / build

- `python src/overlay_app.py` — starts hidden, Insert toggles the window;
  works fine with the game closed (status shows "not responding").
- `python tests/test_offline.py` — the only test suite; no game needed.
- `build.bat` — installs deps, runs PyInstaller against
  `BodycamOverlay.spec`, produces `dist/BodycamOverlay.exe`.
- Release = bump `__version__` in `overlay_app.py` + a `CHANGELOG.md`
  entry + tag `vX.Y.Z` (triggers `.github/workflows/release.yml`).

## Architecture

- File-based RPC: `bridge_client.py` (Python) ↔ `src/mod/ClaudeBridge/
  Scripts/main.lua` (runs inside the game). One request in flight at a
  time; `_send_lock` serializes concurrent Python-side callers.
- `game_api.py` wraps every Lua call/save-file edit into a plain Python
  function — nothing else should touch `bridge_client`/`gvas2` directly.
- `AsyncRunner` (`ui_common.py`) runs every blocking call off the Tk main
  thread — never block the UI thread with a live game call.
- One `tab_*.py` module per notebook tab. `ui_theme.py`'s factories
  (`ui.button`/`ui.label`/`ui.toplevel`/etc.) are the only way to build a
  widget — never a raw `tk.Widget(...)` call in a tab.

## Conventions

- **"No Lua error" is never proof of an effect** — verify a real
  before/after value before claiming a function does something.
- **Back up before any binary save-file write** (`Loadout.sav`) —
  automatic timestamped backups exist for exactly this.
- **Guard disruptive host actions** through `HostTab._guard_other_players`
  (check the live roster, confirm if anyone else is connected). Purely
  local writes (currency, unlocks, own-pawn cheats) don't need this.
- **Any `main.lua` edit needs a full game restart** to take effect — Ctrl+R
  hot-reload doesn't pick up a mod-file change.
- **Commit only when explicitly asked.** Never force-push without
  separate, explicit confirmation. Always merge, never rebase.

## Docs map & runtime state

`README.md` — user-facing setup/features. `docs/DOCUMENTATION.md` —
per-tab how-to, file formats, troubleshooting, runtime paths (§7).
`docs/INTERNALS.md` — protocol/engine design notes (`§5.x`, cited from
source comments). `CHANGELOG.md` — release history.

## dev/

Gitignored scratch space (`TODO.md`, research notes, test scripts).
Promote a confirmed fact into `docs/INTERNALS.md` before it's relied on
elsewhere, then commit — `dev/` itself never ships.
