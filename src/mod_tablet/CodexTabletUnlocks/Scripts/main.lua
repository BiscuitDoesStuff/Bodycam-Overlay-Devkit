local VIS_FIELD = 'bVisible_1_4375E67A4588B31E5C46DF92FFDED609'

local function valid(o)
    if o == nil then return false end
    local ok, v = pcall(function() return o:IsValid() end)
    return ok and v == true
end

local function show(w)
    if not valid(w) then return end
    w:SetVisibility(0)
    w:SetIsEnabled(true)
    w:SetRenderOpacity(1.0)
end

local function unlockButtons()
    for _, menu in ipairs(FindAllOf('W_LoadoutManagerMenu_C') or {}) do
        if valid(menu) and menu:GetFullName():find('/Engine/Transient.', 1, true) then
            show(menu.NewLoadoutButton)
            show(menu.DuplicateButton)
            show(menu.ModifyButton)
        end
    end

    for _, menu in ipairs(FindAllOf('W_MainMenuOptions_C') or {}) do
        if valid(menu) and menu:GetFullName():find('/Engine/Transient.', 1, true) then
            show(menu.SystemInfoButton)
            show(menu.PlaylistButton)
            show(menu.ForwardButton)
        end
    end
end

local function unlockTabs()
    for _, menu in ipairs(FindAllOf('W_MainMenu_C') or {}) do
        if valid(menu) and menu:GetFullName():find('/Engine/Transient.', 1, true) then
            menu.TabDefinitions:ForEach(function(_, entry)
                entry:get()[VIS_FIELD] = true
            end)

            if valid(menu.MainTabBar) then
                local count = 0
                menu.MainTabBar.DataMap:ForEach(function() count = count + 1 end)
                if count < 6 then menu:PreConstruct(false) end
            end
        end
    end
end

local ROOT=assert(_G.__BodycamModsRoot,'__BodycamModsRoot is not set; run Reapply.ps1')
if ROOT:sub(-1)~='/' then ROOT=ROOT..'/' end
local catalog = dofile(ROOT..'CodexTabletUnlocks/Scripts/catalog.lua')
local function apply()
    unlockButtons()
    unlockTabs()
    catalog.apply()
end

_G.__CodexTabletReveal = apply
if not IsKeyBindRegistered(Key.F11) then
    RegisterKeyBind(Key.F11, function()
        ExecuteInGameThread(function()
            local ok, err = pcall(_G.__CodexTabletReveal)
            if not ok then print('[CodexTabletUnlocks] ' .. tostring(err) .. '\n') end
        end)
    end)
end
print('[CodexTabletUnlocks] F11 reveals tablet controls and catalog entries after loading.\n')


