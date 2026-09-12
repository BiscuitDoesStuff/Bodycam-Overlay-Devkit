local ROOT=assert(_G.__BodycamModsRoot,'__BodycamModsRoot is not set; run Reapply.ps1')
if ROOT:sub(-1)~='/' then ROOT=ROOT..'/' end
-- Already dofile'd once by reapply.lua's own load chain; re-executing it here
-- re-ran the whole controller module (idempotent, but wasteful) on every UI load.
local API=assert(_G.__ServerToolsControlAPI,'server-tools-controller.lua must load before server-tools-ui.lua')
local S=_G.__ServerToolsUI or {hooks={},attached={},clicks=0}
_G.__ServerToolsUI=S
S.pending={}
local function trace(stage)
 S.stage=stage
 local f=io.open(ROOT..'ui-open.log','a');if f then f:write(os.date(), ' ',stage,'\n');f:close()end
end
-- Hooks only enqueue work. Native menu creation/rebuild and asset loading
-- must happen after the triggering engine event has returned.
function S.defer(key,fn) S.pending[key]=fn end
function S.drain()
 local batch=S.pending;S.pending={}
 for key,fn in pairs(batch)do
  trace(key..': start')
  local ok,e=xpcall(fn,debug.traceback)
  if not ok then S.lastError=tostring(e);trace(key..': ERROR '..tostring(e))else trace(key..': done')end
 end
end
local function live(o)return valid(o)and o:GetFullName():find('/Engine/Transient.',1,true)~=nil end
local function hook(path,fn)
 if S.hooks[path]then pcall(UnregisterHook,path,S.hooks[path][1],S.hooks[path][2])end
 local ok,a,b=pcall(RegisterHook,path,fn);if ok then S.hooks[path]={a,b}end
end
local function settext(o,t)
 if valid(o)then o:SetText(FText(t))end
end
local function refresh(w)
 if _G.__ServerToolsConfig then _G.__ServerToolsConfig.refresh(w);return end
 local state=_G.__ServerToolsControlState
 local speeds={'Default','250','500','1000','1600'};local grav={'-980','-490','-196','0','196'}
 local labels={'Fly: '..(state.fly and 'ON' or 'OFF'),'Speed: '..speeds[state.speedIndex],'Ammo: '..(state.infiniteAmmo and 'ON' or 'OFF'),'Gravity: '..grav[state.gravityIndex],'Reset All'}
 for i,n in ipairs({'W_SmallButton','W_SmallButton_1','W_SmallButton_2','W_SmallButton_3','W_SmallButton_4'})do w[n]:SetButtonText(FText(labels[i]));w[n]:SetIsEnabled(true)end
 settext(w.Breadcrumbs.BreadcrumbText,'Server Tools')
 settext(w.ButtonText_2,'Movement and ammunition')
 settext(w.ButtonText_3,'World settings')
end
local function attach(w)
 if not live(w)then return end
 trace('attach: begin');S.page=w:GetFullName();S.opening=false
 _G.__ServerToolsCommandProbe={page=S.page,hits={}}
 for _,n in ipairs({'W_SettingRowEntry','W_SettingRowEntry_1','W_SettingRowEntry_2','W_SettingRowEntry_3','W_SettingRowEntry_4','W_SettingRowEntry_5','W_SettingRowEntry_6','W_SettingRowEntry_7','W_SettingRowEntry_8','W_SettingRowEntry_9','W_SystemInfoParamRowEntry','ButtonText','ButtonText_1'})do
  local ok,o=pcall(function()return w[n]end);if ok and valid(o)then o:SetVisibility(1)end
 end
 trace('attach: build/refresh');refresh(w)
 trace('attach: focus')
 if _G.__ServerToolsUX and _G.__ServerToolsUX.focus then _G.__ServerToolsUX.focus(w)end
end
local function openImpl(m)
 trace('open: options route');S.opening=true
 local o=FindFirstOf('W_MainMenuOptions_C')
 do
  m.InfoBar:BndEvt__W_InfoBar_OptionsButton_K2Node_ComponentBoundEvent_0_CommonButtonBaseClicked__DelegateSignature(m.InfoBar.OptionsButton)
  o=FindFirstOf('W_MainMenuOptions_C')
  for _,candidate in ipairs(FindAllOf('W_MainMenuOptions_C')or{})do if live(candidate)and candidate:IsActivated()then o=candidate end end
 end
 assert(live(o),'Options menu was not created')
 o.SystemInfoButton:SetVisibility(0);o.SystemInfoButton:SetIsEnabled(true)
 trace('open: system info click');o.SystemInfoButton:SimulateButtonClick()
 trace('open: locate active page')
 for _,w in ipairs(FindAllOf('W_SystemInfoSubmenu_C')or{})do if live(w)and w:IsActivated()then attach(w)end end
end
local function open(m)
 if S.openRunning then return end
 S.openRunning=true
 local ok,e=xpcall(function()openImpl(m)end,debug.traceback)
 S.openRunning=false
 if not ok then S.opening=false;error(e)end
end
local MAIN='/Game/UI/Menus/Main/W_MainMenu.W_MainMenu_C'
local GAME='/Game/UI/Game/Tablet/W_GameMenu.W_GameMenu_C'
local INFO='/Game/UI/Menus/Dev/W_SystemInfoSubmenu.W_SystemInfoSubmenu_C'
if _G.__ServerToolsConsoleHook then UnregisterHook('/Script/Engine.KismetSystemLibrary:ExecuteConsoleCommand',_G.__ServerToolsConsoleHook[1],_G.__ServerToolsConsoleHook[2])end
do
 local a,b=RegisterHook('/Script/Engine.KismetSystemLibrary:ExecuteConsoleCommand',function(_,world,command)
  local probe=_G.__ServerToolsCommandProbe;local o=world:get()
  if probe and valid(o)and o:GetFullName()==probe.page then probe.hits[#probe.hits+1]=command:get():ToString();command:set('')end
 end)
 _G.__ServerToolsConsoleHook={a,b}
end
local actions={'fly','speed','ammo','gravity','reset'}
local suffixes={'W_SmallButton_K2Node_ComponentBoundEvent_0','W_SmallButton_1_K2Node_ComponentBoundEvent_1','W_SmallButton_2_K2Node_ComponentBoundEvent_2','W_SmallButton_3_K2Node_ComponentBoundEvent_3','W_SmallButton_4_K2Node_ComponentBoundEvent_6'}
for i,suffix in ipairs(suffixes)do
 local action=actions[i]
 hook(INFO..':BndEvt__W_SystemInfoSubmenu_'..suffix..'_CommonButtonBaseClicked__DelegateSignature',function(context)
  local w=context:get();if not live(w)or w:GetFullName()~=S.page then return end
  local probe=_G.__ServerToolsCommandProbe;if not probe or probe.page~=S.page then return end
  local ok,e=pcall(function()if _G.__ServerToolsConfig then action=_G.__ServerToolsConfig.click(i)else API.ensureMovementHook();API[action]()end end);S.clicks=S.clicks+1;S.lastAction=action;S.lastError=not ok and tostring(e)or nil
  refresh(w)
 end)
end
hook(INFO..':BP_OnActivated',function(context)if S.opening then local name=context:get():GetFullName();S.defer('attach',function()local w=StaticFindObject(name);if live(w)and w:IsActivated()and S.opening then attach(w)end end)end end)
local function restorePage(w)
 if not live(w)or w:GetFullName()~=S.page then return end
 if _G.__ServerToolsUX then _G.__ServerToolsUX.hide(w)end
 local texts={'As Player ','Force On','Force Off','Full Screen','Tablet'}
 for i,n in ipairs({'W_SmallButton','W_SmallButton_1','W_SmallButton_2','W_SmallButton_3','W_SmallButton_4'})do w[n]:SetButtonText(FText(texts[i]))end
 settext(w.ButtonText,'Latest Changelist');settext(w.ButtonText_1,'Build Config');settext(w.Breadcrumbs.BreadcrumbText,'System Info');settext(w.ButtonText_2,'bc.ForceBotsMethod 0');settext(w.ButtonText_3,'bc.TabletUIMode 1')
 for _,n in ipairs({'W_SettingRowEntry','W_SettingRowEntry_1','W_SettingRowEntry_2','W_SettingRowEntry_3','W_SettingRowEntry_4','W_SettingRowEntry_5','W_SettingRowEntry_6','W_SettingRowEntry_7','W_SettingRowEntry_8','W_SettingRowEntry_9','W_SystemInfoParamRowEntry','ButtonText','ButtonText_1'})do local ok,o=pcall(function()return w[n]end);if ok and valid(o)then o:SetVisibility(4)end end
 S.page=nil;_G.__ServerToolsCommandProbe=nil
 local m=FindFirstOf('W_MainMenu_C');if live(m)then m.MainTabBar:SetSelectedName(FName('Home'))end
 local gm=FindFirstOf('W_GameMenu_C');if live(gm)then gm.MainTabBar:SetSelectedName(FName('Scoreboard'))end
end
local function queueRestore(context)
 local w=context:get();if not live(w)or w:GetFullName()~=S.page then return end
 local name=w:GetFullName();S.defer('restore',function()restorePage(StaticFindObject(name))end)
end
hook(INFO..':BP_OnDeactivated',queueRestore)
hook('/Script/VTSCommonUIExtension.VTSMenuWidget:RequestMenuClose',queueRestore)

hook(MAIN..':BndEvt__W_MainMenu_MainTabBar_K2Node_ComponentBoundEvent_0_OnSelectionChanged__DelegateSignature',function(context,_,_,name)
 if name:get():ToString()=='ServerTools'and not S.openRunning then local id=context:get():GetFullName();S.defer('open',function()local m=StaticFindObject(id);if live(m)then open(m)end end)end
end)
-- detect Mods tab click in W_GameMenu_C by hooking WidgetSwitcher:SetActiveWidgetIndex
local SWI='/Script/UMG.WidgetSwitcher:SetActiveWidgetIndex'
if S.hooks['gametab']then UnregisterHook(SWI,S.hooks['gametab'][1],S.hooks['gametab'][2])end
do
 local ga,gb=RegisterHook(SWI,function(context,idx_param)
  if S.openRunning then return end
  local gm=FindFirstOf('W_GameMenu_C');if not live(gm)then return end
  -- find what index ServerTools occupies in the DataMap
  local modsIdx=-1;local i=0
  gm.MainTabBar.DataMap:ForEach(function(k,_)if tostring(k:get())=='ServerTools'then modsIdx=i end;i=i+1 end)
  if modsIdx<0 then return end
  local idx=idx_param:get();if idx~=modsIdx then return end
  -- verify the switcher being changed belongs to this game menu
  local sw=context:get();if not valid(sw)then return end
  local ok,csname=pcall(function()return gm.ContentSwitcher:GetFullName()end)
  if ok and csname and sw:GetFullName()~=csname then return end
  local id=gm:GetFullName()
  ExecuteWithDelay(100,function()ExecuteInGameThread(function()local m=StaticFindObject(id);if live(m)then open(m)end end)end)
 end)
 S.hooks['gametab']={ga,gb}
end
local function addTab(m)
 if not live(m)or S.building then return end
 local existing=m.MainTabBar:GetDataByName(FName('ServerTools'));if valid(existing)then existing.Text=FText('Mods');for _,tab in ipairs(FindAllOf('W_MainTab_C')or{})do if valid(tab)and valid(tab.CachedData)and tab.CachedData:GetFullName()==existing:GetFullName()then tab.TabText:SetText(FText('Mods'))end end;return end
 S.building=true
 local ok,e=pcall(function()
  m.TabDefinitions:ForEach(function(_,v)v:get().bVisible_1_4375E67A4588B31E5C46DF92FFDED609=true end)
  m:PreConstruct(false)
  local data={};m.MainTabBar.DataMap:ForEach(function(k,v)data[k:get()]=v:get()end)
  local cls=StaticFindObject('/Game/UI/Components/Tabs/BP_MainTabData.BP_MainTabData_C')
  local entry=StaticFindObject('/Script/Engine.Default__GameplayStatics'):SpawnObject(cls,m)
  entry.Text=FText('Mods');entry.bShowTimer=false;data[FName('ServerTools')]=entry
  m.MainTabBar:SetBarData(data)
 end)
 S.building=false;if not ok then S.lastError=tostring(e)end
end
hook(MAIN..':PreConstruct',function(context)if S.building then return end;local id=context:get():GetFullName();S.defer('tab:'..id,function()addTab(StaticFindObject(id))end)end)
hook(GAME..':PreConstruct',function(context)if S.building then return end;local id=context:get():GetFullName();S.defer('gtab:'..id,function()addTab(StaticFindObject(id))end)end)
-- Expose show for F12
S.showForcedMenu=function()
 ExecuteInGameThread(function()
  if not valid(_G.__ForceMainMenu) then
   local pc=FindFirstOf('PlayerController');if not valid(pc)then return end
   local cls=LoadAsset('/Game/UI/Menus/Main/W_MainMenu.W_MainMenu_C');if not valid(cls)then return end
   local wbl=StaticFindObject('/Script/UMG.Default__WidgetBlueprintLibrary')
   local ok,w=pcall(function()return wbl:Create(pc,cls,pc)end);if not ok or not valid(w)then return end
   pcall(function()w:AddToViewport(10)end)
   _G.__ForceMainMenu=w
  end
  local w=_G.__ForceMainMenu;if not valid(w)then return end
  pcall(function()w:SetVisibility(0)end)
  pcall(function()w:ActivateWidget()end)
  S.defer('ftab',function()if S.addTab and valid(_G.__ForceMainMenu)then S.addTab(_G.__ForceMainMenu)end end)
 end)
end
S.open=open;S.attach=attach;S.refresh=refresh;S.addTab=addTab
local m=FindFirstOf('W_MainMenu_C');addTab(m)
local gm=FindFirstOf('W_GameMenu_C');addTab(gm)
for _,w in ipairs(FindAllOf('W_SystemInfoSubmenu_C')or{})do if live(w)and w:IsActivated()then attach(w)end end
return 'Server Tools prototype wired; native diagnostic commands suppressed only on its page'


