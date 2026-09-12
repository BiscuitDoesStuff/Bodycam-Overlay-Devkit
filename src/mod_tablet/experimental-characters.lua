local ROOT=assert(_G.__BodycamModsRoot,'__BodycamModsRoot is not set; run Reapply.ps1')
if ROOT:sub(-1)~='/' then ROOT=ROOT..'/' end
local S=_G.__ModsCharactersState or {originals={}};_G.__ModsCharactersState=S
local M={entries={
 {'AnimMan (blue mannequin)','/Game/AdvancedLocomotionV4/CharacterAssets/MannequinSkeleton/Meshes/AnimMan.AnimMan'},
 {'Skeleton zombie','/Game/ZombiesPackV4/ZombieSquelette/zombie_squelette_rigg_uv_v3.zombie_squelette_rigg_uv_v3'},
 {'Priest zombie','/Game/ZombiesPackV4/PriestZombie/PRIEST_ZOMBIE_BODYCAM_VILLAGE.PRIEST_ZOMBIE_BODYCAM_VILLAGE'},
 {'Mummy','/Game/ZombiesPackV4/Zombie_Momie/momie_final_rigg_uv_v3.momie_final_rigg_uv_v3'},
 {'Joker zombie','/Game/ZombiesPackV4/Zombie_Jocker/ZombieJocker.ZombieJocker'},
 {'Modular soldier E','/Game/AAAModularSoldierPackVol3/Modules/ModularSoldierVol_3/Meshes/SK_Vol3_E.SK_Vol3_E'}
}}
local function path(o)return valid(o)and o:GetFullName():match('^%S+ (.*)')or nil end
local function human(p)
 if not valid(p)then return false end
 local c=p:GetClass();for _=1,12 do if not valid(c)then break end;if c:GetFName():ToString()=='Bodycam_Player_C'then return true end;c=c:GetSuperStruct()end
 return false
end
local function component()
 local pc=UEHelpers.GetPlayerController();assert(valid(pc)and pc:IsLocalController(),'Local player required')
 local p=pc.Pawn;assert(valid(p),'Local pawn unavailable')
 if not human(p)then
  local body
  -- Follow explicit links on the possessed gadget; never pick an arbitrary player.
  for _,field in ipairs({'CharacterOwner','Instigator'})do
   local ok,candidate=pcall(function()return p[field]end)
   if ok and human(candidate)then body=candidate;break end
  end
  assert(body,'Return to your operator before changing character: this gadget has no human-body reference')
  p=body
 end
 assert(valid(p.Mesh),'Player body unavailable');return p.Mesh
end
M.component=component
local function remember(c)
 local key=c:GetFullName();if S.originals[key]then return end
 local x={mesh=path(c.SkeletalMesh),materials={}};for i=0,c:GetNumMaterials()-1 do x.materials[#x.materials+1]=path(c:GetMaterial(i))or false end
 S.originals[key]=x
end
local function swap(c,mesh)
 assert(valid(mesh)and valid(mesh.Skeleton),'Mesh unavailable')
 assert(valid(c.SkeletalMesh)and c.SkeletalMesh.Skeleton:GetFullName()==mesh.Skeleton:GetFullName(),'Character skeleton mismatch')
 c:SetSkeletalMeshAsset(mesh)
 local slot=0;mesh.Materials:ForEach(function(_,r)local material=r:get().MaterialInterface;c:SetMaterial(slot,material);slot=slot+1 end)
 assert(c.SkeletalMesh:GetFullName()==mesh:GetFullName(),'Mesh readback failed')
end
function M.apply(index)
 local entry=assert(M.entries[index]);local mesh=LoadAsset(entry[2]);local c=component();assert(valid(mesh)and valid(mesh.Skeleton)and valid(c.SkeletalMesh)and c.SkeletalMesh.Skeleton:GetFullName()==mesh.Skeleton:GetFullName(),'Selected character is incompatible with your human body skeleton');remember(c);swap(c,mesh);S.selected=entry[1]
 return 'Applied '..entry[1]..' to your body. Reapply after respawn; other clients are unverified.'
end
function M.restore()
 local c=component();local key=c:GetFullName();local x=assert(S.originals[key],'No cosmetic change to restore on this pawn')
 local mesh=LoadAsset(x.mesh);c:SetSkeletalMeshAsset(mesh);for i,p in ipairs(x.materials)do c:SetMaterial(i-1,p and LoadAsset(p)or nil)end
 S.originals[key]=nil;S.selected=nil;return 'Original player body restored.'
end
_G.__ModsCharacters=M;return M

