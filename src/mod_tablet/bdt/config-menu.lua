local BASE=assert(_G.__BodycamModsRoot,'__BodycamModsRoot is not set; run Reapply.ps1')
if BASE:sub(-1)~='/' then BASE=BASE..'/' end
local ROOT=BASE..'bdt/'
local C=dofile(ROOT..'catalog.lua')
local miscFamilies=0
for _,family in ipairs(C.families or {})do
 if family.category=='misc'then
  miscFamilies=miscFamilies+1
  assert(family.loose==true and #(family.variants or {})>0,'Misc family has no loose catalog rows')
 end
end
assert(miscFamilies==1,'catalog.lua must contain exactly one Misc family')
-- game_paths.lua is generated at deploy time by install_bridge.deploy_tablet_mods()
-- (it already knows the real Steam library the game is installed in -- no need to
-- re-guess a single hardcoded path from inside Lua). Missing file / nil manifest
-- both fall back to maps-dynamic.lua's own hardcoded default.
local gamePathsOk,gamePaths=pcall(dofile,ROOT..'game_paths.lua')
local mapdata=dofile(ROOT..'maps-dynamic.lua').load(gamePathsOk and gamePaths.manifest or nil)  -- installed .umap files are the source of truth
if not mapdata.entries then
 local entries={}
 for _,m in ipairs(C.maps or {})do entries[#entries+1]=m end
 mapdata={ok=false,entries=entries,resolve=function(e)return e.path end,modesFor=function()return {}end}
end
local S=_G.__BDTTabletState or {section=1,item=1,values={},status='Choose a setting, adjust it, then Apply.',autoCooldown=0}
_G.__BDTTabletState=S
local M={catalog=C,state=S,sections={}}
local function host()local p=UEHelpers.GetPlayerController();assert(valid(p)and p:HasAuthority(),'Host authority required');return p end
local function world()host();return UEHelpers.GetWorld()end
local function gs()local o=world().GameState;assert(valid(o),'Game state unavailable');return o end
local function gm()local o=world().AuthorityGameMode;assert(valid(o),'Game mode unavailable');return o end
local function cm()
 local p=host();if valid(p.CheatManager)then return p.CheatManager end
 local cls=LoadAsset('/Game/Cheat/BP_BodycamCheatManager.BP_BodycamCheatManager_C');assert(valid(cls),'Cheat manager class unavailable')
 local o=StaticFindObject('/Script/Engine.Default__GameplayStatics'):SpawnObject(cls,p);assert(valid(o),'Cheat manager creation failed');p.CheatManager=o;return o
end
local function message(t)S.status=t end
-- Multiplayer guard: Lua has no blocking confirm dialog (unlike the desktop
-- app's messagebox.askyesno-based _guard_other_players), so a genuinely
-- disruptive/world-affecting action requires two Apply presses within 3s
-- whenever someone besides the host is actually connected. Self-only cheats
-- and pure "draft" saves (cap/team/bots/private/map/mode -- no live effect
-- until Apply hosting settings/Travel) are deliberately NOT wrapped in this,
-- matching this project's own "guard disruptive host actions" convention.
local function rosterCount()
 local n=0;for _,o in ipairs(FindAllOf('PlayerState')or{})do if valid(o)and o:GetFullName():find(':PersistentLevel.',1,true)then n=n+1 end end;return n
end
S.guardArmed=S.guardArmed or {}
local function guarded(key,fn)
 return function(v,i)
  local others=math.max(rosterCount()-1,0)
  if others<=0 then return fn(v,i)end
  local now=os.time()
  if S.guardArmed[key]and now-S.guardArmed[key]<=3 then S.guardArmed[key]=nil;return fn(v,i)end
  S.guardArmed[key]=now
  message(others..' other player(s) connected. Press Apply again within 3s to confirm this affects them too.')
 end
end
local function persist()
 local f=assert(io.open(ROOT..'draft.tmp','w'));for k,v in pairs(S.values)do f:write(k,'\t',tostring(v),'\n')end;f:close();os.remove(ROOT..'draft.txt');assert(os.rename(ROOT..'draft.tmp',ROOT..'draft.txt'))
end
if not S.loadedDraft then local f=io.open(ROOT..'draft.txt','r');if f then for line in f:lines()do local k,v=line:match('^([^\t]+)\t(.*)$');if k then S.values[k]=v end end;f:close()end;S.loadedDraft=true end
local function section(name)local x={name=name,items={}};M.sections[#M.sections+1]=x;return x end
local function add(sec,key,label,values,apply,note)
 local x={key=key,label=label,choices=values,apply=apply,note=note};sec.items[#sec.items+1]=x;return x
end
local function list(x)return type(x.choices)=='function'and x.choices()or x.choices or {'Run'}end
local function chosen(x)local a=list(x);for i,v in ipairs(a)do if tostring(v)==tostring(S.values[x.key])then return v,i,a end end;return a[1],1,a end
local function get(key)for _,sec in ipairs(M.sections)do for _,x in ipairs(sec.items)do if x.key==key then local value=chosen(x);return value end end end end
local function set(key,v)S.values[key]=tostring(v)end
local function action(sec,key,label,fn,note)return add(sec,key,label,{'Run'},fn,note)end
local function ctrl(name)local api=_G.__ServerToolsControlAPI;assert(api);api.ensureMovementHook();api[name]()end
local function cycleTo(field,index,actionName)
 local s=_G.__ServerToolsControlState;for _=1,8 do if s[field]==index then return end;ctrl(actionName)end;error('Control did not reach requested value')
end
local player=section('Player')
add(player,'speed','Human run speed',{'Default','250','500','1000','1600'},function(_,i)cycleTo('speedIndex',i,'speed')end,'Bot walking speed is excluded.')
action(player,'cooldown','Clear gadget cooldown',function()local p=host();p['Server - CheatDisablePerkCooldown'](p)end,'Clear the current perk/gadget cooldown instance.')
add(player,'autoCooldown','Auto-clear interval (seconds)',{'OFF','1','2','5','10'},function(v)S.autoCooldown=tonumber(v)or 0 end,'Reapplies cooldown clearing after gadget reuse.')
action(player,'teleportAbove','Teleport above',function()cm():CheatTeleportAbove()end,'Native cheat: lifts your pawn above its current position.')
action(player,'droneMode','Toggle drone mode',function()cm():CheatDroneMode()end,'Native cheat: switch to drone control.')
action(player,'reset','Restore player and gravity controls',function()ctrl('reset');set('speed','Default');set('gravity','-980');S.autoCooldown=0;set('autoCooldown','OFF')end)
add(player,'character','Experimental character',function()local a={};for _,e in ipairs(_G.__ModsCharacters.entries)do a[#a+1]=e[1]end;return a end,function(_,i)message(_G.__ModsCharacters.apply(i))end,'Local body mesh only. Shared skeleton verified; animation, clipping and remote visibility are experimental. Saved operator stays unchanged.')
action(player,'restoreCharacter','Restore original character',function()message(_G.__ModsCharacters.restore())end,'Restores the body mesh from before your first cosmetic change on this pawn.')
local env=section('Weather / time')
add(env,'slomo','Game speed multiplier',C.slomo,guarded('slomo',function(v)local w=world();StaticFindObject('/Script/Engine.Default__GameplayStatics'):SetGlobalTimeDilation(w,tonumber(v));local actual=StaticFindObject('/Script/Engine.Default__GameplayStatics'):GetGlobalTimeDilation(w);assert(math.abs(actual-tonumber(v))<.001,'Time dilation readback failed')end),'Changes simulation speed for the match.')
add(env,'gravity','World gravity',{'-980','-490','-196','0','196'},guarded('gravity',function(_,i)cycleTo('gravityIndex',i,'gravity')end))
local function weatherNames()local a={};for _,w in ipairs(FindAllOf('UDS_Weather_Settings_C')or{})do if valid(w)then local n=w:GetFName():ToString();if not n:find('^UDS_Weather_Settings_C_')and not n:find('^Default__')then a[#a+1]=n end end end;table.sort(a);if #a==0 then a={'Unavailable on this map'}end;return a end
add(env,'transition','Weather transition (seconds)',{0,1,3,5,10},function()message('Transition duration saved for the next weather change.')end)
add(env,'weather','Weather preset',weatherNames,guarded('weather',function(v)local target;for _,o in ipairs(FindAllOf('UDS_Weather_Settings_C')or{})do if valid(o)and o:GetFName():ToString()==v then target=o end end;assert(target,'Weather preset is not loaded');local manager=gs().WeatherManagerComponent;assert(valid(manager),'Weather manager unavailable');manager:StartWeatherTransition(target,tonumber(get('transition')))end),'Uses the live weather preset objects.')
action(env,'skyLight','Toggle sky light',function()cm():CheatToggleSkyLight()end,'Native cheat: toggles the level sky light.')
action(env,'normalTime','Restore normal game speed',guarded('normalTime',function()StaticFindObject('/Script/Engine.Default__GameplayStatics'):SetGlobalTimeDilation(world(),1);set('slomo',1)end))
local hosting=section('Hosting')
add(hosting,'cap','Player cap',{1,2,4,6,7,8,10,12,16,18,20},function()message('Draft saved. Apply hosting settings to change the session.')end,'Draft only until Apply hosting settings. No automatic manual bot spawning.')
add(hosting,'team','Players per team',{1,2,3,4,5,6,7,8,9,10},function()message('Draft saved.')end)
add(hosting,'bots','Bot fill',{'OFF','ON'},function()message('Draft saved.')end)
add(hosting,'private','Private lobby',{'ON','OFF'},function()message('Draft saved.')end)
local function safePhase()local ph=gs().CurrentPhase.TagName:ToString();assert(ph:find('Lobby')or ph:find('WaitingForPlayers')or ph:find('EndMatch')or ph:find('EndRound'),'Apply hosting settings between rounds; phase is '..ph);return ph end
local function applyHost()
 local p=host();safePhase();local g=gm();local gi=UEHelpers.GetGameInstance();local cap=tonumber(get('cap'))
 local modeName=get('mode');local modeData;for _,x in ipairs(C.modes)do if x.name==modeName then modeData=x;break end end
 local team=(modeData and modeData.team_based==false) and 1 or tonumber(get('team'));assert(team<=cap,'Team size exceeds player cap')
 if valid(g.ConfigDataAsset)then
  g.ConfigDataAsset.TeamConfig.MaxPlayers=cap;g.ConfigDataAsset.TeamConfig.TeamMaxSize=team
  assert(g.ConfigDataAsset.TeamConfig.MaxPlayers==cap,'Cap readback failed')
 end
 gi['Session Max Players']=cap;gi['HMS_ExpectedPlayerCount']=cap
 local sess=(FindAllOf('GameSession')or{})[1];if valid(sess)then pcall(function()sess.MaxPlayers=cap end)end
 pcall(function()g.HMS_bBotsMethod=get('bots')=='ON' end)
 gi:UpdateLobbyAccessMethod(true)
 -- SpawnBot loop (same method the overlay uses — bypasses HMS_bBotsMethod entirely)
 _G.BOTFILL=_G.BOTFILL or {}
 _G.BOTFILL.gen=(_G.BOTFILL.gen or 0)+1
 if get('bots')=='ON' then
  local mygen=_G.BOTFILL.gen;local target=cap
  local function step()
   if _G.BOTFILL.gen~=mygen then return end
   local gm2=(FindAllOf('GameModeBase')or{})[1]
   local gs2=(FindAllOf('GameStateBase')or{})[1]
   if not valid(gm2)or not valid(gs2)then return end
   local n=0;pcall(function()n=gs2:GetNumPlayersAndBot()end)
   if n>=target then return end
   pcall(function()gm2:SpawnBot()end)
   ExecuteWithDelay(2500,function()ExecuteInGameThread(step)end)
  end
  ExecuteWithDelay(1000,function()ExecuteInGameThread(step)end)
  message('Bot fill ON – spawning to cap '..cap..', one every 2.5 s.')
 else
  message('Hosting settings applied. Bot fill stopped. Private: ON.')
 end
end
action(hosting,'applyHost','Apply hosting settings',guarded('applyHost',applyHost))
local mapNames={};for _,e in ipairs(mapdata.entries)do mapNames[#mapNames+1]=e.name end
local modeNames={};for _,x in ipairs(C.modes)do modeNames[#modeNames+1]=x.name end
local mapItem,modeItem
local function selectedMap()local _,i=chosen(mapItem);return mapdata.entries[i]end
local function selectedMode()local _,i=chosen(modeItem);return C.modes[i]end
local function modeBlockReason(mode)
 if mode.status=='working'then return nil end
 if mode.status=='no_content'then return mode.name..': BDT marks this mode as having no playable content. Choose a supported mode such as Deathmatch.'end
 return mode.name..': BDT marks this mode as '..tostring(mode.status)..'. Choose a supported mode such as Deathmatch.'
end
local function travelPopulationReason()
 return nil
end
mapItem=add(hosting,'map','Map',mapNames,function()message('Map choice saved; select Travel to load it.')end,function()local e=selectedMap();local rp=mapdata.resolve(e,selectedMode().name);return 'file: '..(rp or 'none for '..selectedMode().name)..' | modes with a file: '..table.concat(mapdata.modesFor(e),', ')end)
modeItem=add(hosting,'mode','Game mode',modeNames,function()message('Mode choice saved; select Travel to launch it.')end,function()local x=selectedMode();return (modeBlockReason(x)or 'Supported mode')..' | default cap '..x.default_cap..' | '..(x.note or x.class)end)
action(hosting,'modeDefaults','Use selected mode cap defaults',function()local x=selectedMode();set('cap',x.default_cap);set('team',x.default_team_size);message('Mode cap defaults copied to hosting draft.')end)
action(hosting,'travel','Travel to selected map / mode',guarded('travel',function()
 local w=world();assert(valid(w.NetDriver),'Create a host lobby first');safePhase();local m=selectedMap();local mode=selectedMode();assert(not modeBlockReason(mode),modeBlockReason(mode))
 local path=mapdata.resolve(m,mode.name);assert(path,'No '..mode.name..' map file for '..m.name..'. Available modes: '..table.concat(mapdata.modesFor(m),', '))
 local cap=tonumber(get('cap'));local populationReason=travelPopulationReason();assert(not populationReason,populationReason)
 local cls=LoadAsset(mode.class);assert(valid(cls),'Mode class did not load');local cfg=cls:GetCDO().ConfigDataAsset;assert(valid(cfg),'Mode has no hosting configuration')
 applyHost();cfg.TeamConfig.MaxPlayers=cap;cfg.TeamConfig.TeamMaxSize=tonumber(get('team'));assert(cfg.TeamConfig.MaxPlayers==cap,'Destination cap readback failed');StaticFindObject('/Script/Engine.Default__KismetSystemLibrary'):ExecuteConsoleCommand(w,'servertravel '..path..'?game='..mode.class,host());message('Travel requested. Wait for the map to finish loading.')
end),'Applies the chosen map and game mode to the hosted session.')
action(hosting,'startMatch','Start / restart match',guarded('startMatch',function()
 local w=world();assert(valid(w.NetDriver),'No active session – create a host lobby first.')
 local m=selectedMap();local mode=selectedMode()
 assert(not modeBlockReason(mode),modeBlockReason(mode))
 local path=mapdata.resolve(m,mode.name);assert(path,'No '..mode.name..' file for '..m.name..'. Available: '..table.concat(mapdata.modesFor(m),', '))
 local cap=tonumber(get('cap'));local team=tonumber(get('team'))
 local cls=LoadAsset(mode.class);assert(valid(cls),'Mode class unavailable')
 local cfg=cls:GetCDO().ConfigDataAsset;assert(valid(cfg),'Mode has no config')
 local ks=StaticFindObject('/Script/Engine.Default__KismetSystemLibrary')
 local function doTravel()
  applyHost();cfg.TeamConfig.MaxPlayers=cap;cfg.TeamConfig.TeamMaxSize=team
  ks:ExecuteConsoleCommand(world(),'servertravel '..path..'?game='..mode.class,host())
 end
 local ph=gs().CurrentPhase.TagName:ToString()
 local inMatch=not(ph:find('Lobby')or ph:find('WaitingForPlayers')or ph:find('EndMatch')or ph:find('EndRound'))
 if inMatch then
  message('Ending match... loading next match in 5 s')
  cm():CheatEndGameVictory()
  ExecuteWithDelay(5000,function()ExecuteInGameThread(doTravel)end)
 else
  local populationReason=travelPopulationReason();assert(not populationReason,populationReason)
  doTravel();message('Match starting. Loading...')
 end
end),'From lobby: starts immediately. In a live match: force-ends with victory, waits 5 s, then loads the next match.')
local load=section('Loadouts')
local fileCount=5;do local f=io.open(ROOT..'loadout-count.txt','r');if f then fileCount=tonumber(f:read('*a'))or 5;f:close()end end
local loadouts={};for i=1,fileCount do loadouts[#loadouts+1]=i end
add(load,'loadout','Loadout preset',loadouts,function()message('Target preset saved.')end)
add(load,'slot','Loadout slot',{1,2,3,4,5},function()message('Target slot saved.')end,'1 primary, 2 secondary, 3 melee, 4 grenade, 5 gadget. Cross-class builds remain experimental.')
local famNames={};for _,f in ipairs(C.families)do famNames[#famNames+1]=f.name end
local function family()local _,i=chosen(load.items[3]);return C.families[i],i end
add(load,'family','Weapon / gadget family',famNames,function()message('Family saved. Select a variant, then Save weapon.')end,function()local f=family();if f.loose then return f.category..' | '..#f.variants..' loose rows | preserves current bundle and attachments'end;return f.category..' | '..#f.variants..' variants | '..(f.valid and 'rows validated' or 'unresolved rows; save disabled')end)
add(load,'variant','Weapon / gadget variant',function()local f=family();return #f.variants>0 and f.variants or {'Unavailable'}end,function()message('Variant saved.')end)
add(load,'operator','Operator skin',C.operators,function()message('Operator saved. Select Save operator to write it.')end)
add(load,'reloadAfterSave','Reload saved preset after save',{'ON','OFF'},function(v)message('Auto reload after save is '..tostring(v)..'.')end,'Best-effort: reselects the saved preset after the file edit. If the game keeps stale equipment, restart the match.')
local function selectLiveLoadout(index)
 local p=host();local mgr=p.BP_LoadoutSaveManagerComponent;assert(valid(mgr),'Live loadout manager unavailable')
 mgr:SelectNewCurrentLoadout(index-1)
 local ok,actual=pcall(function()return mgr.CurrentLoadoutIndex end)
 assert(not ok or actual==nil or actual==index-1,'Loadout selection readback failed')
 return 'Selected preset '..tostring(index)..'. If equipment did not refresh, restart the match.'
end
local function queue(kind,fi,vi)
 assert(not S.pending,'A save request is already running');local f=io.open(ROOT..'heartbeat.txt','r');local t=f and tonumber(f:read('*a'));if f then f:close()end;assert(t and os.time()-t<5,'Loadout worker is offline')
 local target=tonumber(get('loadout'));local rid=tostring(os.time())..'-'..tostring(math.random(100000,999999));local q=assert(io.open(ROOT..'request.tmp','w'));q:write(rid,'\n',kind,'\n',target,'\n',get('slot'),'\n',fi,'\n',vi,'\n');q:close();assert(os.rename(ROOT..'request.tmp',ROOT..'request.txt'));S.pending=rid;S.pendingLoadout=target;message('Saving a backed-up, validated loadout...')
end
action(load,'saveWeapon','Save weapon and matching parts',function()local f,i=family();assert(f.valid,'Family contains unresolved rows');local _,vi=chosen(load.items[4]);queue('equip',i,vi)end,'Writes the selected preset/slot with its bundle defaults. Restart the match to apply.')
action(load,'saveOperator','Save operator',function()local _,i=chosen(load.items[5]);queue('operator',i,1)end,'Backs up and edits the selected loadout operator.')
action(load,'activateLoadout','Reload / select preset in game',function()message(selectLiveLoadout(tonumber(get('loadout'))))end,'Reselects the live preset. Disk-edited equipment can still require a match restart if the manager keeps stale data.')
local match=section('Match controls')
add(match,'roundSeconds','Round timer seconds',{1,10,30,60,120,300,600},guarded('roundSeconds',function(v)local o=cm();assert(has(o,'CheatSetGameTimer'),'Timer function unavailable');o:CheatSetGameTimer(tonumber(v))end),'Requires the native cheat manager on the current map.')
action(match,'endRound','End round',guarded('endRound',function()local g=gs();assert(has(g,'OverrideScoreLimit'),'Round-end function unavailable');g:OverrideScoreLimit(2)end),'Ends the current round through the verified score-limit override.')
action(match,'win','End match: victory',guarded('win',function()cm():CheatEndGameVictory()end),'BDT native command; unavailable when this map has no cheat manager.')
action(match,'lose','End match: defeat',guarded('lose',function()cm():CheatEndGameDefeat()end),'BDT native command; unavailable when this map has no cheat manager.')
action(match,'forceStart','Force start game',guarded('forceStart',function()cm():CheatForceStartGame()end),'Native cheat: forces the match to start from the lobby/warmup.')
action(match,'restartRound','Restart round',guarded('restartRound',function()cm():CheatRestartRound()end),'Native cheat: restarts the current round.')
add(match,'scoreToWin','Score to win',{1,2,3,5,10,25,50},guarded('scoreToWin',function(v)cm():CheatSetScoreToWin(tonumber(v))end),'Native cheat: sets the round/match score limit.')
action(match,'roster','Read player roster',function()local a={};for _,o in ipairs(FindAllOf('PlayerState')or{})do if valid(o)and o:GetFullName():find(':PersistentLevel.',1,true)then a[#a+1]=o:GetPlayerName():ToString()end end;message(table.concat(a,', '))end)
local troll=section('Trolling')
add(troll,'ragdoll','Ragdoll force',{'OFF','1,000','5,000','10,000','100,000','250,000'},guarded('ragdoll',function(v)
 _G.RAGDOLL_PING=_G.RAGDOLL_PING or {}
 _G.RAGDOLL_PING.gen=(_G.RAGDOLL_PING.gen or 0)+1
 local gen=_G.RAGDOLL_PING.gen
 if v=='OFF' then message('Ragdoll force OFF (gen '..gen..')');return end
 local force=tonumber((v:gsub(',','')))
 local function ping()
  if _G.RAGDOLL_PING.gen~=gen then return end
  local hit=0
  for _,pawn in ipairs(FindAllOf('Character')or{})do
   pcall(function()
    local mesh=pawn.Mesh;if not mesh then return end
    local loc=pawn:K2_GetActorLocation()
    mesh:AddRadialImpulse(loc,50.0,force,0,true)
    hit=hit+1
   end)
  end
  _G.RAGDOLL_PING.last_hit=hit
  ExecuteWithDelay(50,function()ExecuteInGameThread(ping)end)
 end
 ExecuteWithDelay(100,function()ExecuteInGameThread(ping)end)
 message('Ragdoll force ON – '..v..' impulse every 0.05 s')
end),'Pick a force level and Apply to start. Select OFF and Apply to stop cleanly. Requires two Applies within 3s when other players are connected.')
local interface=section('Menu')
action(interface,'revealMenus','Reveal hidden menu controls',function()assert(_G.__CodexTabletReveal,'Use Reapply.ps1 to load the complete Mods package');_G.__CodexTabletReveal();message('Hidden controls and available loadout categories revealed.')end,'Includes extra main-menu tabs, playlist/system controls and loadout buttons.')
action(interface,'reloadMods','Refresh Mods tab',function()local ui=_G.__ServerToolsUI;for _,m in ipairs(FindAllOf('W_MainMenu_C')or{})do if valid(m)then ui.addTab(m)end end;message('Mods tab refreshed.')end,'Full script reload: run Reapply.ps1 beside the Mods source.')
local cosmetics=section('Cosmetics')
add(cosmetics,'materialTarget','Material target',{'Body','First-person arms'},function()message('Choose a material finish, then Apply.')end,'Changes only your human character, including while piloting an RC car.')
add(cosmetics,'materialVariant','Material finish',function()local a={};for _,e in ipairs(_G.__ModsMaterials.entries)do a[#a+1]=e[1]end;return a end,function(_,i)message(_G.__ModsMaterials.apply(get('materialTarget'),i))end,'Experimental borrowed game materials. Texture layout and glow depend on the model and lighting; remote visibility is unverified.')
action(cosmetics,'restoreMaterials','Restore materials',function()message(_G.__ModsMaterials.restore(get('materialTarget')))end,'Restores materials captured before the first finish change. Changing character resets this baseline.')
if not S.initialized then for k,v in pairs({slomo=1,gravity=-980,transition=3,cap=7,team=1,private='ON',bots='OFF',reloadAfterSave='ON'})do if S.values[k]==nil then set(k,v)end end;S.initialized=true end
function M.current()local sec=M.sections[S.section]or M.sections[1];return sec.items[S.item]or sec.items[1],sec end
function M.refresh(w)
 if _G.__ServerToolsUX then _G.__ServerToolsUX.refresh(w);return end
 local x,sec=M.current();local value,index,choices=chosen(x)
 local function text(o,t)o:SetText(FText(t));o:SetVisibility(4)end
 text(w.Breadcrumbs.BreadcrumbText,'Mods / '..sec.name)
 local labels={'Section >','Setting >','< Value','Value >','Apply'}
 for i,n in ipairs({'W_SmallButton','W_SmallButton_1','W_SmallButton_2','W_SmallButton_3','W_SmallButton_4'})do w[n]:SetButtonText(FText(labels[i]));w[n]:SetIsEnabled(true)end
 text(w.ButtonText_2,string.format('%d/%d  %s: %s',S.item,#sec.items,x.label,tostring(value)))
 text(w.ButtonText_3,S.status)
 local note=type(x.note)=='function'and x.note()or x.note or 'Changes apply only when you press Apply.'
 text(w.ButtonText,'Section '..S.section..'/'..#M.sections..'  |  Choice '..index..'/'..#choices)
 text(w.ButtonText_1,note)
 pcall(function()w.ButtonText_1:SetAutoWrapText(true);w.ButtonText_3:SetAutoWrapText(true)end)
end
M.getValue=get
local drafts={materialTarget='Choose Material finish to apply to this target.',cap='Choose Apply hosting settings to use these values.',team='Choose Apply hosting settings to use these values.',bots='Choose Apply hosting settings to use these values.',private='Choose Apply hosting settings to use these values.',map='Choose Travel to selected map / mode to launch.',mode='Choose Travel to selected map / mode to launch.',loadout='Choose Save weapon, Save operator, or Reload / select preset in game.',slot='Choose Save weapon to write this slot.',family='Choose a variant, then Save weapon and matching parts.',variant='Choose Save weapon and matching parts to write this choice.',operator='Choose Save operator to write this choice.',transition='Used the next time a weather preset is applied.'}
function M.availability()
 local x=M.current();if drafts[x.key]then return false,drafts[x.key],true end
 if (x.key=='saveWeapon'or x.key=='saveOperator')and S.pending then return false,'A save is already in progress.'end
 if x.key=='saveWeapon'and not family().valid then return false,'This family has missing game rows.'end
 if x.key=='travel'then
  if not mapdata.resolve(selectedMap(),selectedMode().name)then return false,'No '..selectedMode().name..' map file for this map.'end
  local reason=modeBlockReason(selectedMode());if reason then return false,reason end
  if not valid(UEHelpers.GetWorld().NetDriver)then return false,'Create a host lobby first.'end
  local populationReason=travelPopulationReason();if populationReason then return false,populationReason end
 end
 if x.key=='hostLobby'and valid(UEHelpers.GetWorld().NetDriver)then return false,'A network session already exists.'end
 if x.key=='applyHost'or x.key=='travel'then local ok,e=pcall(safePhase);if not ok then return false,'Available between rounds, outside active combat.'end end
 return true,''
end
function M.getChoices()return chosen(M.current())end
function M.selectSection(i)assert(M.sections[i]);S.section=i;S.item=1;message('Select a setting.')end
function M.selectSetting(i)assert(M.sections[S.section].items[i]);S.item=i;message('Choose a value, then Apply.')end
function M.selectValue(i)local x=M.current();local a=list(x);assert(a[i]);set(x.key,a[i]);persist();message('Selected '..tostring(a[i])..' (not applied).')end
function M.click(i)
 local x=M.current()
 if i==1 then S.section=S.section%#M.sections+1;S.item=1;message('Choose a setting, adjust it, then Apply.')
 elseif i==2 then S.item=S.item%#M.sections[S.section].items+1;message('Choose a value, then Apply.')
 elseif i==3 or i==4 then local _,ix,a=chosen(x);local ni=((ix-1+(i==3 and -1 or 1))%#a)+1;set(x.key,a[ni]);persist();message('Selected '..tostring(a[ni])..' (not applied).')
 else local value,ix=chosen(x);message('Applied: '..x.label);local ok,e=xpcall(function()x.apply(value,ix)end,debug.traceback);S.lastApply={key=x.key,ok=ok,error=not ok and e or nil};if not ok then local f=io.open(ROOT..'apply-errors.log','a');if f then f:write(os.date(), ' ',x.key,'\n',tostring(e),'\n');f:close()end;message('Could not apply: '..tostring(e):match('^[^\n]+'):gsub('^.-:%d+: ',''))end;persist()end
 return x.key
end
function M.tick()
 local queuedUI=_G.__ServerToolsUI;if queuedUI and queuedUI.drain then queuedUI.drain()end
 if S.pending then local f=io.open(ROOT..'response.txt','r');if f then local id=f:read('*l');local status=f:read('*l');local detail=f:read('*a');f:close();if id==S.pending then local target=S.pendingLoadout;S.pending=nil;S.pendingLoadout=nil;if status=='OK'and get('reloadAfterSave')~='OFF'then local ok,e=pcall(function()return selectLiveLoadout(target)end);message(status..': '..detail..' '..(ok and e or ('Reload failed: '..tostring(e))))else message(status..': '..detail)end end end end
 if S.autoCooldown>0 and os.time()-(S.lastCooldown or 0)>=S.autoCooldown then S.lastCooldown=os.time();local ok,e=pcall(function()local p=host();p['Server - CheatDisablePerkCooldown'](p)end);if not ok then S.autoCooldown=0;message('Auto-clear stopped: '..tostring(e))end end
 local ui=_G.__ServerToolsUI;if ui and ui.page then local w=StaticFindObject(ui.page);if valid(w)and w:IsActivated()then M.refresh(w)end end
 if ui and ui.addTab then
  local function tryAdd(mn)if valid(mn)and mn:GetFullName():find('/Engine/Transient.',1,true)then local ex=mn.MainTabBar:GetDataByName(FName('ServerTools'));if not valid(ex)then pcall(ui.addTab,mn)end end end
  tryAdd(FindFirstOf('W_MainMenu_C'));tryAdd(FindFirstOf('W_GameMenu_C'))
 end
end
_G.__ServerToolsConfig=M
if not S.timerStarted then S.timerStarted=true;LoopAsync(1000,function()ExecuteInGameThread(function()local m=_G.__ServerToolsConfig;if m then local ok,e=pcall(m.tick);if not ok then m.state.status=tostring(e)end end end);return false end)end
return M

