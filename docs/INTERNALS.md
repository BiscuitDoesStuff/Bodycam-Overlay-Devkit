# Bodycam Overlay — Internals & design notes

Background for anyone reading, maintaining, or forking the source — the
"why" behind decisions that aren't obvious from the code alone. Per-function
comments in the source point back here (`§5.x`) instead of repeating this.
User-facing behavior (what a tab does, the file formats, troubleshooting)
lives in **[docs/DOCUMENTATION.md](DOCUMENTATION.md)** instead — this file
is for people editing the code, not just running it.

Headings keep their `5.x` numbers from when this content lived inside
DOCUMENTATION.md, so existing source citations still resolve.

## 5.1 Bridge protocol (`bridge_client.py` ↔ `src/mod/ClaudeBridge/Scripts/main.lua`)

File-based RPC, chosen because it needs no open port and no extra
dependency on either side (the game process can't accept a normal client
connection, and there's no in-game console reachable from Python). Both
sides write to a temp name and atomically rename into place, so neither
ever reads a half-written file.

```
req.txt   line 1 = request id (integer), lines 2+ = Lua source
resp.txt  line 1 = request id
          line 2 = OK | ERR
          lines 3+ = captured print() output, then "-- return:" + value
```

Lives under `%LOCALAPPDATA%\Temp` because a game launched by a store client
usually cannot write inside Program Files without elevation.

Safety properties, all load-bearing:

- **One `LoopAsync`, one `ExecuteInGameThread` per request**, gated by a
  `busy` flag — overlapping in-game-thread callbacks crash in
  `process_simple_actions` (a known unfixed UE4SS bug as of this writing).
- **The request is consumed before execution**, so a payload that crashes
  the game cannot replay itself on the next launch. On a Python-side
  timeout, `bridge_client.py` also removes its own `req.txt` before raising
  — otherwise a request the game never got to (e.g. it was closed) would
  still execute the moment it's relaunched.
- **Every payload runs under `pcall`**; a Lua error is reported, not fatal
  — but that only covers Lua-level errors. A bad native call or a
  touched-invalid-UObject can still crash the real game process. There is
  no sandbox.
- **Request ids are seeded from the system clock**
  (`int(time.time() * 1000)`), not a counter restarting at 1 — the Lua
  side's own dedup (`lastId`) persists for the whole game session, so a
  fresh Python-side counter starting at 1 on every overlay restart risked
  colliding with an id the game had already seen, silently dropping that
  request as a duplicate.
- **A `resp.txt` whose id doesn't match what's being waited for is deleted**,
  not left in place — otherwise it gets re-read on every 80ms poll tick
  forever. Deletion happens at most once per distinct stale id observed
  (not on every tick), narrowing — though not fully eliminating — a real
  race: Lua publishes a fresh `resp.txt` via its own remove+rename, and a
  same-instant Python-side delete-by-path could unlink that fresh file
  instead of the actually-stale one it raced against. See §5.9 for the
  general shape of this class of race.
- **`bridge_client._send()` serializes concurrent Python-side callers with a
  `threading.Lock()`** — two `AsyncRunner` threads (e.g. two "Refresh ..."
  buttons clicked close together) writing `req.tmp` at the same moment could
  throw a `PermissionError`, or worse, silently clobber each other's request
  before the game ever read it. `req.txt`/`resp.txt` are a single slot on
  the game side too (the `busy` flag above), so this makes the Python side
  take turns the same way, rather than trying to make the shared files
  themselves collision-proof.
- **`bridge.log` is truncated once per game launch**, then only appended to
  — previously it opened in append mode from the mod's very first line,
  growing without bound for as long as the game stayed open.

`main.lua` injects `pc`, `gm`, `gs`, `pawn`, `valid`, `has`, `render`,
`chainOf`, `props`, `funcs`, `count`, and `UEHelpers` as globals into every
payload's execution environment (see `handle()`) — `game_api.py`'s own Lua
snippets call these the same way a Console user would, instead of each
redeclaring `local pc = UEHelpers.GetPlayerController()`/
`(FindAllOf('GameModeBase') or {})[1]` inline. One subtlety this created:
a snippet that runs on its own timer well after the request that started it
returns (`spawn_bots_to_target`'s bot-fill loop) must alias these to locals
of the same name at the top (`local gm, gs, valid = gm, gs, valid`) rather
than only using the bare globals — otherwise a *different* Lua payload that
runs in between ticks and reassigns one of these names as a bare global
(easy to do by accident from the Console, forgetting `local`) would corrupt
what the timer sees on its next tick, with no `pcall` around that specific
call to catch it.

## 5.2 GVAS save-file editing (`gvas2.py`)

UE5.5's GVAS property format, for `Loadout.sav`, laid out as:

```
Property := Name:FString  TypeName  Size:int32  HasGuid:u8  Payload[Size]
TypeName := Name:FString  ParamCount:int32  ParamCount * TypeName   (recursive)
```

`gvas2.py` walks this structure to find every property's byte region.
Knowing where each `Size` field lives lets it change a string's length in
place and fix up every *enclosing* property's `Size` by the same delta —
that's what `set_rowname` does. `regions()` locates the start of the
property list by finding the `SG_Loadout_C` class-name tag; if that tag
isn't present (wrong file, corrupted save, an unexpected save format) it
raises a `ValueError` rather than silently computing a bogus offset and
parsing garbage as if it were real properties — every write path in this
file, including the verification described below, depends on this anchor
actually being found. (`set_rowname`/`set_row_in_region` raise `ValueError`
on their own invariant checks too, not a bare `assert` — an `assert` is
stripped entirely under Python's `-O` flag, which would silently turn a
real corruption/mismatch into unnoticed garbage data instead of an error.)

`game_api.py`'s `set_operator()`/`set_slot_weapon()` don't write to the
live `Loadout.sav` directly. `_apply_verified()` backs it up
(`backup_save()`, below), edits a throwaway `.pending` copy (`Path(...).
read_bytes()` for the before/after byte comparison), re-parses that copy
and asserts the result matches exactly what the edit was supposed to
produce (`_snapshot_loadouts()` before vs. expected vs. actual), confirms
the live file hasn't changed on disk since the edit started (catching the
game itself autosaving mid-edit), then does one atomic `os.replace()` and
re-verifies the installed result one final time. Earlier this wrote
directly and incrementally across multiple `gvas2` calls with only the
pre-edit backup as a safety net — a crash partway through could leave the
save half-updated (bundle changed but not weapon, say). This closes that
gap without changing the binary format at all.

`backup_save()` keeps only the 20 most recent backups (pruning older ones
on each call). The backup timestamp is second-resolution, so a `-2`/`-3`/...
suffix is appended whenever a backup lands in the same second as an earlier
one (confirmed to happen in practice — several `_apply_verified()` calls in
a fast sequence landed in the same second and would otherwise have silently
overwritten each other's backup slot); `list_backups()` strips that suffix
back out for display as `(#2)`/`(#3)`.

## 5.3 Why some data is hand-maintained (`families.json`)

Reading a weapon's actual in-game category tag crashes the process — it's a
`GameplayTagContainer` read, a documented crash in the UE4SS skills this
tool is built on. So instead: **individual items are always pulled live**
(skins, operators, new maps), but **which family belongs to which slot
category** lives in `families.json`, since that almost never changes. How
the persisted copy in `%LOCALAPPDATA%\BodycamOverlay\` gets seeded, reseeded
on an update, and backed up if hand-edited is covered in
[DOCUMENTATION §5](DOCUMENTATION.md#5-config-files--the-bakseed-mechanism),
not repeated here.

If a game update adds a **wholly new weapon family** (not just a new skin),
add one line to `families.json`:

```json
"NewGun Basic Bundle": {"category": "primary", "prefixes": ["NewGun"]}
```

`category` is one of `primary`, `secondary`, `melee`, `lethal`, `perk`,
`other`. `prefixes` is the item-name prefix(es) used for that weapon's
"Base X" rows in `DT_NewShopItem` — check with the game running:

```python
import game_api as api
[i for i in api._get_shop_items() if "NewGun" in i]
```

Most weapons use their bundle's own name as the prefix. A few don't (M4A1's
items are named "AR15 Base ...", Remington700 sometimes shows up as
"Rivington 700 ..."), which is why `prefixes` is a list, not a single
string.

`maps.json` and `gamemodes.json` are similarly small and hand-curated —
edit them the same way if the game adds a new map or mode. Both carry a
`status` field (`maps.json`: `confirmed`/`unconfirmed`; `gamemodes.json`:
`working`/`untested`/`no_content`/`broken` — see each file's own top-level
`_comment`) plus an optional `note`. The Host tab's pickers group by this
field and show the note for whichever entry is selected — nothing is ever
hidden for being unconfirmed or non-working, only visibly flagged.

## 5.4 `install_bridge.py` — why bundling UE4SS is on the right side of the line

`src/ue4ss_bundle/` holds a straight copy of the UE4SS + enabler-mod files
that were already installed and running on the author's own machine — not
anything downloaded fresh from the internet at install time. Deploying a
user's own, already-vetted files to a game folder they own is a different
thing from an exe silently fetching and planting unknown injection tooling;
that's the line this stays on the right side of. If `src/ue4ss_bundle/` is
ever missing (e.g. a fresh checkout of just the source, without re-running
the bundling step), setup falls back to pointing at the official UE4SS
release page instead of guessing.

`has_ue4ss()` doesn't just check the `ue4ss/` folder exists — a real
install found live also needs `ue4ss/Mods/shared/UEHelpers/UEHelpers.lua`,
the shared Lua library several mods (ClaudeBridge included) `require()`.
Without it, every such mod crashes on its first line with `module UEHelpers
not found` — a silent, total failure that looks like a connectivity problem
from the overlay's side rather than a missing-file one, so the check has to
catch that specifically.

`bridge_up_to_date()` compares the installed `main.lua` against the bundled
one byte-for-byte (`filecmp.cmp`, not just checking the `ClaudeBridge/`
folder exists) — a folder-only check meant an updated mod shipped with a
newer overlay build would never actually reach a user who'd installed an
older version, since the folder was already there. When a full UE4SS
redeploy is actually needed (`has_ue4ss()` fails — UE4SS itself missing or
broken), the existing `ue4ss/` folder is renamed to `ue4ss.bak`, never
deleted outright — a plain `shutil.rmtree()` would silently destroy any
*other* UE4SS mods the user has installed alongside ClaudeBridge. The much
more common case — UE4SS is fine, only ClaudeBridge changed — only replaces
ClaudeBridge's own subfolder, never touching the rest of `ue4ss/` at all.

`find_game_root()` doesn't just guess a handful of default paths — it first
reads the Steam client's own install location from the registry
(`HKCU\Software\Valve\Steam`'s `SteamPath`, falling back to the 32-bit and
64-bit `HKLM\...\Valve\Steam` keys' `InstallPath`, then a couple of hardcoded
default folders as a last resort) and parses that install's
`steamapps/libraryfolders.vdf` for every library folder the user has added,
on any drive. Each library is checked for `steamapps/common/Bodycam/...`
before falling back to `CANDIDATE_ROOTS`'s short guess list. The VDF parsing
is a plain regex over `"path" "..."` lines rather than a real VDF parser --
that's the only key this needs, and libraryfolders.vdf's structure has been
stable for years.

## 5.5 `game_api.py` — live-game hacks and why they're shaped this way

- **`write_cap` / `host_and_travel`**: each gamemode has its **own**
  persistent cap asset (confirmed live: switching Deathmatch cap=20 →
  Versus came back at Versus's own default of 10), so the cap is only
  written *after* the target mode's GameMode instance actually exists —
  i.e. after the travel, not before. `write_cap` also refuses to write
  while `CurrentPhase` is `StartRound` (returns `'ABORT: ...'`); the caller
  (`write_cap_retrying`) polls until that window passes.
- **`host_and_travel`'s private-match password** (`SESSION_PASSWORD`) is
  generated once per process via `secrets.token_hex(4)`, not a fixed string
  — every clone of this app used to share the same hardcoded password,
  which defeats the point of a private match. The Host tab shows the
  current process's password in a persistent label after a private Load
  (not just the status bar, which the very next status update would
  overwrite).
- **Bots**: `HMS_bBotsMethod` lives on the GameMode, not the GameInstance,
  but flipping it doesn't actually change `ShouldSpawnBots()`'s answer —
  that logic is buried in a generic Settings-Manager UI system with no
  direct property/setter reachable by reflection. `spawn_bots_to_target`
  bypasses it entirely, manually calling `GameMode:SpawnBot()` once per 4
  seconds (spawning 25 in one callback froze the game once during testing)
  and is generation-guarded — calling it again supersedes any fill already
  in progress rather than stacking a second timer.
- **`cycle_match`**: the game's own mode rotation loads per-mode-prefixed
  level names (`DM_Airsoft`, `TDM_BombHouse`, `GG_CQB`, ...), not the bare
  package name in `maps.json` — a known mode prefix is stripped before
  comparing (confirmed live: rotation landed on `"DM_BombHouse"` while
  `maps.json` has `"BombHouse"`).
- **Spawning arbitrary actors (e.g. grenades) crashes the game** — confirmed
  via crash dump analysis (null-pointer dereference right after
  `SpawnActor`, most likely GAS-related initialization the game's own item
  spawn path does that a raw `SpawnActor` skips). There is no Spawn tab for
  this reason; don't reintroduce raw actor spawning without solving that.
  See §5.8 for how that crash dump was actually read.
- **`get_match_info`**: three of its five fields (`GetLobbyAccessMethod`,
  `IsHostMigrating`, `GetServerSteamID`) aren't plain getters — each is a
  BlueprintNativeEvent-style function taking one **out** parameter, called
  as `fn(t)` with an empty Lua table that UE4SS fills in afterward
  (confirmed live field names: `t.LobbyAccessMethod`, `t.Yes`, `t.SteamID`).
  `SteamID`'s value is an FString wrapper needing `:ToString()`, same gotcha
  as `get_current_level_name()`. `lobby_private`'s polarity was
  cross-checked live against `GameInstance:UpdateLobbyAccessMethod(True/False)`
  and matches `host_and_travel`'s own `private` argument exactly.
  `IsAllRoundFinish` was tried both argument-free and with an out-table and
  produced no value either way — dropped rather than shipped as a
  permanently-`'n/a'` field. The Team/Stats.Kill/Death/Score/RankName
  struct-field walk this shares with `get_lobby_roster()` (the array
  version, via `GameMode:GetPlayerConnected`) lives in one place,
  `_PC_FIELDS_LUA_HELPER`, embedded into each Lua payload (can't be a
  Lua-side shared function since each ClaudeBridge call is stateless)
  rather than separately-maintained copies of the same field allowlist.
  Also see §5.8: a `UFunction` with **multiple** out-parameters flattens
  all of them into the *first* table argument passed, not one table per
  parameter.
- **`get_player_roster`**: `APlayerState:GetPlayerName()` also returns an
  FString wrapper, not a plain string — same `:ToString()` fix. Doesn't
  attempt to separate real players from bots you spawned yourself (no
  confirmed PlayerState property for that yet), so a roster count includes
  both — see §5.6 for why that's still the right conservative default for
  `HostTab._guard_other_players`.
- **`discover_extra_gamemodes` / `add_gamemode`**: probes candidate class
  paths via `LoadAsset` (loads the package into memory) then
  `StaticFindObject(...) ~= nil` — deliberately does **not** call
  `IsChildOf`/`GetSuperClass` on the resulting class object to verify it's
  really a `GameModeBase` subclass, because calling either of those on a
  `StaticFindObject`-obtained class reference hung the bridge and crashed
  the game during this feature's own development (the same
  struct/reflection-handle crash class documented in §5.8). A plain
  non-nil check is as far as this is pushed. `add_gamemode` defaults new
  finds to `status: "untested"` — see `gamemodes.json`'s own comment for
  the full taxonomy, and why `no_content` (a class/asset reference with
  nothing actually implemented behind it, confirmed for
  Training/Zombie/Pit/OnlyPistol) is kept distinct from `broken`.
- **`list_weather_presets`/`set_weather`**: both the weather object and the
  `GameState` are re-obtained fresh via `FindAllOf` on every call, never
  cached or extracted from a struct — confirmed live (set to Rain, then
  Foggy). `WeatherManagerComponent` is declared on the GameState, not the
  Lobby-only GameMode, so unlike `get_match_info`'s extra fields this is
  expected to also work inside an actual hosted match, though that
  specific combination hasn't been independently tested.
- **`kill_self`/`set_game_timer`/`end_round`/`end_match`/`set_invincible`/
  `set_infinite_ammo`/`set_slomo`**: thin wrappers around the game's own
  developer `CheatManager` (`BP_BodycamCheatManager`, reached via
  `pc().CheatManager`), sharing one `_cheat_manager_call(call_expr,
  timeout)` helper for the common `pcall(...) -> 'OK'/'ERR: ...'` shape.
  `CheatEndRound` (paired with `CheatSetGameTimer(1.0)`) has a real,
  observed effect on `get_live_state()`. **`kill_self`/`set_invincible`/
  `set_infinite_ammo` call cleanly but have NO actual effect** — left
  shipped as harmless no-ops rather than removed. `end_match` is callable
  but its real effect hasn't been independently re-verified either way.
  (`CheatTeleportAbove` was also one of these wrappers but was removed
  after live testing confirmed it reliably kills the player — see §5.8 for
  the actual root cause, since it's more specific than "falling kills you".)
- **`disable_perk_cooldown`**: unlike everything else in this section, this
  calls a real Server RPC (`p['Server - CheatDisablePerkCooldown'](p)`,
  bracket-syntax because of the literal space in the UFunction's name — see
  §5.8), not a plain `CheatManager` function. Confirmed live, by direct
  in-game observation, to genuinely clear an in-progress gadget cooldown —
  but it is NOT a persistent toggle, it only clears whatever cooldown is
  running *right now*, so it has to be re-applied for every new cooldown
  instance. `SpeedTab`'s "Auto-Clear" checkbox exists specifically to work
  around that. The obvious numeric check for this
  (`PlayerState:GetRemainingGadgetCooldown()` before/after) is NOT a
  reliable way to verify it — that value just ticks down with real elapsed
  time regardless of this call, which looked like "no effect" until
  directly contradicted by watching the actual gadget in-game.
- **`get_currency`/`set_currency`/`unlock_item(s)`/`unlock_all_items`/
  `unlock_weapons_and_attachments`**: unlike everything else in this
  section, these don't call a `CheatManager` function at all — they
  read/write plain properties directly on the live GameInstance
  (`GI_BodycamSteamBackend_C`): `ActualReissadPointsScore`/
  `MaxAllowedReissadPoints` for currency, `PlayerInventoryItems` (a
  `TSet<int32>`) for item ownership. `unlock_all_items()` adds the exact
  real id list from `src/item_catalog.json` (2,131 ids, all four shop
  categories); `unlock_weapons_and_attachments()` adds just its
  `DT_WeaponSkins` category (1,507 ids). Reading real ids from
  `DT_NewShopItem` *live, in-game* still crashes by every method tried,
  which is why `item_catalog.json` reads the same table *offline* from the
  game's own decrypted pak files instead — zero live-game risk. ids that
  don't correspond to a real item are inert extra set entries, not errors.
  Visually confirmed in-game that `PlayerInventoryItems` membership alone
  is enough for the Locker/Shop UI to treat an item as owned — no
  `PlayerSkin.sav` entry needed. Both currency and unlock writes reset on
  the next real currency-affecting event (a match ending, a Steam Cloud
  sync, a restart) — see
  [DOCUMENTATION §3](DOCUMENTATION.md#3-persistence-model) for the
  permanent-unlock path (boost + buy for real) and why that one sticks
  when the raw property write doesn't.

## 5.6 The UI layer — a few non-obvious mechanisms

`overlay_app.py` (the `App` class, tray icon, single-instance lock, and the
`__main__` entry point) plus one `tab_*.py` module per tab and
`ui_common.py` (dialogs/mixins/helpers shared across 2+ tabs: `AsyncRunner`,
`PickerDialog`, `SaveButtonDialog`, `render_command_widgets`,
`render_label_or_separator`, `save_cancel_row`, `set_text`,
`ConsoleShellMixin`, `make_scrollable`, `load_ui_state`/`save_ui_state`) and
`ui_theme.py` (palette/fonts/spacing constants, widget factories, and the
`toplevel()` dialog factory).

- **Single-instance lock**: binding a fixed local TCP port (`47821`) is
  used purely as a mutex — a second launch failing to bind means an
  instance is already running. Two copies would each register their own
  Insert hotkey (the "opens two windows" symptom) *and* race on the same
  bridge req/resp files with no locking between them.
- **Tray icon / `quit_app`**: closing the window (X button) just hides it
  (so Insert keeps working), rather than quitting — the tray's "Exit" is
  the only clean shutdown path besides Task Manager. `quit_app` calls
  `os._exit(0)` rather than relying on the Tk mainloop returning naturally,
  because the `keyboard` library's hook thread isn't guaranteed to be a
  daemon thread; just destroying the Tk root could leave the process
  hanging around after "Exit".
- **Setup check on startup**: `install_bridge.ensure_setup()` runs once
  before the first connection poll, so a fresh install (or one missing
  ClaudeBridge/UE4SS, or running a stale ClaudeBridge version) gets fixed
  automatically rather than surfacing as a confusing "not responding"
  status. `api.load_config()` runs even earlier, in `__main__` right after
  the single-instance check and logging setup — deliberately not at
  import time, so a corrupt hand-edited config file raises somewhere that
  can show a real error dialog naming the file, instead of an import-time
  exception silently killing a `--windowed` build with no console to show
  it on. (An entry point that constructs `App()` directly without going
  through `__main__` — a debug script, say — needs to call
  `api.load_config()` itself first, or every map/gamemode/family list
  comes back empty with no error at all.)
- **`ui.toplevel()`**: every dialog (`PickerDialog`, `SaveButtonDialog`,
  the category-picker in Loadout, the recategorize dialog in Saved Command
  Buttons, `PluginPreviewDialog`) is built through this one factory, which
  also calls `transient(parent)` + `grab_set()` — previously each dialog
  reimplemented the rest of the setup (title/background/topmost/Escape)
  but none of them were actually modal, so a click on the main window
  behind an open dialog could still reach it.
- **`ui_theme.button()`'s focus ring**: a plain `RED` `highlightcolor` is
  invisible on a `kind="accent"` button, since the button's own fill is
  already `RED` — confirmed visually (a focused accent button showed no
  discernible ring). `focus_color` is `FG` specifically when the button's
  own `bg` is `RED`, so keyboard focus stays visible on every button kind,
  not just the neutral ones.
- **Host tab's map/gamemode pickers are `ttk.Treeview`, not `Combobox`/
  `Listbox`**: both group their real entries under category header rows
  (`HostTab.CAT_*` constants — a `\x00`-prefixed sentinel iid, since that
  can't appear in a real map/mode name, is how a selection is recognized as
  a category rather than a pickable item).
- **`HostTab._guard_other_players`**: `Load Custom Match` / `Cycle Current
  Match` / `Force Round End` / Match Control's weather/timer/round/match-end
  buttons all route through this before doing anything — a fresh
  `get_player_roster()` read (not cached) that asks for confirmation if
  more than the local player is connected, since any of them forcibly
  disrupts a real match in progress. Added after a real near-miss during
  this project's own testing: repeated live gamemode experiments almost ran
  against a match that turned out to have 5 real strangers in it.
  Deliberately does not try to distinguish bots from real players — an
  extra confirm click when it's actually your own bots is the acceptable
  cost of the safer default. Game Speed tab's Player Cheats section
  deliberately does *not* route through this guard — none of those force
  anything on anyone else.
- **Host tab's right column is a scrollable panel**
  (`make_scrollable(right_outer, panel=True)`, a fixed-width `width=270`
  outer frame with `pack_propagate(False)` so the sidebar's width doesn't
  shrink to fit a Canvas's otherwise-unpredictable requested width) rather
  than a plain fixed frame — needed once the sidebar grew past Live State/
  Match Info/Roster to also fit Match Control (weather, round timer, End
  Round, End Match).

## 5.7 Module map

| File | What it is |
|---|---|
| `overlay_app.py` | Entry point: `App` class, tray icon, single-instance lock, `__main__` |
| `tab_*.py` | One file per notebook tab, each a `ttk.Frame` subclass |
| `ui_common.py` | Dialogs/mixins/helpers shared by 2+ tabs |
| `ui_theme.py` | Palette, fonts, spacing, ttk style setup, widget factories |
| `game_api.py` | High-level API: live Lua calls (via `bridge_client`) + save-file edits (via `gvas2`) |
| `bridge_client.py` | The file-RPC client talking to ClaudeBridge (§5.1) |
| `gvas2.py` | `Loadout.sav` binary format reader/writer (§5.2) |
| `shell_client.py` | Runs Shell-tab scripts via Git Bash |
| `install_bridge.py` | Finds the game, deploys UE4SS + ClaudeBridge (§5.4) |
| `families.json`/`maps.json`/`gamemodes.json`/`item_catalog.json` | Hand-curated or extracted config (§5.3) |
| `mod/ClaudeBridge/` | The UE4SS Lua mod this whole app talks to |
| `ue4ss_bundle/` | A full bundled copy of RE-UE4SS |

## 5.8 UE4SS/Lua gotchas confirmed the hard way

Promoted from local research notes — each of these cost a real crash or a
dead-end investigation to pin down, and none of it is written down anywhere
else shipped with the project.

- **`AuthorityGameMode` can crash the game when dereferenced, without ever
  coming back as Lua `nil`.** `UEHelpers.GetGameModeChecked()` doesn't exist
  in this UE4SS build; the alternative, `pc:GetWorld().AuthorityGameMode`,
  is only a real, usable object when this machine is the authoritative
  server for that world (`pc:GetLocalRole() == 3`, i.e. `ROLE_Authority`).
  On a non-hosting client it's *not* `nil` and not safely dereferenceable —
  calling `:GetClass()` on it crashed the game, root-caused from a real
  crash dump. `(FindAllOf('GameModeBase') or {})[1]` (what `gm()` actually
  does) doesn't have this problem and is what this project uses everywhere
  instead.
- **`AssignTeam`/`KickPlayer` are not implemented, and shouldn't be
  attempted again without solving the underlying problem first.** Both
  need a freshly *constructed* nested struct as an input argument
  (`FSTR_KickVote` wrapping `FSTR_PCInfo`, GUID-mangled field names) —
  categorically different from every pattern confirmed safe elsewhere
  (reading a struct back, or passing through a live `FindAllOf`-obtained
  reference untouched). Confirmed live, twice independently (once with a
  self-read struct, once with a real second connected player's struct):
  passing even a completely unmodified, just-read `FSTR_PCInfo` straight
  into `AssignTeam(t, 1)` crashes the game outright, reproducibly.
- **Struct-extracted object handles are inert — safe to pass back into
  another native call, not safe to introspect.** A UObject pointer pulled
  out of a struct/out-param table (as opposed to obtained directly from
  `FindAllOf`/`UEHelpers`/`pawn()`) crashed the game when a *further*
  reflection method (`GetFName`, an equality check, `IsChildOf`,
  `GetSuperClass`) was called on it, even though those same methods work
  fine on a directly-obtained handle. Treat any such handle as opaque data
  to pass along, never to inspect.
- **The actual crash-report path, for when a bridge call kills the game**:
  `%LOCALAPPDATA%\Bodycam\Saved\Crashes\UECC-Windows-<guid>_0000\` holds a
  real minidump (`UEMinidump.dmp`) plus a human-readable
  `CrashContext.runtime-xml` — both far more informative than
  `ue4ss/UE4SS.log`, which only shows post-restart boot lines, never the
  crash itself. The `AssignTeam` crash above was root-caused this way: the
  error was `EXCEPTION_ACCESS_VIOLATION reading address 0x0000000C` (a
  null-pointer read at a small offset), and the callstack showed ~35 frames
  inside `UE4SS.dll` before ever reaching the game's own code, with one
  group of frames repeating three times in a row — a recursion signature
  consistent with UE4SS's Lua→native struct-packing code walking
  `FSTR_PCInfo`'s nested sub-structures and failing to reconstruct one of
  them correctly, not a problem with the game's own `AssignTeam` code.
- **Calling convention gotchas, collected**:
  - A UFUNCTION with a matching `X__DelegateSignature` entry next to it in
    the header dump is actually a **multicast delegate property** — calling
    it directly fails with `"attempt to call a MulticastDelegateProperty
    value"`. Call `:Broadcast(args...)` on the property instead (confirmed
    for `PropagateXPReward`, `Midnight`, `Instant Time of Day Change`).
  - The header dump renders Blueprint class names with a fake `A`/`U`
    type-prefix (`AGT_Bodycam_C`) that `FindAllOf` will not accept — strip
    it (`GT_Bodycam_C`). Passing the prefixed name doesn't error, it just
    silently returns `nil`, identical to "zero live instances."
  - A UFUNCTION whose display name contains a space (`"Server -
    CheatDisablePerkCooldown"`) can't use `:Name()` colon syntax — index
    with brackets and pass `self` explicitly: `obj['Server -
    CheatDisablePerkCooldown'](obj)`.
  - `"attempt to call a TrivialObject value"` means UE4SS found the named
    interface function but the concrete class never overrides it — safe,
    not a crash, and the actual mechanism `has(obj, name)` checks for
    (`type()` alone can't distinguish this from a real `UFunction`, since
    both read as `"userdata"`).
  - A UFUNCTION with **multiple** out-parameters (e.g.
    `GetScoreToWin(int32& ScoreToWin, int32& MaxKill)`) flattens *all* of
    them into the first table argument passed, not one table per
    parameter.
  - GameMode, GameState, and level-scoped environment actors only exist
    while actually hosting/in a real match — none of them are instantiated
    while sitting in the Lobby/menu, which is the practical reason so much
    of `get_match_info()`'s interface only returns real data from the
    Lobby specifically (it's declared on the Lobby's own gamemode class,
    `AGM_Bodycam_C`, and simply doesn't exist on a per-match GameMode
    instance) — a Lobby-GM-vs-match-GM interface split, not a bug.
- **Teleport Above's real root cause** (why it was removed, and why "just
  add invincibility first" can't fix it): death fires the instant the pawn
  leaves `MOVE_Falling` **by any means**, confirmed via fast-interval
  (0.1–0.2s) polling of `CharacterMovement.Velocity.Z`/`MovementMode`
  through the whole fall — a real landing and a manual
  `SetMovementMode(5, 0)` (forcing `MOVE_Flying` mid-fall) both trigger the
  identical instant-kill. This points at `BP_HandlePlayerDieFromFall` being
  wired to `OnMovementModeChanged` itself, not a ground-collision or
  fall-distance/impact-velocity check — which is why none of `God()`,
  `BreakFall = true`, or force-zeroing `Velocity` shortly before landing
  changed anything: forcing `MovementMode` to `Flying` right after
  teleporting froze the pawn's position with no further fall at all, but
  it was already dead on the very first poll, before any real falling
  motion had time to occur. No fix is possible through property writes or
  UFUNCTION calls alone; it would need patching the actual Blueprint graph
  behind `OnMovementModeChanged`, which UE4SS's Lua reflection surface
  doesn't reach.

## 5.9 Packaging notes

**`--onefile` extraction cost**: the packaged exe re-extracts its bundled
data (JSON configs, the ClaudeBridge mod, the full UE4SS bundle) to a fresh
temp directory on every launch — accepted as the cost of shipping one
downloadable file instead of a folder. `_HERE` (in both `game_api.py` and
`install_bridge.py`) resolves to that extraction directory via
`sys._MEIPASS` when frozen, or the source file's own directory otherwise —
either way, treat anything under it as read-only defaults, never a
persistence location (see
[DOCUMENTATION §3](DOCUMENTATION.md#3-persistence-model)).

**`os.replace()` PermissionError window**: both the bridge protocol (§5.1's
req/resp rename) and `install_bridge.py`'s `ue4ss` → `ue4ss.bak` rename rely
on `os.replace()`/`os.rename()` succeeding in one shot. On Windows, a rename
can fail with a transient `PermissionError` if another process (antivirus,
Explorer, a lingering handle) has the target briefly open — there's no
retry loop around either call. This has not been observed to cause a real
failure in practice, but if it ever does, a bounded retry-with-backoff
around the specific `os.replace()` call is the fix, not a broader redesign.
