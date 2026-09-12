# CLAUDE.md

## What this project actually is

A standalone desktop control panel for **Bodycam** (Unreal Engine 5.5) —
**not** injected into the game process. It runs as its own Python/Tkinter
application, talking to a live, running copy of the game through a UE4SS
Lua mod bundled inside this repo. This is a **fork**: the original
"Bodycam Overlay" was created by **clutch5.9**; this fork (**BDT Overlay
Fork**) is maintained by **BiscuitDoesStuff** at
github.com/BiscuitDoesStuff/BDT-Overlay-Fork, both under the MIT License
(original copyright preserved, per the license's own requirement).

Scope, deliberately: cosmetic/economy unlocks, loadout editing,
weather/time control, and developer-cheat-menu access (self-only).
Nothing in this repo targets or manipulates *other players'* state.

## Architecture: how this actually talks to the game

- **UE4SS** (a Lua scripting/modding framework for Unreal Engine) is
  installed into the game and loads a mod called **ClaudeBridge**
  (`src/mod/ClaudeBridge/Scripts/main.lua`), which runs *inside* the game
  process for as long as the game is open.
- Python (`bridge_client.py`) talks to that Lua mod via a **file-based
  RPC protocol**: write a request file, the Lua mod polls for it, executes
  the Lua, writes a response file. One request in flight at a time (a
  `busy` flag on the game side); `bridge_client.py` serializes concurrent
  Python-side callers with a `threading.Lock()`.
- `game_api.py` wraps this into higher-level Python functions
  (`get_match_info()`, `set_currency()`, `unlock_all_items()`, etc.) that
  `overlay_app.py`'s UI calls asynchronously (never blocking the Tk main
  loop — see `app.runner.run(work, done, err)` used everywhere in the UI).

## Development conventions in this repo

- **Never trust "the call didn't error" as proof of effect.** A function
  succeeding with no Lua error is not evidence it did anything in-game —
  always verify a real before/after value when one is available before
  shipping a claim about what something does.
- **Always back up before any binary save-file write** (`Loadout.sav`,
  etc.) — automatic timestamped backups exist for exactly this reason.
- **Guard disruptive host actions** — check the live roster first, ask
  for confirmation if anyone besides the local player is connected,
  before restarting rounds, changing maps, etc. (see `HostTab._guard_other_players`
  in `tab_host.py`). Purely local/cosmetic writes (currency, unlocks,
  own-pawn cheats) don't need this — they don't affect other players.
- **Commit only when explicitly asked.** Never force-push without
  explicit, separate confirmation for that specific action. Always merge,
  never rebase over the real repo's history.
