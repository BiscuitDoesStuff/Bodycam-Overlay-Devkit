local ROOT=assert(_G.__BodycamModsRoot,'__BodycamModsRoot is not set; run Reapply.ps1')
if ROOT:sub(-1)~='/' then ROOT=ROOT..'/' end
assert(LoadAsset('/Game/UI/Menus/Main/W_MainMenu.W_MainMenu_C'):IsValid(),'Main menu class unavailable')
assert(LoadAsset('/Game/UI/Menus/Dev/W_SystemInfoSubmenu.W_SystemInfoSubmenu_C'):IsValid(),'Tools page class unavailable')
dofile(ROOT..'server-tools-controller.lua')
dofile(ROOT..'CodexTabletUnlocks/Scripts/main.lua')
dofile(ROOT..'experimental-characters.lua')
dofile(ROOT..'material-variants.lua')
dofile(ROOT..'menu-equipment-unlocks.lua')
dofile(ROOT..'bdt/config-menu.lua')
dofile(ROOT..'bdt/tablet-ux.lua')
dofile(ROOT..'server-tools-ui.lua')
_G.__CodexTabletReveal()
dofile(ROOT..'native-loadout-misc.lua')
_G.__F12Handler=function()
 local function live(o)return valid(o)and o:GetFullName():find('/Engine/Transient.',1,true)~=nil end
 local gm=FindFirstOf('W_GameMenu_C')
 if live(gm)then
  -- In-match: toggle the forced lobby menu
  if valid(_G.__ForceMainMenu) then
   pcall(function()_G.__ForceMainMenu:SetVisibility(4)end)
   pcall(function()_G.__ForceMainMenu:RemoveFromParent()end)
   _G.__ForceMainMenu=nil
  else
   _G.__ServerToolsUI.showForcedMenu()
  end
  return
 end
 -- Lobby flow
 local m=FindFirstOf('W_MainMenu_C');if not valid(m)then local h=FindFirstOf('BP_LobbyGameHUD_C');if valid(h)then h:ShowCleanMainMenu();m=FindFirstOf('W_MainMenu_C')end end
 if valid(m)then _G.__ServerToolsUI.addTab(m);_G.__ServerToolsUI.open(m)end
end
if not IsKeyBindRegistered(Key.F12)then RegisterKeyBind(Key.F12,function()ExecuteInGameThread(function()if _G.__F12Handler then _G.__F12Handler()end end)end)end
_G.__InsertHandler=function()
 local function live(o)return valid(o)and o:GetFullName():find('/Engine/Transient.',1,true)~=nil end
 local ui=_G.__ServerToolsUI;if not ui then return end
 local gm=FindFirstOf('W_GameMenu_C')
 if live(gm)then ui.addTab(gm);pcall(function()ui.open(gm)end);return end
 local m=FindFirstOf('W_MainMenu_C');if valid(m)then ui.addTab(m);pcall(function()ui.open(m)end)end
end
if not IsKeyBindRegistered(Key.P)then RegisterKeyBind(Key.P,function()ExecuteInGameThread(function()if _G.__InsertHandler then _G.__InsertHandler()end end)end)end
local n=0;for _,s in ipairs(_G.__ServerToolsConfig.sections)do n=n+#s.items end
return 'Mods ready: '..n..' settings; F12 opens Mods; F11 reveals hidden menus'

