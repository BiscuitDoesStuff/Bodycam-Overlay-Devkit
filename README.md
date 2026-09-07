# Bodycam Overlay

A standalone desktop control panel for Bodycam — **not injected into the game
process**. Toggle it with **Insert**. Requires the game to run in **windowed
or borderless** mode (a separate window can't render on top of exclusive
fullscreen).

Created by **clutch5.9**. Licensed under the [MIT License](LICENSE).

## Repo layout

```
README.md              You're reading it
LICENSE                 MIT license for this app's own code
requirements.txt        Python dependencies
build.bat               Packages src/ into dist/BodycamOverlay.exe
BodycamOverlay.spec     PyInstaller spec for the same build, if you run it directly

docs/
  DOCUMENTATION.md      Console/Shell/Plugins reference, troubleshooting, internals

community/
  buttons/              Shared Saved Command Buttons exports (.json)
  plugins/              Shared Plugin files (.json)

src/
  overlay_app.py         Tkinter UI -- all tabs
  game_api.py            High-level API: bridges live Lua calls + save-file edits
  bridge_client.py       Talks to ClaudeBridge (file-based RPC into the game)
  gvas2.py               Loadout.sav binary format reader/writer
  shell_client.py        Runs Shell tab scripts via Git Bash
  install_bridge.py      Finds the game, deploys UE4SS + ClaudeBridge
  smoke_test.py          Manual smoke test against a running game
  app_icon.ico           App / exe icon
  families.json, maps.json, gamemodes.json    Hand-curated config (see below)
  mod/ClaudeBridge/       The UE4SS Lua mod this whole app talks to
  ue4ss_bundle/           A full copy of RE-UE4SS (MIT-licensed, see its own LICENSE)
```

Everything the app actually runs lives under `src/` as one self-contained
unit — it bundles its own copy of the ClaudeBridge UE4SS mod and a full copy
of UE4SS itself, so `src/` doesn't depend on anything outside itself. Docs,
community content, and build tooling sit alongside it at the repo root.

## Setup (one-time)

```
pip install -r requirements.txt
python src/install_bridge.py
```

`install_bridge.py` finds your Bodycam install — checking every registered
Steam library folder first, then a short list of common fallback paths — or
asks for the path if it still can't find it. If UE4SS isn't already
installed there, it deploys the bundled copy; either way it then
installs/updates the ClaudeBridge mod and adds `ClaudeBridge : 1` to
`mods.txt` if it isn't already there. **Fully restart Bodycam afterward** —
a brand new mod folder isn't picked up by Ctrl+R hot-reload, only a real
restart. The packaged .exe (see below) runs this same check automatically on
startup, so most people never need to run this script by hand.

## Run it

```
python src/overlay_app.py
```

Or run the packaged `dist/BodycamOverlay.exe` (see **Packaging as an .exe**
below) — same behavior, no Python install required, and it repairs its own
UE4SS/ClaudeBridge setup on first launch.

Press **Insert** in-game to show/hide the window. Closing the window (the X
button) just hides it, same as Insert — to fully quit, use **Exit** from the
system tray icon (right-click it), or **Task Manager** if running from
source without the tray.

If the status bar says "not responding," the game either isn't running,
isn't the same install `install_bridge.py` set up, or wasn't fully restarted
after installing the mod.

## What it does

**Host / Create Match tab**
- Pick any map from a filterable, categorized tree — Playlist Maps,
  Dev/Unreleased (dev inventory room, empty loadout map, MoonTown, drone
  racetracks, etc.), and Unconfirmed (a map whose live package path is a
  best-guess, not yet confirmed to actually load — see
  `knowledge_base/CAPABILITIES.md`).
- Pick a gamemode from a similarly categorized tree: Working, Untested,
  No Content (a real class/asset reference exists but there's no actual
  playable content behind it — e.g. Zombie/Pit/OnlyPistol/Training), and
  Broken (engages as the active gamemode but has an actual problem). Every
  gamemode the game's own data references is listed, not just the 7 that
  work — selecting a non-working one shows why underneath the tree, and
  loading one prompts for confirmation first.
- Player cap and (for team modes) team cap.
- Toggle Private (sets a session password) and Bots.
- **Load Custom Match** hosts and travels there directly.
- **↻ Cycle Current Match** reads your *actual current* map/mode/cap/team
  size live from the game, ends the round, and reloads the exact same
  configuration.
- **Force Round End** forces a safe window for cap writes via the score-limit
  trick.
- Load Custom Match / Cycle / Force Round End all check the live player
  roster first and ask for confirmation if anyone besides you is currently
  connected, since any of the three will disrupt a real match in progress.
- Live State panel shows phase/population/cap live from the game. Match Info
  shows match-started/ended, lobby privacy, host-migration status, and
  server SteamID. Roster lists connected players' names (and flags in its
  own header when more than just you are present).
- **Discover More Gamemodes...** probes for gamemode classes the game's data
  references but that aren't in `gamemodes.json` yet, and offers to add any
  it finds (listed as Untested until confirmed).

**Loadout Editor tab**
- Pick any of your loadouts (count is read from the save file, not
  hardcoded).
- **Operator**, and each of the 5 slots, has a **Change** button that opens a
  searchable list pulled *live* from the running game (`DT_OperatorSkins`,
  `DT_NewShopItem`). New skins/operators added by a game update show up here
  automatically, no code changes needed.
- Slot changes let you pick *any* category (Primary/Secondary/Melee/Lethal/
  Perk/Other), not just the slot's usual one.
- **Set as Active Loadout** calls the game's own `SelectNewCurrentLoadout`.
- **Restore Backup...** picks from the automatic timestamped backups every
  edit makes and restores one (itself backing up whatever it's about to
  overwrite first, so it's never a one-way trip).

**Game Speed tab** — Slomo control plus quick 3x speed / reset buttons.

**Console tab** — a raw Lua console into the live game process, with saved
history and a "Save as Button..." action. See
**[docs/DOCUMENTATION.md](docs/DOCUMENTATION.md)** §1 for exactly how this
works, what globals are available, and its safety model.

**Saved Command Buttons tab** — every snippet you've saved from the Console
tab, as a scrollable list of Run Once buttons and Toggle checkboxes. Supports
per-button delete, and **Import** / **Export All** / **Export Selected**
(via a checkbox next to each button) using JSON files, so you can share a
set of commands with someone else.

**Plugins tab** — load a shareable JSON "plugin" file (same shape as a Saved
Command Buttons export, plus a name and optional section labels/dividers)
as its own sub-tab. "Add Plugin..." shows a preview of every button's code
before it's installed. See **[docs/DOCUMENTATION.md](docs/DOCUMENTATION.md)**
§3 for the exact file format, the Run Once vs Toggle mechanism, and how to
write one from scratch or by exporting from Console.

**Shell tab** — runs raw Bash scripts on your own PC via Git Bash, entirely
separate from the game. Also covered in
**[docs/DOCUMENTATION.md](docs/DOCUMENTATION.md)** §2.

**About tab** — credits and license info.

## Sharing buttons & plugins

[`community/buttons/`](community/buttons) and [`community/plugins/`](community/plugins)
hold shared Saved-Command-Button exports and Plugin files people have
contributed — download one and Import/Add it from the matching tab. See
each folder's own README, or **[docs/DOCUMENTATION.md](docs/DOCUMENTATION.md)**
§3, for exactly how. Read a file's `code` fields before adding it — Plugins
tab shows a preview for this reason, but nothing forces you to actually
read it.

## Why some data is hand-maintained (`families.json`)

Reading a weapon's actual in-game category tag crashes the process, so
**individual items are always pulled live** (skins, operators, new maps),
but **which family belongs to which slot category** is hand-curated in
`families.json` (with `maps.json`/`gamemodes.json` alongside it for maps and
modes) since that almost never changes. All three live in
`%LOCALAPPDATA%\BodycamOverlay\` once the app has run once — edit the copy
there to change behavior without rebuilding the exe. See
**[docs/DOCUMENTATION.md](docs/DOCUMENTATION.md)** §5.3 for exactly how to
add a new weapon family.

## Packaging as an .exe

```
build.bat
```
Produces `dist\BodycamOverlay.exe` from `src/`. **Re-run this any time a file
under `src/` changes** — the exe is a build artifact, the Python source is
what you actually edit. Run it from the repo root; `BodycamOverlay.spec`
does the same build if you'd rather invoke PyInstaller directly.

## Known limitations / things worth testing more

- **Attachments aren't fully rebuilt on a slot change** — only the weapon +
  bundle are swapped, plus a couple of attachment rows for weapons known to
  need specific parts to fire (currently just the Crossbow: Trigger +
  Arrow). Other weapons keep whatever attachments the slot already had.
- **Bot on/off** writes `HMS_bBotsMethod`, but `ShouldSpawnBots()` doesn't
  always honor that flag — the player cap is what actually controls how
  many bots get filled.
- **Global hotkey needs the `keyboard` library**, which on some systems
  needs the app run as Administrator to hook Insert while the game has
  focus.
- **The save file is Steam Cloud-synced** — edits made through the Loadout
  tab apply in-session, but a full game restart before the game itself
  re-saves can revert them. Cycle or reselect the loadout in the same
  session to make it stick.
- **Spawning arbitrary actors (e.g. grenades) crashes the game** — confirmed
  via crash dump analysis (null-pointer dereference right after
  `SpawnActor`, most likely GAS-related initialization the game's own item
  spawn path does that a raw `SpawnActor` skips). There is no Spawn tab for
  this reason; don't reintroduce raw actor spawning without solving that.

## License

[MIT](LICENSE) for this application's own code (everything under `src/`
except `src/ue4ss_bundle/`). The bundled UE4SS there carries its own MIT
license from its original author (`src/ue4ss_bundle/ue4ss/LICENSE`). Plugin
files people write for the Plugins tab are their own separate work — see
**[docs/DOCUMENTATION.md](docs/DOCUMENTATION.md)** §3.6.
