"""High-level API the overlay UI calls. Wraps bridge_client (live game RPC) and
gvas2 (Loadout.sav file editing) behind clean functions.

Design rule: individual items (skins, operators, maps found on disk) are always
pulled live/fresh; only the family->category mapping in families.json is
hand-maintained (see docs/DOCUMENTATION.md section 5.3 for why). Rationale for
the trickier live-game hacks below (bot fill, cap/travel ordering,
cycle_match's map-name matching) is centralized in that same file,
section 5.5, rather than repeated per function.
"""
import filecmp
import json
import logging
import os
import re
import shutil
import sys

import bridge_client as bc
import gvas2

# PyInstaller onefile builds extract bundled data (see build.bat's --add-data)
# to a temp dir exposed as sys._MEIPASS -- recreated fresh (and wiped) on every
# launch. Plain `python src/overlay_app.py` runs use this file's own directory.
_HERE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
SAVE_PATH = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Bodycam", "Saved", "SaveGames", "Loadout.sav")

# families.json / maps.json / gamemodes.json are meant to be hand-editable
# (see README) -- that only works if edits survive a restart, which _HERE
# alone can't guarantee in a packaged exe. Seed a persistent copy in AppData
# on first run (see load_config() below), then always read/write THAT copy;
# the bundled files under _HERE are just the initial defaults.
# Just a path -- no I/O here. Seeding/directory-creation happens in
# load_config(), called explicitly by overlay_app.py after logging is set up,
# so a corrupt hand-edited JSON gets a real error dialog instead of silently
# killing a --windowed exe at import time.
_CONFIG_DIR = os.path.join(os.environ.get("LOCALAPPDATA", _HERE), "BodycamOverlay")


def _load_json(name):
    """Loads a config file, dropping any "_..." documentation keys (see
    families.json's own "_comment"). Re-raises with the filename attached --
    json.JSONDecodeError's own message doesn't name the file, which matters
    here since the caller shows it in an error dialog naming "the bad file"."""
    path = os.path.join(_CONFIG_DIR, name)
    try:
        with open(path, encoding="utf-8") as f:
            return {k: v for k, v in json.load(f).items() if not k.startswith("_")}
    except (OSError, ValueError) as e:
        raise RuntimeError(f"{path}: {e}") from e


FAMILIES, MAPS, GAMEMODES = {}, {}, {}
_CONFIG_FILES = {"families.json": FAMILIES, "maps.json": MAPS, "gamemodes.json": GAMEMODES}

# Real item-id -> category mapping extracted offline from the shipped
# DT_NewShopItem.json (see item_catalog.json's own "_comment" for full
# provenance/caveats). Shaped differently from the three flat name->info
# maps above (nested under "categories"), so it gets its own small loader
# instead of going through _CONFIG_FILES. Used by unlock_weapons_and_
# attachments()/unlock_all_items() below to spray real ids instead of a
# guessed numeric range.
ITEM_CATEGORIES = {}


def _reload_item_catalog():
    # Extracted data, never hand-edited -- read straight from the bundled
    # copy under _HERE, not seeded into _CONFIG_DIR like the other three.
    with open(os.path.join(_HERE, "item_catalog.json"), encoding="utf-8") as f:
        data = {k: v for k, v in json.load(f).items() if not k.startswith("_")}
    ITEM_CATEGORIES.clear()
    ITEM_CATEGORIES.update(data.get("categories", {}))


def reload_configs():
    """Re-reads families.json / maps.json / gamemodes.json / item_catalog.json
    from disk in place (so a running overlay picks up hand edits without
    restarting)."""
    for _fname, _target in _CONFIG_FILES.items():
        _target.clear()
        _target.update(_load_json(_fname))
    _reload_item_catalog()


def load_config():
    """Seeds families/maps/gamemodes.json into _CONFIG_DIR (first run), then
    loads everything into FAMILIES/MAPS/GAMEMODES/ITEM_CATEGORIES. Called once
    by overlay_app.py at startup, after logging is configured -- if a
    hand-edited JSON is corrupt, json.load raises here and the caller can show
    a real error dialog instead of the import silently killing the exe.

    Re-seeding: a `.seed` file alongside each config is a copy of what _HERE's
    bundled default looked like the last time it was seeded. Re-seeding only
    happens when that bundled default has since changed (bundled != .seed) --
    a merely-corrupt or hand-edited dest is deliberately left alone otherwise,
    so json.load() below still raises on it instead of this silently "fixing"
    it. When the bundled default DID change, dest is only overwritten as-is if
    it still matches the old .seed (untouched by the user); otherwise it's
    renamed to `.bak` and logged first, never silently discarded."""
    os.makedirs(_CONFIG_DIR, exist_ok=True)
    for _cfg_name in ("families.json", "maps.json", "gamemodes.json"):
        _bundled = os.path.join(_HERE, _cfg_name)
        _dest = os.path.join(_CONFIG_DIR, _cfg_name)
        _seed = _dest + ".seed"
        if not os.path.exists(_dest):
            shutil.copy2(_bundled, _dest)
            shutil.copy2(_bundled, _seed)
        elif not os.path.exists(_seed):
            # Migrating from before the .seed mechanism existed -- seed from
            # the CURRENT bundled default (not the user's dest!), so a future
            # bundled change correctly treats any difference from THIS point
            # on as a real divergence to back up, instead of baselining on
            # whatever hand edits the user's dest might already carry.
            shutil.copy2(_bundled, _seed)
        elif not filecmp.cmp(_bundled, _seed, shallow=False):
            if filecmp.cmp(_dest, _seed, shallow=False):
                shutil.copy2(_bundled, _dest)  # untouched by the user -- safe to update
            else:
                _bak = _dest + ".bak"
                shutil.copy2(_dest, _bak)
                shutil.copy2(_bundled, _dest)
                logging.info(f"{_cfg_name} changed upstream and your copy had diverged -- backed up to {_bak}")
            shutil.copy2(_bundled, _seed)
    reload_configs()


# --------------------------------------------------------------------------- connectivity
def is_connected(timeout=3.0):
    ok, _ = bc.ping(timeout=timeout)
    return ok


def run_raw_lua(code, timeout=20.0):
    """For the Console tab: run arbitrary Lua on the game thread, full output
    (print() lines + the '-- return:' marker, if any) returned untouched."""
    return bc.run_lua_raw(code, timeout=timeout)


# --------------------------------------------------------------------------- saved console snippets
# NOT under _HERE: in a packaged exe, _HERE is PyInstaller's onefile temp
# extraction dir, recreated fresh (and wiped) on every launch -- anything
# written there is lost the moment the app closes. Saved snippets need an
# actual persistent, writable location regardless of frozen/dev-run state.
# Same _CONFIG_DIR the families/maps/gamemodes JSON files were seeded into above.
_SNIPPETS_PATH = os.path.join(_CONFIG_DIR, "snippets.json")
_PLUGINS_DIR = os.path.join(_CONFIG_DIR, "plugins")
os.makedirs(_PLUGINS_DIR, exist_ok=True)


def _normalize_widgets(data):
    """Accepts either the current {'widgets': [...]} shape or the original
    flat {name: code} shape saved buttons used before they had a mode -- so
    files/snippets.json saved before this existed still load correctly."""
    if isinstance(data, dict) and "widgets" in data:
        return list(data["widgets"])
    if isinstance(data, dict):
        return [{"widget": "button", "label": name, "code": code, "mode": "run_once"}
                for name, code in data.items()]
    return []


def list_snippets():
    """Saved Command Buttons, as a flat list of button widget dicts
    ({"widget": "button", "label", "code", "mode", "category"}). "category"
    is "" for an uncategorized button (shown as "General" in the UI) --
    older snippets.json files saved before categories existed just don't
    have the key, which .get("category", "") everywhere treats the same way."""
    if not os.path.exists(_SNIPPETS_PATH):
        return []
    with open(_SNIPPETS_PATH, encoding="utf-8") as f:
        return _normalize_widgets(json.load(f))


def list_snippet_categories():
    """Every distinct non-empty category currently in use, sorted -- for
    populating the category combobox's suggestions when saving/recategorizing
    a button."""
    return sorted({w.get("category") for w in list_snippets() if w.get("category")})


def _write_snippets(widgets):
    with open(_SNIPPETS_PATH, "w", encoding="utf-8") as f:
        json.dump({"version": 2, "widgets": widgets}, f, indent=2)


def save_snippet(name, code, mode="run_once", category=""):
    """Saves (or, if `name` already exists, replaces) one button. Buttons
    sharing the same `category` run together, in the order they appear in
    this list, when the Saved Command Buttons tab's per-category "Run All"
    is used -- re-saving a button (including via recategorizing it) moves it
    to the end of the overall list, and so to the end of its category's run
    order too."""
    widgets = [w for w in list_snippets() if w.get("label") != name]
    widgets.append({"widget": "button", "label": name, "code": code, "mode": mode, "category": category})
    _write_snippets(widgets)


def delete_snippet(name):
    _write_snippets([w for w in list_snippets() if w.get("label") != name])


def export_snippets(path, labels=None):
    """Exports all saved buttons, or only the given ones if `labels` is given
    (used by the Saved Command Buttons tab's Export Selected)."""
    widgets = list_snippets()
    if labels is not None:
        widgets = [w for w in widgets if w.get("label") in labels]
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"version": 2, "widgets": widgets}, f, indent=2)


def import_snippets(path):
    """Returns the button widgets found in `path` (labels/separators, which
    only make sense for a Plugin's layout, are dropped here since Saved
    Command Buttons is just a flat list). Caller decides how to merge/handle
    name conflicts against the existing saved buttons."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return [w for w in _normalize_widgets(data) if w.get("widget", "button") == "button"]


# --------------------------------------------------------------------------- plugins
# A plugin is a JSON file shaped like {"plugin_name": ..., "widgets": [...]}
# -- the same widget shape Saved Command Buttons uses, plus a name and
# optional "label"/"separator" widgets for layout. Deployed copies live under
# _PLUGINS_DIR (same persistent-AppData pattern as families.json/snippets.json)
# so they survive restarts and PyInstaller's MEIPASS wipe.
def list_plugins():
    out = []
    for fname in sorted(os.listdir(_PLUGINS_DIR)):
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(_PLUGINS_DIR, fname), encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        out.append({"id": fname, "plugin_name": data.get("plugin_name", fname[:-5]),
                    "widgets": data.get("widgets", [])})
    return out


def preview_plugin(source_path):
    """Reads and validates a plugin file WITHOUT installing it (no copy into
    _PLUGINS_DIR) -- lets the UI show what a plugin's buttons will actually
    run before the user commits to adding it (docs/DOCUMENTATION.md §3.7).
    Returns (plugin_name, raw_data)."""
    with open(source_path, encoding="utf-8") as f:
        data = json.load(f)
    if "widgets" not in data:
        raise ValueError("Not a valid plugin file: missing 'widgets'.")
    plugin_name = data.get("plugin_name") or os.path.splitext(os.path.basename(source_path))[0]
    return plugin_name, data


def add_plugin(source_path):
    plugin_name, data = preview_plugin(source_path)
    safe = "".join(c for c in plugin_name if c.isalnum() or c in " _-").strip() or "plugin"
    dest_name, counter = safe + ".json", 2
    while os.path.exists(os.path.join(_PLUGINS_DIR, dest_name)):
        dest_name = f"{safe} ({counter}).json"
        counter += 1
    data["plugin_name"] = plugin_name
    with open(os.path.join(_PLUGINS_DIR, dest_name), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return {"id": dest_name, "plugin_name": plugin_name, "widgets": data.get("widgets", [])}


def remove_plugin(plugin_id):
    path = os.path.join(_PLUGINS_DIR, plugin_id)
    if os.path.exists(path):
        os.remove(path)


# --------------------------------------------------------------------------- live catalog (cached per process run)
_cache = {"operators": None, "shop_items": None}


def get_operators(force=False):
    """All operator skin row names, live from DT_OperatorSkins."""
    if _cache["operators"] is None or force:
        body = bc.run_lua(
            "local dt=StaticFindObject('/Game/BodycamCore/ItemsDefinition/Skins/DT_OperatorSkins.DT_OperatorSkins')\n"
            "local rows=dt:GetRowNames()\n"
            "local out={}\n"
            "for _,rn in ipairs(rows) do out[#out+1]=tostring(rn) end\n"
            "return table.concat(out, '\\n')",
            timeout=20,
        )
        _cache["operators"] = sorted(l.strip() for l in body.splitlines() if l.strip())
    return list(_cache["operators"])


def _get_shop_items(force=False):
    """Every row name in DT_NewShopItem, live. Cached -- this table is large (700+ rows)."""
    if _cache["shop_items"] is None or force:
        body = bc.run_lua(
            "local dt=StaticFindObject('/Game/BodycamCore/ItemsDefinition/DT_NewShopItem.DT_NewShopItem')\n"
            "local rows=dt:GetRowNames()\n"
            "local out={}\n"
            "for _,rn in ipairs(rows) do out[#out+1]=tostring(rn) end\n"
            "return table.concat(out, '\\n')",
            timeout=30,
        )
        _cache["shop_items"] = [l.strip() for l in body.splitlines() if l.strip()]
    return _cache["shop_items"]


_ATTACHMENT_HINTS = (
    "trigger", "barrel", "grip", "stock", "magazine", "muzzle", "optic", "wheel",
    "shell", "antenna", "device", "spoiler", "reticle", "cylinder", "hammer",
    "slide", "forearm", "upperbarrel", "underbarrel", "ammo", "mount", "laser",
    "flashlight", "siderail", "sticker",
)


def bundles_by_category(category):
    return [name for name, info in FAMILIES.items() if info.get("category") == category]


def find_weapon_variants(bundle_name):
    """Skin variants for a bundle's base item(s), live-filtered from the shop catalog.
    Returns a sorted list of item row names, e.g. ['AR15 Base Anime', 'M4A1 Base Receiver', ...]."""
    info = FAMILIES.get(bundle_name)
    if not info:
        return []
    prefixes = info["prefixes"]
    category = info["category"]
    items = _get_shop_items()
    matches = set()

    if category == "perk":
        for p in prefixes:
            for it in items:
                if it.startswith(p) and (it.endswith("Chassis") or it.endswith("Drone")):
                    matches.add(it)
        if not matches:
            # fall back to a loose substring search, excluding obvious attachment parts
            for p in prefixes:
                for it in items:
                    low = it.lower()
                    if p.lower() in low and not any(h in low for h in _ATTACHMENT_HINTS):
                        matches.add(it)
    elif category == "lethal":
        for p in prefixes:
            for it in items:
                if it == p or it.startswith(p + " "):
                    low = it.lower()
                    if not any(h in low for h in _ATTACHMENT_HINTS):
                        matches.add(it)
    else:  # primary / secondary / melee / other
        for p in prefixes:
            pat = re.compile(r"^" + re.escape(p) + r" Base ", re.IGNORECASE)
            for it in items:
                if pat.match(it) or it.lower() == (p + " base receiver").lower():
                    matches.add(it)
        if not matches:
            # Some weapons (e.g. the Crossbow) don't use the "<prefix> Base <skin>"
            # convention at all -- fall back to a plain prefix match, excluding
            # rows that look like attachment parts rather than the weapon itself.
            for p in prefixes:
                for it in items:
                    low = it.lower()
                    if low.startswith(p.lower()) and not any(h in low for h in _ATTACHMENT_HINTS):
                        matches.add(it)

    return sorted(matches)


def find_bundle_for_weapon(item_name):
    """Reverse lookup: given a chosen weapon/vehicle item, find its bundle name."""
    for bundle_name, info in FAMILIES.items():
        for p in info["prefixes"]:
            if item_name.startswith(p):
                return bundle_name
    return None


def get_default_attachments_for(bundle_name):
    """A minimal, known-working attachment set for special-case weapons that need
    specific parts to function (mirrors what we verified by hand tonight)."""
    special = {
        "TenpointStealthCrossbow Basic Bundle": ["Crossbow Trigger", "Arrow"],
    }
    return special.get(bundle_name, [])


# --------------------------------------------------------------------------- maps (offline, from curated list)
def list_maps():
    return dict(MAPS)


def list_gamemodes():
    return dict(GAMEMODES)


# --------------------------------------------------------------------------- live match state
def get_live_state(timeout=15):
    """Returns dict: connected, map_gamemode_class, mode_name, phase, count, max, team_size."""
    lua = r"""
local function vld(o) if o==nil then return false end local ok,v=pcall(function() return o:IsValid() end) return ok and v==true end
local function isreal(v) return v ~= nil and not tostring(v):find("^TrivialObject") end
local gm = (FindAllOf('GameModeBase') or {})[1]
local gs = (FindAllOf('GameStateBase') or {})[1]
if not vld(gm) or not vld(gs) then return 'NOMATCH' end
local cls = '?'; pcall(function() cls = gm:GetClass():GetFName():ToString() end)
local ph = '?'; pcall(function() ph = gs.CurrentPhase.TagName:ToString() end)
local n = -1; pcall(function() n = gs:GetNumPlayersAndBot() end)
local mx = -1; pcall(function() mx = gs:GetMaxPlayers() end)
local tms = -1
pcall(function()
    local cfg = gm.ConfigDataAsset
    if isreal(cfg) then
        local tc = cfg.TeamConfig
        if isreal(tc) and isreal(tc.TeamMaxSize) then tms = tc.TeamMaxSize end
    end
end)
return cls .. '|' .. ph .. '|' .. tostring(n) .. '|' .. tostring(mx) .. '|' .. tostring(tms)
"""
    body = bc.run_lua(lua, timeout=timeout).strip()
    if body == "NOMATCH":
        return {"connected": True, "in_match": False}
    cls, ph, n, mx, tms = body.split("|")
    mode_name = None
    for name, info in GAMEMODES.items():
        if info["class"].endswith(cls + "_C") or cls == info["class"].split(".")[-1]:
            mode_name = name
            break

    if mode_name is None:
        # Not one of the 7 known playable modes -- this is the Lobby (GM_Bodycam_C)
        # or a transitional state during map rotation (e.g. GM_Host_C, seen live
        # tonight). Neither is a "real match" as far as cap/cycle logic cares.
        return {"connected": True, "in_match": False, "gamemode_class_short": cls}

    def _num(s, default=-1):
        try:
            return int(s)
        except ValueError:
            return default

    return {
        "connected": True,
        "in_match": True,
        "gamemode_class_short": cls,
        "mode_name": mode_name,
        "phase": ph,
        "count": _num(n),
        "max": _num(mx),
        "team_size": _num(tms),
    }


# Shared by get_match_info()/get_lobby_roster() below -- both read a
# Blueprint struct shaped like FSTR_PCInfo (a live player's team/kill/death/
# score/rank, GUID-mangled field names matched by PREFIX since only the
# prefix is stable across a Blueprint recompile) and used to each
# reimplement this same field walk independently. One definition here,
# embedded into each of those two Lua payloads (they're separate stateless
# ClaudeBridge calls, so it can't be a Lua-side function registered once --
# this just keeps there being exactly one Python-side source of truth for
# what "the safe PCInfo fields" means, instead of two copies that could
# drift). `prefix` distinguishes get_match_info()'s "my_team"/"my_kills"
# style (reading the local player) from get_lobby_roster()'s unprefixed
# "team"/"kills" style (reading someone else) -- same field names
# otherwise. Deliberately only reads plain ints/strings -- see each
# caller's own docstring for why the PC/Character/SteamID/SkinInfo/
# BadgeInfo fields and KillInfo are never touched beyond this (a real
# crash, confirmed live, not caution for its own sake).
_PC_FIELDS_LUA_HELPER = r"""
local function extract_pc_fields(t, out, prefix)
    for k, v in pairs(t) do
        if k:find('^Team_') then
            out[#out+1] = prefix .. 'team=' .. tostring(v)
        elseif k:find('^Stats_') and type(v) == 'table' then
            for sk, sv in pairs(v) do
                if sk:find('^Kill_') then out[#out+1] = prefix .. 'kills=' .. tostring(sv)
                elseif sk:find('^Death_') then out[#out+1] = prefix .. 'deaths=' .. tostring(sv)
                elseif sk:find('^Score_') then out[#out+1] = prefix .. 'score=' .. tostring(sv)
                elseif sk:find('^RankName_') then
                    local ok, rn = pcall(function() return sv:ToString() end)
                    out[#out+1] = prefix .. 'rank=' .. (ok and rn or 'n/a')
                end
            end
        end
    end
end
"""


def force_round_end(timeout=15):
    lua = r"""
local gs = (FindAllOf('GameStateBase') or {})[1]
if not gs then return 'no gamestate' end
local ok = pcall(function() gs:OverrideScoreLimit(2) end)
return tostring(ok)
"""
    return bc.run_lua(lua, timeout=timeout)


def get_match_info(timeout=15):
    """Best-effort read-only extras beyond get_live_state(): match-started/
    ended flags, lobby privacy, host-migration status, server SteamID.
    CONFIRMED LIVE (2026-09-07, in the Lobby): HasMatchStarted/HasMatchEnded
    take no arguments and return a plain bool. GetLobbyAccessMethod,
    IsHostMigrating, and GetServerSteamID are BlueprintNativeEvent-style
    functions that take ONE 'out' parameter -- called as `fn(t)` with an empty
    Lua table `t`, UE4SS fills in `t.<FieldName>` after the call (field names
    -- LobbyAccessMethod / Yes / SteamID -- confirmed live, not guessed).
    GetServerSteamID's value is an FString wrapper needing :ToString(), same
    gotcha as get_current_level_name() -- it reads as empty until you're
    actually hosting/in a session (confirmed empty from the Lobby). Also
    confirmed live: lobby_private's polarity matches host_and_travel's own
    `private` argument exactly -- calling GameInstance:UpdateLobbyAccessMethod
    (True/False) and reading GetLobbyAccessMethod back afterward moved in
    lockstep both directions, so True here really does mean private.
    IsAllRoundFinish was tried both argument-free and with an out-table and
    produced no value either way -- dropped rather than shipped as a
    permanently-'n/a' field.

    IMPORTANT correction (2026-09-07, later same day): GetLobbyAccessMethod/
    IsHostMigrating/GetServerSteamID are declared on AGM_Bodycam_C (the Lobby
    gamemode class specifically, confirmed via the UE4SS-generated C++ SDK)
    and do NOT exist on a
    per-match gamemode instance -- confirmed live: once actually in a
    Deathmatch match (GM_Deathmatch_C active), all three correctly degrade to
    'n/a' via this function's own pcall guard rather than erroring, but that
    means they only ever return real data while sitting in the Lobby. This
    isn't a bug in this function; it's a fact about the game's own class
    hierarchy. HasMatchStarted/HasMatchEnded are apparently on a shared base
    class and keep working in both places.

    Also: my_team/my_kills/my_deaths/my_score/my_rank via
    GetPcInfo, also Lobby-only for the same reason. Confirmed live: the
    struct's mangled field names match the real UE4SS-generated SDK exactly,
    and reading a nested struct (Stats) this way
    works fine -- the "structs aren't readable" reflection ceiling
    documented elsewhere applies to props()-style property reads, not to an
    explicit out-param call like this one. Deliberately does NOT read the
    PC/Character/SteamID/SkinInfo/BadgeInfo fields from this struct -- see
    the Lua comment inline for why (a real crash, not caution for its own
    sake)."""
    lua = _PC_FIELDS_LUA_HELPER + r"""
local function safe_out(fn, field, needs_tostring)
    local t = {}
    local ok = pcall(function() fn(t) end)
    if not ok or t[field] == nil then return 'n/a' end
    if needs_tostring then
        local ok2, s = pcall(function() return t[field]:ToString() end)
        if ok2 then return s end
    end
    return tostring(t[field])
end
local function safe_plain(fn)
    local ok, v = pcall(fn)
    if ok and v ~= nil then return tostring(v) end
    return 'n/a'
end
local gm = (FindAllOf('GameModeBase') or {})[1]
if not gm then return 'NOMATCH' end
local out = {}
out[#out+1] = 'started=' .. safe_plain(function() return gm:HasMatchStarted() end)
out[#out+1] = 'ended=' .. safe_plain(function() return gm:HasMatchEnded() end)
out[#out+1] = 'lobby_private=' .. safe_out(function(t) gm:GetLobbyAccessMethod(t) end, 'LobbyAccessMethod')
out[#out+1] = 'host_migrating=' .. safe_out(function(t) gm:IsHostMigrating(t) end, 'Yes')
out[#out+1] = 'server_steam_id=' .. safe_out(function(t) gm:GetServerSteamID(t) end, 'SteamID', true)

-- GetPcInfo (Lobby-only, like the three above) hands back the local player's
-- own FSTR_PCInfo -- see _PC_FIELDS_LUA_HELPER's own comment for the field
-- allowlist/exclusions this shares with get_lobby_roster().
local pcOk, pcErr = pcall(function()
    local t = {}
    gm:GetPcInfo(t)
    extract_pc_fields(t, out, 'my_')
end)
if not pcOk then out[#out+1] = 'my_team=n/a' end

return table.concat(out, '\n')
"""
    body = bc.run_lua(lua, timeout=timeout).strip()
    if body == "NOMATCH":
        return None
    info = {}
    for line in body.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            info[k] = v
    return info


def get_player_roster(timeout=15):
    """Read-only connected-player names via the base-engine
    APlayerState:GetPlayerName() -- confirmed live (2026-09-07): it returns
    an FString wrapper, not a plain Lua string, needing :ToString() (same
    gotcha as get_current_level_name()/get_match_info()'s SteamID field).
    Team assignment isn't included: no PlayerState property for it has been
    confirmed live yet."""
    lua = r"""
local out = {}
for _, ps in ipairs(FindAllOf('PlayerState') or {}) do
    local ok, name = pcall(function() return ps:GetPlayerName() end)
    if ok and name ~= nil then
        local ok2, s = pcall(function() return name:ToString() end)
        if ok2 and s ~= '' then out[#out+1] = s end
    end
end
return table.concat(out, '\n')
"""
    body = bc.run_lua(lua, timeout=timeout).strip()
    return [l.strip() for l in body.splitlines() if l.strip()]


def get_lobby_roster(timeout=15):
    """Per-connected-player team/kills/deaths/score/rank via
    GameMode:GetPlayerConnected(TArray<FSTR_PCInfo>&) -- the array version of
    get_match_info()'s my_* fields (which use the single-entry GetPcInfo).
    Lobby-only, same reason as everything else declared on AGM_Bodycam_C
    (see get_match_info()'s docstring) -- returns [] outside the Lobby.

    UNTESTED WITH MULTIPLE PLAYERS (2026-09-07) -- only ever exercised solo,
    where the call succeeds (`ok=true`) but the array legitimately comes back
    with zero entries (there's no one else "connected" to list). The
    per-entry field extraction below has never actually run against a
    populated array.

    Design rationale for why this is still safe to ship untested: a single
    out-param whose value IS an array is assumed to flatten the same way
    GetPcInfo's single out-param struct flattens directly into the passed
    table (confirmed live) -- i.e. `t[1], t[2], ...` are the individual
    FSTR_PCInfo entries, not nested under a 'PlayerConnected' key. This is an
    educated guess, not a confirmed fact. If it's wrong, `ipairs(t)` simply
    yields zero iterations (Lua's `ipairs` stops at the first missing integer
    key rather than erroring), so a wrong guess produces the same empty
    result as "genuinely no one else connected" -- there's no path here that
    errors or crashes from the shape being different than expected. Per-entry
    field extraction reuses get_match_info()'s exact safe-field allowlist
    (Team, Stats.Kill/Death/Score/RankName by name PREFIX) and the exact same
    exclusions (never PC/Character/SteamID/SkinInfo/BadgeInfo, never
    KillInfo) for the same reasons -- see that function's docstring.
    Re-verify this docstring
    against reality the first time it actually runs with 2+ connected
    players, and correct the flattening assumption above if the real shape
    turns out to be different."""
    lua = _PC_FIELDS_LUA_HELPER + r"""
local gm = (FindAllOf('GameModeBase') or {})[1]
if not gm then return 'NOGM' end
local out = {}
pcall(function()
    local t = {}
    gm:GetPlayerConnected(t)
    for i, entry in ipairs(t) do
        if type(entry) == 'table' then
            local fields = {}
            extract_pc_fields(entry, fields, '')
            out[#out+1] = tostring(i) .. '|' .. table.concat(fields, ',')
        end
    end
end)
return table.concat(out, '\n')
"""
    body = bc.run_lua(lua, timeout=timeout).strip()
    if body in ("NOGM", ""):
        return []
    roster = []
    for line in body.splitlines():
        if "|" not in line:
            continue
        idx, rest = line.split("|", 1)
        entry = {"index": idx}
        for pair in rest.split(","):
            if "=" in pair:
                k, v = pair.split("=", 1)
                entry[k] = v
        roster.append(entry)
    return roster


# --------------------------------------------------------------------------- weather (found via the UE4SS SDK dump, 2026-09-07)
def list_weather_presets(timeout=15):
    """Every live UDS_Weather_Settings_C instance's name, found via
    FindAllOf -- confirmed live: 19 instances, 13 with real names matching
    DT_WeatherWeight's rows exactly (Clear_Skies, Cloudy, Foggy, Overcast,
    Partly_Cloudy, Rain, Rain_Light, Rain_Thunderstorm, Sand_Dust_Calm,
    Sand_Dust_Storm, Snow, Snow_Blizzard, Snow_Light), plus a handful of
    unnamed `UDS_Weather_Settings_C_N` ones -- those are filtered out here
    since there's nothing meaningful to pick from a bare index."""
    lua = r"""
local out = {}
for _, w in ipairs(FindAllOf('UDS_Weather_Settings_C') or {}) do
    local ok, name = pcall(function() return w:GetFName():ToString() end)
    if ok and name and not name:find('^UDS_Weather_Settings_C_%d+$') then
        out[#out+1] = name
    end
end
return table.concat(out, '\n')
"""
    body = bc.run_lua(lua, timeout=timeout).strip()
    return sorted(l.strip() for l in body.splitlines() if l.strip())


def set_weather(name, transition_seconds=3.0, timeout=15):
    """Forces a weather transition via
    GameState.WeatherManagerComponent:StartWeatherTransition(weather_obj,
    seconds). Confirmed live 2026-09-07 (set to 'Rain' from the Lobby, game
    stayed stable). WeatherManagerComponent is declared on GT_Base (the
    GameState), not the Lobby's GameMode -- unlike get_match_info()'s
    Lobby-only fields, this SHOULD also work from inside an actual hosted
    match, but that specific combination hasn't been independently tested.
    `name` must be one of list_weather_presets()'s results; both `name`
    lookup and the weather object itself use only FindAllOf-obtained live
    instances, never a struct-extracted reference, so this doesn't touch
    any of the crash-prone patterns documented elsewhere in this file."""
    lua = f"""
local target = nil
for _, w in ipairs(FindAllOf('UDS_Weather_Settings_C') or {{}}) do
    local ok, wname = pcall(function() return w:GetFName():ToString() end)
    if ok and wname == {name!r} then target = w break end
end
if not target then return 'NOTFOUND' end
local gs = (FindAllOf('GameStateBase') or {{}})[1]
if not gs then return 'NOGS' end
local ok, err = pcall(function()
    gs.WeatherManagerComponent:StartWeatherTransition(target, {float(transition_seconds)})
end)
return ok and 'OK' or ('ERR: ' .. tostring(err))
"""
    result = bc.run_lua(lua, timeout=timeout).strip()
    if result == "NOTFOUND":
        raise ValueError(f"Weather preset {name!r} not found live -- see list_weather_presets()")
    if result == "NOGS":
        raise RuntimeError("No GameState found -- is the bridge connected?")
    if result != "OK":
        raise RuntimeError(result)


# --------------------------------------------------------------------------- CheatManager (BP_BodycamCheatManager, found via the UE4SS SDK dump, 2026-09-07)
# The game ships its own developer cheat menu, reachable the same way
# SpeedTab's Slomo already reaches it: `pc.CheatManager:SomeFunction()`. All
# of the functions wrapped below were confirmed live (2026-09-07, solo, from
# the Lobby) to call successfully with no error and no crash -- see each
# function's own docstring for exactly what was independently observed
# versus just "the call didn't error."
def _cheat(fn_name, timeout=15):
    lua = f"""
local pc = UEHelpers.GetPlayerController()
local ok, err = pcall(function() pc.CheatManager:{fn_name}() end)
return ok and 'OK' or ('ERR: ' .. tostring(err))
"""
    result = bc.run_lua(lua, timeout=timeout).strip()
    if result != "OK":
        raise RuntimeError(result)


def kill_self(timeout=15):
    """CheatManager:CheatKillMyself() -- the call itself succeeds with no
    Lua error, but per the app maintainer's own later, more careful
    real-gameplay testing, it does NOT actually kill the local character.
    This directly contradicts an earlier, wrong claim in this docstring
    ("confirmed live: killed the local character") that was based on an
    indirect/insufficiently-verified observation, not a clean before/after
    check -- corrected here rather than left standing. Calling this is
    therefore currently indistinguishable from a no-op as far as any
    observable in-game effect goes."""
    _cheat("CheatKillMyself", timeout)


def set_game_timer(seconds, timeout=15):
    """CheatManager:CheatSetGameTimer(seconds) -- sets the current round's
    timer, e.g. to skip a slow pre-match/warmup countdown by setting it low.
    Confirmed live the call succeeds; its real effect was observed
    indirectly (see end_round()'s docstring -- called together with this in
    the same test) rather than watched in isolation for this specific call."""
    lua = f"""
local pc = UEHelpers.GetPlayerController()
local ok, err = pcall(function() pc.CheatManager:CheatSetGameTimer({float(seconds)}) end)
return ok and 'OK' or ('ERR: ' .. tostring(err))
"""
    result = bc.run_lua(lua, timeout=timeout).strip()
    if result != "OK":
        raise RuntimeError(result)


def end_round(timeout=15):
    """CheatManager:CheatEndRound() -- confirmed live: called (immediately
    after also calling set_game_timer(1.0)) while a Deathmatch match existed
    in the background; get_live_state() moved GM_Deathmatch_C phase
    EndMatch -> (a few seconds later) WaitingForPlayers, i.e. it drove a
    real round-end-and-restart cycle, not a no-op. A cleaner alternative to
    force_round_end()'s OverrideScoreLimit trick wherever CheatManager is
    reachable."""
    _cheat("CheatEndRound", timeout)


def end_match(victory=True, timeout=15):
    """CheatManager:CheatEndGameVictory() / CheatEndGameDefeat() -- NOT
    individually confirmed live (end_round() was the one actually exercised
    end-to-end) but the exact same proven zero-arg CheatManager call
    pattern as kill_self()/end_round()/etc."""
    _cheat("CheatEndGameVictory" if victory else "CheatEndGameDefeat", timeout)


def set_invincible(timeout=15):
    """CheatManager:CheatSetInvincible() -- the call succeeds with no Lua
    error, but confirmed by the app maintainer's real-gameplay testing to
    have NO actual effect -- taking damage afterward was not prevented.
    Kept here (not removed) since it's still a harmless, error-free call,
    but do not expect it to do anything. `UCheatManager:God()` (the plain
    Unreal Engine base-class cheat, not Bodycam-specific) was also tried
    and confirmed NOT to prevent death from the now-removed
    `CheatTeleportAbove` cheat's fall (see docs/INTERNALS.md)."""
    _cheat("CheatSetInvincible", timeout)


def set_infinite_ammo(timeout=15):
    """CheatManager:CheatInfiniteAmmo() -- the call succeeds with no Lua
    error, but confirmed by the app maintainer's real-gameplay testing to
    have NO actual effect -- ammo was not observed to be infinite
    afterward. Kept here (not removed) since it's still a harmless,
    error-free call, but do not expect it to do anything."""
    _cheat("CheatInfiniteAmmo", timeout)


def disable_perk_cooldown(timeout=15):
    """PlayerController Server RPC `Server - CheatDisablePerkCooldown` --
    NOT a plain CheatManager function, a real Server RPC (confirmed live
    2026-09-08 as a genuine non-hosting client, LocalRole=2, in a real
    10-player match). Confirmed by the app maintainer's own direct in-game
    observation to genuinely clear an in-progress perk/gadget cooldown
    (equipped: the FPV drone, 90s base cooldown -- became redeployable
    immediately after this call).

    A numeric check via PlayerState:GetRemainingGadgetCooldown() before/
    after is NOT a reliable way to verify this call's effect -- repeated
    live tests showed that value just ticking down by ordinary elapsed
    time regardless of this call, which looked like "no effect" but was
    contradicted by direct observation of the actual gadget becoming
    usable again. Trust the real in-game result over that specific readback.

    IMPORTANT: this is NOT a persistent "cooldowns off forever" toggle --
    confirmed it has to be called again for each new cooldown instance
    (e.g. every time the gadget is redeployed and a fresh cooldown starts),
    not just once at the start of a session. `overlay_app.py`'s SpeedTab has
    an "Auto-Clear" checkbox that periodically re-calls this on a timer to
    work around exactly that limitation, since manually re-clicking after
    every single redeploy isn't practical."""
    lua = r"""
local pc = UEHelpers.GetPlayerController()
local ok, err = pcall(function() pc['Server - CheatDisablePerkCooldown'](pc) end)
return ok and 'OK' or ('ERR: ' .. tostring(err))
"""
    result = bc.run_lua(lua, timeout=timeout).strip()
    if result != "OK":
        raise RuntimeError(result)


# Candidate class paths for gamemodes DT_GamemodeInfo/DT_GameModeData list
# (Zombie, Pit, Training, OnlyPistol) that aren't in gamemodes.json -- the 7
# modes already there all live at /Game/GM/Gamemode/GM_<Name>.GM_<Name>_C, so
# that's the first guess for each; Zombie also gets a second guess mirroring
# where its DT_Zombie* data tables live (/Game/GM/Zombie/Gamemode/...), since
# its gameplay code may be organized in its own subfolder the same way.
# UNVERIFIED paths -- discover_extra_gamemodes() only tells you which of these
# guesses resolves to a real class, not that the guess was the "correct" or
# only path.
_GAMEMODE_CANDIDATES = {
    "Zombie": [
        "/Game/GM/Gamemode/GM_Zombie",
        "/Game/GM/Zombie/Gamemode/GM_Zombie",
    ],
    "Pit": [
        "/Game/GM/Gamemode/GM_Pit",
    ],
    "Training": [
        "/Game/GM/Gamemode/GM_Training",
    ],
    "OnlyPistol": [
        "/Game/GM/Gamemode/GM_OnlyPistol",
    ],
}


def discover_extra_gamemodes(timeout=25):
    """Probes _GAMEMODE_CANDIDATES via LoadAsset (loads the package into
    memory -- does NOT construct or spawn anything, so this is safe to run
    blind even against a wrong guess) then confirms with StaticFindObject.
    Returns {mode_name: class_path_or_None}. A hit still needs manually
    sanity-checking (team_based / default cap / team size) before trusting it
    in a real match -- see docs/DOCUMENTATION.md §5.3 for the gamemodes.json
    format add_gamemode() below writes into."""
    found = {}
    for mode_name, paths in _GAMEMODE_CANDIDATES.items():
        found[mode_name] = None
        for base_path in paths:
            class_name = base_path.rsplit("/", 1)[-1] + "_C"
            class_path = f"{base_path}.{class_name}"
            lua = f"""
pcall(function() LoadAsset({base_path!r}) end)
local cls = StaticFindObject({class_path!r})
return tostring(cls ~= nil)
"""
            try:
                body = bc.run_lua(lua, timeout=timeout).strip()
            except bc.BridgeError:
                body = "false"
            if body == "true":
                found[mode_name] = class_path
                break
    return found


def add_gamemode(name, class_path, team_based=False, default_cap=8, default_team_size=1,
                  status="untested", note=""):
    """Appends a new entry to the persisted gamemodes.json (the copy in
    _CONFIG_DIR seeded on first run, not the bundled default -- see
    reload_configs()/docs/DOCUMENTATION.md §5.3) and reloads GAMEMODES in
    place. Used by the Host tab's 'Discover More Gamemodes...' so a confirmed
    class path can be added without hand-editing the file first.

    `status` is one of 'working' / 'untested' / 'broken' -- a freshly
    discovered class defaults to 'untested' since finding the class path
    proves nothing about whether it's actually hostable (Training/
    GM_Training_C is a real example of exactly that gap -- see
    gamemodes.json's own entry for it). The Host tab groups its gamemode list by this field and shows
    `note` for whichever entry is selected, so a mode is never silently
    presented as equivalent to the confirmed-working ones."""
    path = os.path.join(_CONFIG_DIR, "gamemodes.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    entry = {"class": class_path, "team_based": team_based,
             "default_cap": default_cap, "default_team_size": default_team_size,
             "status": status}
    if note:
        entry["note"] = note
    data[name] = entry
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    reload_configs()


def write_cap(cap, team_size=None, bots=None, timeout=15):
    """Writes MaxPlayers (and optionally TeamMaxSize, HMS_bBotsMethod) only if
    not in StartRound (see docs/DOCUMENTATION.md §5.5). Returns a status string;
    caller should check for 'ABORT' and retry."""
    ts_line = f"pcall(function() gm.ConfigDataAsset.TeamConfig.TeamMaxSize={team_size} end)" if team_size is not None else ""
    bots_line = f"pcall(function() gm.HMS_bBotsMethod={str(bool(bots)).lower()} end)" if bots is not None else ""
    lua = f"""
local gm = (FindAllOf('GameModeBase') or {{}})[1]
local gs = (FindAllOf('GameStateBase') or {{}})[1]
if not gm or not gs then return 'no match loaded' end
local ph = '?'; pcall(function() ph = gs.CurrentPhase.TagName:ToString() end)
if ph:find('StartRound') then return 'ABORT: ' .. ph end
pcall(function() gm.ConfigDataAsset.TeamConfig.MaxPlayers = {cap} end)
{ts_line}
{bots_line}
local gi = UEHelpers.GetGameInstance()
pcall(function() gi['Session Max Players'] = {cap} end)
local sess = (FindAllOf('GameSession') or {{}})[1]
if sess then pcall(function() sess.MaxPlayers = {cap} end) end
local sb = '?'; pcall(function() sb = tostring(gm:ShouldSpawnBots()) end)
return 'WROTE phase=' .. ph .. ' ShouldSpawnBots=' .. sb
"""
    return bc.run_lua(lua, timeout=timeout)


def write_cap_retrying(cap, team_size=None, bots=None, attempts=8, delay=2.0, timeout=15):
    import time
    for i in range(attempts):
        result = write_cap(cap, team_size=team_size, bots=bots, timeout=timeout)
        if "WROTE" in result:
            return result
        time.sleep(delay)
    return result


def spawn_bots_to_target(target_count, timeout=15):
    """Manually fills to target_count via GameMode:SpawnBot(), one per 4s,
    bypassing ShouldSpawnBots()/HMS_bBotsMethod entirely -- see
    docs/DOCUMENTATION.md §5.5 for why. Generation-guarded: calling this again
    supersedes any fill already in progress rather than stacking a second
    timer."""
    lua = f"""
local function vld(o) if o==nil then return false end local ok,v=pcall(function() return o:IsValid() end) return ok and v==true end
local gm = (FindAllOf('GameModeBase') or {{}})[1]
local gs = (FindAllOf('GameStateBase') or {{}})[1]
if not vld(gm) or not vld(gs) then return 'no match loaded' end
_G.BOTFILL = _G.BOTFILL or {{}}
_G.BOTFILL.gen = (_G.BOTFILL.gen or 0) + 1
local MYGEN = _G.BOTFILL.gen
local TARGET = {target_count}
local function step()
    if _G.BOTFILL.gen ~= MYGEN then return end
    local gm2 = (FindAllOf('GameModeBase') or {{}})[1]
    local gs2 = (FindAllOf('GameStateBase') or {{}})[1]
    if not vld(gm2) or not vld(gs2) then return end
    local n = 0; pcall(function() n = gs2:GetNumPlayersAndBot() end)
    if n >= TARGET then return end
    local b; pcall(function() b = gm2:SpawnBot() end)
    if vld(b) then
        ExecuteWithDelay(2500, function() ExecuteInGameThread(function()
            pcall(function() if not vld(b.Pawn) then gm2:RestartPlayer(b) end end)
        end) end)
    end
    ExecuteWithDelay(4000, function() ExecuteInGameThread(step) end)
end
ExecuteWithDelay(1000, function() ExecuteInGameThread(step) end)
return 'bot fill gen ' .. MYGEN .. ' armed, target=' .. TARGET
"""
    return bc.run_lua(lua, timeout=timeout)


def stop_bot_fill(timeout=10):
    """Cancels any in-progress spawn_bots_to_target loop without starting a new one."""
    return bc.run_lua("_G.BOTFILL = _G.BOTFILL or {}; _G.BOTFILL.gen = (_G.BOTFILL.gen or 0) + 1; "
                       "return 'stopped'", timeout=timeout)


def host_and_travel(map_path, gamemode_class, cap, team_size, private, bots, session_name="Custom Match", timeout=20):
    """Full flow: end current round if in one (wait for it to settle), travel to
    map+mode, then write cap/team AFTER the new mode has loaded -- each gamemode
    has its own persistent cap asset, so writing it only makes sense once the
    target mode's GameMode instance actually exists (see docs/DOCUMENTATION.md
    §5.5). private=True sets both UpdateLobbyAccessMethod(true) and a session
    password as a second layer; bots=True bypasses HMS_bBotsMethod entirely and
    spawns manually via spawn_bots_to_target() (same section explains why).
    """
    import time
    state = get_live_state(timeout=timeout)
    if state.get("in_match"):
        force_round_end(timeout=timeout)
        time.sleep(15)  # let the phase actually settle before ending/traveling

    password = "ClaudeOverlay" if private else ""
    lua = f"""
local gi = UEHelpers.GetGameInstance()
pcall(function() gi['HostAlone?'] = false end)
pcall(function() gi['Session Use LAN'] = false end)
pcall(function() gi['Session Password'] = {password!r} end)
pcall(function() gi['Session Name'] = {session_name!r} end)
pcall(function() gi['Session Max Players'] = {cap} end)
pcall(function() gi['HMS_ExpectedPlayerCount'] = {cap} end)
pcall(function() gi:UpdateLobbyAccessMethod({str(bool(private)).lower()}) end)
local KSL = StaticFindObject('/Script/Engine.Default__KismetSystemLibrary')
local w = UEHelpers.GetWorld()
local pc = UEHelpers.GetPlayerController()
local ok = pcall(function() KSL:ExecuteConsoleCommand(w, 'servertravel {map_path}?game={gamemode_class}', pc) end)
if {str(not private).lower()} then pcall(function() gi.HMS_AdvertiseSession(gi) end) end
return 'travel issued ok=' .. tostring(ok)
"""
    travel_result = bc.run_lua(lua, timeout=timeout)

    time.sleep(12)  # let the new map/mode actually load before touching its cap/bots
    cap_result = write_cap_retrying(cap, team_size=team_size, bots=bots, attempts=10, delay=2.0, timeout=timeout)

    bot_result = ""
    if bots:
        bot_result = "; " + spawn_bots_to_target(cap, timeout=timeout)
    else:
        stop_bot_fill(timeout=timeout)  # cancel any earlier fill so it doesn't keep adding bots

    return f"{travel_result}; cap: {cap_result}{bot_result}"


def get_current_level_name(timeout=15):
    """Best-effort current level name via UGameplayStatics::GetCurrentLevelName.
    That function returns an FString object, not a plain Lua string -- it needs
    an explicit :ToString() (same as FName), tostring() alone just shows the
    wrapper's type+address."""
    lua = r"""
local GS = StaticFindObject('/Script/Engine.Default__GameplayStatics')
local w = UEHelpers.GetWorld()
local ok, name = pcall(function() return GS:GetCurrentLevelName(w, true) end)
if not ok or name == nil then return 'UNKNOWN' end
local ok2, s = pcall(function() return name:ToString() end)
if ok2 and s and s ~= '' then return s end
return 'UNKNOWN'
"""
    body = bc.run_lua(lua, timeout=timeout).strip()
    return None if body == "UNKNOWN" else body


def cycle_match(fallback_map_path=None, private=False, bots=True, timeout=20):
    """Capture current map/mode/cap/team size, end the match, and reload the exact same thing.
    fallback_map_path is used if the live level name can't be matched to a known map
    (pass the map_path the UI last hosted, if any). private/bots aren't reliably
    readable back from the live game, so the caller should pass through whatever
    it last set (the UI remembers this from its own last host/create-match action)."""
    state = get_live_state(timeout=timeout)
    if not state.get("in_match"):
        raise RuntimeError("not currently in a match -- nothing to cycle")
    mode_name = state.get("mode_name")
    if not mode_name:
        raise RuntimeError(f"couldn't map current gamemode class {state.get('gamemode_class_short')} to a known mode")
    gamemode_class = GAMEMODES[mode_name]["class"]

    level_name = get_current_level_name(timeout=timeout)
    map_path = None
    if level_name:
        # Mode rotation uses per-mode-prefixed level names, not maps.json's bare
        # package name -- strip a known prefix before comparing (docs/DOCUMENTATION.md §5.5).
        bare = level_name
        for prefix in ("DM_", "TDM_", "GG_", "HP_", "BB_", "VS_", "WM_"):
            if bare.startswith(prefix):
                bare = bare[len(prefix):]
                break
        for name, info in MAPS.items():
            last_segment = info["path"].rsplit("/", 1)[-1]
            if (last_segment.lower() == bare.lower()
                    or last_segment.lower() == level_name.lower()
                    or name.lower() == bare.lower()):
                map_path = info["path"]
                break
    if map_path is None:
        map_path = fallback_map_path
    if map_path is None:
        raise RuntimeError(
            f"couldn't resolve current level '{level_name}' to a known map path, "
            "and no fallback_map_path was given"
        )

    result = host_and_travel(
        map_path, gamemode_class, state["max"], state["team_size"],
        private=private, bots=bots, session_name="Cycled Match", timeout=timeout,
    )
    return {"map_path": map_path, "mode_name": mode_name, "cap": state["max"],
            "team_size": state["team_size"], "result": result}


# --------------------------------------------------------------------------- loadout file editing
def loadout_count():
    d, regs, rows, L = gvas2.slots(SAVE_PATH)
    return len(L)


def dump_loadout(idx):
    d, regs, rows, L = gvas2.slots(SAVE_PATH)
    lo = L[idx]

    def names(r):
        return [k["value"] for k in gvas2.row_in(rows, r)] if r else []

    return {
        "operator": names(lo["op"])[0] if names(lo["op"]) else None,
        "slots": [
            {"weapon": (names(s["weapon"]) or [None])[0], "bundle": (names(s["bundle"]) or [None])[0]}
            for s in lo["slots"]
        ],
    }


_BACKUP_PREFIX = os.path.basename(SAVE_PATH) + ".backup-"


def _list_backup_filenames():
    d = os.path.dirname(SAVE_PATH)
    if not os.path.isdir(d):
        return []
    return sorted(f for f in os.listdir(d) if f.startswith(_BACKUP_PREFIX))


def backup_save(keep=20):
    """Copies Loadout.sav to a timestamped .backup-<ts> file alongside it, then
    prunes down to the `keep` most recent backups so these don't accumulate
    forever (see docs/DOCUMENTATION.md §5.2). The timestamp is second-
    resolution, so a `-2`/`-3`/... suffix is appended whenever that exact
    filename is already taken (confirmed to happen in practice -- three
    _apply_verified() calls in a fast test run all landed in the same
    second and would otherwise have silently overwritten the same backup
    slot, each save() call's real "before this edit" state clobbering the
    previous one's instead of each being individually recoverable)."""
    import shutil, time
    ts = time.strftime("%Y%m%d-%H%M%S")
    dst = SAVE_PATH + f".backup-{ts}"
    n = 2
    while os.path.exists(dst):
        dst = SAVE_PATH + f".backup-{ts}-{n}"
        n += 1
    shutil.copy2(SAVE_PATH, dst)
    names = _list_backup_filenames()
    for old in names[:-keep] if keep > 0 else names:
        try:
            os.remove(os.path.join(os.path.dirname(SAVE_PATH), old))
        except OSError:
            pass
    return dst


_BACKUP_TS_RE = re.compile(r"^(\d{8}-\d{6})(?:-(\d+))?$")


def list_backups():
    """Available Loadout.sav backups, newest first, as (display_label, full_path)."""
    import time
    d = os.path.dirname(SAVE_PATH)
    out = []
    for fname in reversed(_list_backup_filenames()):
        ts = fname[len(_BACKUP_PREFIX):]
        m = _BACKUP_TS_RE.match(ts)
        if m:
            base_ts, dup_n = m.groups()
            try:
                label = time.strftime("%Y-%m-%d %H:%M:%S", time.strptime(base_ts, "%Y%m%d-%H%M%S"))
                if dup_n:
                    label += f" (#{dup_n})"
            except ValueError:
                label = ts
        else:
            label = ts
        out.append((label, os.path.join(d, fname)))
    return out


def restore_backup(backup_path):
    """Restores Loadout.sav from a backup made by backup_save(), after first
    backing up the current (about-to-be-overwritten) file the same way."""
    backup_save()
    shutil.copy2(backup_path, SAVE_PATH)


def _snapshot_loadouts(path):
    """Full structural snapshot of every loadout in `path`, as plain
    lists/strings (no gvas2 region objects, so two snapshots can be compared
    with plain ==). Same shape dump_loadout() exposes publicly, just
    including attachments too (which it intentionally leaves out) since a
    write-verification pass needs the complete picture, not just the two
    fields the UI displays."""
    d, regs, rows, L = gvas2.slots(path)

    def names(region):
        return [k["value"] for k in gvas2.row_in(rows, region)] if region else []

    return [
        {
            "operator": names(lo["op"]),
            "slots": [
                {"bundle": names(s["bundle"]), "weapon": names(s["weapon"]),
                 "attachments": names(s["attachments"])}
                for s in lo["slots"]
            ],
        }
        for lo in L
    ]


def _apply_verified(edit_fn, expect_fn):
    """Applies a save-file edit safely: backs up the live file, edits a
    throwaway COPY (never SAVE_PATH directly), re-parses that copy and
    asserts it matches exactly what the edit was supposed to produce, checks
    the live file hasn't changed on disk since this started (e.g. the game
    itself autosaving mid-edit), then atomically installs the verified copy
    over the live file and re-checks the installed result one last time.
    SAVE_PATH is only ever touched by the final atomic os.replace() -- if
    anything above fails, the real file is untouched and the original
    exception propagates (backup_save() already ran, so it's always
    recoverable even in that case).

    edit_fn(path) -- performs the actual gvas2 writes against `path`
        (a copy of the live save, never SAVE_PATH itself).
    expect_fn(before) -- takes _snapshot_loadouts(SAVE_PATH) as taken BEFORE
        any edit, returns the full snapshot the edit is supposed to produce.

    Modeled on the same round-trip-verify-before-install discipline a
    related tool's save-file worker uses (write to a copy, re-parse and
    diff against the expected result, confirm the live file didn't move
    underneath you, then swap in atomically) -- see
    dev/DECRYPTED_DATA_CAPABILITIES.md-adjacent research for where that
    pattern came from. Previously this app wrote directly and incrementally
    to the live file across multiple gvas2 calls with only a pre-edit backup
    as a safety net; a mid-edit crash could leave Loadout.sav partially
    updated (e.g. bundle changed but not weapon). This closes that gap."""
    backup_save()
    original_bytes = open(SAVE_PATH, "rb").read()
    before = _snapshot_loadouts(SAVE_PATH)
    candidate = SAVE_PATH + ".pending"
    shutil.copy2(SAVE_PATH, candidate)
    try:
        edit_fn(candidate)
        expected = expect_fn(before)
        actual = _snapshot_loadouts(candidate)
        if actual != expected:
            raise AssertionError(
                f"Candidate edit did not match the expected result -- live save left untouched.\n"
                f"expected: {expected}\nactual:   {actual}"
            )
        if open(SAVE_PATH, "rb").read() != original_bytes:
            raise AssertionError(
                "Loadout.sav changed on disk during this edit (likely the game itself saving) "
                "-- live save left untouched, retry after leaving the loadout editor."
            )
        os.replace(candidate, SAVE_PATH)
        installed = _snapshot_loadouts(SAVE_PATH)
        if installed != expected:
            raise AssertionError("Installed save differs from the verified candidate -- should be impossible.")
    finally:
        if os.path.exists(candidate):
            try:
                os.remove(candidate)
            except OSError:
                pass


def set_operator(loadout_idx, operator_name):
    def edit(path):
        gvas2.set_row_in_region(path, lambda L, i=loadout_idx: L[i]["op"], operator_name)

    def expect(before):
        expected = json.loads(json.dumps(before))  # cheap deep copy, save snapshots are plain JSON-safe types
        expected[loadout_idx]["operator"] = [operator_name]
        return expected

    _apply_verified(edit, expect)


def set_slot_weapon(loadout_idx, slot_idx, weapon_item_name, bundle_name=None, attachments=None):
    """Set a loadout slot's weapon (+ bundle, + optionally a couple of attachment rows).
    bundle_name defaults to the reverse-lookup from families.json."""
    if bundle_name is None:
        bundle_name = find_bundle_for_weapon(weapon_item_name)
        if bundle_name is None:
            raise ValueError(f"don't know the bundle for '{weapon_item_name}' -- pass bundle_name explicitly")
    if attachments is None:
        attachments = get_default_attachments_for(bundle_name)

    def edit(path):
        gvas2.set_row_in_region(path, lambda L, i=loadout_idx, s=slot_idx: L[i]["slots"][s]["bundle"], bundle_name)
        gvas2.set_row_in_region(path, lambda L, i=loadout_idx, s=slot_idx: L[i]["slots"][s]["weapon"], weapon_item_name)
        for att in attachments:
            d, regs, rows, L = gvas2.slots(path)
            att_region = L[loadout_idx]["slots"][slot_idx]["attachments"]
            ks = gvas2.row_in(rows, att_region)
            idx = attachments.index(att)
            if idx < len(ks):
                gvas2.set_rowname(path, ks[idx]["str_off"], ks[idx]["value"], att)

    def expect(before):
        expected = json.loads(json.dumps(before))
        slot = expected[loadout_idx]["slots"][slot_idx]
        slot["bundle"] = [bundle_name]
        slot["weapon"] = [weapon_item_name]
        # Mirrors edit()'s own logic exactly: only the first len(existing
        # attachment rows) entries in `attachments` actually get written
        # (set_rowname replaces an existing row, it can't add new ones), any
        # attachment beyond that count is silently skipped, same as before.
        existing_count = len(slot["attachments"])
        for i, att in enumerate(attachments):
            if i < existing_count:
                slot["attachments"][i] = att
        return expected

    _apply_verified(edit, expect)
    return True


def select_active_loadout(loadout_idx, timeout=15):
    """Calls SelectNewCurrentLoadout on the live PlayerController's loadout manager."""
    lua = f"""
local pc = UEHelpers.GetPlayerController()
local mgr
pcall(function() mgr = pc.BP_LoadoutSaveManagerComponent end)
if not mgr then for _,c in ipairs(FindAllOf('BP_LoadoutSaveManagerComponent_C') or {{}}) do mgr = c end end
if not mgr then return 'manager not found' end
local ok = pcall(function() mgr:SelectNewCurrentLoadout({loadout_idx}) end)
return 'SelectNewCurrentLoadout({loadout_idx}) ok=' .. tostring(ok)
"""
    return bc.run_lua(lua, timeout=timeout)


# --------------------------------------------------------------------------- currency / item unlocks (live GameInstance)
#
# Both confirmed live. No CheatManager function is involved -- both currency
# and item ownership are plain properties on the
# live GameInstance (class GI_BodycamSteamBackend_C) -- a direct property
# write / TSet mutation, the same low-risk category as every other live
# UObject property this app already writes (e.g. Loadout slot names,
# HMS_bBotsMethod). No UFUNCTION call, no struct marshaling, so none of the
# crash classes documented elsewhere in this file apply.
def get_currency(timeout=15):
    """Reads the live Reissad Points balance and cap straight from the
    GameInstance. Confirmed live: matches what the in-game currency display
    presumably shows (not independently screen-verified, but this is the
    same field CheatGetReissadPoint's test read from, and it's the field
    set_currency() below writes to)."""
    lua = r"""
local gi = UEHelpers.GetGameInstance()
return tostring(gi.ActualReissadPointsScore) .. '|' .. tostring(gi.MaxAllowedReissadPoints)
"""
    body = bc.run_lua(lua, timeout=timeout).strip()
    balance_s, cap_s = body.split("|", 1)
    return {"balance": int(balance_s), "cap": int(cap_s)}


def set_currency(amount, timeout=15):
    """Directly sets Reissad Points balance (and raises the cap to match if
    needed, so the new balance isn't silently clamped) via a live property
    write on the GameInstance -- confirmed live (2026-09-07): balance read
    back immediately afterward matched what was set, and stayed changed
    across repeated reads.

    This is a live override, not a real currency grant, and gets reset by
    the next thing that legitimately touches Reissad Points -- confirmed
    twice: (1) a game restart re-syncs the real balance from scratch
    (confirmed live: set to 999999, the game crashed/relaunched for an
    unrelated reason, balance was back to its real prior value afterward);
    (2) per the app's maintainer's own observation, a value set *above* the
    real cap (40000 as of this writing) reverts back down to 40000 on the
    next currency-affecting event even without a restart -- a match ending,
    a Steam Cloud sync, etc. This is expected and intended (per the
    maintainer), not a bug in this override -- treat set_currency() as a
    temporary boost that lasts until the next real currency update, not a
    permanent change. Re-run it whenever you want the boost back.

    Important asymmetry, also confirmed by the app's maintainer: an item
    actually bought through the real in-game Shop UI *while* the boosted
    balance is active DOES survive a restart -- only the currency number
    itself resets, not a purchase legitimately made with it (a real purchase
    goes through the game's own transaction flow and gets written back to
    the real backend; the balance override has nothing behind it once the
    next resync happens). For a *permanent* unlock, boost currency here and
    buy it for real in the Shop -- unlock_item()/unlock_all_items() below are
    for immediate, this-session access, not a lasting change (see their own
    docstrings).

    Unlike CheatManager:CheatGetReissadPoint(N) (confirmed NOT to work, see
    the section header above), this reaches all the way through -- there is
    no known cooldown on a raw property write, since it never calls the
    purchase/grant functions that a cooldown (if the game enforces one)
    would actually be watching."""
    amount = int(amount)
    lua = f"""
local gi = UEHelpers.GetGameInstance()
if {amount} > gi.MaxAllowedReissadPoints then gi.MaxAllowedReissadPoints = {amount} end
gi.ActualReissadPointsScore = {amount}
return tostring(gi.ActualReissadPointsScore) .. '|' .. tostring(gi.MaxAllowedReissadPoints)
"""
    body = bc.run_lua(lua, timeout=timeout).strip()
    balance_s, cap_s = body.split("|", 1)
    return {"balance": int(balance_s), "cap": int(cap_s)}


def unlock_items(item_ids, timeout=20):
    """Adds one or more item ids to GameInstance.PlayerInventoryItems (a live
    TSet<int32>) -- confirmed live 2026-09-07, both mechanically (add/remove/
    contains all work cleanly on a throwaway id) and visually in-game (a
    batch of 17 speculative ids unlocked 3 real skins -- Zbr, AirforceOne,
    Executioner -- in the Locker's Skins tab, with NO other file touched).
    Membership in this TSet alone is enough for the Locker/Shop UI to treat
    an item as owned; no PlayerSkin.sav entry is needed.

    `item_ids` that don't correspond to a real catalog item are harmless --
    confirmed live (2000 was in that same batch and produced no error, crash,
    or visible effect on its own). Live DataTable row-reading crashed the
    game when tried directly (see CAPABILITIES.md); unlock_all_items() and
    unlock_weapons_and_attachments() below sidestep that by reading the real
    id list offline instead, from the same table decrypted from the game's
    own pak files (item_catalog.json) -- this harmlessness guarantee is what
    made the old blind-range-spray approach safe before that existed, and
    is now just a safety net for the (should be zero) case of a stale id.

    Like set_currency() on the same GameInstance, this is a live-session
    override, not a permanent save: confirmed by the app's maintainer that
    unlocks made this way reset on a game restart, same as currency does.
    Re-run whichever unlock call/button you want after every restart. For a
    permanent unlock, use set_currency() to boost your balance and buy the
    item for real through the in-game Shop instead -- a real purchase sticks
    (see set_currency()'s docstring); this function does not."""
    ids = [int(i) for i in item_ids]
    if not ids:
        return
    ids_lua = "{" + ",".join(str(i) for i in ids) + "}"
    lua = f"""
local gi = UEHelpers.GetGameInstance()
local s = gi.PlayerInventoryItems
for _, id in ipairs({ids_lua}) do
    pcall(function() s:Add(id) end)
end
return 'done'
"""
    bc.run_lua(lua, timeout=timeout)


def unlock_item(item_id, timeout=15):
    """Single-id convenience wrapper around unlock_items()."""
    unlock_items([item_id], timeout=timeout)


def unlock_all_items(timeout=60):
    """Unlocks every real item in the shop catalog -- the exact id list from
    item_catalog.json (all 4 categories combined, 2131 real ids extracted
    offline from the shipped DT_NewShopItem.json), not a guessed numeric
    range. Previously sprayed every integer 1..max_id (default 3250) because
    there was no known safe way to read the real catalog's id list live
    (DataTable row-reading crashed the game -- see CAPABILITIES.md); that's
    no longer necessary since the same table is now readable offline with
    zero live-game risk (see item_catalog.json's own "_comment"). This is
    strictly better than the old range spray: real ids actually run 1-4495,
    not a clean range, so raising max_id further would still have missed
    them, and it's also a smaller batch (2131 ids vs. up to 3250) since
    nothing between real ids gets sprayed anymore. ids that don't correspond
    to anything real are inert regardless (confirmed live, see
    unlock_items()'s docstring)."""
    all_ids = sorted({i for ids in ITEM_CATEGORIES.values() for i in ids})
    unlock_items(all_ids, timeout=timeout)


def unlock_weapons_and_attachments(timeout=60):
    """"Guns and attachments only" unlock -- sprays exactly the
    item_catalog.json "DT_WeaponSkins" id list (1507 real ids), which is the
    game's own grouping (every row in DT_NewShopItem whose AssociatedItemSkinRow
    points at DT_WeaponSkins -- weapons and their attachments/magazines
    together, confirmed by inspecting real rows, e.g. "Magazine Operator
    Black Shadow" lands in this same table), not an inferred numeric cutoff.
    Replaces the old ids-1-to-999 guess: verified against the same 4
    previously-confirmed real ids (128/281 land in DT_WeaponSkins, 1006/1013
    don't, matching what live testing already established), and catches
    1,116 real weapon/attachment ids that guess entirely missed because
    they're >= 1000 (74% of the real total -- ids are interleaved across
    categories, not grouped in blocks). Same underlying mechanism otherwise
    (a plain TSet spray via unlock_items(), ids that don't correspond to
    anything real are harmless)."""
    unlock_items(ITEM_CATEGORIES.get("DT_WeaponSkins", []), timeout=timeout)
