-- Local equipment UI overrides; no purchase or backend inventory requests.
local S=_G.__ModsMenuUnlocks or {hits=0};_G.__ModsMenuUnlocks=S
local base='/Game/UI/Menus/Main/Submenus/Loadout/'
local menus={'W_LoadoutSwapItemMenu','W_LoadoutCustomizeItemMenu'}
local old=base..'W_LoadoutSwapItemMenu.W_LoadoutSwapItemMenu_C:IsLocked'
if S.hook then UnregisterHook(old,S.hook[1],S.hook[2]);S.hook=nil end
S.hooks=S.hooks or {}
local function live(w)return valid(w)and w:GetFullName():find('/Engine/Transient.',1,true)end
local function hook(path,fn)
 if S.hooks[path]then UnregisterHook(path,S.hooks[path][1],S.hooks[path][2])end
 local a,b=RegisterHook(path,fn);S.hooks[path]={a,b}
end
local M={}
function M.apply()
 local count=0
 for _,name in ipairs(menus)do for _,w in ipairs(FindAllOf(name..'_C')or{})do if live(w)then
  for _,e in ipairs(w.ItemsListView:GetListItems())do local ok,d=pcall(function()return e:get()end);d=ok and d or e;if valid(d)and d.bLocked then d.bLocked=false;count=count+1 end end
  if w:IsActivated()then
   if valid(w.LockedIcon)then w.LockedIcon:SetVisibility(1)end
   if valid(w.LockedCount)then w.LockedCount:SetVisibility(1)end
   local ok,selected=pcall(function()return w.ItemsListView:GetSelectedItem()end);if not ok then selected=nil end
   if valid(selected)then if name=='W_LoadoutSwapItemMenu'then w:UpdateInfo(selected)else w:UpdateItemDisplayedInfo(selected)end end
  end
 end end end
 for _,card in ipairs(FindAllOf('W_LoadoutCard_C')or{})do if live(card)and valid(card.ItemData)then
  if card.ItemData.bLocked then card.ItemData.bLocked=false;count=count+1 end
  card:UpdateLocked()
 end end
 return count
end
for _,name in ipairs(menus)do
 local path=base..name..'.'..name..'_C';local cls=LoadAsset(path);assert(valid(cls),'Equipment class unavailable: '..name)
 hook(path..':IsLocked',function(context,item,locked)
  if not live(context:get())then return end
  locked:set(false);S.hits=S.hits+1
 end)
 local function schedule(context)
  if not live(context:get())then return end
  local ui=_G.__ServerToolsUI
  if ui and ui.defer then ui.defer('equipment-lock-refresh',function()_G.__ModsMenuUnlockAPI.apply()end)end
 end
 hook(path..':BP_OnActivated',schedule)
 if name=='W_LoadoutSwapItemMenu'then hook(path..':InitializeAllItemsForSlot',schedule)
 else hook(path..':InitializeAllAttachmentsForSlot',schedule);hook(path..':InitializeAllAttachmentSlotsForItem',schedule)end
end
_G.__ModsMenuUnlockAPI=M
M.apply();return M
