-- Discover current catalog rows instead of maintaining a partial allow-list.
local function catalogRows()
 local lib=StaticFindObject('/Script/Engine.Default__DataTableFunctionLibrary')
 local fields={ShopRowsForItemClasses='DT_NewShopItem',BasicBundleRowsForItemClasses='DT_BasicBundles'}
 local rows={}
 for field,n in pairs(fields)do
  local d=StaticFindObject('/Game/BodycamCore/ItemsDefinition/'..n..'.'..n)
  assert(d and d:IsValid(),'Catalog not loaded: '..n)
  local names={};lib:GetDataTableRowNames(d,names);rows[field]={}
  for _,r in ipairs(names)do local ok,v=pcall(function()return r:get()end);r=ok and v or r;rows[field][#rows[field]+1]=r:ToString()end
 end
 return rows
end

local function valid(o)
 local ok,v=pcall(function()return o:IsValid()end);return ok and v==true
end
local applied={}
local function apply()
 local o=FindFirstOf('LoadoutHelperSubsystem')
 if not valid(o) then return end
 local key=o:GetFullName()
 if applied[key] then return end
 local groups=0; o.BasicBundleRowsForItemClasses:ForEach(function()groups=groups+1 end)
 if groups==0 then return end
 local total=0; local missing={}
 for field,names in pairs(catalogRows())do
  local classes={}
  for _,name in ipairs(names)do
   local tag=o:GetItemClassForRow(FName(name)).TagName:ToString()
   if tag~='None'and tag~=''then classes[#classes+1]={name=name,tag=tag} else missing[#missing+1]=name end
  end
  o[field]:ForEach(function(k,v)
   local group=k:get().TagName:ToString();local set=v:get().ItemRows
   for _,r in ipairs(classes)do
    if type(r)=='table'and r.tag and (r.tag==group or r.tag:sub(1,#group+1)==group..'.')then
     local name=FName(r.name)
     if not set:Contains(name)then set:Add(name);total=total+1 end
    end
   end
  end)
 end
 applied[key]=true
 local root=_G.__BodycamModsRoot or ''
 if root~='' and root:sub(-1)~='/' then root=root..'/' end
 local f=io.open(root..'unresolved-catalog-rows.txt','w');if f then f:write(table.concat(missing,'\n'));f:close()end
 print('[CodexTabletUnlocks] Added '..total..' catalog memberships; '..#missing..' unresolved rows listed in unresolved-catalog-rows.txt\n')
end
return {apply=apply}

