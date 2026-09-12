local lib=StaticFindObject('/Script/Engine.Default__DataTableFunctionLibrary')
for _,n in ipairs({'DT_NewShopItem','DT_BasicBundles'})do
 local dt=StaticFindObject('/Game/BodycamCore/ItemsDefinition/'..n..'.'..n);local h=lib:GetDataTableColumnAsString(dt,FName('bHiddenInGame'));local hidden=0
 for _,v in ipairs(h)do local ok,x=pcall(function()return v:get()end);v=ok and x or v;local s=type(v)=='string'and v or v:ToString();if s:lower()=='true'then hidden=hidden+1 end end
 print(n..' total='..#h..' hidden='..hidden);assert(hidden==0)
end
for _,cn in ipairs({'W_LoadoutSwapItemMenu_C','W_LoadoutCustomizeItemMenu_C'})do for _,w in ipairs(FindAllOf(cn)or{})do if valid(w)and w:GetFullName():find('/Engine/Transient.',1,true)then
 print('MENU '..w:GetFullName()..' active='..tostring(w:IsActivated()))
 if valid(w.ItemsListView)then print('list_count='..#w.ItemsListView:GetListItems())end
end end end
return 'All catalog visibility flags clear'
