"""Exact, console-bound community profile URLs from publishers' public sitemaps."""
import datetime as dt,functools,json,urllib.parse,xml.etree.ElementTree as ET
from pathlib import Path
from scripts import stores,ratings
ROOT=Path(__file__).resolve().parents[1]
SOURCES={'Switch':('www.nintendolife.com',{'nintendo-switch','switch-eshop'}),'PS5':('www.pushsquare.com',{'ps5'})}
INTERVALS={**{host:5 for host,_ in SOURCES.values()},'purenintendo.com':10,'www.psu.com':5,'www.nintendoworldreport.com':1.1}

def valid_url(url,platform):
    parsed=urllib.parse.urlparse(url);host,folders=SOURCES[platform];parts=parsed.path.split('/')
    return parsed.scheme=='https' and parsed.hostname==host and len(parts)==4 and parts[1]=='games' and parts[2] in folders and bool(parts[3]) and not parsed.query and not parsed.fragment

def parse_sitemap(page,platform):
    result={}
    for node in ET.fromstring(page).iter():
        if node.tag.rsplit('}',1)[-1]!='loc':continue
        url=(node.text or '').strip()
        if not valid_url(url,platform):continue
        key=stores.identity(urllib.parse.unquote(url.rsplit('/',1)[-1]).replace('_',' '))
        if key:result.setdefault(key,[]).append(url)
    return result

@functools.lru_cache(maxsize=1)
def load():
    path=ROOT/'data/community-index.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'platforms':{}}

def refresh(get):
    cached=load();cutoff=(dt.datetime.now(dt.timezone.utc)-dt.timedelta(days=1)).isoformat();changed=False
    for platform,(host,_) in SOURCES.items():
        previous=cached.setdefault('platforms',{}).get(platform,{})
        if previous.get('updated','')>=cutoff:continue
        try:
            url='https://'+host+'/sitemap.games.xml';_,page=get(url);games=parse_sitemap(page,platform)
            if not games:raise ValueError('Empty console-specific sitemap; retaining previous index')
            cached['platforms'][platform]={'updated':dt.datetime.now(dt.timezone.utc).isoformat(),'source':url,'games':games};changed=True
        except Exception as exc:print('Community index',platform,str(exc)[:120],flush=True)
    if changed:
        (ROOT/'data/community-index.json').write_text(json.dumps(cached,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');load.cache_clear()

def candidates(game):
    platform=game['platform'];host,folders=SOURCES[platform];index=load().get('platforms',{}).get(platform,{}).get('games',{})
    names=list(dict.fromkeys(name for name in [ratings.MC_ALIASES.get(game['title'],game['title']),game['title']]+game.get('aliases',[]) if name))
    indexed=[url for name in names for url in index.get(stores.identity(name),[]) if valid_url(url,platform)]
    guessed=['https://'+host+'/games/'+folder+'/'+ratings.slug(name).replace('-','_') for name in names[:4] for folder in sorted(folders)]
    return list(dict.fromkeys(indexed+guessed))
