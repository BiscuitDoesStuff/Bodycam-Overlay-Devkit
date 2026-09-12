# Bodycam Overlay — Documentation

Everything past the README quick-start: setup/reset, a per-tab how-to, where
data actually lives, the Plugin/Saved-Command-Button file format,
troubleshooting, and every runtime path this app touches. Design rationale
and internal implementation notes for anyone reading or forking the source
live separately in **[docs/INTERNALS.md](INTERNALS.md)** — this file is the
user-facing reference; that one is the "why it's built this way" reference.

## Contents

1. [Setup & reset](#1-setup--reset)
2. [Per-tab how-to](#2-per-tab-how-to)
3. [Persistence model](#3-persistence-model)
4. [Saved Command Buttons / Plugin file format](#4-saved-command-buttons--plugin-file-format)
5. [Config files & the `.bak`/`.seed` mechanism](#5-config-files--the-bakseed-mechanism)
6. [Troubleshooting](#6-troubleshooting)
7. [Runtime paths](#7-runtime-paths)

---

## 1. Setup & reset

Normal setup is just running the app — see the README's **Install** section.
This section is for when something's actually broken.

**The overlay, not the game, owns setup/repair.** Every launch,
`install_bridge.ensure_setup()` runs once before the first connection poll:
it finds your Bodycam install, and if UE4SS is missing there, deploys the
bundled copy; either way it then installs or updates the ClaudeBridge mod.
None of this happens on the game's side — the game only ever loads whatever
is already sitting in its own `ue4ss/` folder.

**A full `ue4ss/` redeploy only happens when UE4SS is entirely missing or
broken there** (specifically: `ue4ss/Mods/shared/UEHelpers/UEHelpers.lua`
isn't found). When that happens, the overlay renames the existing `ue4ss/`
folder to `ue4ss.bak` first — never deletes it outright — so your other
UE4SS mods are recoverable if something goes wrong, then deploys a fresh
copy. The much more common case — UE4SS is fine, only ClaudeBridge itself
changed — only touches ClaudeBridge's own subfolder; your other mods and the
rest of `ue4ss/` are never touched.

**If you need to force a full reset by hand:**

1. Exit the overlay (system tray → **Exit**) and fully close Bodycam.
2. Delete `%LOCALAPPDATA%\Temp\bodycam_bridge` — safe to remove any time
   either side is closed; both sides recreate it as needed.
3. Rename (don't delete) the `ue4ss` folder inside **the `Binaries\Win64`
   folder the overlay reported** — check the status bar or
   `%LOCALAPPDATA%\BodycamOverlay\overlay.log` for the actual path it
   detected; it depends on which Steam library Bodycam is installed to, so
   don't assume a fixed `Program Files` location.
4. **Launch the overlay first**, not the game — it's the one that redeploys
   `ue4ss/`. Then launch Bodycam.
5. Still broken? Open the overlay's **Console tab** (not the game's own dev
   console, not a Windows terminal) and look for an error there before
   reporting an issue — it usually names exactly what failed.

---

## 2. Per-tab how-to

### 2.1 Host / Create Match

Pick a map and gamemode from filterable, categorized trees (maps: Playlist /
Dev-Unreleased / Unconfirmed; gamemodes: Working / Untested / No Content /
Broken — every gamemode the game's data references is listed, not just the
working ones, and a non-working pick shows its `note` and asks for
confirmation first). Zombie, Pit, OnlyPistol, and Training currently show
under "No Content" — their classes exist but there's no real playable
content behind them yet; **Discover More Gamemodes...** is for genuinely new
additions in future updates, not a way to unlock these.

**Load Custom Match / ↻ Cycle Current Match / Force Round End all check the
live player roster first** and ask for confirmation if anyone besides you is
currently connected — all three disrupt a real match in progress. Match
Control's weather/timer/round/match-end buttons route through the same
guard, for the same reason. Bot on/off writes `HMS_bBotsMethod`, but the
game doesn't always honor that flag directly — the player cap is what
actually controls how many bots get filled (see
[INTERNALS §5.5](INTERNALS.md#55-game_apipy--live-game-hacks-and-why-theyre-shaped-this-way)
for the manual-fill fallback this app uses instead).

**Reload Maps/Modes (from disk)** re-reads `families.json`/`maps.json`/
`gamemodes.json` from your `%LOCALAPPDATA%\BodycamOverlay\` copies and
repopulates both trees immediately — use it after hand-editing one of those
files instead of restarting the whole app.

### 2.2 Loadout Editor

Operator and each of the 5 slots have a **Change** button opening a
searchable list pulled *live* from the running game — a new skin/operator
added by a game update shows up with no code changes needed. Slot changes
let you pick any category, not just that slot's usual one. **Attachments
aren't fully rebuilt on a slot change** — only the weapon + bundle swap, plus
a couple of attachment rows for the one weapon currently known to need
specific parts to fire (the Crossbow: Trigger + Arrow); other weapons keep
whatever attachments the slot already had.

Every write is automatically backed up first (**Restore Backup...** picks
from up to 20 timestamped backups, itself backing up whatever it's about to
overwrite before restoring). **The save file is Steam Cloud-synced** — an
edit applies in-session, but a full game restart *before* the game itself
re-saves can revert it; reselect or cycle the loadout in the same session to
make a change stick.

Currency & Unlocks are live `GameInstance` overrides, not save-file writes —
see [§3](#3-persistence-model) for exactly what resets on restart and what
doesn't.

### 2.3 Game Speed

Slomo: 8 presets (0.1x–5x) plus a custom value field. **Player Cheats (Kill
Self, Invincible, Infinite Ammo) call cleanly but have no actual effect** —
left in as harmless no-ops; see [INTERNALS §5.5](INTERNALS.md#55-game_apipy--live-game-hacks-and-why-theyre-shaped-this-way)
for which functions and what was observed. **Perk / Gadget Cooldown** is a
real, working Server RPC: **Clear Cooldown Now** clears whatever cooldown is
currently running, and **Auto-Clear** repeats that on a timer, since the
effect only clears the *current* instance rather than disabling the system —
it has to be reapplied every time a new cooldown starts.

### 2.4 Saved Command Buttons

Every snippet saved from the Console tab, grouped by category, as Run Once
buttons and Toggle checkboxes. Each category's **▶ Run All** runs every
button in that group once, in saved order, stopping at the first error (a
toggle run this way is always forced ON). Per-button delete/recategorize,
plus Import / Export All / Export Selected for sharing a set of commands —
see [§4](#4-saved-command-buttons--plugin-file-format) for the file format.

### 2.5 Console

Raw Lua **inside the running game process** — see
[INTERNALS §5.1](INTERNALS.md#51-bridge-protocol-bridge_clientpy--srcmodclaudebridgescriptsmainlua)
for the request/response round trip. Every payload runs in a `pcall` on the
game's side, so a Lua-level error comes back as a normal message, not a
crash — but that only covers Lua errors. A bad native call, or touching an
invalid/freed UObject, can still crash the actual game the same way any
other UE4SS Lua mod can. **There is no sandbox.** Test one small thing at a
time, especially before saving it as a button.

Globals available in every payload (all injected by ClaudeBridge itself —
see `main.lua`'s `handle()`):

| Global | What it does |
|---|---|
| `pawn()` | The local player's current pawn, or `nil`. |
| `pc()` | The local `PlayerController`, or `nil`. |
| `gm()` | The live `GameModeBase` instance, or `nil` outside a match/lobby. |
| `gs()` | The live `GameStateBase` instance, or `nil`. |
| `UEHelpers` | The standard UE4SS helper module (`GetWorld`, `GetGameInstance`, etc). |
| `props(obj)` | Every readable property on `obj` (default `pawn()`), walking the full class chain. Only "safe" types are read (ints/floats/bools/names/object refs); structs/arrays/maps/sets are named but never read. |
| `funcs(obj)` | Every `UFunction` name on `obj`'s class chain (existence only, not the signature). |
| `count(clsName)` | How many live instances of `clsName` exist, plus up to 20 full paths. |
| `render(v)` | Turns any Lua value (including a UObject/struct) into a readable string. |
| `valid(o)` | True only if `o` is non-nil AND `o:IsValid()` is true. Check before touching any object you didn't just get from `pawn()`/`pc()`/`gm()`/`gs()`/`UEHelpers`. |
| `chainOf(obj)` | The list of `UClass` objects from `obj`'s own class up to (not including) `UObject`. |
| `has(obj, name)` | True only if `obj` has a real, live `UFunction` called `name` (a missing one shows up as UE4SS's `TrivialObject` placeholder, also `"userdata"` to plain `type()`). |

If your code ends with `return <something>`, it's appended after any
`print()` output as `-- return: <rendered value>`. Alt+Up/Alt+Down replay
what you've run this session (in-memory, not saved). "Save as Button..."
opens a small dialog for a name and Run Once vs Toggle — see §4.3.

### 2.6 Plugins

Loads a shareable JSON "plugin" file — same widget shape as a Saved Command
Buttons export, plus a name and optional section labels/dividers — as its
own sub-tab. "Add Plugin..." shows a preview of every button's code first,
highlighting any occurrence of `os.*`/`io.*`/`require`/`dofile`/`load` in
red — a strong hint to read closely, not a guarantee the rest is safe. See
[§4.7](#47-safety-note) before adding anyone else's plugin.

### 2.7 Shell

Runs a Bash script on **your PC**, through Git Bash, completely separate
from the game — same unsandboxed access as a terminal you opened yourself
(your filesystem, your environment, whatever's installed). A Timeout field
(default 60s) kills a runaway script; that's the only guard rail. It does
not reach into the running game — that's the Console tab's job.

### 2.8 About

Credits, license info, and the app's version number.

---

## 3. Persistence model

Everything the app persists between runs lives in one place:
`%LOCALAPPDATA%\BodycamOverlay\` (see [§7](#7-runtime-paths) for the full
listing). Three different kinds of "doesn't reset" are easy to conflate —
they're genuinely different:

| What | Where | Resets on... |
|---|---|---|
| `families.json`/`maps.json`/`gamemodes.json` | `%LOCALAPPDATA%\BodycamOverlay\*.json` | Never on its own — hand-edited or app-written, it stays until you (or an app update, see §5) change it again |
| Saved Command Buttons / Plugins / UI state | `%LOCALAPPDATA%\BodycamOverlay\{snippets.json, plugins\, ui_state.json}` | Never on its own |
| Loadout slots (`Loadout.sav`) | The game's own save file, Steam Cloud-synced | Persists like any other game save, but a full restart *before* the game re-saves can revert a same-session edit — see §2's Loadout Editor note |
| Currency, item unlocks | Live `GameInstance` properties only, never written to a file | The **next** real currency-affecting event (a match ending, a Steam Cloud sync, a restart) — not a fixed timer, and not something this app can prevent |

The currency/unlock row is the one worth internalizing: those two features
are a **temporary boost**, full stop — re-run them whenever you want the
effect back. The one way to make an unlock permanent is to boost currency
here and then buy the item for real through the in-game Shop; a real
purchase goes through the game's own transaction flow and survives a
restart even though the currency number itself doesn't.

---

## 4. Saved Command Buttons / Plugin file format

### 4.1 The big picture

A "plugin" is a plain JSON file describing a tab full of buttons (plus
optional section labels/dividers). Loading one doesn't run any Python code
from the file and doesn't install anything beyond copying that JSON file —
it's purely a way to package and share a themed set of Console commands
instead of retyping them.

Saved Command Buttons (its own tab) and Plugins use the **exact same**
widget format under the hood:

| | Saved Command Buttons | Plugin |
|---|---|---|
| Scope | One flat personal list | A named, shareable bundle, with optional labels/separators for layout |
| Added via | "Save as Button..." in the Console tab | "Add Plugin..." in the Plugins tab |
| Stored at | `%LOCALAPPDATA%\BodycamOverlay\snippets.json` | `%LOCALAPPDATA%\BodycamOverlay\plugins\<name>.json` |

Exporting your Saved Command Buttons (Export All / Export Selected) already
produces a file that works as a plugin — add a `"plugin_name"` key at the
top and it's valid.

### 4.2 The file format

```json
{
  "version": 2,
  "plugin_name": "Movement Toggles",
  "widgets": [
    { "widget": "label", "label": "Movement" },
    {
      "widget": "button",
      "label": "Fly",
      "mode": "toggle",
      "code": "local p = pawn()\nif not p then return 'no pawn' end\nif TOGGLE_ON then\n  p:SetActorEnableCollision(false)\n  return 'fly ON'\nelse\n  p:SetActorEnableCollision(true)\n  return 'fly OFF'\nend"
    },
    { "widget": "separator" },
    {
      "widget": "button",
      "label": "Kill Self",
      "mode": "run_once",
      "code": "local p = pawn()\nif not p then return 'no pawn' end\npcall(function() p:K2_DestroyActor() end)\nreturn 'done'"
    }
  ]
}
```

Top level:

- `version` — currently `2`. Written by the app on every save/export; not
  required when writing one by hand (a missing `version` is treated the
  same as `2`).
- `plugin_name` — plugin files only. String shown as the tab's title. If
  missing, the Plugins tab falls back to the file's own name (minus
  `.json`) instead of failing to load.

**Legacy shape**: a Saved Command Buttons file saved before `"version"`/
`"widgets"` existed is a flat `{name: code}` object — no wrapper, no mode,
no category:

```json
{ "Kill Self": "local p = pawn()\np:K2_DestroyActor()" }
```

Both shapes still load today: a dict with a `"widgets"` key is read as
current-format, a dict without one is treated as this legacy flat shape
(each entry becomes a `run_once` button with no category), anything else
(a list, a string, `null`) loads as zero widgets rather than erroring.

`widgets` is a list, rendered top to bottom. Each entry has a `"widget"`
field:

- **`"label"`** — `{ "widget": "label", "label": "Section title" }`. A bold
  heading, no button.
- **`"separator"`** — `{ "widget": "separator" }`. A horizontal divider.
- **`"button"`** (or omit `"widget"` — it's the default, which is why the
  legacy flat shape above still loads):
  - `label` — button text.
  - `code` — Lua source, exactly what you'd type into the Console tab
    (same globals, §2's table).
  - `mode` — `"run_once"` or `"toggle"`, default `"run_once"`.
  - `category` — **Saved Command Buttons only** (a plugin's own `"label"`/
    `"separator"` widgets already cover sectioning). Buttons sharing a
    category group under one header with a "▶ Run All". Omit it (or use
    `""`) for an uncategorized button — shown first, under "General".

### 4.3 Run Once vs Toggle

**run_once**: click it, your code runs once, done.

**toggle**: renders as a checkbox. Every click, *before* your code runs, the
app injects one line ahead of it: `local TOGGLE_ON = true` (or `false`,
whichever the checkbox's new state is). Your code branches on that one
variable — there's no separate on-code/off-code. If your code errors, the
checkbox reverts to its previous state, so it never lies about whether the
effect actually applied.

The checkbox's state lives only in the running app — not saved to disk, and
not read back from the game. Every toggle starts unchecked on a fresh
launch regardless of what's actually active in-game; write the "off" branch
so it's safe to run even if the real state doesn't match the checkbox.

### 4.4 How to make one

1. Console tab: write and test your Lua until it does what you want — test
   both run_once and toggle behavior for real before saving.
2. "Save as Button...", name it, pick Run Once or Toggle.
3. Repeat for as many commands as you want in the pack.
4. Saved Command Buttons tab: check the ones to share, "Export Selected...".
5. Open that file, add a top-level `"plugin_name"`, optionally add
   `"label"`/`"separator"` widgets for sections.
6. Plugins tab → "Add Plugin..." → pick it. The preview shows every
   button's code before "Add Plugin" actually installs it.

Or write the JSON by hand from §4.2 — nothing the UI does isn't representable
directly in the file.

**Removing a plugin**: select its sub-tab, "Remove Selected Plugin" —
deletes the underlying file. There's no per-button removal inside a plugin;
edit the file and re-add it instead.

### 4.5 Editing an existing plugin

Edit the `.json` file in `%LOCALAPPDATA%\BodycamOverlay\plugins\` directly
in a text editor, then restart the overlay (or remove + re-add it) to see
the change — plugin tabs are only built at startup / on Add Plugin, and
there's deliberately no in-app JSON editor.

### 4.6 Licensing of plugin files

This application's own code is MIT-licensed (`LICENSE`). A plugin file you
write is your own separate work — this project claims no license over
plugin content, and loading someone else's plugin grants you no rights to
redistribute it beyond whatever its author says. If you're sharing one
publicly, state your own terms somewhere in it (a `"label"` widget, a note
alongside it) — there's no in-app mechanism to enforce this either way.

### 4.7 Safety note

A plugin's code runs with exactly the same access as anything typed into
the Console tab — full Lua reflection into the live game process, no
sandbox, and (via `os.execute`/`io.open`, which ClaudeBridge's Lua exposes)
**arbitrary code on your PC, not just the game**. Adding someone else's
plugin means running their code, unreviewed. Read a plugin's `code` fields
before adding it, the same way you'd read a script before running it in a
real shell — the preview highlights an obvious OS call, but skimming past
the rest is still on you.

---

## 5. Config files & the `.bak`/`.seed` mechanism

`families.json`/`maps.json`/`gamemodes.json` are meant to be hand-editable
(see [INTERNALS §5.3](INTERNALS.md#53-why-some-data-is-hand-maintained-familiesjson))
— on first run each is copied from the bundled default into
`%LOCALAPPDATA%\BodycamOverlay\`, and every launch after that reads/writes
*that* copy, not the bundled one. `item_catalog.json` is extracted data,
never hand-edited, and is read straight from the app's own install — it is
not seeded or copied anywhere.

Every launch, before loading these three files, the app checks whether the
*bundled* default has changed since it was last seeded (tracked via a
`.seed` file next to each config — a copy of what was bundled at seed time):

- **Bundled default unchanged** → your copy is left completely alone,
  whatever state it's in. A corrupt hand-edit surfaces as a real error
  dialog naming the file, not a silent "fix".
- **Bundled default changed, and your copy still matches the old `.seed`**
  (you never touched it) → silently updated to the new default.
- **Bundled default changed, and your copy no longer matches** (you hand-
  edited it) → your copy is renamed to `<file>.bak` first, then replaced —
  never silently discarded — and this is logged to `overlay.log`.

Restoring a hand-edit after an update that triggered a `.bak`: close the
overlay, delete the new `<file>.json`, rename `<file>.json.bak` back to
`<file>.json`, relaunch.

---

## 6. Troubleshooting

**"not responding" in the status bar** — almost always one of: Bodycam
isn't running, it's a different install than the one the overlay set up, or
it was hot-reloaded (Ctrl+R) instead of fully restarted after the mod was
installed/updated. See [§1](#1-setup--reset) for the full reset procedure.

**Check the logs before anything else.** `%LOCALAPPDATA%\BodycamOverlay\overlay.log`
captures the overlay's own errors (a `--windowed` build has no console to
print to). `%LOCALAPPDATA%\Temp\bodycam_bridge\bridge.log` is ClaudeBridge's
own log, written from inside the game — check it if the overlay looks fine
but nothing in-game is happening.

**A Console/Plugin snippet that spawns an actor (e.g. a grenade) crashes the
game.** Confirmed via crash-dump analysis — a null-pointer dereference right
after `SpawnActor`, most likely GAS-related initialization the game's own
item-spawn path does that a raw `SpawnActor` skips. There is no known
workaround; don't spawn actors directly from Lua.

**Load Custom Match / Cycle Current Match reports success but nothing on
screen actually changes.** Observed after several travel attempts fired in
a short window (a handful within a few minutes) — the game's own travel
system can stop honoring `servertravel` calls entirely, even for a
map/mode combination that worked moments earlier. No in-app fix; fully
restart Bodycam and space out subsequent attempts. (If instead nothing
happened because a confirmation dialog appeared and was missed — see
§2's Host tab roster guard — check for a dialog behind the main window.)

---

## 7. Runtime paths

| Path | What's there |
|---|---|
| `%LOCALAPPDATA%\BodycamOverlay\families.json`, `maps.json`, `gamemodes.json` | Hand-editable config, seeded from the app's bundled defaults (§5) |
| `%LOCALAPPDATA%\BodycamOverlay\item_catalog.json` | Extracted shop-item catalog, read-only, not seeded |
| `%LOCALAPPDATA%\BodycamOverlay\snippets.json` | Saved Command Buttons |
| `%LOCALAPPDATA%\BodycamOverlay\plugins\*.json` | Installed Plugins |
| `%LOCALAPPDATA%\BodycamOverlay\ui_state.json` | Host tab's last-used map/gamemode/cap/team/private/bots |
| `%LOCALAPPDATA%\BodycamOverlay\overlay.log` | The overlay's own log (rotating, capped) |
| `%LOCALAPPDATA%\Temp\bodycam_bridge\` | `req.txt`/`resp.txt` (the live RPC channel) + `bridge.log` (ClaudeBridge's own log) |
| `<Bodycam>\Binaries\Win64\ue4ss\` | UE4SS itself + all Mods, including ClaudeBridge — the exact folder location depends on which Steam library Bodycam is installed to |
| `<Bodycam>\Binaries\Win64\ue4ss\Mods\mods.txt` | Enabled mods. Besides `ClaudeBridge`, expects 6 UE4SS enabler mods this app relies on: `CheatManagerEnablerMod`, `ConsoleCommandsMod`, `ConsoleEnablerMod`, `BPML_GenericFunctions`, `BPModLoaderMod`, `Keybinds` |
