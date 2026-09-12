local S=_G.__ServerToolsUXState or {pages={},buttons={},choicePage=1,lastKey=''}
_G.__ServerToolsUXState=S
local U={state=S}
local ROOT=assert(_G.__BodycamModsRoot,'__BodycamModsRoot is not set; run Reapply.ps1')
if ROOT:sub(-1)~='/' then ROOT=ROOT..'/' end
local Images=dofile(ROOT..'bdt/images.lua')
local function obj(n)local o=n and StaticFindObject(n);return valid(o)and o or nil end
local function native(class,owner,parent)
 local o=StaticConstructObject(StaticFindObject('/Script/UMG.'..class),owner.WidgetTree);assert(valid(o),'Could not create '..class);if parent then parent:AddChild(o)end;return o
end
local function pad(slot,l,t,r,b)slot:SetPadding({Left=l,Top=t,Right=r,Bottom=b})end
local function text(owner,parent,size)
 local t=native('TextBlock',owner,parent);t:SetFont(owner.ButtonText.Font);local f=t.Font;f.Size=size;t:SetFont(f);t:SetAutoWrapText(true);pad(t.Slot,0,5,0,5);return t:GetFullName()
end
local function button(owner,parent,label,fn,height)
 local b=StaticFindObject('/Script/UMG.Default__WidgetBlueprintLibrary'):Create(UEHelpers.GetWorld(),owner.W_SmallButton:GetClass(),UEHelpers.GetPlayerController())
 assert(valid(b));parent:AddChild(b);b.ButtonText:SetAutoWrapText(true);local font=b.ButtonText.Font;font.Size=16;b.ButtonText:SetFont(font);b:SetButtonText(FText(label));b:SetMinDimensions(0,height or 38);pad(b.Slot,3,3,3,3)
 S.buttons[b:GetFullName()]={page=owner:GetFullName(),fn=fn};return b:GetFullName()
end
local function setText(n,s)local t=obj(n);if t then t:SetText(FText(s))end end
local function label(n,s,selected)local b=obj(n);if b then b:SetButtonText(FText((selected and '> 'or'')..s));b:SetIsSelected(selected==true,false)end end
local function build(w)
 local key=w:GetFullName();local old=S.pages[key];if old and obj(old.root)and old.version==4 then return old end
 if old then local r=obj(old.root);if r then r:SetVisibility(1)end;for n,v in pairs(old.original)do local child=obj(n);if child then child:SetVisibility(v)end end end
 local content=w.ButtonText:GetParent();local p={version=4,original={},tabs={},rows={},values={}}
 for i=0,content:GetChildrenCount()-1 do local child=content:GetChildAt(i);p.original[child:GetFullName()]=child:GetVisibility()end
 local root=native('VerticalBox',w,content);p.root=root:GetFullName();pad(root.Slot,8,4,8,4)
 local tabs=native('HorizontalBox',w,root)
 local m=_G.__ServerToolsConfig
 for i,sec in ipairs(m.sections)do
  p.tabs[i]=button(w,tabs,({'Player','World','Hosting','Loadouts','Match','Troll','Menu','Cosmetics'})[i]or sec.name,function()m=_G.__ServerToolsConfig;m.selectSection(i);S.choicePage=1 end,42)
  obj(p.tabs[i]).Slot:SetSize({Value=1,SizeRule=1})
 end
 p.summary=text(w,root,16)
 local body=native('HorizontalBox',w,root)
 local scroll=native('ScrollBox',w,body);scroll.Slot:SetSize({Value=1,SizeRule=1});pad(scroll.Slot,0,6,16,0)
 local left=native('VerticalBox',w,scroll)
 local right=native('VerticalBox',w,body);right.Slot:SetSize({Value=1.25,SizeRule=1});pad(right.Slot,10,6,0,0)
 p.listTitle=text(w,left,20)
 for i=1,12 do p.rows[i]=button(w,left,'Setting',function()local m=_G.__ServerToolsConfig;m.selectSetting(i);S.choicePage=1 end,38)end
 p.title=text(w,right,24);p.selected=text(w,right,18)
 local frame=native('SizeBox',w,right);frame:SetHeightOverride(160);p.previewFrame=frame:GetFullName()
 local scale=native('ScaleBox',w,frame);scale:SetStretch(2)
 local img=native('Image',w,scale);p.preview=img:GetFullName();p.previewCaption=text(w,right,14)
 p.help=text(w,right,15)
 for row=1,4 do local line=native('HorizontalBox',w,right);for col=1,2 do local i=(row-1)*2+col
  p.values[i]=button(w,line,'Value',function()local m=_G.__ServerToolsConfig;local _,_,values=m.getChoices();local n=(S.choicePage-1)*8+i;if n<=#values then m.selectValue(n)end end,38)
  obj(p.values[i]).Slot:SetSize({Value=1,SizeRule=1})
 end end
 local nav=native('HorizontalBox',w,right)
 p.previous=button(w,nav,'Previous page',function()S.choicePage=math.max(1,S.choicePage-1)end,34)
 p.next=button(w,nav,'Next page',function()local _,_,a=_G.__ServerToolsConfig.getChoices();S.choicePage=math.min(math.ceil(#a/8),S.choicePage+1)end,34)
 p.pageLabel=text(w,right,14)
 p.apply=button(w,right,'Apply',function()_G.__ServerToolsConfig.click(5)end,46)
 p.status=text(w,root,16)
 S.pages[key]=p;return p
end
function U.refresh(w)
 local p=build(w);obj(p.root):SetVisibility(4)
 for n in pairs(p.original)do local o=obj(n);if o then o:SetVisibility(1)end end
 local m=_G.__ServerToolsConfig;local state=m.state;local x,sec=m.current();local value,index,choices=m.getChoices()
 if S.lastKey~=x.key then S.lastKey=x.key;S.choicePage=math.floor((index-1)/8)+1 end
 local pages=math.max(1,math.ceil(#choices/8));S.choicePage=math.max(1,math.min(pages,S.choicePage))
 w.Breadcrumbs.BreadcrumbText:SetText(FText('Mods'))
 for i,name in ipairs(p.tabs)do label(name,({'Player','World','Hosting','Loadouts','Match','Troll','Menu','Cosmetics'})[i],state.section==i)end
 if p.tabs[4]then local b=obj(p.tabs[4]);if b then b:SetVisibility(1)end end
 setText(p.summary,'Select a setting on the left. Choose a value, then Apply.');setText(p.listTitle,sec.name)
 for i,n in ipairs(p.rows)do local b=obj(n);local item=sec.items[i];if b then b:SetVisibility(item and 0 or 1);if item then label(n,item.label,state.item==i)end end end
 setText(p.title,x.label)
 local active;local controls=_G.__ServerToolsControlState
 if x.key=='fly'then active=controls.fly and 'ON'or'OFF' elseif x.key=='ammo'then active=controls.infiniteAmmo and 'ON'or'OFF' elseif x.key=='speed'then active=({'Default','250','500','1000','1600'})[controls.speedIndex] elseif x.key=='gravity'then active=({'-980','-490','-196','0','196'})[controls.gravityIndex] elseif x.key=='slomo'then active=StaticFindObject('/Script/Engine.Default__GameplayStatics'):GetGlobalTimeDilation(UEHelpers.GetWorld())end
 setText(p.selected,(#choices==1 and choices[1]=='Run')and 'Action' or 'Selected: '..tostring(value)..(active and '  |  Active: '..tostring(active)or''))
 local previewKey=x.key..'|'..tostring(value)
 if p.previewKey~=previewKey then
  p.previewKey=previewKey;local path=Images.path(x.key,tostring(value));local tex=path and LoadAsset(path)
  obj(p.previewFrame):SetVisibility(valid(tex)and 4 or 1)
  if valid(tex)then obj(p.preview):SetBrushFromTexture(tex,true);setText(p.previewCaption,'Game item preview')else setText(p.previewCaption,(x.key=='family'or x.key=='variant'or x.key=='operator')and 'No preview supplied for this item.'or'')end
 end
 local note=type(x.note)=='function'and x.note()or x.note or '';if #note>260 then note=note:sub(1,257)..'...'end;setText(p.help,note)
 local isAction=#choices==1 and choices[1]=='Run'
 for i,n in ipairs(p.values)do local k=(S.choicePage-1)*8+i;local b=obj(n);b:SetVisibility(not isAction and k<=#choices and 0 or 1);if k<=#choices then label(n,tostring(choices[k]),k==index)end end
 obj(p.previous):SetVisibility(pages>1 and 0 or 1);obj(p.next):SetVisibility(pages>1 and 0 or 1)
 obj(p.previous):SetIsEnabled(S.choicePage>1);obj(p.next):SetIsEnabled(S.choicePage<pages)
 setText(p.pageLabel,not isAction and #choices..' choices  |  Page '..S.choicePage..' / '..pages or '')
 local allowed,reason,draft=true,'',false
 if m.availability then local ok,a,r,d=pcall(m.availability);if ok then allowed,reason,draft=a,r,d else allowed=false;reason='Unavailable while the game changes state.'end end
 obj(p.apply):SetVisibility(draft and 1 or 0);obj(p.apply):SetIsEnabled(allowed)
 if reason~=''then setText(p.help,note..(#note>0 and '\n\n'or'')..reason)end
 label(p.apply,isAction and x.label or 'Apply '..tostring(value),false)
 setText(p.status,state.status)
end
function U.focus(w)local p=S.pages[w:GetFullName()];if p then local b=obj(p.rows[_G.__ServerToolsConfig.state.item]);if b then b:SetUserFocus(UEHelpers.GetPlayerController())end end end
function U.hide(w)
 local p=S.pages[w:GetFullName()];if not p then return end
 local r=obj(p.root);if r then r:SetVisibility(1)end
 for n,v in pairs(p.original)do local o=obj(n);if o then o:SetVisibility(v)end end
end
if S.hook then UnregisterHook('/Script/CommonUI.CommonButtonBase:HandleButtonClicked',S.hook[1],S.hook[2])end
local a,b=RegisterHook('/Script/CommonUI.CommonButtonBase:HandleButtonClicked',function(context)
 local button=context:get();if not valid(button)then return end;local entry=S.buttons[button:GetFullName()];if not entry then return end
 local ui=_G.__ServerToolsUI;if not ui or ui.page~=entry.page then return end
 local w=obj(entry.page);if not w or not w:IsActivated()then return end
 local id=button:GetFullName()
 ui.defer('click:'..id,function()
  local current=S.buttons[id];local page=current and obj(current.page)
  if not current or not page or _G.__ServerToolsUI.page~=current.page or not page:IsActivated()then return end
  local ok,e=pcall(current.fn);if not ok then _G.__ServerToolsConfig.state.status='Could not apply: '..tostring(e)end
  _G.__ServerToolsUX.refresh(page)
 end)
end)
S.hook={a,b};_G.__ServerToolsUX=U
-- FRAGILE, known limitation (not a general fix -- see dev/TABLET_MOD_INTEGRATION.md):
-- these two widget names are specific auto-generated instance suffixes from one
-- particular editor session (the numeric suffix UE assigns is not stable across a
-- Blueprint re-save or engine content update). They're two leftover native rows
-- inside the hijacked System Info page that shouldn't show once this mod's own
-- content replaces it, so their cached "original visibility" is force-collapsed (4)
-- here rather than left at whatever the game's real default was. If a future game
-- update changes these instance names, this silently stops matching -- the warning
-- below at least surfaces that instead of failing silent.
do
 local matched=false
 for _,p in pairs(S.pages)do for n in pairs(p.original)do if n:match('%.VerticalBox_105$')or n:match('%.Spacer_263$')then p.original[n]=4;matched=true end end end
 if not matched and _G.__ServerToolsConfig then _G.__ServerToolsConfig.state.status='tablet-ux: widget-name patch matched nothing -- UI layout may need a manual check (see tablet-ux.lua)' end
end
for name in pairs(S.buttons)do local b=obj(name);if b then b.ButtonText:SetAutoWrapText(true);local f=b.ButtonText.Font;f.Size=16;b.ButtonText:SetFont(f)end end
local ui=_G.__ServerToolsUI;if ui and ui.page then local w=obj(ui.page);if w then U.refresh(w)end end
return U


