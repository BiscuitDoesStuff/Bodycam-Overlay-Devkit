-- Dynamic map list: the installed .umap files are the source of truth.
-- Reads the game's own UFS manifest (plain text, no pak decryption) at load time,
-- so map additions/removals in a game update are reflected automatically.
--
-- The authoritative playable maps live under /Game/GM_Maps/<ModeFolder>/<Prefix>_<Base>,
-- which is exactly what the game servertravels to. We derive:
--   * the list of base map names that actually have files, and
--   * for any (base, mode) pair, the exact real file path (nil if no such file).
-- A short set of standalone utility maps (lobby/range/dev) is included only when
-- its file is present in the same manifest, so every entry is file-verified.

local M = {}

local MANIFEST = 'C:/Program Files (x86)/Steam/steamapps/common/Bodycam/Manifest_UFSFiles_Win64.txt'

-- game mode name (as used in catalog.lua C.modes) -> GM_Maps folder + file prefix
local MODE_FOLDER = {
    ['Deathmatch']       = {folder = 'DeathMatch',      prefix = 'DM'},
    ['Team Deathmatch']  = {folder = 'TeamDeathmatch',  prefix = 'TDM'},
    ['Gun Game']         = {folder = 'GunGame',         prefix = 'GG'},
    ['Hardpoint']        = {folder = 'Hardpoint',       prefix = 'HP'},
    ['Body Bomb']        = {folder = 'BodyBomb',        prefix = 'BB'},
    ['Versus']           = {folder = 'Versus',          prefix = 'VS'},
    ['Wingman']          = {folder = 'Wingman',         prefix = 'WM'},
}

-- Standalone (non-gamemode) maps worth offering; each is emitted only if present.
local STANDALONE = {
    {name = 'Lobby',               path = '/Game/Map/Lobby/Lobby'},
    {name = 'Lobby B',             path = '/Game/Map/Lobby/LobbyB'},
    {name = 'Lobby Host',          path = '/Game/Map/LobbyHost/LobbyHost'},
    {name = 'Shooting Range',      path = '/Game/Map/ShootingRange/ShootingRange'},
    {name = 'Dev Inventory (Theo)',path = '/Game/Map/Devs/Dev_Inventory_THEO_ONLY'},
    {name = 'Loadout Map',         path = '/Game/Map/Devs/LoadoutMap'},
    {name = 'Loadout Map (Empty)', path = '/Game/Map/Devs/LoadoutMapEmpty'},
    {name = 'MoonTown',            path = '/Game/MenuSystemPro/ExampleContent/Levels/MoonTown'},
    {name = 'Drone Racetrack',     path = '/Game/Doors/Lobby_Drone_Racetrack'},
    {name = 'Drone Racetrack 2',   path = '/Game/Doors/Lobby_Drone_Racetrack2'},
}

local function prettyBase(base)
    local s = base:gsub('_Level_Design$', ''):gsub('_', ' ')
    return s
end

-- Parse the manifest into a set of /Game/... package paths for every .umap.
function M.load(manifestPath)
    manifestPath = manifestPath or MANIFEST
    local present = {}          -- [/Game/.../Name] = true
    local f = io.open(manifestPath, 'r')
    if not f then
        return {ok = false, error = 'Manifest not found: ' .. manifestPath, bases = {}, standalone = {}}
    end
    for line in f:lines() do
        local rel = line:match('(Bodycam/Content/[%w_/%.%-]+%.umap)')
        if rel then
            local pkg = rel:gsub('^Bodycam/Content/', '/Game/'):gsub('%.umap$', '')
            present[pkg] = true
        end
    end
    f:close()

    -- Build the (mode,base) -> path matrix from GM_Maps and the set of base names.
    local combos = {}           -- [modeName .. '|' .. base] = path
    local baseSet = {}
    for pkg in pairs(present) do
        local folder, file = pkg:match('^/Game/GM_Maps/([^/]+)/(.+)$')
        if folder then
            for modeName, mf in pairs(MODE_FOLDER) do
                if mf.folder == folder then
                    local base = file:match('^' .. mf.prefix .. '_(.+)$')
                    if base then
                        combos[modeName .. '|' .. base] = pkg
                        baseSet[base] = true
                    end
                end
            end
        end
    end

    local bases = {}
    for base in pairs(baseSet) do bases[#bases + 1] = base end
    table.sort(bases)

    local standalone = {}
    for _, e in ipairs(STANDALONE) do
        if present[e.path] then standalone[#standalone + 1] = {name = e.name, path = e.path} end
    end

    local mapEntries = {}       -- ordered list of {name, base=..., standalone=path}
    for _, base in ipairs(bases) do
        mapEntries[#mapEntries + 1] = {name = prettyBase(base), base = base}
    end
    for _, e in ipairs(standalone) do
        mapEntries[#mapEntries + 1] = {name = e.name, standalonePath = e.path}
    end

    return {
        ok = true,
        present = present,
        combos = combos,
        bases = bases,
        entries = mapEntries,
        -- exact real file path for a (mapEntry, modeName), or nil if no file exists
        resolve = function(entry, modeName)
            if entry.standalonePath then return entry.standalonePath end
            if entry.base then return combos[modeName .. '|' .. entry.base] end
            return nil
        end,
        -- list of mode names that actually have a file for this base
        modesFor = function(entry)
            if entry.standalonePath then return {'(any, gamemode forced)'} end
            local out = {}
            for modeName in pairs(MODE_FOLDER) do
                if combos[modeName .. '|' .. entry.base] then out[#out + 1] = modeName end
            end
            table.sort(out)
            return out
        end,
    }
end

return M
