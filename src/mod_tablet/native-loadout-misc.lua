-- Adds a native Misc category to the primary-weapon picker. The game's own
-- root-category population creates fully initialized cards; this module only
-- removes cards already represented by the four shipped category tabs.
local S = _G.__NativeLoadoutMisc or { hooks = {}, hits = 0 }
_G.__NativeLoadoutMisc = S

local MENU = '/Game/UI/Menus/Main/Submenus/Loadout/W_LoadoutSwapItemMenu.W_LoadoutSwapItemMenu_C'
local TAB_CLASS = '/Game/UI/Components/Tabs/BP_MainTabData.BP_MainTabData_C'
local PRIMARY = 'Item.PrimaryWeapon'
local NORMAL = {
    'Item.PrimaryWeapon.Assault Rifles',
    'Item.PrimaryWeapon.Machine pistol',
    'Item.PrimaryWeapon.Shotguns',
    'Item.PrimaryWeapon.Sniper Rifles',
}

local function isValid(o)
    if o == nil then return false end
    local ok, value = pcall(function() return o:IsValid() end)
    return ok and value == true
end

local function isLive(menu)
    return isValid(menu) and menu:GetFullName():find('/Engine/Transient.', 1, true) ~= nil
end

local function unwrap(v)
    local ok, value = pcall(function() return v:get() end)
    return ok and value or v
end

local function asString(v)
    v = unwrap(v)
    local ok, value = pcall(function() return v:ToString() end)
    return ok and value or tostring(v)
end

local function isChild(tag, root)
    return tag == root or tag:sub(1, #root + 1) == root .. '.'
end

local function isNormal(tag)
    for _, root in ipairs(NORMAL) do
        if isChild(tag, root) then return true end
    end
    return false
end

local function miscSelected(menu)
    if not isLive(menu) or not isValid(menu.CategoryBar) then return false end
    local entry = menu.CategoryBar:GetDataByName(FName('Misc'))
    local selected = menu.CategoryBar:GetSelectedData()
    return isValid(entry) and isValid(selected) and entry:GetAddress() == selected:GetAddress()
end

local function selectedKey(bar)
    local selected = bar:GetSelectedData()
    if not isValid(selected) then return nil end
    local key = nil
    bar.DataMap:ForEach(function(k, v)
        local value = unwrap(v)
        if isValid(value) and value:GetAddress() == selected:GetAddress() then
            key = unwrap(k):ToString()
        end
    end)
    return key
end

local function filterMisc(menu)
    if not miscSelected(menu) or not isValid(menu.ItemsListView) then return 0 end
    local keep = {}
    for _, wrapped in ipairs(menu.ItemsListView:GetListItems()) do
        local item = unwrap(wrapped)
        if isValid(item) then
            local tag = ''
            pcall(function() tag = item.ItemClass.TagName:ToString() end)
            if isChild(tag, PRIMARY) and not isNormal(tag) then
                item.bLocked = false
                keep[#keep + 1] = item
            end
        end
    end
    menu.ItemsListView:BP_SetListItems(keep)
    if #keep > 0 then
        menu.ItemsListView:BP_SetSelectedItem(keep[1])
        menu:UpdateInfo(keep[1])
    end
    menu.ItemsListView:RequestRefresh()
    S.hits = S.hits + 1
    S.lastCount = #keep
    return #keep
end

local function addTab(menu, rebuild)
    if not isLive(menu) or not isValid(menu.CategoryBar) then return false end
    local bar = menu.CategoryBar
    if not isValid(bar:GetDataByName(FName('Assault Rifles'))) then return false end
    local helper = StaticFindObject('/Script/Bodycam.Default__LoadoutHelperLibrary')
    if not isValid(helper) then return false end
    local rootTag = helper:GetGameplayTagFromString(PRIMARY)
    if rootTag.TagName:ToString() ~= PRIMARY then return false end

    local entry = bar:GetDataByName(FName('Misc'))
    local created = false
    if not isValid(entry) then
        local cls = StaticFindObject(TAB_CLASS)
        if not isValid(cls) then return false end
        entry = StaticFindObject('/Script/Engine.Default__GameplayStatics'):SpawnObject(cls, menu)
        if not isValid(entry) then return false end
        created = true
    end
    entry.Text = FText('Misc')
    entry.bShowTimer = false
    entry.TabGameplayTag = rootTag

    if created or rebuild then
        local restore = selectedKey(bar) or S.lastSelection
        local data = {}
        bar.DataMap:ForEach(function(k, v) data[unwrap(k)] = unwrap(v) end)
        data[FName('Misc')] = entry
        bar:SetBarData(data)
        if restore and isValid(bar:GetDataByName(FName(restore))) then
            bar:SetSelectedName(FName(restore))
        else
            bar:SetSelectedName(FName('Assault Rifles'))
        end
        S.rebuilds = (S.rebuilds or 0) + 1
    elseif not isValid(bar:GetSelectedData()) then
        local restore = S.lastSelection
        if not restore or not isValid(bar:GetDataByName(FName(restore))) then restore = 'Assault Rifles' end
        bar:SetSelectedName(FName(restore))
        S.reselections = (S.reselections or 0) + 1
    end

    if miscSelected(menu) then
        if menu.ItemsListView:GetNumItems() == 0 and isValid(bar:GetDataByName(FName('Assault Rifles'))) then
            bar:SetSelectedName(FName('Assault Rifles'))
            bar:SetSelectedName(FName('Misc'))
        end
        filterMisc(menu)
    end
    return true
end

local function defer(key, fn)
    local ui = _G.__ServerToolsUI
    if ui and ui.defer then ui.defer(key, fn) else fn() end
end

local function scheduleAdd(context)
    local menu = context:get()
    if not isLive(menu) then return end
    local id = menu:GetFullName()
    defer('native-misc-add:' .. id, function() addTab(StaticFindObject(id), true) end)
end

local function installHook(path, callback)
    if S.hooks[path] then
        UnregisterHook(path, S.hooks[path][1], S.hooks[path][2])
    end
    local a, b = RegisterHook(path, callback)
    S.hooks[path] = { a, b }
end

assert(isValid(LoadAsset(MENU)), 'Native loadout menu unavailable')
installHook(MENU .. ':InitializeCategories', scheduleAdd)
installHook(MENU .. ':InitializeData', scheduleAdd)
installHook(MENU .. ':BP_OnActivated', scheduleAdd)
installHook(MENU .. ':BndEvt__W_LoadoutEditMenu_CategoryBar_K2Node_ComponentBoundEvent_6_OnSelectionChanged__DelegateSignature',
    function(context, _, _, name)
        local selection = asString(name)
        if selection ~= '' and selection ~= 'None' then S.lastSelection = selection end
        if selection ~= 'Misc' then return end
        local menu = context:get()
        if not isLive(menu) then return end
        local id = menu:GetFullName()
        defer('native-misc-filter:' .. id, function() filterMisc(StaticFindObject(id)) end)
    end)

local M = { addTab = addTab, filter = filterMisc }
function M.apply()
    local added = 0
    for _, menu in ipairs(FindAllOf('W_LoadoutSwapItemMenu_C') or {}) do
        local active = false
        if isLive(menu) then pcall(function() active = menu:IsActivated() end) end
        if active and addTab(menu, true) then added = added + 1 end
    end
    return added
end

_G.__NativeLoadoutMiscAPI = M
M.apply()
return M
