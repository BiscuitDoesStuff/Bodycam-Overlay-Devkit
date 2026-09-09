# CLAUDE.md

Shared context for any Claude session working on this repo — Claude Code
(with live tool/game access) or a Claude.ai Project (chat-only, reading a
GitHub-synced snapshot of these files). If you're in a chat-only session,
everything here is current **as of the last "Sync now" click** on the
Project, not live.

This repo holds the **official, shipped application only**. Active
development, experimental findings, and research notes are kept locally
and are not published here — don't expect a running log of "what was
tried and what happened" in this repo; expect the current, working state
of the app plus documentation of what it actually does.

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

## Repo layout

```
README.md                 User-facing feature list and setup instructions
CLAUDE.md                  This file
LICENSE                    MIT (original clutch5.9 copyright preserved)
docs/DOCUMENTATION.md       Console/Shell/Plugins reference, troubleshooting,
                            internals notes
community/                  Shared Saved-Command-Button and Plugin exports
src/
  overlay_app.py            Entry point -- App class, tray icon, single-
                            instance lock, __main__. One file per tab lives
                            alongside it: tab_host.py, tab_loadout.py,
                            tab_speed.py, tab_saved_buttons.py,
                            tab_console.py, tab_plugins.py, tab_shell.py,
                            tab_about.py. ui_common.py holds what's shared
                            across 2+ of them (AsyncRunner, PickerDialog,
                            SaveButtonDialog, render_command_widgets,
                            ConsoleShellMixin, _make_scrollable, ui-state
                            persistence).
  ui_theme.py                Central palette/fonts/spacing + widget factories
  game_api.py                High-level API: live Lua calls + save-file edits
  bridge_client.py           Talks to the ClaudeBridge UE4SS mod (file-based RPC)
  gvas2.py                   Loadout.sav binary format reader/writer
  mod/ClaudeBridge/           The UE4SS Lua mod this whole app talks to
  ue4ss_bundle/                A full bundled copy of RE-UE4SS (MIT-licensed)
```

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

## Feature inventory (what's actually shipped, tab by tab)

- **Host / Create Match** — pick map/gamemode from categorized trees
  (working / untested / no-content / broken; confirmed / unconfirmed
  maps), player/team caps, private/bots toggles, Load/Cycle/Force-Round-End
  (all guarded: check the live roster first, confirm if anyone besides you
  is connected before doing anything disruptive), a Match Control section
  (weather, round timer, end round/match — same guard), and Discover More
  Gamemodes.
- **Loadout Editor** — edit any loadout slot from the live catalog
  (`DT_OperatorSkins`/`DT_NewShopItem`), automatic timestamped backups
  before every write. **Currency & Unlocks panel**: set Reissad Points
  balance directly, unlock individual items, or sweep a full id range. See
  README for the full persistence model (both are session-only overrides,
  not permanent — a real Shop purchase made while boosted is the one path
  to a permanent unlock).
- **Game Speed** — Slomo presets/custom value. **Player Cheats**: Kill
  Self / Invincible / Infinite Ammo / Teleport Above (Kill Self,
  Invincible, and Infinite Ammo are known, confirmed non-functional —
  kept as harmless no-ops rather than removed). **Perk/Gadget Cooldown**:
  a genuinely working feature — "Clear Cooldown Now" and an "Auto-Clear
  every N sec" timer, since the effect must be reapplied for every new
  cooldown instance rather than being a one-time toggle.
- **Saved Command Buttons** — user-saved Console snippets as buttons,
  grouped by category, with a per-category "Run All" (sequential, saved
  order), import/export.
- **Console** — raw Lua console, saved history, "Save as Button."
- **Plugins** — load a shareable JSON plugin file as its own sub-tab.
- **Shell** — raw Bash on the local PC, unrelated to the game.
- **About** — credits (original vs. this fork, see top of this file).

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
- **This repo holds official, shipped state only.** Active development,
  in-progress experiments, and research notes belong outside this repo —
  don't add a running research log or scratchpad material here.

## For a chat-only (Claude.ai Project) session specifically

- You're reading a snapshot from the last manual "Sync now" click, not
  live state. If a question depends on very recent work, ask the user to
  sync first rather than assuming this file is current.
- You cannot run Lua, touch the game, or run Python here — implementation
  and live verification happen in a Claude Code session. Use this context
  for planning, design discussion, and reviewing what's already shipped;
  hand actual implementation back to Claude Code.
- If something the user says here conflicts with what's actually in this
  repo's files, say so — don't assume the repo snapshot is stale just
  because it disagrees with the conversation.
- `src/ue4ss_bundle/ue4ss/UE4SS.dll` is excluded from this Project's synced
  context (too large) — everything else in the repo is available. This is
  a bundled third-party binary (part of the RE-UE4SS distribution, not
  this project's own code), so its absence shouldn't matter for reasoning
  about anything this repo actually built; don't assume it's missing due
  to a sync problem or try to infer its contents.
