const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const src=fs.readFileSync(require('node:path').join(__dirname,'../website/app.js'),'utf8');
const context={URL,ratings:{},enrichment:{},stores:{},entryKey:g=>`${g.platform}:${g.id}`};vm.createContext(context);
vm.runInContext(src.slice(src.indexOf('function portugalStore('),src.indexOf('function storeButton(')),context);
const sw={title:'Example',id:'1',platform:'Switch'},ps={title:'Example',id:'1',platform:'PS5'};
for(const url of ['https://www.nintendo.com/us/store/products/example-switch/','https://www.nintendo.com/en-gb/Games/Example-123.html','https://www.nintendo.com/pt-pt/Jogos/Nintendo-Switch-2-games/Example.html']){
 context.enrichment['Switch:1']={store:{url}};context.stores['Switch:1']={url};assert.equal(context.officialStore(sw),null);
}
for(const url of ['https://store.playstation.com/en-us/product/EXAMPLE','https://store.playstation.com/en-gb/concept/123','https://evil.test/pt-pt/product/EXAMPLE']){
 context.ratings['PS5:1']={user:{source:'PSN',url}};context.stores['PS5:1']={url};context.enrichment['PS5:1']={store:{url}};assert.equal(context.officialStore(ps),null);
}
const pt='https://www.nintendo.com/pt-pt/Jogos/Example-123.html';context.stores['Switch:1']={url:pt,region:'PT',verified:true};
assert.equal(context.officialStore(sw).url,pt,'A foreign primary cannot hide a valid PT fallback');
context.stores['Switch:1'].verified=false;assert.equal(context.officialStore(sw),null);
const exact={...ps,title:'It Takes Two'};assert.equal(context.officialStore(exact).url,'https://store.playstation.com/pt-pt/product/EP0006-PPSA02343_00-ITTAKESTWORETAIL');
console.log('PASS: Portugal links only across enriched, legacy, offline and PSN fallbacks; exact It Takes Two preserved.');
