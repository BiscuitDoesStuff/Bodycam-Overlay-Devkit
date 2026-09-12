-- Cosmetic material overrides on the local human body or first-person arms.
local M={entries={
 {'Mannequin surface','/Game/AdvancedLocomotionV4/CharacterAssets/MannequinSkeleton/Materials/M_AnimMan_Default.M_AnimMan_Default'},
 {'Gold weapon finish','/Game/BodycamWeapons/Guns/BenelliM2/Textures/MI_benellim2_Gold.MI_benellim2_Gold'},
 {'Emissive surface','/Engine/EngineMaterials/EmissiveMeshMaterial.EmissiveMeshMaterial'}
}}
local S=_G.__ModsMaterialState or {originals={}};_G.__ModsMaterialState=S
local function component(target)
 local body=_G.__ModsCharacters.component()
 local c=target=='First-person arms'and body:GetOwner().Arms or body
 assert(valid(c)and valid(c.SkeletalMesh),'Selected character component is unavailable');return c
end
function M.apply(target,index)
 local c=component(target);local entry=assert(M.entries[index]);local mat=LoadAsset(entry[2]);assert(valid(mat),'Material asset unavailable')
 local key=c:GetFullName();local mesh=c.SkeletalMesh:GetFullName();local old=S.originals[key]
 if not old or old.mesh~=mesh then old={mesh=mesh,materials={}};for i=0,c:GetNumMaterials()-1 do old.materials[i+1]=c:GetMaterial(i)end;S.originals[key]=old end
 for i=0,c:GetNumMaterials()-1 do c:SetMaterial(i,mat);assert(c:GetMaterial(i):GetFullName()==mat:GetFullName(),'Material readback failed')end
 return 'Applied '..entry[1]..' to '..target..'. Session-only cosmetic.'
end
function M.restore(target)
 local c=component(target);local key=c:GetFullName();local old=S.originals[key]
 if old and old.mesh==c.SkeletalMesh:GetFullName()then
  for _,m in ipairs(old.materials)do assert(valid(m),'Original materials expired; change character to restore mesh defaults')end
  for i,m in ipairs(old.materials)do c:SetMaterial(i-1,m)end
 else
  local i=0;c.SkeletalMesh.Materials:ForEach(function(_,r)c:SetMaterial(i,r:get().MaterialInterface);i=i+1 end)
 end
 S.originals[key]=nil;return 'Materials restored on '..target..'.'
end
M.component=component;_G.__ModsMaterials=M;return M
