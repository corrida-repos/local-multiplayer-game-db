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
    # NFKC first so single-character numerals (Ⅱ, Ⅲ) and full-width text reach the Roman-numeral rule.
    value=unicodedata.normalize('NFKC',value or '').replace('™','').replace('®','').replace('©','')
    value=re.sub(r'\s*[-:|–—]?\s*(?:Standard Edition|Cross[- ]Gen Bundle)\s*$','',value,flags=re.I)
    value=re.sub(r"^(?:arcade[ -]+archives(?:[ -]+2)?|console[ -]+archives|aca[ -]+neogeo|sega[ -]+ages|johnny[ -]+turbo['’]?s[ -]+arcade)[ :\-]+",'',value,flags=re.I)
    value=value.replace('&',' and ')
    value=re.sub(r'\bPlayStation[®™ ]*5\b','',value,flags=re.I)
    value=re.sub(r'\bPS4\s*(?:&|and|/|e|,)?\s*PS5\b|\bPS5\b|\bPS4\b','',value,flags=re.I)
    value=re.sub(r'\s*[-:|–—]?\s*(?:Standard Edition|Cross[- ]Gen Bundle)\s*$','',value,flags=re.I)
    value=re.sub(r'\b(iii|ii|iv)\b',lambda m:{'ii':'2','iii':'3','iv':'4'}[m[1].lower()],value,flags=re.I)
    return normal(value)
# Platform-port labels ("for Nintendo Switch", "para a PS5™", "Nintendo Switch™ Version") name the
# same product on the requested console; they never distinguish a different game.
PLATFORM_SUFFIX=re.compile(r"\s*[-–—:|]?\s*(?:(?:for|para)(?:\s+(?:a|o|the))?\s+)?(?:Nintendo\s*Switch|PlayStation\s*5|PS4\s*[™®]*\s*(?:&|and|e|/|,)\s*PS5|PS5)\s*[™®]*(?:\s+(?:Version|Edition|Edição|Versão))?\s*[™®]*\s*$",re.I)
# Trailing descriptive qualifiers such as "(QUByte Classics)", "(Classic)" or "(Enhanced)". Qualifiers
# containing digits (years, volumes, packs) can separate different games and are never dropped.
QUALIFIER=re.compile(r"\s*[\(\[][^()\[\]\d]{2,40}[\)\]]\s*$")
# Standard edition names of one base game. Only used where a unique official product is required.
EDITION=re.compile(r"\s*[-–—:|]?\s*(?:(?:the\s+)?(?:definitive|ultimate|deluxe|complete|anniversary|game of the year|goty)\s+edition|reloaded(?:\s+edition)?|remastered|deluxe|hd)\s*[™®]*\s*$",re.I)
def name_keys(value):
    """Identity keys from strictest to loosest; the first key is always identity(value)."""
    keys=[identity(value)]
    stripped=PLATFORM_SUFFIX.sub('',value or '')
    for variant in [stripped,PLATFORM_SUFFIX.sub('',QUALIFIER.sub('',stripped))]:
        key=identity(variant)
        if len(key)>=3 and key not in keys:keys.append(key)
    return [key for key in keys if key]
def edition_key(value):
    key=identity(EDITION.sub('',PLATFORM_SUFFIX.sub('',QUALIFIER.sub('',PLATFORM_SUFFIX.sub('',value or '')))))
    return key if len(key)>=3 else ''
def slug(value):
    value=value.replace('&',' and ').replace('+',' plus ')
    value=unicodedata.normalize('NFKD',value).encode('ascii','ignore').decode().lower().replace("'",'')
    return re.sub('[^a-z0-9]+','-',value).strip('-')

def official_url(platform,url):
    parsed=urllib.parse.urlparse(url)
    if parsed.scheme!='https':return False
    if platform=='PS5':return parsed.hostname=='store.playstation.com' and re.match(r'^/[a-z]{2}-[a-z]{2}/(?:product|concept)/[^/]+/?$',parsed.path) is not None
    return platform=='Switch' and parsed.hostname=='www.nintendo.com' and (parsed.path.startswith('/us/store/products/') or re.match(r'^/(pt-pt/Jogos|en-gb/Games)/',parsed.path)) and '-switch-2/' not in parsed.path.lower() and 'nintendo-switch-2' not in parsed.path.lower()

def portugal_url(platform,url):
    if not official_url(platform,url):return False
    return urllib.parse.urlparse(url).path.startswith('/pt-pt/')

def verified_portugal(record,platform):
    return portugal_url(platform,record.get('url','')) and record.get('region')=='PT' and record.get('verified') is True

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
    page_names=[re.split(r' for (?:the )?Nintendo| [–-] Nintendo Official Site| \| (?:Nintendo|Jogos|Aplicações|Games)| [–-] Official Site',name,flags=re.I)[0] for name in [meta.title,meta.head_title] if name]
    names=[title]+NINTENDO_NAMES.get(title,[])+(aliases or [])
    canonical=lambda value:normal(re.sub(r"^(?:Arcade Archives(?: 2)?|Console Archives|ACA NEOGEO|SEGA AGES|Johnny Turbo['’]?s Arcade)[ :]+",'',value,flags=re.I))
    if any(canonical(name) in {canonical(value) for value in names} for name in page_names):return True
    expected={key for value in names for key in name_keys(value)}
    return any(expected.intersection(name_keys(name)) for name in page_names)

def fetch(url):
    global last
    time.sleep(max(0,1.1-(time.monotonic()-last)));last=time.monotonic()
    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':AGENT}),timeout=20) as response:return response.geturl(),response.read().decode('utf-8')

def resolve(game,ratings):
    # Diagnostic entrypoint shares the same exact-console Portugal verifier.
    from scripts import enrichment as e
    metadata=e.resolve_psn(game,ratings.get('PS5:'+game['id'],{}),{}) if game['platform']=='PS5' else e.resolve_nintendo(game,{})
    return metadata.get('store')

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--limit',type=int,default=60);args=parser.parse_args()
    catalog=json.loads((ROOT/'data/catalog.json').read_text(encoding='utf-8'));ratings=json.loads((ROOT/'data/ratings.json').read_text(encoding='utf-8')).get('games',{})
    path=ROOT/'data/stores.json';previous=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'games':{}};stores=previous['games']
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
        path.write_text(json.dumps({'updated':entry['attempted'],'games':stores},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(game['title'],game['platform'],entry.get('url') or entry.get('error'),flush=True)
    db.close()
if __name__=='__main__':main()
