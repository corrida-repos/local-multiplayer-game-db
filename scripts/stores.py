"""Find verified, platform-specific official digital store pages."""
import argparse,datetime as dt,html,json,re,sqlite3,time,unicodedata,urllib.request,urllib.parse
from pathlib import Path
from html.parser import HTMLParser
ROOT=Path(__file__).resolve().parents[1]
AGENT='SofaDuoCatalog/1.0 (+https://github.com/corrida-repos/local-multiplayer-game-db)'
EXACT={('PS5','Unrailed 2: Back on Track'):'https://store.playstation.com/pt-pt/concept/10015599',('PS5','It Takes Two'):'https://store.playstation.com/pt-pt/product/EP0006-PPSA02343_00-ITTAKESTWORETAIL'}
NINTENDO_SLUGS={'The LEGO NINJAGO Movie Video Game':'lego-ninjago-movie-video-game','Rayman Legends':'rayman-legends-definitive-edition','Super Mario 3D World + Bowser’s Fury':'super-mario-3d-world-plus-bowsers-fury'}
NINTENDO_NAMES={'The LEGO NINJAGO Movie Video Game':['LEGO NINJAGO Movie Video Game'],'Rayman Legends':['Rayman Legends Definitive Edition'],'Kirby Super Star':['Super Nintendo Entertainment System Nintendo Switch Online','Super Nintendo Entertainment System Nintendo Classics'],"Kirby's Dream Land 3":['Super Nintendo Entertainment System Nintendo Switch Online','Super Nintendo Entertainment System Nintendo Classics']}
NSO={'Kirby Super Star',"Kirby's Dream Land 3"}
last=0

def normal(value):
    value=html.unescape(value).replace('Σ',' sigma ').replace('σ',' sigma ').replace('+',' plus ').replace('™','').replace('®','').replace('©','')
    return re.sub('[^a-z0-9]','',unicodedata.normalize('NFKD',value).encode('ascii','ignore').decode().lower())

def identity(value):
    value=(value or '').replace('™','').replace('®','').replace('©','')
    value=re.sub(r'\s*[-:|–—]?\s*(?:Standard Edition|Cross[- ]Gen Bundle)\s*$','',value,flags=re.I)
    value=re.sub(r"^(?:arcade[ -]+archives(?:[ -]+2)?|console[ -]+archives|aca[ -]+neogeo|sega[ -]+ages|johnny[ -]+turbo['’]?s[ -]+arcade)[ :\-]+",'',value,flags=re.I)
    value=value.replace('&',' and ')
    value=re.sub(r'\bPlayStation[®™ ]*5\b','',value,flags=re.I)
    value=re.sub(r'\bPS4\s*(?:&|and|/|e|,)?\s*PS5\b|\bPS5\b|\bPS4\b','',value,flags=re.I)
    value=re.sub(r'\s*[-:|–—]?\s*(?:Standard Edition|Cross[- ]Gen Bundle)\s*$','',value,flags=re.I)
    value=re.sub(r'\b(iii|ii|iv)\b',lambda m:{'ii':'2','iii':'3','iv':'4'}[m[1].lower()],value,flags=re.I)
    return normal(value)
def slug(value):
    value=value.replace('&',' and ').replace('+',' plus ')
    value=unicodedata.normalize('NFKD',value).encode('ascii','ignore').decode().lower().replace("'",'')
    return re.sub('[^a-z0-9]+','-',value).strip('-')

def official_url(platform,url):
    parsed=urllib.parse.urlparse(url)
    if parsed.scheme!='https':return False
    if platform=='PS5':return parsed.hostname=='store.playstation.com' and re.match(r'^/[a-z]{2}-[a-z]{2}/(?:product|concept)/[^/]+/?$',parsed.path) is not None
    return platform=='Switch' and parsed.hostname=='www.nintendo.com' and (parsed.path.startswith('/us/store/products/') or re.match(r'^/(pt-pt/Jogos|en-gb/Games)/',parsed.path)) and '-switch-2/' not in parsed.path.lower() and 'nintendo-switch-2' not in parsed.path.lower()

class Meta(HTMLParser):
    def __init__(self):super().__init__();self.title='';self.head_title='';self.in_title=False
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='title':self.in_title=True
        if tag=='meta' and attrs.get('property')=='og:title':self.title=attrs.get('content','')

    def handle_endtag(self,tag):
        if tag=='title':self.in_title=False
    def handle_data(self,text):
        if self.in_title:self.head_title+=text

def nintendo_match(page,title,aliases=None):
    meta=Meta();meta.feed(page)
    page_names=[re.split(r' for (?:the )?Nintendo| [–-] Nintendo Official Site| \| Nintendo| [–-] Official Site',name,flags=re.I)[0] for name in [meta.title,meta.head_title] if name]
    names=[title]+NINTENDO_NAMES.get(title,[])+(aliases or [])
    canonical=lambda value:normal(re.sub(r"^(?:Arcade Archives(?: 2)?|Console Archives|ACA NEOGEO|SEGA AGES|Johnny Turbo['’]?s Arcade)[ :]+",'',value,flags=re.I))
    return any(canonical(name) in {canonical(value) for value in names} for name in page_names)

def fetch(url):
    global last
    time.sleep(max(0,1.1-(time.monotonic()-last)));last=time.monotonic()
    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':AGENT}),timeout=20) as response:return response.geturl(),response.read().decode('utf-8')

def resolve(game,ratings):
    platform,title=game['platform'],game['title'];now=dt.datetime.now(dt.timezone.utc).isoformat()
    if (platform,title) in EXACT:return {'url':EXACT[(platform,title)],'label':'Abrir na PlayStation Store','checked':now}
    if platform=='PS5':
        user=ratings.get(platform+':'+game['id'],{}).get('user',{})
        if user.get('source')=='PSN' and official_url(platform,user.get('url','')):return {'url':user['url'],'label':'Abrir na PlayStation Store','checked':user.get('checked') or now}
        return None
    candidate=game['url'] if official_url(platform,game['url']) else 'https://www.nintendo.com/us/store/products/'+NINTENDO_SLUGS.get(title,slug(title))+'-switch/'
    if title in NSO:candidate='https://www.nintendo.com/us/store/products/super-nintendo-entertainment-system-nintendo-switch-online-switch/'
    url,page=fetch(candidate)
    if not official_url(platform,url) or not nintendo_match(page,title):return None
    result={'url':url,'label':'Abrir na Nintendo eShop','checked':now}
    if title in NSO:result.update(label='Ver no Nintendo Switch Online',note='Este jogo está incluído na aplicação de Super Nintendo do Nintendo Switch Online.')
    return result

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--limit',type=int,default=60);args=parser.parse_args()
    catalog=json.loads((ROOT/'data/catalog.json').read_text());ratings=json.loads((ROOT/'data/ratings.json').read_text()).get('games',{})
    path=ROOT/'data/stores.json';previous=json.loads(path.read_text()) if path.exists() else {'games':{}};stores=previous['games']
    queue=sorted(catalog['games'],key=lambda g:stores.get(g['platform']+':'+g['id'],{}).get('attempted',''))
    db=sqlite3.connect(ROOT/'data/games.sqlite');db.execute('CREATE TABLE IF NOT EXISTS stores(game_key TEXT PRIMARY KEY,payload TEXT NOT NULL)')
    for game in queue[:args.limit]:
        key=game['platform']+':'+game['id'];entry=dict(stores.get(key,{}))
        try:
            found=resolve(game,ratings)
            if found:entry={**found,'error':None}
            else:entry['error']='No exact official store match verified'
        except Exception as e:entry['error']=str(e)[:160]
        entry['attempted']=dt.datetime.now(dt.timezone.utc).isoformat();stores[key]=entry
        db.execute('INSERT OR REPLACE INTO stores VALUES(?,?)',(key,json.dumps(entry,ensure_ascii=False)));db.commit()
        path.write_text(json.dumps({'updated':entry['attempted'],'games':stores},ensure_ascii=False,indent=2)+'\n')
        print(game['title'],game['platform'],entry.get('url') or entry.get('error'),flush=True)
    db.close()
if __name__=='__main__':main()
