"""Flag pixel-art games for the site's "Permitir jogos em pixel art?" filter.

Sources, in order:
1. data/art-style-overrides.json: manual title -> true/false corrections.
2. Steam user tags (via SteamSpy) for an exact-name Steam match: "Pixel Graphics"
   among the game's top tags with a few votes.
3. Or the catalogue synopsis/co-op text mentioning pixel art or 8/16-bit graphics.
Games with no evidence are treated as not pixel art (they stay visible).
"""
import argparse,datetime as dt,json,re,sys,time,urllib.parse,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.stores import normal
from scripts.gallery import name_variants
OUT=ROOT/'data'/'art-style.json'
CACHE=ROOT/'data'/'art-style-cache.json'
OVERRIDES=ROOT/'data'/'art-style-overrides.json'
PIXEL_TAG='Pixel Graphics'
MIN_VOTES=5
TEXT=re.compile(r'\bpixel[\s-]*(?:art|graphics|style|aesthetic|visuals)\b|\bpixel(?:ated|-art)\b|\b(?:8|16)[\s-]?bit\b(?![\s-]*(?:music|sound|soundtrack|chiptune|audio))|\bpixel artists?\b',re.I)
UA={'User-Agent':'local-multiplayer-game-db art-style classifier'}

def now():return dt.datetime.now(dt.timezone.utc).isoformat()

def get_json(url,tries=3):
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=30) as r:return json.loads(r.read().decode('utf-8'))
        except Exception:
            if attempt==tries-1:raise
            time.sleep(5*(attempt+1))

def steam_match(names):
    wanted={normal(n) for n in names if normal(n)}
    for name in names[:3]:
        items=get_json('https://store.steampowered.com/api/storesearch/?cc=pt&l=english&term='+urllib.parse.quote(name)).get('items') or []
        time.sleep(1.5)
        match=next((i for i in items if i.get('type')=='app' and normal(i.get('name',''))in wanted),None)
        if match:return int(match['id']),match['name']
    return None,None

def steam_tags(app):
    tags=get_json('https://steamspy.com/api.php?request=appdetails&appid=%d'%app).get('tags') or {}
    time.sleep(1.1)
    return tags if isinstance(tags,dict) else {}

def steam_release(app):
    data=(get_json('https://store.steampowered.com/api/appdetails?cc=pt&l=english&filters=release_date&appids=%d'%app).get(str(app)) or {}).get('data') or {}
    time.sleep(1.5)
    match=re.search(r'(19|20)\d\d',(data.get('release_date') or {}).get('date') or '')
    return int(match[0]) if match else None

def pixel_from_tags(tags):
    # SteamSpy only returns a game's top ~20 tags, so being listed at all is a strong signal.
    return tags.get(PIXEL_TAG,0)>=MIN_VOTES

def pixel_from_text(game):
    return bool(TEXT.search((game.get('synopsis') or '')+' '+(game.get('coop_description') or '')))

def classify(entry,game,override):
    if override is not None:return override,'manual'
    tags=entry.get('steam_tags')
    if tags and pixel_from_tags(tags):return True,'Steam tags'
    if pixel_from_text(game):return True,'description'
    return False,'Steam tags' if tags else 'no evidence'

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--refresh',action='store_true',help='look up Steam again even for titles already checked')
    p.add_argument('--offline',action='store_true',help='only reclassify from cached Steam data and overrides')
    p.add_argument('--limit',type=int,default=0)
    p.add_argument('--releases',action='store_true',help='fetch Steam release years for matched apps (sanity check for name collisions)')
    a=p.parse_args()
    games=json.loads((ROOT/'data'/'catalog.json').read_text(encoding='utf-8'))['games']
    cache=json.loads(CACHE.read_text(encoding='utf-8')) if CACHE.exists() else {}
    overrides={normal(k):v for k,v in json.loads(OVERRIDES.read_text(encoding='utf-8')).items() if not k.startswith('_')} if OVERRIDES.exists() else {}
    by_title={}
    for g in games:by_title.setdefault(normal(g['title']),[]).append(g)
    done=0
    for key,group in by_title.items():
        entry=cache.setdefault(key,{'title':group[0]['title']})
        if a.releases and entry.get('steam_app') and 'steam_year' not in entry:
            try:entry['steam_year']=steam_release(entry['steam_app'])
            except Exception as exc:print('release',entry['title'],exc,flush=True)
            done+=1
            if done%100==0:print(done,'release years',flush=True);write(games,cache,overrides)
            continue
        if a.offline or a.releases or (entry.get('checked') and not a.refresh) or key in overrides:continue
        if a.limit and done>=a.limit:break
        try:
            app,name=steam_match(name_variants([group[0]['title']]))
            entry.update(steam_app=app,steam_name=name,steam_tags=steam_tags(app) if app else {},checked=now())
            entry.pop('error',None)
        except Exception as exc:entry['error']=str(exc)[:200]
        done+=1
        if done%50==0:
            print(done,'titles looked up',flush=True);write(games,cache,overrides)
    write(games,cache,overrides)

def write(games,cache,overrides):
    out={}
    for g in games:
        key=normal(g['title']);entry=cache.get(key,{})
        pixel,source=classify(entry,g,overrides.get(key))
        out[g['platform']+':'+g['id']]={'pixel':pixel,'source':source,**({'steam_app':entry['steam_app']} if entry.get('steam_app') else {})}
    CACHE.write_text(json.dumps(cache,ensure_ascii=False,indent=1,sort_keys=True),encoding='utf-8')
    rule='manual override, else Steam "%s" among the top tags with >= %d votes or catalogue text mentioning pixel art'%(PIXEL_TAG,MIN_VOTES)
    OUT.write_text(json.dumps({'updated':now(),'rule':rule,'games':out},ensure_ascii=False,indent=1,sort_keys=True),encoding='utf-8')

if __name__=='__main__':main()
