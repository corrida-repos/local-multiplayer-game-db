"""Continuous per-game enrichment: all basics first, then composite scores and trailers.
Each result owns its provenance and missing-field reasons. No synthetic ratings.
"""
import argparse, concurrent.futures, datetime as dt, html, json, re, sqlite3, subprocess, threading, time, socket, email.utils, urllib.parse, urllib.request, urllib.error
from pathlib import Path
from scripts import composites, ratings, stores, trailers, psplus, community_index
ROOT=Path(__file__).resolve().parents[1]
VERSION=6
SEARCH_HASH='4df6284f982e57bec70f23c77e2c219dc792eb19af7fb3d3a81767aa3f1958aa'
locks={};last={};guard=threading.Lock()
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
    return json.loads(path.read_text()) if path.exists() else (default if default is not None else {'games':{}})
identity=stores.identity
def source_match(game):
    return read('source-aliases.json',{}).get(game.get('platform','')+':'+game.get('title',''),{})
def known_names(game):return list(dict.fromkeys(name for name in [game['title'],ratings.MC_ALIASES.get(game['title'],'')]+source_match(game).get('names',[])+game.get('aliases',[]) if name))
def matches_name(game,name):
    return bool(identity(name)) and identity(name) in {identity(value) for value in known_names(game)}
def image_from_media(media):
    for role in ['MASTER','GAMEHUB_COVER_ART','PORTRAIT_BANNER','FOUR_BY_THREE_BANNER','SCREENSHOT']:
        for item in media or []:
            if item.get('type')=='IMAGE' and item.get('role')==role and item.get('url','').startswith('https://'):return item['url']
def psn_search(title,country='PT',language='pt'):
    variables={'countryCode':country,'languageCode':language,'nextCursor':'','pageOffset':0,'pageSize':24,'searchTerm':title}
    extensions={'persistedQuery':{'version':1,'sha256Hash':SEARCH_HASH}}
    query=urllib.parse.urlencode({'operationName':'getSearchResults','variables':json.dumps(variables),'extensions':json.dumps(extensions)})
    _,page=get('https://web.np.playstation.com/api/graphql/v1//op?'+query,{'Accept':'application/json','Content-Type':'application/json','x-psn-store-locale-override':language+'-'+country})
    data=json.loads(page)
    if data.get('errors'):raise ValueError(str(data['errors'])[:150])
    return data['data']['universalSearch']['results']
def psn_metadata(game,url,page):
    if not url.startswith('https://store.playstation.com/pt-pt/'):raise ValueError('Portugal PSN URL required')
    product=ratings.psn_product(page,url)
    if not product or 'PS5' not in product.get('platforms',[]) or not any(matches_name(game,name) for name in [product.get('name',''),product.get('invariantName','')]):raise ValueError('Exact PS5 product identity not verified')
    if product.get('storeDisplayClassification') in ['ADD_ON','DEMO','TRIAL'] or product.get('topCategory')=='ADD_ON':raise ValueError('Not the full game')
    checked=now();result={'store':{'url':url,'label':'Abrir na PlayStation Store','checked':checked},'image':{'url':image_from_media(product.get('media')),'source':url,'checked':checked}}
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
    tried=set(candidates)
    for title in known_names(game)[:4]:
        for country,language in [('PT','pt'),('GB','en')]:
            try:results=psn_search(title,country,language)
            except Exception as exc:
                errors.append(str(exc)[:120]);continue
            for item in results:
                if not matches_name(game,item.get('name','')):continue
                if item.get('__typename')=='Product':
                    if 'PS5' not in (item.get('platforms') or []):continue
                    urls=['https://store.playstation.com/pt-pt/product/'+item['id']]
                else:
                    products=sorted(item.get('products') or [],key=lambda p:'PPSA' not in p['id'])
                    urls=['https://store.playstation.com/pt-pt/concept/'+item['id']]+['https://store.playstation.com/pt-pt/product/'+p['id'] for p in products[:8]]
                for url in urls:
                    if url in tried:continue
                    tried.add(url)
                    try:final,page=get(url);return psn_metadata(game,final,page)
                    except Exception as exc:errors.append(str(exc)[:120])
    raise ValueError('No exact Portugal PS5 product verified'+(': '+'; '.join(errors[:2]) if errors else ''))

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
    return canonical(doc.get('title','')) in {canonical(value) for value in known_names(game)+stores.NINTENDO_NAMES.get(game['title'],[])}

def resolve_nintendo(game,known_store):
    title=game['title'];errors=[]
    candidates=[known_store.get('url'),source_match(game).get('store_url')]
    if title in stores.NSO:candidates.append('https://www.nintendo.com/us/store/products/super-nintendo-entertainment-system-nintendo-switch-online-switch/')
    else:candidates.extend('https://www.nintendo.com/us/store/products/'+stores.NINTENDO_SLUGS.get(name,stores.slug(name))+'-switch/' for name in known_names(game)[:4])
    tried=set()
    for url in dict.fromkeys(candidate for candidate in candidates if candidate):
        tried.add(url)
        try:
            final,page=get(url)
            if not stores.official_url('Switch',final) or not stores.nintendo_match(page,title,known_names(game)):raise ValueError('Exact Nintendo Switch store identity not verified')
            store={'url':final,'label':'Abrir na Nintendo eShop','checked':now()}
            if title in stores.NSO:store.update(label='Ver no Nintendo Switch Online',note='Incluído na aplicação Super Nintendo do Nintendo Switch Online.')
            return {'store':store,'image':{'url':meta_image(page),'source':final,'checked':now()}}
        except Exception as exc:errors.append(str(exc)[:120])
    for name in known_names(game)[:4]:
        for language in ['pt','en']:
            params=urllib.parse.urlencode({'q':'"'+name.replace('"','')+'"','fq':'type:GAME AND system_type:nintendoswitch*','rows':100,'wt':'json'})
            try:
                _,page=get('https://searching.nintendo-europe.com/'+language+'/select?'+params)
                docs=json.loads(page)['response']['docs']
            except Exception as exc:errors.append(str(exc)[:120]);continue
            for doc in docs:
                if not nintendo_index_match(game,doc):continue
                candidate=urllib.parse.urljoin('https://www.nintendo.com',doc.get('url',''))
                if candidate in tried or not stores.official_url('Switch',candidate):continue
                tried.add(candidate)
                try:
                    final,page=get(candidate)
                    if not stores.official_url('Switch',final) or not stores.nintendo_match(page,title,known_names(game)+[doc['title']]):raise ValueError('Official product page does not match the indexed game')
                    checked=now();image=meta_image(page) or doc.get('image_url_sq_s')
                    return {'store':{'url':final,'label':'Abrir na Nintendo eShop','checked':checked},'image':{'url':image,'source':final,'checked':checked},'aliases':list(dict.fromkeys(game.get('aliases',[])+[doc['title']]))}
                except Exception as exc:errors.append(str(exc)[:120])
    raise ValueError('Official Nintendo lookup: '+'; '.join(errors[-2:]))

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
    cutoff=(dt.datetime.now(dt.timezone.utc)-dt.timedelta(days=7)).isoformat()
    if cached.get('updated','')>=cutoff:return
    try:
        _,page=get('https://www.nindiespotlight.com/sitemap.xml');index={}
        for value in re.findall(r'<loc>(.*?)</loc>',page):
            url=html.unescape(value);slug=urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get('game',[''])[0]
            if slug.endswith('-switch'):index.setdefault(identity(slug[:-7]),[]).append(url)
        if index:(ROOT/'data/nindie-index.json').write_text(json.dumps({'updated':now(),'source':'https://www.nindiespotlight.com/sitemap.xml','games':index},ensure_ascii=False,indent=2)+'\n')
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

def minimal_metacritic(game):
    platform='playstation-5' if game['platform']=='PS5' else 'nintendo-switch';expected='PlayStation 5' if game['platform']=='PS5' else 'Nintendo Switch';errors={}
    names=list(dict.fromkeys([ratings.MC_ALIASES.get(game['title'],ratings.slug(game['title']))]+[ratings.slug(name) for name in known_names(game) if name]))[:4]
    for name in names:
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
    params={'action':'query','generator':'search','gsrsearch':'"'+game['title'].replace('"','')+'" video game','gsrlimit':5,'prop':'pageimages|categories','piprop':'thumbnail','pithumbsize':500,'pilicense':'any','cllimit':50,'format':'json'}
    _,page=get('https://en.wikipedia.org/w/api.php?'+urllib.parse.urlencode(params))
    return wikipedia_image_data(json.loads(page),game)

def has_score(value):return isinstance(value.get('score'),(int,float)) and value.get('scale',0)>0 and 0<=value['score']<=value['scale']
def requirements(entry):
    rating=entry.get('ratings',{})
    return {'image':valid_image(entry.get('image',{}).get('url')),'store':bool(entry.get('store',{}).get('url')),'rating':any(has_score(rating.get(kind,{})) for kind in ['user','critic'])}

def share_artwork(games,entries):
    by_title={}
    for game in games:by_title.setdefault(game['title'],[]).append(game)
    for game in games:
        entry=entries.get(game['platform']+':'+game['id'],{})
        if valid_image(entry.get('image',{}).get('url')) or not game.get('synopsis'):continue
        candidates=[]
        for other in by_title[game['title']]:
            if other['platform']==game['platform'] or ' '.join(other.get('synopsis','').split())!=' '.join(game['synopsis'].split()):continue
            art=entries.get(other['platform']+':'+other['id'],{}).get('image',{})
            if valid_image(art.get('url')):candidates.append((other,art))
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

def basics(game,previous,legacy,known_store,old_composite,old_trailer,artwork):
    result=dict(previous or {});errors={};key=game['platform']+':'+game['id'];stamp=now()
    if old_trailer.get('id'):result.setdefault('trailer',old_trailer)
    match=source_match(game)
    if not result.get('image',{}).get('url') and match.get('image_url','').startswith('https://www.nintendo.com/'):
        result['image']={'url':match['image_url'],'source':match['source'],'checked':stamp,'method':'official-product-index'}
    if result.get('image') and not valid_image(result['image'].get('url')):result.pop('image')
    if valid_image(artwork.get('url')) and not result.get('image',{}).get('url'):result['image']=artwork
    source_game={**game,'aliases':result.get('aliases',[])+source_match(game).get('names',[])}
    current_store=result.get('store') or known_store
    try:metadata=resolve_psn(source_game,legacy,current_store) if game['platform']=='PS5' else resolve_nintendo(source_game,current_store);result.update({k:v for k,v in metadata.items() if k!='image' or v.get('url')})
    except Exception as exc:errors['store']=str(exc)[:200]
    source_game={**source_game,'aliases':list(dict.fromkeys(source_game['aliases']+result.get('aliases',[])))}
    critics=[];users=[]
    prior_ratings=result.get('ratings') or old_composite
    if has_score(prior_ratings.get('critic',{})):critics=list(prior_ratings['critic'].get('sources',[]))
    elif has_score(legacy.get('critic',{})):
        c=legacy['critic'];critics=[{'name':c.get('source','Metacritic'),'score':c['score'],'url':c['url'],'platform':game['platform']}]
    if has_score(prior_ratings.get('user',{})):users=[{**source,'checked':source.get('checked') or prior_ratings.get('attempted','')} for source in prior_ratings['user'].get('sources',[])]
    fresh=result.get('user')
    if fresh:
        users=[u for u in users if not u.get('name','').startswith('PSN')]+[fresh]
    elif game['platform']=='PS5' and has_score(legacy.get('user',{})):
        raw=legacy['user'];users.append({**raw,'name':raw.get('source','PSN'),'platform':raw.get('scope')})
    if not opaque_critic({'sources':critics}):critics.extend(curated_critics(game))
    if (not critics and not users) or not result.get('image',{}).get('url'):
        try:
            c,u,image=community({**source_game,'aliases':result.get('aliases',[])+source_match(game).get('names',[])});critics.extend(c);users.extend(u)
            if image.get('url') and not result.get('image',{}).get('url'):result['image']=image
        except Exception as exc:errors['community']=str(exc)[:200]
    if game['platform']=='Switch' and ((not critics and not users) or not result.get('store',{}).get('url') or not result.get('image',{}).get('url')):
        try:
            c,image,candidate=nindie(source_game);critics.extend(c)
            if image.get('url') and not result.get('image',{}).get('url'):result['image']=image
            if not result.get('store',{}).get('url'):
                try:result.update(resolve_nintendo(source_game,{'url':candidate}));errors.pop('store',None)
                except Exception as exc:errors['store']=str(exc)[:160]
        except Exception as exc:errors['nindie']=str(exc)[:160]
    if not critics and not users:
        c,u,failures=minimal_metacritic(source_game);critics.extend(c);users.extend(u);errors.update(failures)
    if game['platform']=='Switch' and not critics and not users:
        try:critics.append(slush_review(source_game))
        except Exception as exc:errors['slush']=str(exc)[:160]
    if not result.get('image',{}).get('url'):
        try:result['image']=wikipedia_image(source_game)
        except Exception as exc:errors['image']=str(exc)[:160]
    result['ratings']={'critic':composites.critic_composite(critics),'user':composites.user_composite(users),'attempted':stamp}
    for kind in ['critic','user']:
        prior=(previous or {}).get('ratings',{}).get(kind,{})
        if not has_score(result['ratings'][kind]) and has_score(prior):result['ratings'][kind]=prior
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
    if not chosen or chosen.get('kind')!='gameplay':
        url='https://www.playstation.com/en-us/games/'+ratings.PS_ALIASES.get(game['title'],ratings.slug(game['title']))+'/'
        try:
            _,page=get(url);chosen=trailers.choose_video(chosen,trailers.videos_from_official_page(page,game['title'],url))
        except Exception as exc:errors['trailer']=str(exc)[:160]
    if chosen:result['trailer']=chosen
    result.update(full_attempted=now(),full_version=VERSION,errors=errors);result['requirements']=requirements(result)
    return result

def export(entries,db):
    games=read('catalog.json')['games'];audit=[]
    db.executemany('INSERT OR REPLACE INTO enrichment VALUES(?,?)',[(key,json.dumps(value,ensure_ascii=False)) for key,value in entries.items()]);db.commit()
    for game in games:
        key=game['platform']+':'+game['id'];entry=entries.get(key,{});required=requirements(entry);missing=[k for k,v in required.items() if not v]
        if missing:audit.append({'key':key,'title':game['title'],'platform':game['platform'],'missing':missing,'attempted':entry.get('basics_attempted'),'reasons':entry.get('errors',{})})
    report={'total':len(games),'attempted':sum(bool(entries.get(g['platform']+':'+g['id'],{}).get('basics_attempted')) for g in games),'ready':len(games)-len(audit),'missing_image':sum('image' in e['missing'] for e in audit),'missing_store':sum('store' in e['missing'] for e in audit),'missing_rating':sum('rating' in e['missing'] for e in audit),'full_attempted':sum(bool(entries.get(g['platform']+':'+g['id'],{}).get('full_attempted')) for g in games)}
    (ROOT/'data/enrichment.json').write_text(json.dumps({'updated':now(),'version':VERSION,'coverage':report,'games':entries},ensure_ascii=False,indent=2)+'\n')
    (ROOT/'data/enrichment-audit.json').write_text(json.dumps({'updated':now(),'coverage':report,'entries':audit},ensure_ascii=False,indent=2)+'\n')
    print('COVERAGE',json.dumps(report),flush=True)

def lookup_upgrade(game,entry):
    return entry.get('version',0)<VERSION and not all(requirements(entry).values())

def select_work(games,entries,seen):
    unseen=[g for g in games if (g['platform']+':'+g['id'],'basics') not in seen and not entries.get(g['platform']+':'+g['id'],{}).get('basics_attempted')]
    if unseen:return 'basics',unseen
    # Finish every game's minimum data before spending requests on extra sources.
    cutoff=(dt.datetime.now(dt.timezone.utc)-dt.timedelta(days=1)).isoformat()
    retry=[g for g in games if (g['platform']+':'+g['id'],'basics') not in seen and not all(requirements(entries.get(g['platform']+':'+g['id'],{})).values()) and (lookup_upgrade(g,entries.get(g['platform']+':'+g['id'],{})) or entries.get(g['platform']+':'+g['id'],{}).get('basics_attempted','')<cutoff)]
    if retry:return 'basics',sorted(retry,key=lambda g:entries.get(g['platform']+':'+g['id'],{}).get('basics_attempted',''))
    full_cutoff=(dt.datetime.now(dt.timezone.utc)-dt.timedelta(days=7)).isoformat()
    full=[g for g in games if (g['platform']+':'+g['id'],'full') not in seen and (entries.get(g['platform']+':'+g['id'],{}).get('full_version',0)<VERSION or entries.get(g['platform']+':'+g['id'],{}).get('full_attempted','')<full_cutoff)]
    if full:return 'full',sorted(full,key=lambda g:(requirements(entries.get(g['platform']+':'+g['id'],{}))['rating'],entries.get(g['platform']+':'+g['id'],{}).get('full_attempted',''),g['title']))
    stale=[g for g in games if (g['platform']+':'+g['id'],'basics') not in seen and entries.get(g['platform']+':'+g['id'],{}).get('basics_attempted','')<cutoff]
    return 'basics',stale

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--minutes',type=float,default=50);ap.add_argument('--workers',type=int,default=4);ap.add_argument('--ids');ap.add_argument('--checkpoint-push',action='store_true');args=ap.parse_args()
    from scripts.apply_recoveries import apply_pending
    applied=apply_pending()
    if applied and args.checkpoint_push:subprocess.run(['bash','scripts/checkpoint-enrichment.sh'],cwd=ROOT,check=True)
    refresh_review_index()
    community_index.refresh(get)
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
        batch=queue[:max(10,args.workers)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures={}
            for game in batch:
                key=game['platform']+':'+game['id'];seen.add((key,phase))
                task=pool.submit(basics,game,entries.get(key,{}),legacy.get(key,{}),known_stores.get(key,{}),old_composites.get(key,{}),old_trailers.get(key,{}),artwork.get(game['title'],{})) if phase=='basics' else pool.submit(complete,game,entries.get(key,{}),legacy.get(key,{}),curated)
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
