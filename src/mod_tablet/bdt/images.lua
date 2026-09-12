-- Native skin icon lookup; no external images or remote content.
local M={icons={},links={},loaded=false}
local function str(v)local ok,u=pcall(function()return v:get()end);v=ok and u or v;return type(v)=='string'and v or v:ToString()end
local function tablePath(n)return '/Game/BodycamCore/ItemsDefinition/'..n..'.'..n end
function M.load()
 if M.loaded then return end
 local l=StaticFindObject('/Script/Engine.Default__DataTableFunctionLibrary')
 for _,n in ipairs({'DT_WeaponSkins','DT_PerkSkins','DT_OperatorSkins','DT_CommonSkins'})do
  local d=StaticFindObject('/Game/BodycamCore/ItemsDefinition/Skins/'..n..'.'..n)
  if valid(d)then local rows={};l:GetDataTableRowNames(d,rows);local icons=l:GetDataTableColumnAsString(d,FName('ItemIcons'));for i,r in ipairs(rows)do local s=str(icons[i]);M.icons[n..'|'..str(r)]=s:match('"(/Game/[^\"]+)"')end end
 end
 for _,n in ipairs({'DT_NewShopItem','DT_BasicBundles'})do local d=StaticFindObject(tablePath(n));if valid(d)then local rows={};l:GetDataTableRowNames(d,rows);local refs=l:GetDataTableColumnAsString(d,FName('AssociatedItemSkinRow'));for i,r in ipairs(rows)do local s=str(refs[i]);local t=s:match('/(DT_[%w_]+)%.');local row=s:match('RowName="([^"]+)"');if t and row then M.links[str(r)]=t..'|'..row end end end end
 M.loaded=true
end
function M.path(key,value)
 if key~='family'and key~='variant'and key~='operator'then return nil end
 M.load();if key=='operator'then return M.icons['DT_OperatorSkins|'..value]end
 return M.icons[M.links[value]or'']
end
return M
