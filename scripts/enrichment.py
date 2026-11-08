"""Continuous per-game enrichment: all basics first, then composite scores and trailers.
Each result owns its provenance and missing-field reasons. No synthetic ratings.
"""
import argparse, copy, concurrent.futures, datetime as dt, html, json, re, sqlite3, subprocess, threading, time, socket, email.utils, urllib.parse, urllib.request, urllib.error
from pathlib import Path
from scripts import composites, ratings, stores, trailers, psplus, gallery, community_index, nintendo_index, recovery_state, direct_reviews
ROOT=Path(__file__).resolve().parents[1]
VERSION=7
MEDIA_VERSION=1
MEDIA_DAYS=30
PSPLUS_HOURS=20
SEARCH_HASH='4df6284f982e57bec70f23c77e2c219dc792eb19af7fb3d3a81767aa3f1958aa'
locks={};last={};guard=threading.Lock();request_trace=threading.local()
def now():return dt.datetime.now(dt.timezone.utc).isoformat()
def retry_delay(exc,attempt):
    """Retry transport failures and throttling, never missing or forbidden pages."""
    if isinstance(exc,urllib.error.HTTPError):
        if exc.code not in [408,429,500,502,503,504]:return None
        value=exc.headers.get('Retry-After','') if exc.headers else ''
        try:delay=float(value)
        except ValueError:
            try:delay=(email.utils.parsedate_to_datetime(value)-dt.datetime.now(dt.timezone.utc)).total_seconds()
            except (ValueError,TypeError):delay=2**attempt
        # Do not ignore a server's long cooldown by retrying too early.
        return max(0,delay) if delay<=30 else None
    if isinstance(exc,(urllib.error.URLError,TimeoutError,ConnectionError,socket.timeout)):return 2**attempt
    return None

def get(url,headers=None,_redirects=0):
    host=urllib.parse.urlparse(url).hostname
    if hasattr(request_trace,'urls'):request_trace.urls.append(url)
    with guard:lock=locks.setdefault(host,threading.Lock())
    for attempt in range(3):
        with lock:
            time.sleep(max(0,community_index.INTERVALS.get(host,1.1)-(time.monotonic()-last.get(host,0))));last[host]=time.monotonic()
        request=urllib.request.Request(url,headers={'User-Agent':ratings.AGENT,**(headers or {})})
        try:
            with urllib.request.urlopen(request,timeout=18) as response:return response.geturl(),response.read().decode('utf-8')
        except urllib.error.HTTPError as exc:
            if exc.code==301 and host=='backend.metacritic.com' and _redirects<2:
                try:
                    data=json.loads(exc.read());platform=re.search(r'/platform/([^/]+)/',url)[1]
                    choices=list(dict.fromkeys(item['slug'] for error in data.get('errors',[]) for item in error.get('context',{}).get('availableOn',[]) if item.get('slug','').endswith('/'+platform)))
                    target=choices[0].rsplit('/',1)[0] if len(choices)==1 else None
                    old=re.search(r'/games/([^/]+)/platform/',url)[1]
                    if not target or target==old or not re.fullmatch(r'[a-z0-9-]+',target):raise ValueError('No unique canonical slug on the requested console')
                except (ValueError,KeyError,TypeError,IndexError):raise exc
                return get(url.replace('/games/'+old+'/platform/','/games/'+target+'/platform/',1),headers,_redirects+1)
            delay=retry_delay(exc,attempt)
            if attempt==2 or delay is None:raise
            time.sleep(delay)
        except (urllib.error.URLError,TimeoutError,ConnectionError,socket.timeout) as exc:
            if attempt==2:raise
            time.sleep(retry_delay(exc,attempt))

def read(name,default=None):
    path=ROOT/'data'/name
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else (default if default is not None else {'games':{}})
identity=stores.identity
def source_match(game):
    return read('source-aliases.json',{}).get(game.get('platform','')+':'+game.get('title',''),{})
def known_names(game):return list(dict.fromkeys(name for name in [game['title'],ratings.MC_ALIASES.get(game['title'],'')]+source_match(game).get('names',[])+game.get('aliases',[]) if name))
def name_tier(game,name):
    """0: exact identity; 1: same name without a platform-port label or descriptive qualifier."""
    if not identity(name):return None
    known=known_names(game)
    if identity(name) in {identity(value) for value in known}:return 0
    if set(stores.name_keys(name)).intersection(key for value in known for key in stores.name_keys(value)):return 1
    return None
def matches_name(game,name):return name_tier(game,name) is not None
def image_from_media(media):
    for role in ['MASTER','GAMEHUB_COVER_ART','PORTRAIT_BANNER','FOUR_BY_THREE_BANNER','SCREENSHOT']:
        for item in media or []:
            if item.get('type')=='IMAGE' and item.get('role')==role and item.get('url','').startswith('https://'):return item['url']
def psn_search(title,country='PT',language='pt'):
    offset=0;cursor='';seen=set();results=[]
    while True:
        variables={'countryCode':country,'languageCode':language,'nextCursor':cursor,'pageOffset':offset,'pageSize':24,'searchTerm':title}
        extensions={'persistedQuery':{'version':1,'sha256Hash':SEARCH_HASH}}
        query=urllib.parse.urlencode({'operationName':'getSearchResults','variables':json.dumps(variables),'extensions':json.dumps(extensions)})
        _,page=get('https://web.np.playstation.com/api/graphql/v1//op?'+query,{'Accept':'application/json','Content-Type':'application/json','x-psn-store-locale-override':language+'-'+country})
        data=json.loads(page)
        if data.get('errors'):raise ValueError(str(data['errors'])[:150])
        response=data['data']['universalSearch'];items=response['results'];results.extend(items);info=response.get('pageInfo',{})
        if info.get('isLast',True):return results
        following=response.get('next')
        if not items or not following or following in seen:raise ValueError('Incomplete or repeating PSN search pagination')
        seen.add(following);cursor=following;offset+=len(items)

EDITION_TAIL=re.compile(r"(?:[^\s:]+\s+){0,2}(?:edition|edição|cut)|(?:edição|edition)\s+[^\s:]+|(?:versão|version)\s+(?:do|of the)\s+(?:diretor|director)",re.I)
def psn_edition_tier(game,name):
    """A PS5 product sold under an edition name of this exact title ("X: Console Edition", "X - Final Cut"),
    or this catalog title is a standard edition of the product's plain name. Never another catalog game."""
    clean=stores.PLATFORM_SUFFIX.sub('',(name or '').replace('™','').replace('®','')).strip()
    if not clean or identity(clean) in reserved_titles(game):return False
    known={identity(value) for value in known_names(game)}
    for found in re.finditer(r'\s*(?::|\s[-–—]|[-–—]\s)\s*',clean):
        if identity(clean[:found.start()]) in known and EDITION_TAIL.fullmatch(clean[found.end():].strip()):return True
    return any(stores.edition_key(value) and stores.edition_key(value)!=identity(value) and stores.edition_key(value)==identity(clean) for value in known_names(game))

def psn_metadata(game,url,page,edition=False):
    if not url.startswith('https://store.playstation.com/pt-pt/'):raise ValueError('Portugal PSN URL required')
    product=ratings.psn_product(page,url)
    names=[product.get('name',''),product.get('invariantName','')] if product else []
    if not product or 'PS5' not in product.get('platforms',[]) or not any(matches_name(game,name) or (edition and psn_edition_tier(game,name)) for name in names):raise ValueError('Exact PS5 product identity not verified')
    if product.get('storeDisplayClassification') in ['ADD_ON','DEMO','TRIAL'] or product.get('topCategory')=='ADD_ON':raise ValueError('Not the full game')
    checked=now();result={'store':{'url':url,'label':'Abrir na PlayStation Store','checked':checked,'region':'PT','verified':True},'image':{'url':image_from_media(product.get('media')),'source':url,'checked':checked}}
    user=ratings.psn_rating(page,url)
    if user:result['user']={**user,'name':'PSN'+(' (PS4/PS5 shared product)' if 'PS4/PS5' in user['scope'] else ''),'scale':5,'source':'PSN','url':url,'checked':checked,'platform':user['scope']}
    try:result['psplus']={**psplus.parse_catalog(page,url),'region':'PT','source':url,'checked':checked}
    except Exception as exc:result['psplus_error']=str(exc)[:150]
    return result

def resolve_psn(game,legacy,known_store):
    candidates=[];exact=source_match(game).get('store_url') or stores.EXACT.get(('PS5',game['title']))
    if exact:candidates.append(exact)
    for candidate in [known_store.get('url'),legacy.get('user',{}).get('url')]:
        if candidate and candidate.startswith('https://store.playstation.com/pt-pt/') and candidate not in candidates:candidates.append(candidate)
    errors=[]
    for url in candidates:
        try:final,page=get(url);return psn_metadata(game,final,page)
        except Exception as exc:errors.append(str(exc)[:120])
    tried=set(candidates);ps4_only=False;editions=[]
    for title in known_names(game)[:4]:
        for country,language in [('PT','pt'),('GB','en')]:
            try:results=psn_search(title,country,language)
            except Exception as exc:
                errors.append(str(exc)[:120]);continue
            ranked=[(tier,i,item) for i,item in enumerate(results) for tier in [name_tier(game,item.get('name',''))] if tier is not None]
            editions.extend(item for item in results if item.get('__typename')=='Product' and 'PS5' in (item.get('platforms') or []) and name_tier(game,item.get('name','')) is None and psn_edition_tier(game,item.get('name','')))
            for _,_,item in sorted(ranked,key=lambda value:value[:2]):
                if item.get('__typename')=='Product':
                    if 'PS5' not in (item.get('platforms') or []):
                        if 'PS4' in (item.get('platforms') or []):ps4_only=True
                        continue
                    urls=['https://store.playstation.com/pt-pt/product/'+item['id']]
                else:
                    products=sorted(item.get('products') or [],key=lambda p:'PPSA' not in p['id'])
                    urls=['https://store.playstation.com/pt-pt/concept/'+item['id']]+['https://store.playstation.com/pt-pt/product/'+p['id'] for p in products[:8]]
                for url in urls:
                    if url in tried:continue
                    tried.add(url)
                    try:final,page=get(url);return psn_metadata(game,final,page)
                    except Exception as exc:errors.append(str(exc)[:120])
    # Only when no exact product exists: a full PS5 game sold under an edition name of the same title.
    for item in editions:
        url='https://store.playstation.com/pt-pt/product/'+item['id']
        if url in tried:continue
        tried.add(url)
        try:final,page=get(url);return psn_metadata(game,final,page,edition=True)
        except Exception as exc:errors.append(str(exc)[:120])
    raise ValueError(('PS4-only listings found; native PS5 identity requires review. ' if ps4_only else '')+'No exact Portugal PS5 product verified'+(': '+'; '.join(errors[:2]) if errors else ''))

def valid_image(url):
    if not isinstance(url,str):return False
    parsed=urllib.parse.urlparse(url)
    if parsed.scheme!='https' or not parsed.hostname:return False
    if parsed.hostname in ['images.nintendolife.com','images.pushsquare.com'] and not re.match(r'^/[a-zA-Z0-9]+/',parsed.path):return False
    return True

def meta_image(page):
    for tag in re.findall(r'<meta\b[^>]*>',page,re.I):
        if re.search(r'(?:property|name)=["\']og:image["\']',tag,re.I):
            match=re.search(r'content=["\']([^"\']+)',tag,re.I)
            if match and valid_image(html.unescape(match[1]).strip()):return html.unescape(match[1]).strip()

def nintendo_index_match(game,doc):
    systems=doc.get('system_type',[])
    if not any(re.match(r'^nintendoswitch(?:_|$)',system) for system in systems):return False
    canonical=lambda value:identity(re.sub(r'^(?:Arcade Archives|ACA NEOGEO|SEGA AGES)\s+','',value,flags=re.I))
    names=known_names(game)+stores.NINTENDO_NAMES.get(game['title'],[])
    if canonical(doc.get('title','')) in {canonical(value) for value in names}:return True
    return bool(set(stores.name_keys(doc.get('title',''))).intersection(key for value in names for key in stores.name_keys(value)))

NSO_APP=re.compile(r'Nintendo Classics|Nintendo Switch Online',re.I);nso_lock=threading.Lock();nso_cache={}
def nso_listing(page):
    """Included games on an official Nintendo Switch Online app page: title and the game's own artwork."""
    games=[]
    for item in re.finditer(r'<li\b[^>]*data-nt-item-title-master="([^"]+)"[^>]*>(.*?)</li>',page,re.S):
        image=re.search(r'data-xs="(https://[^"]+)"',item[2])
        games.append({'title':html.unescape(item[1]).strip().rstrip('*').strip(),'image':image[1] if image and valid_image(image[1]) else None})
    return games
def nso_catalog():
    """Games listed on every Portuguese Nintendo Switch Online / Nintendo Classics app page, fetched once per run."""
    with nso_lock:
        if 'games' in nso_cache:return nso_cache['games']
        apps=[(pid,p) for pid,p in nintendo_index.load().get('products',{}).items() if any(NSO_APP.search(n) for n in p['names']) and stores.portugal_url('Switch',p.get('pt_url',''))]
        if not apps:raise ValueError('No Nintendo Switch Online app listings indexed')
        games=[]
        for pid,product in sorted(apps):
            final,page=get(product['pt_url'])
            if not stores.portugal_url('Switch',final) or not urllib.parse.urlparse(final).path.endswith('-'+pid+'.html'):raise ValueError('Nintendo Switch Online app page identity not verified')
            app=re.split(r'\s+[–-]\s+',product.get('pt_title') or product['names'][0])[0]
            games.extend({**game,'url':final,'app':app} for game in nso_listing(page))
        nso_cache['games']=games;return games
def resolve_nso(game):
    matches=[item for item in nso_catalog() if matches_name(game,item['title'])]
    if len({item['url'] for item in matches})!=1:raise ValueError('Not listed on one Nintendo Switch Online app' if not matches else 'Listed on several Nintendo Switch Online apps')
    item=matches[0];checked=now()
    store={'url':item['url'],'label':'Ver no Nintendo Switch Online','checked':checked,'region':'PT','verified':True,'note':'Incluído na aplicação '+item['app']+' do Nintendo Switch Online.','nso_title':item['title']}
    return {'store':store,'image':{'url':item['image'],'source':item['url'],'checked':checked,'method':'nintendo-switch-online-listing'}}

catalog_lock=threading.Lock();catalog_cache={}
def reserved_titles(game):
    """Identities of other catalog games on the same console, which loose title matching must not claim."""
    with catalog_lock:
        if 'titles' not in catalog_cache:
            index={}
            for item in read('catalog.json',{'games':[]}).get('games',[]):index.setdefault(item.get('platform'),set()).add(identity(item.get('title','')))
            catalog_cache['titles']=index
    own={identity(name) for name in known_names(game)}
    return frozenset(catalog_cache['titles'].get(game.get('platform'),set())-own)

def release_reserved_store(game,entry,reserved):
    """Drop a Switch link whose official product is named after a different catalog game, not this one."""
    url=(entry.get('store') or {}).get('url','')
    found=re.search(r'-(\d+)\.html$',url)
    product=nintendo_index.load().get('products',{}).get(found[1] if found else '',{})
    if game['platform']!='Switch' or not product or (entry.get('store') or {}).get('nso_title'):return False
    names={identity(name) for name in product.get('names',[])}
    if names & {identity(game['title'])} or not names & reserved:return False
    entry['store_released']={'url':url,'checked':now(),'reason':'Official product is a separate catalog game: '+product['names'][0]}
    entry.pop('store',None);entry.get('field_status',{}).pop('store',None)
    if (entry.get('image') or {}).get('source')==url:entry.pop('image',None);entry.get('field_status',{}).pop('image',None)
    if entry.get('aliases'):entry['aliases']=[name for name in entry['aliases'] if identity(name) not in names]
    return True

def resolve_nintendo(game,known_store):
    names=known_names(game)+stores.NINTENDO_NAMES.get(game['title'],[]);errors=[];tried=set()
    products=nintendo_index.candidates(game,names,known_store,reserved_titles(game))
    candidates=[]
    for url in [known_store.get('url'),source_match(game).get('store_url')]:
        if url and stores.portugal_url('Switch',url):candidates.append((url,names,''))
    candidates.extend((doc['pt_url'],names+doc['names'],doc['id']) for doc in products)
    for url,aliases,product_id in candidates:
        if url in tried:continue
        tried.add(url)
        try:
            final,page=get(url)
            # A name-matched index product is also verified by its official product ID surviving to the final URL,
            # since localized page titles can add regional subtitles (e.g. "com Êxitos Internacionais").
            same_product=bool(product_id) and urllib.parse.urlparse(final).path.endswith('-'+product_id+'.html')
            if not stores.portugal_url('Switch',final) or not (stores.nintendo_match(page,game['title'],aliases) or same_product):raise ValueError('Exact Portuguese Nintendo Switch product identity not verified')
            checked=now();store={'url':final,'label':'Abrir na Nintendo eShop','checked':checked,'region':'PT','verified':True}
            if game['title'] in stores.NSO:store.update(label='Ver no Nintendo Switch Online',note='Incluído na aplicação Super Nintendo do Nintendo Switch Online.')
            return {'store':store,'image':{'url':meta_image(page),'source':final,'checked':checked},'aliases':list(dict.fromkeys(aliases))}
        except Exception as exc:errors.append(str(exc)[:160])
    # Query-time fallback also works when the daily cache refresh was unavailable.
    for name in names[:4]:
        params=urllib.parse.urlencode({'q':'"'+name.replace('"','')+'"','fq':'type:GAME AND system_type:nintendoswitch*','rows':100,'wt':'json'})
        try:
            _,page=get('https://searching.nintendo-europe.com/pt/select?'+params);docs=json.loads(page)['response']['docs']
        except Exception as exc:errors.append(str(exc)[:160]);continue
        for doc in docs:
            if not nintendo_index_match(game,doc):continue
            if identity(doc.get('title','')) in reserved_titles(game) and identity(doc.get('title',''))!=identity(game['title']):continue
            candidate=urllib.parse.urljoin('https://www.nintendo.com',doc.get('url',''))
            if candidate in tried or not stores.portugal_url('Switch',candidate):continue
            tried.add(candidate)
            try:
                final,page=get(candidate)
                if not stores.portugal_url('Switch',final) or not stores.nintendo_match(page,game['title'],names+[doc['title']]):raise ValueError('Portuguese product page identity mismatch')
                checked=now()
                return {'store':{'url':final,'label':'Abrir na Nintendo eShop','checked':checked,'region':'PT','verified':True},'image':{'url':meta_image(page) or doc.get('image_url_sq_s'),'source':final,'checked':checked},'aliases':list(dict.fromkeys(names+[doc['title']]))}
            except Exception as exc:errors.append(str(exc)[:160])
    # Classic games sold only inside a Nintendo Switch Online app link to that official app, as Kirby Super Star does.
    try:return resolve_nso(game)
    except Exception as exc:errors.append(str(exc)[:160])
    raise ValueError('No exact Portuguese Switch listing verified'+(': '+'; '.join(errors[-2:]) if errors else ''))

def community(game):
    expected='PlayStation 5' if game['platform']=='PS5' else 'Nintendo Switch'
    source_game={**game,'aliases':known_names(game)};errors=[];fallback=None
    for url in community_index.candidates(source_game):
        try:
            final,page=get(url);critics,users=composites.community_data(page,final,source_game,expected)
            found=(critics,users,{'url':meta_image(page),'source':final,'checked':now()})
            if critics or users:return found
            if not fallback and found[2].get('url'):fallback=found
        except Exception as exc:errors.append(str(exc)[:100])
    if fallback:return fallback
    raise ValueError('; '.join(errors))

def nindie_data(page,url,game):
    parsed=urllib.parse.urlparse(url)
    if parsed.path.endswith('/error.cfm'):raise ValueError('No review profile indexed for this game')
    game_slug=urllib.parse.parse_qs(parsed.query).get('game',[''])[0]
    if game['platform']!='Switch' or parsed.hostname not in ['www.nindiespotlight.com','nindiespotlight.com'] or not game_slug.endswith('-switch'):raise ValueError('Not a Switch 1 review')
    heading=re.search(r'<title[^>]*>(.*?)</title>',page,re.S|re.I)
    if not heading or not re.search(r'on Nintendo Switch\s*[-–]',html.unescape(heading[1])):raise ValueError('Nintendo Switch review identity missing')
    for text in re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',page,re.S|re.I):
        try:nodes=composites.walk(json.loads(text))
        except ValueError:continue
        for node in nodes:
            if node.get('@type')!='Game' or not matches_name(game,html.unescape(node.get('name',''))):continue
            candidate=node.get('offers',{}).get('availability','');cp=urllib.parse.urlparse(candidate)
            if cp.hostname!='www.nintendo.com' or not cp.path.endswith('-switch'):raise ValueError('Review does not identify the Switch 1 store product')
            critics=[]
            for review in node.get('review',[]):
                r=review.get('reviewRating',{})
                try:score=float(r['ratingValue'])/float(r['bestRating'])*100
                except (KeyError,TypeError,ValueError,ZeroDivisionError):continue
                if 0<=score<=100:critics.append({'name':'Nindie Spotlight','score':score,'url':url,'platform':'Nintendo Switch','via':'Direct console-specific review'})
            if '/store/products/' in candidate:candidate=candidate.replace('/store/products/','/us/store/products/')+'/'
            return critics,{'url':node.get('image'),'source':url,'checked':now()},candidate
    raise ValueError('No exact scored Nintendo Switch review')

def refresh_review_index():
    cached=read('nindie-index.json',{})
    cutoff=(dt.datetime.now(dt.timezone.utc)-dt.timedelta(days=1)).isoformat()
    if cached.get('updated','')>=cutoff:return
    try:
        _,page=get('https://www.nindiespotlight.com/sitemap.xml');index={}
        for value in re.findall(r'<loc>(.*?)</loc>',page):
            url=html.unescape(value);slug=urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get('game',[''])[0]
            if slug.endswith('-switch'):index.setdefault(identity(slug[:-7]),[]).append(url)
        if index:(ROOT/'data/nindie-index.json').write_text(json.dumps({'updated':now(),'source':'https://www.nindiespotlight.com/sitemap.xml','games':index},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    except Exception as exc:print('Review index refresh:',str(exc)[:100],flush=True)

def nindie(game):
    name=stores.slug(game['title']);index=read('nindie-index.json',{}).get('games',{})
    candidates=list(dict.fromkeys(url for alias in known_names(game) for url in index.get(identity(alias),[]))) or ['https://www.nindiespotlight.com/game_profile.cfm?game='+name+'-switch']
    for url in candidates:
        try:final,page=get(url);return nindie_data(page,final,game)
        except Exception as exc:error=exc
    raise ValueError(str(error)[:160])

def opaque_critic(critic):
    return critic.get('method')=='single-aggregate-fallback-incomplete-index' or any('aggregate' in source.get('name','').lower() or source.get('name')=='Metacritic' for source in critic.get('sources',[]))

def curated_critics(game):
    expected='PlayStation 5' if game['platform']=='PS5' else 'Nintendo Switch'
    return [source for source in source_match(game).get('critic_sources',[]) if source.get('platform')==expected and isinstance(source.get('score'),(int,float)) and 0<=source['score']<=100 and source.get('scale',100)==100 and source.get('url','').startswith('https://')]

def slush_title(name):
    match=re.fullmatch(r'(.*?)\s+(?:Nintendo\s+)?Switch\s+(?:Game\s+)?Review',html.unescape(name).strip(),re.I)
    return match[1].strip(' :-–') if match else None

def slush_data(page,url,game):
    if game['platform']!='Switch' or urllib.parse.urlparse(url).hostname not in ['gameslushpile.com','www.gameslushpile.com']:raise ValueError('Not a Switch critic source')
    for text in re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',page,re.S|re.I):
        try:nodes=composites.walk(json.loads(text))
        except ValueError:continue
        for node in nodes:
            if node.get('@type')!='Review' or node.get('url','').rstrip('/')!=url.rstrip('/'):continue
            title=slush_title(node.get('name',''))
            if not title or not matches_name(game,title):continue
            rating=node.get('reviewRating',{})
            try:raw=float(rating['ratingValue']);scale=float(rating['bestRating']);score=raw/scale*100
            except (KeyError,TypeError,ValueError,ZeroDivisionError):continue
            if 0<=score<=100:
                return {'name':'The Game Slush Pile','score':score,'url':url,'date':node.get('datePublished',''),'platform':'Nintendo Switch','via':'Direct console-specific review','original_score':raw,'original_scale':scale}
    raise ValueError('No exact scored Nintendo Switch review')

def slush_review(game):
    candidates=list(source_match(game).get('review_urls',[]))
    if not candidates:
        params=urllib.parse.urlencode({'search':game['title'],'per_page':5})
        _,page=get('https://gameslushpile.com/wp-json/wp/v2/search?'+params)
        for item in json.loads(page):
            title=slush_title(item.get('title',''))
            if title and matches_name(game,title):candidates.append(item['url'])
    for url in candidates:
        try:final,page=get(url);return slush_data(page,final,game)
        except Exception as exc:error=exc
    raise ValueError(str(error)[:150] if candidates else 'No scored Switch review indexed')

def metacritic_search(game,expected):
    """Slugs from Metacritic's own search whose title matches this game and which list the exact console."""
    slugs=[]
    for name in known_names(game)[:2]:
        query=urllib.parse.quote(re.sub(r'[/?#%]',' ',name).strip())
        _,page=get(f'https://backend.metacritic.com/finder/metacritic/search/{query}/web?offset=0&limit=20&mcoTypeId=13&componentName=search-tabs&componentDisplayName=Search+Page+Tab+Filters&componentType=FilterConfig')
        for item in json.loads(page).get('data',{}).get('items',[]):
            slug=item.get('slug','')
            if re.fullmatch(r'[a-z0-9-]+',slug) and expected in [p.get('name') for p in item.get('platforms') or []] and matches_name(game,item.get('title','')):slugs.append(slug)
        if slugs:break
    return list(dict.fromkeys(slugs))

def metacritic_slugs(game,guessed,expected,errors):
    # Guessed slugs first; Metacritic search only when none of them produced a score.
    yield from guessed
    try:found=metacritic_search(game,expected)
    except Exception as exc:errors['metacritic_search']=str(exc)[:160];return
    yield from [slug for slug in found if slug not in guessed][:3]

def minimal_metacritic(game):
    platform='playstation-5' if game['platform']=='PS5' else 'nintendo-switch';expected='PlayStation 5' if game['platform']=='PS5' else 'Nintendo Switch';errors={}
    names=list(dict.fromkeys([ratings.MC_ALIASES.get(game['title'],ratings.slug(game['title']))]+[ratings.slug(name) for name in known_names(game) if name]))[:4]
    for name in metacritic_slugs(game,names,expected,errors):
        critics=[];users=[]
        try:
            url=f'https://backend.metacritic.com/reviews/metacritic/user/games/{name}/platform/{platform}/stats/web';final,page=get(url);u=json.loads(page)['data']['item']
            canonical=re.search(r'/games/([^/]+)/platform/',final)[1]
            if u.get('reviewCount',0)>=4 and u.get('score') is not None:users.append({'name':'Metacritic users','score':u['score'],'scale':10,'count':u['reviewCount'],'url':f'https://www.metacritic.com/game/{canonical}/user-reviews/?platform={platform}','platform':expected})
        except Exception as exc:errors['metacritic_users']=str(exc)[:160]
        if not users:
            try:
                offset=0;total=None;reviews=[]
                while total is None or offset<total:
                    url=f'https://backend.metacritic.com/reviews/metacritic/critic/games/{name}/platform/{platform}/web?offset={offset}&limit=10&filterBySentiment=all&sort=score'
                    _,page=get(url);index=json.loads(page)['data'];items=index['items'];total=int(index['totalResults'])
                    if not items and offset<total:raise ValueError('Incomplete console-specific critic index')
                    reviews.extend({'name':r['publicationName'],'score':r['score'],'url':r['url'],'date':r.get('date',''),'platform':expected,'via':'Metacritic review index'} for r in items if r.get('platform')==expected)
                    offset+=len(items)
                    if total==0:break
                critics=reviews
            except Exception as exc:errors['metacritic_reviews']=str(exc)[:160]
        if not users and not critics:
            try:
                url=f'https://www.metacritic.com/game/{name}/';_,page=get(url);score=ratings.mc_critic(page,name,expected)
                if score is not None:critics.append({'name':'Metacritic aggregate','score':score,'url':url+'critic-reviews/?platform='+platform,'platform':expected})
            except Exception as exc:errors['metacritic_critics']=str(exc)[:160]
        if critics or users:return critics,users,errors
    return [],[],errors

def wikipedia_image_data(payload,game):
    candidates=[]
    for page in payload.get('query',{}).get('pages',{}).values():
        title=re.sub(r'\s*\((?:\d{4} )?(?:video )?game\)$','',page.get('title',''),flags=re.I)
        categories=[c.get('title','').lower() for c in page.get('categories',[])]
        if not any('video games' in category for category in categories):continue
        if not matches_name(game,title):continue
        image=page.get('thumbnail',{}).get('source','')
        if image.startswith('https://upload.wikimedia.org/'):
            candidates.append({'url':image,'source':'https://en.wikipedia.org/wiki/'+urllib.parse.quote(page['title'].replace(' ','_')),'checked':now(),'method':'verified-game-article'})
    if len(candidates)!=1:raise ValueError('No unique matching video-game article with artwork')
    return candidates[0]

def wikipedia_image(game):
    error=None
    for name in known_names(game)[:4]:
        params={'action':'query','generator':'search','gsrsearch':'"'+name.replace('"','')+'" video game','gsrlimit':5,'prop':'pageimages|categories','piprop':'thumbnail','pithumbsize':500,'pilicense':'any','cllimit':50,'format':'json'}
        _,page=get('https://en.wikipedia.org/w/api.php?'+urllib.parse.urlencode(params))
        try:return wikipedia_image_data(json.loads(page),game)
        except ValueError as exc:error=exc
    raise ValueError(str(error) if error else 'No exact video-game artwork found')

def has_score(value):return isinstance(value.get('score'),(int,float)) and value.get('scale',0)>0 and 0<=value['score']<=value['scale']
def requirements(entry):
    rating=entry.get('ratings',{})
    return {'image':valid_image(entry.get('image',{}).get('url')) and entry.get('image',{}).get('validation')!='invalid','store':stores.verified_portugal(entry.get('store',{}),entry.get('platform') or ('PS5' if 'playstation.com' in entry.get('store',{}).get('url','') else 'Switch')),'rating':any(has_score(rating.get(kind,{})) for kind in ['user','critic'])}

def migrate_entry(game,entry):
    entry.setdefault('title',game['title']);entry.setdefault('platform',game['platform'])
    store=entry.get('store',{})
    if store.get('url'):
        if stores.portugal_url(game['platform'],store['url']) and store.get('checked') and store.get('verified') is not False:
            store.update(region='PT',verified=True)
        elif not stores.verified_portugal(store,game['platform']):
            evidence=entry.setdefault('store_evidence',[])
            if not any(item.get('url')==store['url'] for item in evidence):evidence.append(store)
            entry.pop('store',None)
    entry['coverage_policy']=recovery_state.POLICY

def share_artwork(games,entries):
    by_title={}
    for game in games:by_title.setdefault(game['title'],[]).append(game)
    for game in games:
        entry=entries.get(game['platform']+':'+game['id'],{})
        if requirements(entry)['image'] or not game.get('synopsis'):continue
        candidates=[]
        for other in by_title[game['title']]:
            if other['platform']==game['platform'] or ' '.join(other.get('synopsis','').split())!=' '.join(game['synopsis'].split()):continue
            art=entries.get(other['platform']+':'+other['id'],{}).get('image',{})
            if valid_image(art.get('url')) and art.get('validation')!='invalid':candidates.append((other,art))
        if len(candidates)==1:
            other,art=candidates[0];entry['image']={**art,'method':'same-game-artwork','artwork_from':other['platform']+':'+other['id'],'note':'Shared artwork only; ratings and store remain console-specific.'}
            entry['requirements']=requirements(entry)

def seed(games,entries,legacy,known_stores,old_composites,old_trailers,artwork,old_plus):
    # Audit existing verified data too; unattempted enrichment is not missing data.
    for game in games:
        key=game['platform']+':'+game['id'];entry=entries.setdefault(key,{'title':game['title'],'platform':game['platform']})
        if entry.get('image') and not valid_image(entry['image'].get('url')):entry.pop('image')
        if valid_image(artwork.get(game['title'],{}).get('url')) and not entry.get('image',{}).get('url'):entry['image']=artwork[game['title']]
        if known_stores.get(key,{}).get('url') and not entry.get('store',{}).get('url'):entry['store']=known_stores[key]
        migrate_entry(game,entry)
        if release_reserved_store(game,entry,reserved_titles({**game,'aliases':[]})):entry['requirements']=requirements(entry)
        if old_trailers.get(key,{}).get('id'):entry.setdefault('trailer',old_trailers[key])
        if old_plus.get(key,{}).get('checked'):entry.setdefault('psplus',old_plus[key])
        if 'ratings' not in entry:
            existing=old_composites.get(key)
            if existing:entry['ratings']=existing
            else:
                source=legacy.get(key,{});result={}
                for kind in ['critic','user']:
                    raw=source.get(kind,{})
                    if has_score(raw):
                        scale=100 if kind=='critic' else 10
                        result[kind]={'score':raw['score']/raw['scale']*scale,'scale':scale,'source_count':1,'method':'single-source','sources':[{**raw,'name':raw.get('source','Verified source'),'platform':raw.get('scope',game['platform'])}]}
                    else:result[kind]={'score':None,'scale':100 if kind=='critic' else 10,'source_count':0,'sources':[]}
                result['attempted']=source.get('attempted','');entry['ratings']=result
        entry['requirements']=requirements(entry)
    share_artwork(games,entries)

def source_revision(game,aliases):return recovery_state.revision(game,aliases)+':'+str(VERSION)

def source_registry(game):
    sources={'psn':('store','image','rating')} if game['platform']=='PS5' else {'nintendo':('store','image'),'nindie':('image','rating'),'slush':('rating',)}
    sources.update(community=('image','rating'),metacritic=('rating',),wikipedia=('image',))
    for source in direct_reviews.for_platform(game['platform']):sources[source]=('rating',)
    return sources

def basics(game,previous,legacy,known_store,old_composite,old_trailer,artwork):
    from scripts.apply_recoveries import critic_merge,user_merge
    result=copy.deepcopy(previous or {});migrate_entry(game,result);stamp=now();errors=dict(result.get('errors',{}))
    if old_trailer.get('id'):result.setdefault('trailer',old_trailer)
    if not result.get('ratings'):result['ratings']=copy.deepcopy(old_composite or {})
    prior=result['ratings']
    if prior.get('user',{}).get('sources'):
        prior['user']['sources']=[{**source,'checked':source.get('checked') or prior.get('attempted','')} for source in prior['user']['sources']]
    if valid_image(artwork.get('url')) and not requirements(result)['image']:result['image']=dict(artwork)
    source_game={**game,'aliases':list(dict.fromkeys(result.get('aliases',[])+source_match(game).get('names',[])))}
    revision=source_revision(game,source_game['aliases']);registry=source_registry(game)
    def merge_scores(critics,users):
        rating=result.setdefault('ratings',{});fresh_user=composites.user_composite([{**u,'checked':u.get('checked') or now()} for u in users])
        rating['critic']=critic_merge(rating.get('critic',{}),composites.critic_composite(critics))
        rating['user']=user_merge(rating.get('user',{}),fresh_user,rating.get('attempted',''),stamp)
        rating['attempted']=stamp
    def metadata(value):
        store=value.get('store',{})
        if stores.verified_portugal(store,game['platform']):result['store']=store;result.pop('platform_review',None)
        image=value.get('image',{})
        if valid_image(image.get('url')) and not requirements(result)['image'] and not (result.get('image',{}).get('validation')=='invalid' and result['image'].get('url')==image['url']):result['image']=image
        for field in ['user','psplus']:
            if value.get(field):result[field]=value[field]
        if value.get('aliases'):
            source_game['aliases']=list(dict.fromkeys(source_game['aliases']+value['aliases']));result['aliases']=source_game['aliases']
        if value.get('user'):merge_scores([], [value['user']])
    def run(source,fn,consume):
        missing=[field for field in registry[source] if not requirements(result)[field]]
        if not missing or not recovery_state.due(result,source,missing,revision):return
        request_trace.urls=[]
        try:
            value=fn();consume(value);errors.pop(source,None)
            for field in missing:
                good=requirements(result)[field];reason='' if good else 'No qualifying '+field+' found on this source'
                recovery_state.record(result,source,[field],revision,'verified' if good else 'not_found',reason)
        except Exception as exc:
            if 'PS4-only' in str(exc):result['platform_review']={'reason':str(exc)[:300],'checked':now()}
            errors[source]=str(exc)[:500];recovery_state.record(result,source,missing,revision,recovery_state.classify(exc),exc,exc=exc)
        finally:
            urls=list(dict.fromkeys(request_trace.urls))[-3:]
            for field in missing:
                check=result.get('field_status',{}).get(field,{}).get('sources',{}).get(source)
                if check and urls:check['attempted_urls']=urls;check['url']=urls[-1]
            del request_trace.urls
    if game['platform']=='PS5':run('psn',lambda:resolve_psn(source_game,legacy,result.get('store') or known_store),metadata)
    else:run('nintendo',lambda:resolve_nintendo(source_game,result.get('store') or known_store),metadata)
    if legacy.get('user') and game['platform']=='PS5' and not requirements(result)['rating']:
        raw=legacy['user']
        if raw.get('source')=='PSN' and has_score(raw):merge_scores([], [{**raw,'name':'PSN','platform':raw.get('scope','PlayStation 5')}])
    merge_scores(curated_critics(game),[])
    def consume_community(value):
        c,u,image=value;merge_scores(c,u)
        if valid_image(image.get('url')) and not requirements(result)['image'] and not (result.get('image',{}).get('validation')=='invalid' and result['image'].get('url')==image['url']):result['image']=image
    run('community',lambda:community(source_game),consume_community)
    if game['platform']=='Switch':
        def consume_nindie(value):
            c,image,_=value;merge_scores(c,[])
            if valid_image(image.get('url')) and not requirements(result)['image'] and not (result.get('image',{}).get('validation')=='invalid' and result['image'].get('url')==image['url']):result['image']=image
        run('nindie',lambda:nindie(source_game),consume_nindie)
    def consume_metacritic(value):
        c,u,failures=value
        if not c and not u and failures:raise ValueError('; '.join(failures.values()))
        merge_scores(c,u)
    run('metacritic',lambda:minimal_metacritic(source_game),consume_metacritic)
    if game['platform']=='Switch':run('slush',lambda:slush_review(source_game),lambda value:merge_scores([value],[]))
    for source in direct_reviews.for_platform(game['platform']):run(source,lambda source=source:direct_reviews.collect(source_game,source,get),lambda value:merge_scores([value],[]))
    run('wikipedia',lambda:wikipedia_image(source_game),lambda value:metadata({'image':value}))
    result['requirements']=requirements(result);result.update(title=game['title'],platform=game['platform'],basics_attempted=stamp,version=VERSION,errors=errors)
    return result

def complete(game,previous,legacy,curated):
    from scripts.apply_recoveries import critic_merge,user_merge
    result=dict(previous);errors=dict(result.get('errors',{}));raw=dict(legacy)
    source_game={**game,'aliases':list(dict.fromkeys(result.get('aliases',[])+source_match(game).get('names',[])))}
    if result.get('user'):raw['user']=result['user']
    try:
        composite=composites.collect(source_game,raw)
        for kind in ['critic','user']:
            if not has_score(composite.get(kind,{})) and has_score(result.get('ratings',{}).get(kind,{})):composite[kind]=result['ratings'][kind]
        if game['platform']=='Switch':
            try:
                c,_,_=nindie(source_game);errors.pop('nindie',None)
                # Never mix an opaque aggregate with potentially overlapping reviews.
                if not opaque_critic(composite['critic']):composite['critic']=composites.critic_composite(composite['critic'].get('sources',[])+c)
            except Exception as exc:errors['nindie']=str(exc)[:160]
        if game['platform']=='Switch' and not opaque_critic(composite['critic']) and not any('gameslushpile.com' in source.get('url','') for source in composite['critic'].get('sources',[])):
            try:
                composite['critic']=composites.critic_composite(composite['critic'].get('sources',[])+[slush_review(source_game)]);errors.pop('slush',None)
            except Exception as exc:errors['slush']=str(exc)[:160]
        if not opaque_critic(composite['critic']):composite['critic']=composites.critic_composite(composite['critic'].get('sources',[])+curated_critics(game))
        if not opaque_critic(composite['critic']):
            for source in direct_reviews.for_platform(game['platform']):
                host=direct_reviews.SOURCES[source]['host'].removeprefix('www.')
                if any(urllib.parse.urlparse(item.get('url','')).hostname in [host,'www.'+host] for item in composite['critic'].get('sources',[])):continue
                try:
                    review=direct_reviews.collect(source_game,source,get)
                    composite['critic']=composites.critic_composite(composite['critic'].get('sources',[])+[review]);errors.pop(source,None)
                except Exception as exc:errors[source]=str(exc)[:200]
        prior=result.get('ratings',{})
        prior_critic=prior.get('critic',{})
        replaces_aggregate=opaque_critic(prior_critic) and composite.get('critic_index_complete') and any(source.get('via')=='Metacritic review index' for source in composite['critic'].get('sources',[]))
        if not replaces_aggregate:composite['critic']=critic_merge(prior_critic,composite['critic'])
        composite['user']=user_merge(prior.get('user',{}),composite['user'],prior.get('attempted',''),composite.get('attempted',now()))
        result['ratings']=composite
        errors.pop('composites',None)
        if composite.get('errors'):errors['composites']='; '.join(composite['errors'])[:500]
    except Exception as exc:errors['composites']=str(exc)[:160]
    chosen=curated.get(game['title']) or result.get('trailer')
    # A YouTube search result is only a stand-in until an official video is found.
    searched=None if official_trailer(chosen) else chosen
    if searched:chosen=None
    if not chosen or chosen.get('kind')!='gameplay':
        url='https://www.playstation.com/en-us/games/'+ratings.PS_ALIASES.get(game['title'],ratings.slug(game['title']))+'/'
        try:
            _,page=get(url);chosen=trailers.choose_video(chosen,trailers.videos_from_official_page(page,game['title'],url))
        except Exception as exc:errors['trailer']=str(exc)[:160]
    chosen=chosen or searched
    if chosen:result['trailer']=chosen
    result.update(full_attempted=now(),full_version=VERSION,errors=errors);result['requirements']=requirements(result)
    return result

def psplus_due(game,entry):
    if game['platform']!='PS5' or not stores.verified_portugal(entry.get('store',{}),'PS5'):return False
    cutoff=(dt.datetime.now(dt.timezone.utc)-dt.timedelta(hours=PSPLUS_HOURS)).isoformat()
    return max(entry.get('psplus',{}).get('checked',''),entry.get('psplus_attempted',''))<cutoff

def refresh_psplus(game,previous):
    """Daily PS Plus catalogue check on the game's verified Portugal store page."""
    result=copy.deepcopy(previous);errors=dict(result.get('errors',{}))
    try:
        url,page=get(result['store']['url'])
        result['psplus']={**psplus.parse_catalog(page,url),'region':'PT','source':url,'checked':now()};errors.pop('psplus',None)
    except Exception as exc:errors['psplus']=str(exc)[:200]
    result.update(psplus_attempted=now(),errors=errors);return result

def media_due(entry):
    cutoff=(dt.datetime.now(dt.timezone.utc)-dt.timedelta(days=MEDIA_DAYS)).isoformat()
    return entry.get('media_version',0)<MEDIA_VERSION or entry.get('media_attempted','')<cutoff

def official_trailer(video):return bool(video and video.get('id') and video.get('source')!='YouTube search')

def collect_media(game,previous,curated):
    """Screenshots from the store page (Steam as fallback) and a trailer for every game."""
    result=copy.deepcopy(previous);errors=dict(result.get('errors',{}))
    names=list(dict.fromkeys([game['title']]+result.get('aliases',[])+source_match(game).get('names',[])))
    shots=[];page_video=None;store=result.get('store',{})
    if stores.verified_portugal(store,game['platform']):
        try:
            url,page=get(store['url'])
            if game['platform']=='PS5':
                shots=gallery.psn_screenshots(page,url)
                try:result['psplus']={**psplus.parse_catalog(page,url),'region':'PT','source':url,'checked':now()};result['psplus_attempted']=now()
                except Exception:pass
            else:
                shots=gallery.nintendo_screenshots(page);page_video=gallery.nintendo_video(page,game['title'],url)
            errors.pop('screenshots',None)
        except Exception as exc:errors['screenshots']=str(exc)[:200]
    if not shots:
        try:shots=gallery.steam_screenshots(game,names,get)
        except Exception as exc:errors['screenshots_steam']=str(exc)[:200]
    if shots:result['screenshots']={'items':shots,'checked':now()};errors.pop('screenshots_steam',None)
    elif not result.get('screenshots',{}).get('items'):errors.setdefault('screenshots','No screenshots found on the store page or Steam')
    video=curated.get(game['title']) or result.get('trailer')
    if not official_trailer(video) and page_video:video=page_video
    if not official_trailer(video):
        try:video=gallery.youtube_trailer(game,names,get);errors.pop('trailer_search',None)
        except Exception as exc:errors['trailer_search']=str(exc)[:200]
    if video and video.get('id'):result['trailer']={**video,'checked':video.get('checked') or now()}
    result.update(media_attempted=now(),media_version=MEDIA_VERSION,errors=errors);return result

def export(entries,db):
    games=read('catalog.json')['games'];audit=[]
    db.executemany('INSERT OR REPLACE INTO enrichment VALUES(?,?)',[(key,json.dumps(value,ensure_ascii=False)) for key,value in entries.items()]);db.commit()
    for game in games:
        key=game['platform']+':'+game['id'];entry=entries.get(key,{});required=requirements(entry);missing=[k for k,v in required.items() if not v]
        if missing:audit.append({'key':key,'title':game['title'],'platform':game['platform'],'missing':missing,'attempted':entry.get('basics_attempted'),'reasons':entry.get('errors',{}),'field_status':entry.get('field_status',{}),'next_retry':recovery_state.next_due(entry,missing)})
    report={'total':len(games),'attempted':sum(bool(entries.get(g['platform']+':'+g['id'],{}).get('basics_attempted')) for g in games),'ready':len(games)-len(audit),'missing_image':sum('image' in e['missing'] for e in audit),'missing_store':sum('store' in e['missing'] for e in audit),'missing_rating':sum('rating' in e['missing'] for e in audit),'full_attempted':sum(bool(entries.get(g['platform']+':'+g['id'],{}).get('full_attempted')) for g in games),'image_health_pending':sum(image_health_due(entries.get(g['platform']+':'+g['id'],{})) for g in games)}
    (ROOT/'data/enrichment.json').write_text(json.dumps({'updated':now(),'version':VERSION,'coverage':report,'coverage_policy':recovery_state.POLICY,'games':entries},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    public={key:{field:value for field,value in entry.items() if field in ['title','platform','image','store','ratings','psplus','trailer','aliases']} for key,entry in entries.items()}
    (ROOT/'data/enrichment-public.json').write_text(json.dumps({'updated':now(),'coverage_policy':recovery_state.POLICY,'coverage':report,'games':public},ensure_ascii=False,separators=(',',':'))+'\n',encoding='utf-8')
    media={key:{'screenshots':[shot['url'] for shot in entry.get('screenshots',{}).get('items',[])]} for key,entry in entries.items() if entry.get('screenshots',{}).get('items')}
    media_report={'games':len(games),'with_screenshots':sum(bool(media.get(g['platform']+':'+g['id'])) for g in games),'with_trailer':sum(bool(entries.get(g['platform']+':'+g['id'],{}).get('trailer',{}).get('id')) for g in games),'media_attempted':sum(bool(entries.get(g['platform']+':'+g['id'],{}).get('media_attempted')) for g in games)}
    (ROOT/'data/media-public.json').write_text(json.dumps({'updated':now(),'coverage':media_report,'games':media},ensure_ascii=False,separators=(',',':'))+chr(10),encoding='utf-8')
    print('MEDIA',json.dumps(media_report),flush=True)
    (ROOT/'data/enrichment-audit.json').write_text(json.dumps({'updated':now(),'coverage':report,'coverage_policy':recovery_state.POLICY,'entries':audit},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('COVERAGE',json.dumps(report),flush=True)

def image_health_due(entry):
    image=entry.get('image',{})
    if not valid_image(image.get('url')):return False
    check=entry.get('field_status',{}).get('image',{}).get('sources',{}).get('image_health',{})
    return check.get('url')!=image.get('url') or recovery_state.due(entry,'image_health',['image'],'health-v1')

def verify_image(game,previous):
    result=copy.deepcopy(previous);image=result.get('image',{});url=image.get('url','');host=urllib.parse.urlparse(url).hostname
    def request(method):
        with guard:lock=locks.setdefault(host,threading.Lock())
        with lock:
            time.sleep(max(0,community_index.INTERVALS.get(host,1.1)-(time.monotonic()-last.get(host,0))));last[host]=time.monotonic()
        return urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':ratings.AGENT,**({'Range':'bytes=0-65535'} if method=='GET' else {})},method=method),timeout=18)
    try:
        if not valid_image(url):raise ValueError('Known invalid image placeholder')
        try:response=request('HEAD')
        except urllib.error.HTTPError as exc:
            if exc.code not in [405,501]:raise
            response=request('GET')
        with response:
            content=response.headers.get('Content-Type','').split(';')[0].lower();length=response.headers.get('Content-Length')
            if not content.startswith('image/') or length=='0' or not valid_image(response.geturl()):raise ValueError('Invalid image response or placeholder')
        image.update(validation='verified',validated_at=now());recovery_state.record(result,'image_health',['image'],'health-v1','verified',url=url)
    except Exception as exc:
        status=recovery_state.classify(exc)
        if (isinstance(exc,urllib.error.HTTPError) and exc.code in [404,410]) or isinstance(exc,ValueError):
            image.update(validation='invalid',invalidated_at=now());result.setdefault('invalidations',[]).append({'field':'image','url':url,'reason':str(exc)[:250],'at':now()})
        recovery_state.record(result,'image_health',['image'],'health-v1',status,exc,url=url,exc=exc)
    result['requirements']=requirements(result);return result

def lookup_upgrade(game,entry):return entry.get('version',0)<VERSION and not all(requirements(entry).values())

def basic_due(game,entry):
    missing=[field for field,good in requirements(entry).items() if not good]
    if not missing:return False
    if lookup_upgrade(game,entry):return True
    revision=source_revision(game,entry.get('aliases',[])+source_match(game).get('names',[]))
    return any(recovery_state.due(entry,source,[field for field in fields if field in missing],revision) for source,fields in source_registry(game).items() if any(field in missing for field in fields))

def select_work(games,entries,seen):
    def entry(g):return entries.get(g['platform']+':'+g['id'],{})
    def unseen(g,phase):return (g['platform']+':'+g['id'],phase) not in seen
    new=[g for g in games if unseen(g,'basics') and not entry(g).get('basics_attempted')]
    if new:return 'basics',new
    plus=[g for g in games if unseen(g,'psplus') and psplus_due(g,entry(g))]
    if plus:return 'psplus',sorted(plus,key=lambda g:entry(g).get('psplus',{}).get('checked',''))
    retry=[g for g in games if unseen(g,'basics') and basic_due(g,entry(g))]
    if retry:return 'basics',sorted(retry,key=lambda g:(recovery_state.next_due(entry(g),[f for f,v in requirements(entry(g)).items() if not v]),entry(g).get('basics_attempted',''),g['title']))
    health=[g for g in games if unseen(g,'health') and image_health_due(entry(g))]
    if health:return 'health',sorted(health,key=lambda g:entry(g).get('image',{}).get('validated_at',''))
    media=[g for g in games if unseen(g,'media') and media_due(entry(g))]
    if media:return 'media',sorted(media,key=lambda g:(bool(entry(g).get('trailer',{}).get('id')),bool(entry(g).get('screenshots')),entry(g).get('media_attempted',''),g['title']))
    cutoff=(dt.datetime.now(dt.timezone.utc)-dt.timedelta(days=7)).isoformat()
    full=[g for g in games if unseen(g,'full') and (entry(g).get('full_version',0)<VERSION or entry(g).get('full_attempted','')<cutoff)]
    if full:return 'full',sorted(full,key=lambda g:(requirements(entry(g))['rating'],entry(g).get('full_attempted',''),g['title']))
    cutoff=(dt.datetime.now(dt.timezone.utc)-dt.timedelta(days=1)).isoformat()
    return 'basics',[g for g in games if unseen(g,'basics') and entry(g).get('basics_attempted','')<cutoff]

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--minutes',type=float,default=50);ap.add_argument('--workers',type=int,default=4);ap.add_argument('--ids');ap.add_argument('--checkpoint-push',action='store_true');args=ap.parse_args()
    from scripts.apply_recoveries import apply_pending
    applied=apply_pending()
    if applied and args.checkpoint_push:subprocess.run(['bash','scripts/checkpoint-enrichment.sh'],cwd=ROOT,check=True)
    refresh_review_index()
    community_index.refresh(get)
    nintendo_index.refresh(get)
    direct_reviews.refresh(get)
    entries=read('enrichment.json')['games'];legacy=read('ratings.json')['games'];known_stores=read('stores.json')['games'];old_composites=read('composites.json')['games'];old_trailers=read('trailers.json')['games'];curated=read('trailers-curated.json',{});artwork=read('images.json',{});seen=set();started=time.monotonic()
    # All network stages share per-host pacing, including the composite collector.
    composites.get=get
    seed(read('catalog.json')['games'],entries,legacy,known_stores,old_composites,old_trailers,artwork,read('psplus.json')['games'])
    db=sqlite3.connect(ROOT/'data/enrichment.sqlite');db.execute('CREATE TABLE IF NOT EXISTS enrichment(game_key TEXT PRIMARY KEY,payload TEXT NOT NULL)')
    while time.monotonic()-started<args.minutes*60:
        games=read('catalog.json')['games']
        if args.ids:games=[g for g in games if g['platform']+':'+g['id'] in args.ids.split(',')]
        seed(games,entries,legacy,known_stores,old_composites,old_trailers,artwork,read('psplus.json')['games'])
        phase,queue=select_work(games,entries,seen)
        if not queue:break
        # Light page checks amortise the checkpoint push over a bigger batch.
        batch=queue[:{'psplus':60,'media':40}.get(phase,max(10,args.workers))]
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures={}
            for game in batch:
                key=game['platform']+':'+game['id'];seen.add((key,phase))
                task=pool.submit(basics,game,entries.get(key,{}),legacy.get(key,{}),known_stores.get(key,{}),old_composites.get(key,{}),old_trailers.get(key,{}),artwork.get(game['title'],{})) if phase=='basics' else pool.submit(verify_image,game,entries.get(key,{})) if phase=='health' else pool.submit(refresh_psplus,game,entries.get(key,{})) if phase=='psplus' else pool.submit(collect_media,game,entries.get(key,{}),curated) if phase=='media' else pool.submit(complete,game,entries.get(key,{}),legacy.get(key,{}),curated)
                futures[task]=(key,game)
            for task in concurrent.futures.as_completed(futures):
                key,game=futures[task]
                try:entry=task.result()
                except Exception as exc:entry={**entries.get(key,{}),'title':game['title'],'platform':game['platform'],'errors':{'pipeline':str(exc)[:200]},phase+'_attempted':now()}
                entries[key]=entry;db.execute('INSERT OR REPLACE INTO enrichment VALUES(?,?)',(key,json.dumps(entry,ensure_ascii=False)));db.commit();print(phase,key,game['title'],requirements(entry),flush=True)
        export(entries,db)
        if args.checkpoint_push:
            db.close();subprocess.run(['bash','scripts/checkpoint-enrichment.sh'],cwd=ROOT,check=True)
            # A checkpoint can pull a newly verified recovery batch while this
            # collector is running. Merge under this writer lock and reload it
            # before the next export so in-memory entries cannot overwrite it.
            if apply_pending():
                entries=read('enrichment.json')['games']
                subprocess.run(['bash','scripts/checkpoint-enrichment.sh'],cwd=ROOT,check=True)
            community_index.load.cache_clear()
            db=sqlite3.connect(ROOT/'data/enrichment.sqlite')
    export(entries,db);db.close()
if __name__=='__main__':main()
