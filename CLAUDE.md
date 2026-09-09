# CLAUDE.md

Shared context for any Claude session working on this repo — Claude Code
(with live tool/game access) or a Claude.ai Project (chat-only, reading a
GitHub-synced snapshot of these files). If you're in a chat-only session,
everything here is current **as of the last "Sync now" click** on the
Project, not live — treat anything time-sensitive (crash status, live
balances, in-game state) as historical record, not present tense.

## What this project actually is

A standalone desktop control panel for **Bodycam** (Unreal Engine 5.5) —
**not** injected into the game process. It runs as its own Python/Tkinter
application, talking to a live, running copy of the game through a UE4SS
Lua mod bundled inside this repo. This is a **fork**: the original
"Bodycam Overlay" was created by **clutch5.9**; this fork (**BDT Overlay
Fork**) is maintained by **BiscuitDoesStuff** at
github.com/BiscuitDoesStuff/BDT-Overlay-Fork, both under the MIT License
(original copyright preserved, per the license's own requirement).

This is a **modding/research tool for a single-player-adjacent game**, not
a competitive-multiplayer cheat. Scope, deliberately: cosmetic/economy
unlocks, loadout editing, weather/time control, developer-cheat-menu
access (self-only), and a research "Testing" tab for trying out newly
discovered game functions before deciding whether they're worth shipping.
Nothing in this repo targets or manipulates *other players'* state in a
way that currently works — the one attempt that would have (`AssignTeam`/
`KickPlayer`) was tried, crashed the game reproducibly, root-caused from
real crash dumps, and abandoned. See "Known crash classes" below.

## Repo layout

```
README.md                 User-facing feature list and setup instructions
LICENSE                    MIT (original clutch5.9 copyright preserved)
docs/DOCUMENTATION.md       Console/Shell/Plugins reference, troubleshooting,
                            §5 internals notes -- WHY things are shaped the
                            way they are, for anyone extending game_api.py
knowledge_base/
  CAPABILITIES.md           The primary living technical log -- what's
                            actually in the game, what's confirmed safe,
                            what crashes, what's confirmed NOT to work
                            despite calling cleanly. Read this before
                            trusting any claim about game behavior.
  sdk_headers/              A curated subset of real UE4SS-generated C++
                            headers (see "SDK reflection pass" below)
  dumps/                    Harvested content: operators, shop items,
                            maps, gamemodes, live state snapshots
community/                  Shared Saved-Command-Button and Plugin exports
src/
  overlay_app.py            Entry point -- App class, tray icon, single-
                            instance lock, __main__. One file per tab lives
                            alongside it: tab_host.py, tab_loadout.py,
                            tab_speed.py, tab_saved_buttons.py, tab_testing.py,
                            tab_console.py, tab_plugins.py, tab_shell.py,
                            tab_about.py. ui_common.py holds what's shared
                            across 2+ of them (AsyncRunner, PickerDialog,
                            SaveButtonDialog, render_command_widgets,
                            ConsoleShellMixin, _make_scrollable, ui-state
                            persistence). Split 2026-09-09 from one ~2,600-line
                            overlay_app.py -- pure reorganization, no behavior
                            change.
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
- **UE4SS's C++ Header Generator** (`Ctrl+H` in-game, or `GenerateSDK()`)
  dumps the real, live reflection graph of every currently-loaded class in
  the game to `<game>/Binaries/Win64/ue4ss/CXXHeaderDump/` — this is how
  most of the "what functions exist" knowledge in this project was
  actually discovered, not guessed or reverse-engineered by hand.

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
  balance directly, unlock individual items, or sweep a full id range
  (1-3250, or a narrower 1-999 guns-and-attachments-only sweep) — see
  "Currency & Unlocks" section below for the full persistence model.
- **Game Speed** — Slomo presets/custom value. **Player Cheats**: Kill
  Self / Invincible / Infinite Ammo / Teleport Above (see "Confirmed NOT
  working" below — these are kept but don't do anything). **Perk/Gadget
  Cooldown**: a genuinely working feature — "Clear Cooldown Now" and an
  "Auto-Clear every N sec" timer (see "Confirmed working" below).
- **Saved Command Buttons** — user-saved Console snippets as buttons,
  grouped by category, with a per-category "Run All" (sequential, saved
  order), import/export.
- **Testing** — one-click buttons for functions found via SDK-dump
  digging, not yet promoted into a real tab. Where a cheap readable value
  exists, checks it before AND after the call and reports whether it
  actually changed, not just whether the call errored (see "Confirmed NOT
  working" — this rigor is exactly what was missing before, and it's why
  this tab exists at all). Several rows are labeled "needs an active
  hosted match" or "HOST ONLY" because the underlying object genuinely
  doesn't exist, or isn't safe to touch, outside those conditions.
- **Console** — raw Lua console, saved history, "Save as Button."
- **Plugins** — load a shareable JSON plugin file as its own sub-tab.
- **Shell** — raw Bash on the local PC, unrelated to the game.
- **About** — credits (original vs. this fork, see top of this file).

## Currency & Unlocks — what it does and its real limits

- `set_currency(amount)` and `unlock_item(s)`/`unlock_all_items()`/
  `unlock_weapons_and_attachments()` write **directly to live GameInstance
  properties** (`ActualReissadPointsScore`/`MaxAllowedReissadPoints` for
  currency, `PlayerInventoryItems` — a `TSet<int32>` — for ownership) on
  `GI_BodycamSteamBackend_C`. No purchase call, no cheat-menu call.
- **Confirmed live, visually, in the actual Locker/Shop UI**: adding an id
  to `PlayerInventoryItems` is sufficient on its own for the game to treat
  an item as owned/equippable — no `PlayerSkin.sav` entry needed.
- **Both are session-only overrides, not permanent changes.** Confirmed:
  a value set above the real cap (40,000) resets back to 40,000 on the
  next real currency-affecting event (a match ending, a Steam Cloud sync,
  a restart) — this is expected/intended, not a bug. Item unlocks reset
  the same way, on the same kinds of events.
- **The one real path to a *permanent* unlock**: boost currency, then
  actually buy the item for real through the game's own Shop UI before the
  next resync. A real purchase survives a restart even though the currency
  number itself doesn't — confirmed directly by the app maintainer.
- There is no safe way to read the game's real item-catalog id list
  (every DataTable field-read approach tried crashes the game — see
  "Known crash classes"), so `unlock_all_items()` sprays a plausible id
  range rather than a precise one. Ids that don't correspond to a real
  item are confirmed harmless (silently inert).
- `unlock_weapons_and_attachments()`'s 1-999 cutoff is inferred from a
  sample of exactly 4 known real ids (2 weapon skins under 1000, a badge
  and an operator skin both at or above 1000) — a reasonable guess, not a
  verified category boundary.

## Confirmed NOT working (despite calling with no error) — don't trust "no error" alone

This is the single most important lesson embedded in this codebase: **a
Lua call succeeding with no error is not evidence that it did anything.**
An earlier version of this project's docs wrongly claimed `CheatKillMyself`
was confirmed to kill the local character, based on an insufficiently
verified observation. It was later directly contradicted by careful
real-gameplay testing. Corrected, and this class of mistake is now
explicitly guarded against in the Testing tab (before/after value checks,
not just "did it error").

- `CheatManager:CheatKillMyself()` / `CheatSetInvincible()` /
  `CheatInfiniteAmmo()` — all call cleanly, all confirmed to have **no
  actual effect** (self didn't die, damage wasn't prevented, ammo wasn't
  infinite). Kept shipped as harmless no-ops, not removed.
- The Server RPC versions of these (`Server - Cheat_KillMyself`, `Server -
  Cheat_ToggleInfiniteAmmo`, found on the player pawn) were specifically
  tried as a genuine non-hosting client (not just hosting with others
  joining in) on the theory that a real network RPC might route
  differently than a plain local call. **Also confirmed to have no
  effect** — ruling out "it only failed because you weren't host" as the
  explanation.
- `UCheatManager:God()` (the plain Unreal Engine base-class cheat, not
  Bodycam's own) also calls cleanly with an unconfirmed real effect either
  way — not established as different from `CheatSetInvincible`.

## Confirmed WORKING (the reliable capability list)

- Weather (`list_weather_presets()`/`set_weather()`) via
  `GameState.WeatherManagerComponent:StartWeatherTransition`.
- `kill_self()`'s sibling `end_round()` (`CheatEndRound`, paired with
  `CheatSetGameTimer(1.0)`) — confirmed via a real observed phase
  transition, not just "no error."
- Currency/inventory writes (see above) — visually confirmed.
- `RestartRound()` on the real per-match GameMode — confirmed via
  `get_match_info()`'s `started` flag flipping.
- `Midnight` / `Instant Time of Day Change` on `Ultra_Dynamic_Sky_C` (via
  `:Broadcast()` — see gotchas below).
- `Inspect()` / `Drop()` on a live equippable item.
- **`Server - CheatDisablePerkCooldown`** (a real Server RPC on the
  PlayerController) — confirmed via direct in-game observation to
  genuinely clear an in-progress gadget cooldown (tested against the FPV
  drone's 90s cooldown). **Important**: not a one-time toggle — it only
  clears whatever cooldown is running *right now*, so it must be
  reapplied for every new cooldown instance. The shipped "Auto-Clear"
  timer in the Game Speed tab exists specifically to work around this.
  Note: the obvious numeric check for this (`PlayerState:GetRemainingGadgetCooldown()`
  before/after) is **not reliable** — it just ticks down with real elapsed
  time regardless of the cheat, which looked like "no effect" until
  directly contradicted by watching the actual gadget in-game. A textbook
  case of "the observable you chose, not the function, is what didn't show
  an effect."

## Known crash classes — do not repeat these

All four root-caused from real crash dumps (`%LOCALAPPDATA%\Bodycam\Saved\Crashes\`),
never guessed. Read `CAPABILITIES.md` for full incident detail before
attempting anything similar.

1. Calling `IsChildOf`/`GetSuperClass` on a UClass reference obtained via
   `StaticFindObject`.
2. Calling `GetFName()`/equality on a UObject pointer extracted from
   *inside* a marshaled struct (safe on objects obtained directly from
   `FindAllOf`/`UEHelpers`/`pawn()`).
3. Passing a custom struct (`FSTR_PCInfo`/`FSTR_KickVote`) as a function
   **argument** — crashed `AssignTeam`/`KickPlayer` reproducibly, twice,
   with a real second player connected the second time. Root cause:
   UE4SS's Lua-to-native struct packing failing on nested sub-structures.
   **`AssignTeam`/`KickPlayer` are not implemented anywhere in this repo
   for this reason** — the feature was deliberately abandoned, not
   forgotten.
4. **`pc:GetWorld().AuthorityGameMode` is not a real usable object on a
   non-hosting client** (`pc:GetLocalRole() != 3`). It does NOT come back
   as Lua `nil` there — a plain `if not gm` check does not catch it — but
   dereferencing it (e.g. `:GetClass()`) crashed the game outright
   (`EXCEPTION_ACCESS_VIOLATION` at a near-null address). **Always check
   `pc:GetLocalRole() == 3` before touching `AuthorityGameMode` at all.**
   `(FindAllOf('GameModeBase') or {})[1]` does not have this problem and
   is preferred when you just need a nil-safe existence check.

Also: reading a DataTable row's field data (not just `GetRowNames()`) via
`DataTableFunctionLibrary`/`GetDataTableRowFromName`/
`GetDataTableColumnAsString` crashes, reproducibly, regardless of wildcard
pins vs. plain return types — the whole `Default__DataTableFunctionLibrary`
CDO pattern is unsafe in this UE4SS build. `GetRowNames()` (names only, no
field data) remains the ceiling for DataTable enumeration.

## UE4SS/Lua calling-convention gotchas (confirmed live, easy to get wrong)

- A UFUNCTION with a paired `X__DelegateSignature` entry in the header
  dump is a **multicast delegate property**, not a plain function — call
  `:Broadcast(args...)` on it, not the property itself (confirmed for
  `PropagateXPReward`, `Midnight`, `Instant Time of Day Change`).
- The SDK header dump renders Blueprint class names with a fake `A`/`U`
  type-prefix (`AGT_Bodycam_C`) that `FindAllOf` will not accept — strip
  it (`GT_Bodycam_C`). Passing the prefixed name silently returns `nil`,
  identical to "zero live instances."
- `UEHelpers.GetGameStateChecked()`/`GetGameModeChecked()` don't exist in
  this UE4SS build. Use `pc:GetWorld().GameState` /
  `pc:GetWorld().AuthorityGameMode` instead (but see crash class 4 above
  for the latter).
- A UFUNCTION whose name contains a space (`"Set Achievement"`) can't use
  `:Name()` colon syntax — index with brackets, pass `self` explicitly:
  `obj['Set Achievement'](obj, 'Name')`.
- A `UBlueprintFunctionLibrary` function with no natural instance is
  reachable via its CDO: `StaticFindObject('/Script/Bodycam.Default__SomeLibrary')`,
  then call directly on that — safe, distinct from crash class 1 (a CDO is
  a normal instance, not a bare class reference).
- `"attempt to call a TrivialObject value"` means the interface function
  was found but the concrete class never overrides it (empty default
  stub) — safe, not a crash, and not a bug to work around.
- A function whose header-dump name starts with `"Server - "` is a real
  Remote Procedure Call. Confirmed testable this way, but confirmed (for
  the ones tried) to have the same real-world effect as the plain
  function — being an RPC doesn't automatically mean it "really" works
  where a plain call didn't.

## SDK reflection pass — what's actually bespoke vs. third-party

A full pass over the SDK header dump (1,414 files, 162,330 lines) found
**12,277 classes/structs, 23,322 total function signatures**. Most of that
is publicly documented, not bespoke to this game:

- **`SteamCorePro`**, **`LootLockerSDK`** (`ULootLockerManager`, 221
  functions — the largest game-related class in the dump; LootLocker is a
  real, public SaaS game backend), **`MenuSystemPro`**,
  **`Ultra_Dynamic_Sky`/`Ultra_Dynamic_Weather`**, and **`ALS`**
  (Advanced Locomotion System) are all identifiable, publicly-documented
  third-party Marketplace products — no reverse-engineering needed for
  their own behavior.
- **`UBodycamSteamMockLibrary`** — a literal mock Steam layer for
  Bodycam's own dev/test use. Likely explains why
  `PurchaseInventoryItemWithSoftCurrency` calls cleanly but changes
  nothing (see CAPABILITIES.md).
- **Flagged, deliberately NOT tested**: `ULootLockerManager::GrantAssetToPlayerInventory`/
  `CreditBalanceToWallet`/`DebitBalanceToWallet`. Unlike everything else
  in this project, these are direct calls into a **real third-party cloud
  SDK** — if they reach a live (non-mocked) backend, they could write an
  actual persistent record to a real, company-hosted account, not a
  client-local illusion that resets on the next sync. A categorically
  different risk than anything else here. Do not call these without a
  separate, explicit decision to do so.
- The genuinely bespoke Bodycam surface (no public docs exist for this
  part, ever) is roughly 166 classes with "Bodycam" in the name plus a
  handful that don't (the Zombie-mode chain, `AAI_Humanoid_C`,
  `ABombe_C`, `BP_FPV_Drone_C`, `BP_RC_Car_Base_C`) — ~2,000-2,500
  functions of the 23,322 total. This is the only part where live testing
  is the *only* way to learn anything.

## Development conventions in this repo

- **Never trust "the call didn't error" as proof of effect.** Always
  check a real before/after value when one is cheaply available (see the
  `kill_self` correction above for what happens when this rule is
  skipped).
- **Always back up before any binary save-file write** (`Loadout.sav`,
  etc.) — automatic timestamped backups exist for exactly this reason.
- **Guard disruptive host actions** — check the live roster first, ask
  for confirmation if anyone besides the local player is connected,
  before restarting rounds, changing maps, etc. (see `HostTab._guard_other_players`).
  Purely local/cosmetic writes (currency, unlocks, own-pawn cheats) don't
  need this — they don't affect other players.
- **Crashes get root-caused from real crash dumps**
  (`%LOCALAPPDATA%\Bodycam\Saved\Crashes\`), never guessed at. This is far
  more informative than `ue4ss/UE4SS.log`, which only shows post-restart
  boot logs.
- **Commit only when explicitly asked.** Never force-push. Always merge,
  never rebase over the real repo's history.
- **Keep `knowledge_base/CAPABILITIES.md` as the single source of truth**
  for game behavior — this file (`CLAUDE.md`) summarizes it for
  quick/chat-only context, but CAPABILITIES.md has the full incident-level
  detail, exact function signatures, and dated findings. If the two ever
  disagree, CAPABILITIES.md is more likely to be current.

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
