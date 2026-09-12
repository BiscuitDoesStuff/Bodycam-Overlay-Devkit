local UEHelpers = require('UEHelpers')

local SPEEDS = {0, 250, 500, 1000, 1600}
local GRAVITIES = {-980, -490, -196, 0, 196}
local AMMO_EFFECT_PATH = '/Game/BodycamCore/AbilitySystem/GameplayEffects/Cheats/GE_Cheat_InfiniteAmmo.GE_Cheat_InfiniteAmmo_C'
local INVINCIBLE_EFFECT_PATH = '/Game/BodycamCore/AbilitySystem/GameplayEffects/GE_Invicible.GE_Invicible_C'
local HEALTH_EFFECT_PATH = '/Game/BodycamCore/AbilitySystem/GameplayEffects/Cheats/GE_Cheat_InfiniteHealth.GE_Cheat_InfiniteHealth_C'

local function valid(o)
    if o == nil then return false end
    local ok, v = pcall(function() return o:IsValid() end)
    return ok and v == true
end

local function has(o, name)
    if not valid(o) then return false end
    local s = ''
    local ok = pcall(function() s = tostring(o[name]) end)
    return ok and s:find('^UFunction:') ~= nil
end

local function localHost()
    for _, o in ipairs(FindAllOf('PC_Bodycam_C') or {}) do
        if valid(o) and o:IsLocalController() and o:HasAuthority() and valid(o.Pawn) then return o end
    end
    return nil
end

local function worldPrefix(pc)
    return valid(pc) and pc:GetFullName():match(' (.*):PersistentLevel%.') or nil
end

local function currentObjects(className, prefix)
    local out = {}
    for _, o in ipairs(FindAllOf(className) or {}) do
        if valid(o) and o:GetFullName():find(prefix .. ':PersistentLevel.', 1, true) then out[#out + 1] = o end
    end
    return out
end

local S = _G.__ServerToolsControlState or {
    speedIndex = 1,
    gravityIndex = 1,
    infiniteAmmo = false,
    fly = false,
    speedOriginals = {},
    gravityOriginals = {},
    flyOriginals = {},
    ammoApplied = {},
    hooksInstalled = false,
}
_G.__ServerToolsControlState = S
-- defensive init for fields added after the original state table (reload-safe)
S.invincible = S.invincible or false
S.infiniteHealth = S.infiniteHealth or false
S.invincibleApplied = S.invincibleApplied or {}
S.healthApplied = S.healthApplied or {}

local function notify(text)
    local pc = localHost()
    if valid(pc) and has(pc, 'Update Warning (Client)') then
        local ok = pcall(function() pc['Update Warning (Client)'](pc, text) end)
        if ok then return end
    end
    print('[CodexAdminMenu] ' .. text .. '\n')
end

local function currentWorldSettings(pc)
    local prefix = worldPrefix(pc)
    if not prefix then return nil end
    for _, ws in ipairs(FindAllOf('WorldSettings') or {}) do
        if valid(ws) and ws:GetFullName():find(prefix .. ':PersistentLevel.', 1, true) then return ws, prefix end
    end
    return nil
end

local function applySpeedToPawn(pawn)
    if not valid(pawn) or not pawn:HasAuthority() then return end
    if pawn:GetClass():GetFName():ToString() ~= 'Bodycam_Player_C' then return end
    local movement = pawn.CharacterMovement
    if not valid(movement) then return end
    local name = pawn:GetFullName()
    if not S.speedOriginals[name] then
        S.speedOriginals[name] = {walk = movement.MaxWalkSpeed, crouch = movement.MaxWalkSpeedCrouched}
    end
    local speed = SPEEDS[S.speedIndex]
    if speed > 0 then movement.MaxWalkSpeed = speed; movement.MaxWalkSpeedCrouched = speed end
end

local function restoreSpeeds()
    for name, original in pairs(S.speedOriginals) do
        local pawn = StaticFindObject(name)
        if valid(pawn) and valid(pawn.CharacterMovement) then
            pawn.CharacterMovement.MaxWalkSpeed = original.walk
            pawn.CharacterMovement.MaxWalkSpeedCrouched = original.crouch
        end
    end
    S.speedOriginals = {}
end

local function ammoClass()
    local k = StaticFindObject(AMMO_EFFECT_PATH)
    return valid(k) and k or nil
end

local function applyAmmoToPawn(pawn)
    if not S.infiniteAmmo or not valid(pawn) or not pawn:HasAuthority() then return end
    if pawn:GetClass():GetFName():ToString() ~= 'Bodycam_Player_C' then return end
    local name = pawn:GetFullName()
    if S.ammoApplied[name] then return end
    local asc, effect = pawn.AbilitySystemComponent, ammoClass()
    if not valid(asc) or not effect then return end
    local ctx = asc:MakeEffectContext()
    asc:BP_ApplyGameplayEffectToSelf(effect, 1.0, ctx)
    S.ammoApplied[name] = true
end

local function removeAmmo()
    local effect = ammoClass()
    if effect then
        for name in pairs(S.ammoApplied) do
            local pawn = StaticFindObject(name)
            if valid(pawn) and valid(pawn.AbilitySystemComponent) then
                pawn.AbilitySystemComponent:RemoveActiveGameplayEffectBySourceEffect(effect, pawn.AbilitySystemComponent, -1)
            end
        end
    end
    S.ammoApplied = {}
end

-- Generic self-applied GameplayEffect toggles (same verified path as infinite ammo)
local function effectClass(path)
    local k = StaticFindObject(path)
    if not valid(k) then local ok, l = pcall(function() return LoadAsset(path) end); if ok then k = l end end
    return valid(k) and k or nil
end

local function applyEffect(pawn, path, appliedTbl)
    if not valid(pawn) or not pawn:HasAuthority() then return end
    if pawn:GetClass():GetFName():ToString() ~= 'Bodycam_Player_C' then return end
    local name = pawn:GetFullName()
    if appliedTbl[name] then return end
    local asc, effect = pawn.AbilitySystemComponent, effectClass(path)
    if not valid(asc) or not effect then return end
    local ctx = asc:MakeEffectContext()
    asc:BP_ApplyGameplayEffectToSelf(effect, 1.0, ctx)
    appliedTbl[name] = true
end

local function removeEffect(path, appliedTbl)
    local effect = effectClass(path)
    if effect then
        for name in pairs(appliedTbl) do
            local pawn = StaticFindObject(name)
            if valid(pawn) and valid(pawn.AbilitySystemComponent) then
                pawn.AbilitySystemComponent:RemoveActiveGameplayEffectBySourceEffect(effect, pawn.AbilitySystemComponent, -1)
            end
        end
    end
    for k in pairs(appliedTbl) do appliedTbl[k] = nil end
end

local function toggleEffect(flagField, path, appliedTbl)
    S[flagField] = not S[flagField]
    if S[flagField] then
        local pc = localHost(); local prefix = worldPrefix(pc)
        if prefix then for _, pawn in ipairs(currentObjects('Bodycam_Player_C', prefix)) do applyEffect(pawn, path, appliedTbl) end end
    else
        removeEffect(path, appliedTbl)
    end
end

local function toggleInvincible() toggleEffect('invincible', INVINCIBLE_EFFECT_PATH, S.invincibleApplied) end
local function toggleInfiniteHealth() toggleEffect('infiniteHealth', HEALTH_EFFECT_PATH, S.healthApplied) end

local function showMenu()
    local speed = SPEEDS[S.speedIndex]
    local speedText = speed == 0 and 'DEFAULT' or tostring(speed)
    notify(string.format(
        'ADMIN MENU | F6 Fly/Noclip: %s | F7 Human Speed: %s | F8 Gravity: %s | F9 Infinite Ammo: %s | F10 Reset',
        S.fly and 'ON' or 'OFF', speedText, tostring(GRAVITIES[S.gravityIndex]), S.infiniteAmmo and 'ON' or 'OFF'))
end

local function toggleFly()
    local pc = localHost(); if not valid(pc) or not valid(pc.Pawn) then notify('Fly unavailable: no authoritative host pawn'); return end
    local pawn, movement = pc.Pawn, pc.Pawn.CharacterMovement
    if not valid(movement) then notify('Fly unavailable: no movement component'); return end
    local name = pawn:GetFullName()
    if not S.fly then
        S.flyOriginals[name] = {collision = pawn:GetActorEnableCollision(), mode = movement.MovementMode, custom = movement.CustomMovementMode}
        pawn:SetActorEnableCollision(false)
        movement:SetMovementMode(5, 0)
        S.fly = true
    else
        local original = S.flyOriginals[name]
        pawn:SetActorEnableCollision(original and original.collision ~= false)
        movement:SetMovementMode(original and original.mode or 1, original and original.custom or 0)
        S.fly = false
    end
    showMenu()
end

local function cycleSpeed()
    S.speedIndex = (S.speedIndex % #SPEEDS) + 1
    if SPEEDS[S.speedIndex] == 0 then restoreSpeeds() else
        local pc = localHost(); local prefix = worldPrefix(pc)
        if prefix then for _, pawn in ipairs(currentObjects('Bodycam_Player_C', prefix)) do applySpeedToPawn(pawn) end end
    end
    showMenu()
end

local function cycleGravity()
    local pc = localHost(); local ws, prefix = currentWorldSettings(pc)
    if not valid(ws) then notify('Gravity unavailable: no authoritative world'); return end
    if not S.gravityOriginals[prefix] then S.gravityOriginals[prefix] = {gravity = ws.WorldGravityZ, wasSet = ws.bWorldGravitySet} end
    S.gravityIndex = (S.gravityIndex % #GRAVITIES) + 1
    ws.bWorldGravitySet = true
    ws.WorldGravityZ = GRAVITIES[S.gravityIndex]
    ws:OnRep_WorldGravityZ()
    showMenu()
end

local function toggleAmmo()
    S.infiniteAmmo = not S.infiniteAmmo
    if S.infiniteAmmo then
        local pc = localHost(); local prefix = worldPrefix(pc)
        if prefix then for _, pawn in ipairs(currentObjects('Bodycam_Player_C', prefix)) do applyAmmoToPawn(pawn) end end
    else removeAmmo() end
    showMenu()
end

local function resetAll()
    local pc = localHost()
    if S.fly and valid(pc) and valid(pc.Pawn) and valid(pc.Pawn.CharacterMovement) then
        local name = pc.Pawn:GetFullName(); local original = S.flyOriginals[name]
        pc.Pawn:SetActorEnableCollision(original and original.collision ~= false)
        pc.Pawn.CharacterMovement:SetMovementMode(original and original.mode or 1, original and original.custom or 0)
    end
    S.fly = false; S.flyOriginals = {}
    restoreSpeeds(); S.speedIndex = 1
    removeAmmo(); S.infiniteAmmo = false
    removeEffect(INVINCIBLE_EFFECT_PATH, S.invincibleApplied); S.invincible = false
    removeEffect(HEALTH_EFFECT_PATH, S.healthApplied); S.infiniteHealth = false
    local ws, prefix = currentWorldSettings(pc)
    local original = prefix and S.gravityOriginals[prefix] or nil
    if valid(ws) then
        ws.WorldGravityZ = original and original.gravity or -980
        ws.bWorldGravitySet = original and original.wasSet or false
        ws:OnRep_WorldGravityZ()
    end
    S.gravityOriginals = {}; S.gravityIndex = 1
    notify('ADMIN MENU | All settings restored')
end

_G.__ServerToolsControlAPI = {show = showMenu, fly = toggleFly, speed = cycleSpeed, gravity = cycleGravity, ammo = toggleAmmo, invincible = toggleInvincible, health = toggleInfiniteHealth, reset = resetAll}

local function ensureMovementHook()
if not S.hooksInstalled then
    local hookPath = '/Game/AdvancedLocomotionV4/Blueprints/CharacterLogic/ALS_Base_CharacterBP.ALS_Base_CharacterBP_C:UpdateCharacterMovement'
    if not valid(StaticFindObject(hookPath)) then return end
    RegisterHook('/Game/AdvancedLocomotionV4/Blueprints/CharacterLogic/ALS_Base_CharacterBP.ALS_Base_CharacterBP_C:UpdateCharacterMovement', function(Context)
        local pawn = Context:get(); local state = _G.__ServerToolsControlState
        if state and valid(pawn) and pawn:GetClass():GetFName():ToString() == 'Bodycam_Player_C' and pawn:HasAuthority() then
            if SPEEDS[state.speedIndex] > 0 then applySpeedToPawn(pawn) end
            if state.infiniteAmmo then applyAmmoToPawn(pawn) end
            if state.invincible then applyEffect(pawn, INVINCIBLE_EFFECT_PATH, state.invincibleApplied) end
            if state.infiniteHealth then applyEffect(pawn, HEALTH_EFFECT_PATH, state.healthApplied) end
        end
    end)
    S.hooksInstalled = true
end
end


_G.__ServerToolsControlAPI.ensureMovementHook = ensureMovementHook
return _G.__ServerToolsControlAPI
