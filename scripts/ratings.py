"""Fetch platform-specific critic/user ratings from their public source pages."""
import argparse,datetime as dt,html,json,re,sqlite3,time,unicodedata,urllib.request,urllib.error
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
AGENT='SofaDuoCatalog/1.0 (+https://github.com/corrida-repos/local-multiplayer-game-db)'
last=0

def fetch(url):
    global last
    time.sleep(max(0,1.1-(time.monotonic()-last)));last=time.monotonic()
    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':AGENT}),timeout=25) as r:return r.read().decode()

def slug(title):
    title=title.replace('Σ',' sigma ').replace('σ',' sigma ').replace('&',' and ').replace('+',' plus ')
    title=unicodedata.normalize('NFKD',title).encode('ascii','ignore').decode().lower().replace("'",'')
    return re.sub(r'[^a-z0-9]+','-',title).strip('-')

MC_ALIASES={"Baldur's Gate III":"baldurs-gate-3",'Rayman Legends':'rayman-legends-definitive-edition','Super Mario 3D World + Bowser’s Fury':'super-mario-3d-world-plus-bowsers-fury','Overcooked! Special Edition':'overcooked-special-edition','LEGO City: Undercover':'lego-city-undercover'}
PS_CONCEPTS={'Teenage Mutant Ninja Turtles: Mutants Unleashed':'10008636','Teenage Mutant Ninja Turtles: Splintered Fate':'10011976','Overcooked! All You Can Eat!':'10000899','Teenage Mutant Ninja Turtles Arcade: Wrath of the Mutants':'10009199'}
PS_ALIASES={"Baldur's Gate III":"baldurs-gate-3",'Overcooked! All You Can Eat!':'overcooked-all-you-can-eat','Teenage Mutant Ninja Turtles: Shredder\'s Revenge':'teenage-mutant-ninja-turtles-shredders-revenge'}

def nuxt(page):
    m=re.search(r'<script[^>]*id="__NUXT_DATA__"[^>]*>(.*?)</script>',page,re.S)
    if not m:raise ValueError('Metacritic page format unavailable')
    return json.loads(m[1])

def mc_critic(page,game_slug,platform):
    a=nuxt(page)
    for obj in a:
        if not isinstance(obj,dict) or 'platforms' not in obj or 'slug' not in obj or 'criticScoreSummary' not in obj:continue
        if a[obj['slug']]!=game_slug:continue
        for index in a[obj['platforms']]:
            p=a[index]
            if a[p['name']]!=platform:continue
            summary=a[p['criticScoreSummary']];score=a[summary['score']]
            return score if isinstance(score,(int,float)) and 0<=score<=100 else None
    return None

def mc_user(page,game_slug,platform_slug):
    a=nuxt(page)
    for obj in a:
        if not isinstance(obj,dict) or not all(k in obj for k in ('max','score','reviewCount','url')):continue
        url=a[obj['url']]
        if isinstance(url,str) and url==f'/game/{game_slug}/user-reviews/?platform={platform_slug}' and a[obj['max']]==10:
            score=a[obj['score']]
            return score if isinstance(score,(int,float)) and 0<=score<=10 and isinstance(a[obj['reviewCount']],(int,float)) and a[obj['reviewCount']]>=4 else None
    return None

def psn_cache(page):
    # Product fields are split between independently rendered components.
    cache={}
    for content in re.findall(r'<script[^>]*type="application/json"[^>]*>(.*?)</script>',page,re.S):
        try:obj=json.loads(content)
        except (ValueError,TypeError):continue
        for key,value in obj.get('cache',{}).items():
            if isinstance(value,dict):cache.setdefault(key,{}).update(value)
    return cache

def psn_product(page,url=None):
    cache=psn_cache(page)
    if url:
        match=re.search(r'/product/([^/?]+)',url)
        if match:return cache.get('Product:'+match[1])
        match=re.search(r'/concept/(\d+)',url)
        if match:
            concept=cache.get('Concept:'+match[1],{})
            return cache.get((concept.get('defaultProduct') or {}).get('__ref',''))
    # Legacy callers use only a concept's actual default product.
    for concept in cache.values():
        if concept.get('__typename')=='Concept' and isinstance(concept.get('defaultProduct'),dict):
            product=cache.get(concept['defaultProduct'].get('__ref'),{})
            if 'PS5' in product.get('platforms',[]):return product
    return None

def psn_rating(page,url=None):
    product=psn_product(page,url)
    if not product or 'PS5' not in product.get('platforms',[]):return None
    rating=product.get('starRating') or {};score=rating.get('averageRating');count=rating.get('totalRatingsCount')
    if isinstance(score,(int,float)) and 0<=score<=5 and isinstance(count,(int,float)) and count>0:
        return {'score':score,'count':count,'scope':'PSN · PS4/PS5' if 'PS4' in product.get('platforms',[]) else 'PSN · PS5'}
    return None

def enrich(game,previous):
    title=game['title'];platform=game['platform'];game_slug=MC_ALIASES.get(title,slug(title));platform_slug='playstation-5' if platform=='PS5' else 'nintendo-switch'
    mc_url=f'https://www.metacritic.com/game/{game_slug}/'; result=dict(previous or {});errors=[]
    try:
        critic=mc_critic(fetch(mc_url),game_slug,'PlayStation 5' if platform=='PS5' else 'Nintendo Switch')
        result['critic']={'score':critic,'scale':100,'source':'Metacritic','url':mc_url+'critic-reviews/?platform='+platform_slug,'checked':dt.datetime.now(dt.timezone.utc).isoformat()}
    except Exception as e:errors.append('Metacritic: '+str(e)[:120])
    if platform=='Switch':
        url=mc_url+'user-reviews/?platform=nintendo-switch'
        try:
            score=mc_user(fetch(url),game_slug,'nintendo-switch')
            result['user']={'score':score,'scale':10,'source':'Metacritic','url':url,'checked':dt.datetime.now(dt.timezone.utc).isoformat()}
        except Exception as e:errors.append('Metacritic users: '+str(e)[:120])
    else:
        try:
            concept_id=PS_CONCEPTS.get(title)
            if not concept_id:
                overview=fetch('https://www.playstation.com/pt-pt/games/'+PS_ALIASES.get(title,slug(title))+'/')
                concept=re.search(r'<meta\s+name="conceptId"\s+content="(\d+)"',overview)
                if not concept:raise ValueError('No matching PSN concept found')
                concept_id=concept[1]
            url='https://store.playstation.com/pt-pt/concept/'+concept_id
            rating=psn_rating(fetch(url),url)
            if rating:result['user']={**rating,'scale':5,'source':'PSN','url':url,'checked':dt.datetime.now(dt.timezone.utc).isoformat()}
            else:raise ValueError('No PS5 default-product rating available')
        except Exception as e:errors.append('PSN: '+str(e)[:120])
    result['errors']=errors;result['attempted']=dt.datetime.now(dt.timezone.utc).isoformat()
    return result

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--limit',type=int,default=60);args=ap.parse_args()
    data=json.loads((ROOT/'data/catalog.json').read_text());path=ROOT/'data/ratings.json'
    existing=json.loads(path.read_text()) if path.exists() else {'games':{}};games=existing['games']
    queue=sorted(data['games'],key=lambda g:games.get(g['platform']+':'+g['id'],{}).get('attempted',''))
    db=sqlite3.connect(ROOT/'data/games.sqlite');db.execute('CREATE TABLE IF NOT EXISTS ratings(game_key TEXT PRIMARY KEY,payload TEXT NOT NULL)')
    for g in queue[:args.limit]:
        key=g['platform']+':'+g['id'];games[key]=enrich(g,games.get(key));db.execute('INSERT OR REPLACE INTO ratings VALUES(?,?)',(key,json.dumps(games[key],ensure_ascii=False)));db.commit()
        print(g['title'],g['platform'], 'critic',games[key].get('critic',{}).get('score'),'user',games[key].get('user',{}).get('score'),flush=True)
        path.write_text(json.dumps({'updated':dt.datetime.now(dt.timezone.utc).isoformat(),'games':games},ensure_ascii=False,indent=2)+'\n')
    db.close()
if __name__=='__main__':main()
