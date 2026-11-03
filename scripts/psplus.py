"""Verify PS5 catalogue inclusion from Portugal PlayStation Store full-game offers."""
import argparse,datetime as dt,json,re,sqlite3,time,urllib.request,urllib.parse
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
CATALOG_TYPES=('PS_PLUS_GAME_CATALOG','PS_PLUS_CLASSICS_CATALOG')

def parse_catalog(page,url,now=None):
    parsed=urllib.parse.urlparse(url)
    if parsed.scheme!='https' or parsed.hostname!='store.playstation.com' or not parsed.path.startswith('/pt-pt/'):raise ValueError('Portugal store page required')
    cache={};ctas=[]
    for text in re.findall(r'<script[^>]*type="application/json"[^>]*>(.*?)</script>',page,re.S):
        try:obj=json.loads(text)
        except ValueError:continue
        for key,value in obj.get('cache',{}).items():
            if not isinstance(value,dict):continue
            cache.setdefault(key,{}).update(value)
            if value.get('__typename')=='GameCTA':ctas.append((key,value))
    product=None
    if '/product/' in parsed.path:
        pid=parsed.path.split('/product/')[1].strip('/');product=cache.get('Product:'+pid)
    else:
        match=re.search(r'/concept/(\d+)',parsed.path)
        concept=cache.get('Concept:'+match[1],{}) if match else {}
        product=cache.get(concept.get('defaultProduct',{}).get('__ref',''))
        pid=product.get('id') if product else None
    if not product or 'PS5' not in product.get('platforms',[]):raise ValueError('PS5 product not verified')
    now=now or dt.datetime.now(dt.timezone.utc)
    for key,cta in ctas:
        if ':'+pid+'-' not in key:continue
        if not any(kind in cta.get('type','') for kind in CATALOG_TYPES):continue
        price=cta.get('price') or {}
        if price.get('membershipType')!='PS_PLUS' or not price.get('isTiedToSubscription') or price.get('discountedValue')!=0:continue
        tier=price.get('tierLabel')
        if tier not in ('TIER_20','TIER_30'):continue
        end=price.get('endTime')
        if end and float(end)/1000<=now.timestamp():continue
        return {'in_catalog':True,'tier':'Premium' if tier=='TIER_30' else 'Extra','product_id':pid}
    return {'in_catalog':False,'tier':None,'product_id':pid}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--limit',type=int,default=60);args=parser.parse_args()
    games=[g for g in json.loads((ROOT/'data/catalog.json').read_text(encoding='utf-8'))['games'] if g['platform']=='PS5'];stores=json.loads((ROOT/'data/stores.json').read_text(encoding='utf-8'))['games']
    path=ROOT/'data/psplus.json';data=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'region':'PT','games':{}};entries=data['games'];db=sqlite3.connect(ROOT/'data/games.sqlite');db.execute('CREATE TABLE IF NOT EXISTS psplus(game_key TEXT PRIMARY KEY,payload TEXT NOT NULL)')
    queue=sorted(games,key=lambda g:entries.get('PS5:'+g['id'],{}).get('attempted',''))
    for game in queue[:args.limit]:
        key='PS5:'+game['id'];entry=dict(entries.get(key,{}));url=stores.get(key,{}).get('url','')
        try:
            if not url.startswith('https://store.playstation.com/pt-pt/'):raise ValueError('Portugal store URL unavailable')
            time.sleep(1.1)
            with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'SofaDuoCatalog/1.0 (+https://github.com/corrida-repos/local-multiplayer-game-db)'}),timeout=25) as response:
                final_url=response.geturl();page=response.read().decode()
            entry={**parse_catalog(page,final_url),'source':final_url,'region':'PT','checked':dt.datetime.now(dt.timezone.utc).isoformat(),'error':None}
        except Exception as e:entry['error']=str(e)[:160]
        entry['attempted']=dt.datetime.now(dt.timezone.utc).isoformat();entries[key]=entry;db.execute('INSERT OR REPLACE INTO psplus VALUES(?,?)',(key,json.dumps(entry,ensure_ascii=False)));db.commit()
        path.write_text(json.dumps({'region':'PT','updated':entry['attempted'],'games':entries},ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(game['title'],entry.get('in_catalog'),entry.get('tier'),entry.get('error'),flush=True)
    db.close()
if __name__=='__main__':main()
