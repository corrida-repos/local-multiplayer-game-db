const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const src=fs.readFileSync(require('node:path').join(__dirname,'../website/app.js'),'utf8');
const start=src.indexOf('let pricing={}'),end=src.indexOf('function refreshPriceSection(');
assert.ok(start>0&&end>start,'price view code not found');
assert.ok(src.includes('${storeButton(g)}${priceMarkup(g)}'),'detail view must render the price block');
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const safeUrl=s=>{try{const u=new URL(s);return u.protocol==='https:'?u.href:''}catch{return ''}};
const context={URL,Date,Math,Number,esc,safeUrl,entryKey:g=>`${g.platform}:${g.id}`};vm.createContext(context);
vm.runInContext(src.slice(start,end).replace('let pricing={},pricingSources=[];','var pricing={},pricingSources=[];'),context);
const now=Date.now(),iso=ms=>new Date(now+ms).toISOString(),g={id:'1',platform:'PS5',title:'Example'};
const physical={format:'physical',delivery:'physical_copy',edition:'Standard',retailer:'Darty Portugal',seller:'Darty Portugal',item_cents:3729,shipping_cents:270,fees_cents:0,total_cents:3999,url:'https://darty.pt/products/x',checked_at:iso(-3600e3),saving:{percent:'37.8',reference_cents:5999,label:'preço regular oficial',cross_format:true}};
const digital={format:'digital',delivery:'download',edition:'Deluxe Edition',retailer:'PlayStation Store',item_cents:3999,shipping_cents:0,fees_cents:0,total_cents:3999,url:'https://store.playstation.com/pt-pt/product/X',checked_at:iso(-7200e3),condition:'Desconto PS Plus (incluído no Premium)'};
const set=offers=>vm.runInContext('pricing=__p;pricingSources=[{status:"active"},{status:"active"},{status:"candidate"}]',Object.assign(context,{__p:{'PS5:1':{offers}}}));

set([physical,digital]);
let html=context.priceMarkup(g);
assert.match(html,/mesmo total em físico e digital/);assert.match(html,/price-options tied/);
assert.match(html,/Comprar em Darty Portugal/);assert.match(html,/Comprar em PlayStation Store/);
assert.match(html,/−37,8% face ao preço regular oficial/);assert.match(html,/referência da versão digital/);
assert.match(html,/Deluxe Edition/);assert.match(html,/Desconto PS Plus/);assert.match(html,/2 lojas monitorizadas/);

set([physical,{...digital,total_cents:3499,item_cents:3499}]);
html=context.priceMarkup(g);
assert.doesNotMatch(html,/Darty/);assert.match(html,/Digital/);assert.doesNotMatch(html,/tied/);

// A promotion always shows when it ends.
set([{...digital,total_cents:999,item_cents:999,expires_at:iso(86400e3)},physical]);
html=context.priceMarkup(g);assert.match(html,/Preço válido até/);assert.match(html,new RegExp(String(new Date(now+86400e3).getUTCFullYear())));assert.match(html,/hora de Lisboa/);

// An expired promotion falls back to the next verified minimum between daily runs.
set([{...digital,total_cents:999,item_cents:999,expires_at:iso(-60e3)},physical]);
html=context.priceMarkup(g);assert.match(html,/Darty/);assert.match(html,/portes/);

// Stale observations and non-HTTPS links never show.
set([{...physical,checked_at:iso(-37*3600e3)},{...digital,url:'http://store.playstation.com/x'}]);
assert.match(context.priceMarkup(g),/Preço atual indisponível/);
set([]);assert.match(context.priceMarkup(g),/Preço atual indisponível/);
// Cards flag games whose shown best price is under the MSRP/regular price.
assert.ok(src.includes('${imageMarkup(g)}${saleBadge(g)}'),'cards must render the sale badge');
set([physical,digital]);html=context.saleBadge(g);assert.match(html,/€↓/);assert.match(html,/Abaixo do PVP: −37,8%/);
set([{...physical,saving:undefined},digital]);assert.equal(context.saleBadge(g),'');
set([physical,{...digital,total_cents:3499,item_cents:3499}]);assert.equal(context.saleBadge(g),'');
set([]);assert.equal(context.saleBadge(g),'');
console.log('price view ok');
