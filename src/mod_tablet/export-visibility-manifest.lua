-- Export only stable row identities. Reading DataTable row names through an
-- output array has crashed this build, so names come from the shipped catalog
-- captured for this release and the Python validator proves an exact match
-- against the live TMap before making any visibility write.
local ROOT = assert(_G.__BodycamModsRoot, '__BodycamModsRoot is not set; run Reapply.ps1')
if ROOT:sub(-1) ~= '/' then ROOT = ROOT .. '/' end

local wanted = { DT_NewShopItem = {}, DT_BasicBundles = {} }
local source = assert(io.open(ROOT .. 'complete-catalog.tsv', 'r'))
for line in source:lines() do
    local tableName, rowName = line:match('^([^\t]+)\t([^\t]+)\t')
    if wanted[tableName] and rowName ~= 'Row' then
        wanted[tableName][#wanted[tableName] + 1] = rowName
    end
end
source:close()

local outputPath = ROOT .. 'catalog-visibility-manifest.tsv'
local tempPath = outputPath .. '.tmp'
local output = assert(io.open(tempPath, 'w'))
for _, tableName in ipairs({ 'DT_NewShopItem', 'DT_BasicBundles' }) do
    local dt = StaticFindObject('/Game/BodycamCore/ItemsDefinition/' .. tableName .. '.' .. tableName)
    assert(dt and dt:IsValid(), 'Missing data table: ' .. tableName)
    local rows = wanted[tableName]
    output:write('TABLE\t', tableName, '\t', tostring(dt:GetAddress()), '\t', tostring(#rows), '\n')
    for _, rowName in ipairs(rows) do
        output:write('ROW\t', tableName, '\t', tostring(FName(rowName):GetComparisonIndex()), '\t', rowName, '\n')
    end
end
output:close()
os.remove(outputPath)
assert(os.rename(tempPath, outputPath), 'Could not publish catalog manifest')
return 'Catalog identity manifest exported safely'
