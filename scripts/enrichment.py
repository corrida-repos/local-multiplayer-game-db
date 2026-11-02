"""Continuous per-game enrichment: all basics first, then composite scores and trailers.
Each result owns its provenance and missing-field reasons. No synthetic ratings.
"""
import argparse, concurrent.futures, datetime as dt, html, json, re, sqlite3, subprocess, threading, time, urllib.parse, urllib.request
from pathlib import Path
from scripts import composites, ratings, stores, trailers, psplus
ROOT=Path(__file__).resolve().parents[1]
VERSION=2
SEARCH_HASH='4df6284f982e57bec70f23c77e2c219dc792eb19af7fb3d3a81767aa3f1958aa'
locks={};last={};guard=threading.Lock()
def now():return dt.datetime.now(dt.timezone.utc).isoformat()
def get(url,headers=None):
    host=urllib.parse.urlparse(url).hostname
    with guard:lock=locks.setdefault(host,threading.Lock())
    with lock:
        time.sleep(max(0,1.1-(time.monotonic()-last.get(host,0))));last[host]=time.monotonic()
    request=urllib.request.Request(url,headers={'User-Agent':ratings.AGENT,**(headers or {})})
    with urllib.request.urlopen(request,timeout=18) as response:return response.geturl(),response.read().decode('utf-8')
def read(name,default=None):
    path=ROOT/'data'/name
    return json.loads(path.read_text()) if path.exists() else (default if default is not None else {'games':{}})
def identity(value):
    value=value.replace('&',' and ')
    value=re.sub(r'\bPlayStation[®™ ]*5\b','',value,flags=re.I)
    value=re.sub(r'\bPS4\s*(?:&|and|/|e|,)?\s*PS5\b|\bPS5\b|\bPS4\b','',value,flags=re.I)
    value=re.sub(r'\b(iii|ii|iv)\b',lambda m:{'ii':'2','iii':'3','iv':'4'}[m[1].lower()],value,flags=re.I)
    return stores.normal(value)
def matches_name(game,name):
    return bool(identity(name)) and identity(name) in {identity(game['title']),identity(ratings.MC_ALIASES.get(game['title'],''))}
def image_from_media(media):
    for role in ['MASTER','GAMEHUB_COVER_ART','PORTRAIT_BANNER','FOUR_BY_THREE_BANNER','SCREENSHOT']:
        for item in media or []:
            if item.get('type')=='IMAGE' and item.get('role')==role and item.get('url','').startswith('https://'):return item['url']
def psn_search(title):
    variables={'countryCode':'PT','languageCode':'pt','nextCursor':'','pageOffset':0,'pageSize':24,'searchTerm':title}
    extensions={'persistedQuery':{'version':1,'sha256Hash':SEARCH_HASH}}
    query=urllib.parse.urlencode({'operationName':'getSearchResults','variables':json.dumps(variables),'extensions':json.dumps(extensions)})
    _,page=get('https://web.np.playstation.com/api/graphql/v1//op?'+query,{'Accept':'application/json','Content-Type':'application/json','x-psn-store-locale-override':'pt-PT'})
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
    candidates=[];exact=stores.EXACT.get(('PS5',game['title']))
    if exact:candidates.append(exact)
    for candidate in [known_store.get('url'),legacy.get('user',{}).get('url')]:
        if candidate and candidate.startswith('https://store.playstation.com/pt-pt/') and candidate not in candidates:candidates.append(candidate)
    errors=[]
    for url in candidates:
        try:final,page=get(url);return psn_metadata(game,final,page)
        except Exception as exc:errors.append(str(exc)[:120])
    results=psn_search(game['title'])
    for item in results:
        if not matches_name(game,item.get('name','')):continue
        if item.get('__typename')=='Product':
            if 'PS5' not in item.get('platforms',[]):continue
            urls=['https://store.playstation.com/pt-pt/product/'+item['id']]
        else:
            products=sorted(item.get('products',[]),key=lambda p:'PPSA' not in p['id'])
            urls=['https://store.playstation.com/pt-pt/concept/'+item['id']]+['https://store.playstation.com/pt-pt/product/'+p['id'] for p in products[:8]]
        for url in urls:
            try:final,page=get(url);return psn_metadata(game,final,page)
            except Exception as exc:errors.append(str(exc)[:120])
    raise ValueError('No exact Portugal PS5 product verified'+(': '+'; '.join(errors[:2]) if errors else ''))

def meta_image(page):
    for tag in re.findall(r'<meta\b[^>]*>',page,re.I):
        if re.search(r'(?:property|name)=["\']og:image["\']',tag,re.I):
            match=re.search(r'content=["\']([^"\']+)',tag,re.I)
            if match and html.unescape(match[1]).startswith('https://'):return html.unescape(match[1])

def nintendo_index_match(game,doc):
    systems=doc.get('system_type',[])
    if not any(re.match(r'^nintendoswitch(?:_|$)',system) for system in systems):return False
    canonical=lambda value:identity(re.sub(r'^(?:Arcade Archives|ACA NEOGEO|SEGA AGES)\s+','',value,flags=re.I))
    return canonical(doc.get('title','')) in {canonical(value) for value in [game['title']]+stores.NINTENDO_NAMES.get(game['title'],[])}

def resolve_nintendo(game,known_store):
    title=game['title'];url=known_store.get('url') or 'https://www.nintendo.com/us/store/products/'+stores.NINTENDO_SLUGS.get(title,stores.slug(title))+'-switch/'
    if title in stores.NSO:url='https://www.nintendo.com/us/store/products/super-nintendo-entertainment-system-nintendo-switch-online-switch/'
    try:
        final,page=get(url)
        if not stores.official_url('Switch',final) or not stores.nintendo_match(page,title):raise ValueError('Exact Nintendo Switch store identity not verified')
        store={'url':final,'label':'Abrir na Nintendo eShop','checked':now()}
        if title in stores.NSO:store.update(label='Ver no Nintendo Switch Online',note='Incluído na aplicação Super Nintendo do Nintendo Switch Online.')
        return {'store':store,'image':{'url':meta_image(page),'source':final,'checked':now()}}
    except Exception as original_error:
        # Official European search supplies real product URLs instead of guessing slugs.
        for language in ['pt','en']:
            params=urllib.parse.urlencode({'q':'"'+title.replace('"','\\"')+'"','fq':'type:GAME AND system_type:nintendoswitch*','rows':24,'wt':'json'})
            try:
                _,page=get('https://searching.nintendo-europe.com/'+language+'/select?'+params)
                for doc in json.loads(page)['response']['docs']:
                    if not nintendo_index_match(game,doc):continue
                    candidate=urllib.parse.urljoin('https://www.nintendo.com',doc['url'])
                    if not stores.official_url('Switch',candidate):continue
                    final,page=get(candidate)
                    if not stores.official_url('Switch',final):continue
                    checked=now();image=meta_image(page) or doc.get('image_url_sq_s')
                    return {'store':{'url':final,'label':'Abrir na Nintendo eShop','checked':checked},'image':{'url':image,'source':final,'checked':checked}}
            except Exception:continue
        raise ValueError('Official Nintendo lookup: '+str(original_error)[:150])

def community(game):
    expected='PlayStation 5' if game['platform']=='PS5' else 'Nintendo Switch';name=ratings.MC_ALIASES.get(game['title'],ratings.slug(game['title'])).replace('-','_');domain='www.pushsquare.com' if game['platform']=='PS5' else 'www.nintendolife.com'
    folders=['ps5'] if game['platform']=='PS5' else ['nintendo-switch','switch-eshop']
    errors=[]
    for folder in folders:
        url=f'https://{domain}/games/{folder}/{name}'
        try:
            final,page=get(url);critics,users=composites.community_data(page,final,game,expected)
            return critics,users,{'url':meta_image(page),'source':final,'checked':now()}
        except Exception as exc:errors.append(str(exc)[:100])
    raise ValueError('; '.join(errors))

def nindie_data(page,url,game):
    parsed=urllib.parse.urlparse(url);game_slug=urllib.parse.parse_qs(parsed.query).get('game',[''])[0]
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

def nindie(game):
    name=stores.slug(game['title']);url='https://www.nindiespotlight.com/game_profile.cfm?game='+name+'-switch'
    final,page=get(url);return nindie_data(page,final,game)

def has_score(value):return isinstance(value.get('score'),(int,float)) and value.get('scale',0)>0 and 0<=value['score']<=value['scale']
def requirements(entry):
    rating=entry.get('ratings',{})
    return {'image':bool(entry.get('image',{}).get('url')),'store':bool(entry.get('store',{}).get('url')),'rating':any(has_score(rating.get(kind,{})) for kind in ['user','critic'])}

def seed(games,entries,legacy,known_stores,old_composites,old_trailers,artwork,old_plus):
    # Audit existing verified data too; unattempted enrichment is not missing data.
    for game in games:
        key=game['platform']+':'+game['id'];entry=entries.setdefault(key,{'title':game['title'],'platform':game['platform']})
        if artwork.get(game['title'],{}).get('url'):entry.setdefault('image',artwork[game['title']])
        if known_stores.get(key,{}).get('url'):entry.setdefault('store',known_stores[key])
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

def basics(game,previous,legacy,known_store,old_composite,old_trailer,artwork):
    result=dict(previous or {});errors={};key=game['platform']+':'+game['id'];stamp=now()
    if old_trailer.get('id'):result.setdefault('trailer',old_trailer)
    if artwork.get('url'):result.setdefault('image',artwork)
    try:metadata=resolve_psn(game,legacy,known_store) if game['platform']=='PS5' else resolve_nintendo(game,known_store);result.update({k:v for k,v in metadata.items() if k!='image' or v.get('url')})
    except Exception as exc:errors['store']=str(exc)[:200]
    critics=[];users=[]
    if has_score(old_composite.get('critic',{})):critics=old_composite['critic'].get('sources',[])
    elif has_score(legacy.get('critic',{})):
        c=legacy['critic'];critics=[{'name':c.get('source','Metacritic'),'score':c['score'],'url':c['url'],'platform':game['platform']}]
    if has_score(old_composite.get('user',{})):users=list(old_composite['user'].get('sources',[]))
    fresh=result.get('user')
    if fresh:
        users=[u for u in users if not u.get('name','').startswith('PSN')]+[fresh]
    elif game['platform']=='PS5' and has_score(legacy.get('user',{})):
        raw=legacy['user'];users.append({**raw,'name':raw.get('source','PSN'),'platform':raw.get('scope')})
    if (not critics and not users) or not result.get('image',{}).get('url'):
        try:
            c,u,image=community(game);critics.extend(c);users.extend(u)
            if image.get('url') and not result.get('image',{}).get('url'):result['image']=image
        except Exception as exc:errors['community']=str(exc)[:200]
    if game['platform']=='Switch' and ((not critics and not users) or not result.get('store',{}).get('url') or not result.get('image',{}).get('url')):
        try:
            c,image,candidate=nindie(game);critics.extend(c)
            if image.get('url') and not result.get('image',{}).get('url'):result['image']=image
            if not result.get('store',{}).get('url'):
                try:result.update(resolve_nintendo(game,{'url':candidate}));errors.pop('store',None)
                except Exception as exc:errors['store']=str(exc)[:160]
        except Exception as exc:errors['nindie']=str(exc)[:160]
    if not critics and not users:
        name=ratings.MC_ALIASES.get(game['title'],ratings.slug(game['title']));platform='playstation-5' if game['platform']=='PS5' else 'nintendo-switch'
        try:
            url=f'https://backend.metacritic.com/reviews/metacritic/user/games/{name}/platform/{platform}/stats/web';_,page=get(url);u=json.loads(page)['data']['item']
            if u.get('reviewCount',0)>=4 and u.get('score') is not None:users.append({'name':'Metacritic users','score':u['score'],'scale':10,'count':u['reviewCount'],'url':f'https://www.metacritic.com/game/{name}/user-reviews/?platform={platform}','platform':game['platform']})
        except Exception as exc:errors['metacritic_users']=str(exc)[:160]
        if not users:
            try:
                url=f'https://backend.metacritic.com/reviews/metacritic/critic/games/{name}/platform/{platform}/web?offset=0&limit=10&filterBySentiment=all&sort=score'
                _,page=get(url);index=json.loads(page)['data'];items=index['items']
                # One scored review is enough even when the aggregate is still TBD.
                # Only use this page if it is the complete index, never a top-score prefix.
                if 0<int(index['totalResults'])<=len(items):
                    expected='PlayStation 5' if game['platform']=='PS5' else 'Nintendo Switch'
                    critics.extend({'name':r['publicationName'],'score':r['score'],'url':r['url'],'platform':expected,'via':'Metacritic review index'} for r in items if r.get('platform')==expected)
            except Exception as exc:errors['metacritic_reviews']=str(exc)[:160]
        if not users and not critics:
            try:
                url=f'https://www.metacritic.com/game/{name}/';_,page=get(url);score=ratings.mc_critic(page,name,'PlayStation 5' if game['platform']=='PS5' else 'Nintendo Switch')
                if score is not None:critics.append({'name':'Metacritic aggregate','score':score,'url':url+'critic-reviews/?platform='+platform,'platform':game['platform']})
            except Exception as exc:errors['metacritic_critics']=str(exc)[:160]
    result['ratings']={'critic':composites.critic_composite(critics),'user':composites.user_composite(users),'attempted':stamp}
    for kind in ['critic','user']:
        prior=(previous or {}).get('ratings',{}).get(kind,{})
        if not has_score(result['ratings'][kind]) and has_score(prior):result['ratings'][kind]=prior
    result['requirements']=requirements(result);result.update(title=game['title'],platform=game['platform'],basics_attempted=stamp,version=VERSION,errors=errors)
    return result

def complete(game,previous,legacy,curated):
    result=dict(previous);errors=dict(result.get('errors',{}));raw=dict(legacy)
    if result.get('user'):raw['user']=result['user']
    try:
        composite=composites.collect(game,raw)
        for kind in ['critic','user']:
            if not has_score(composite.get(kind,{})) and has_score(result.get('ratings',{}).get(kind,{})):composite[kind]=result['ratings'][kind]
        if game['platform']=='Switch':
            try:
                c,_,_=nindie(game)
                # Never mix an opaque aggregate with potentially overlapping reviews.
                if composite['critic'].get('method')!='single-aggregate-fallback-incomplete-index':composite['critic']=composites.critic_composite(composite['critic'].get('sources',[])+c)
            except Exception as exc:errors['nindie']=str(exc)[:160]
        result['ratings']=composite
    except Exception as exc:errors['composites']=str(exc)[:160]
    chosen=curated.get(game['title']) or result.get('trailer')
    if not chosen or chosen.get('kind')!='gameplay':
        url='https://www.playstation.com/en-us/games/'+ratings.PS_ALIASES.get(game['title'],ratings.slug(game['title']))+'/'
        try:
            _,page=get(url);chosen=trailers.choose_video(chosen,trailers.videos_from_official_page(page,game['title'],url))
        except Exception as exc:errors['trailer']=str(exc)[:160]
    if chosen:result['trailer']=chosen
    result.update(full_attempted=now(),errors=errors);result['requirements']=requirements(result)
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

def select_work(games,entries,seen):
    unseen=[g for g in games if (g['platform']+':'+g['id'],'basics') not in seen and not entries.get(g['platform']+':'+g['id'],{}).get('basics_attempted')]
    if unseen:return 'basics',unseen
    # Finish every game's minimum data before spending requests on extra sources.
    cutoff=(dt.datetime.now(dt.timezone.utc)-dt.timedelta(days=1)).isoformat()
    retry=[g for g in games if (g['platform']+':'+g['id'],'basics') not in seen and not all(requirements(entries.get(g['platform']+':'+g['id'],{})).values()) and (entries.get(g['platform']+':'+g['id'],{}).get('version',0)<VERSION or entries.get(g['platform']+':'+g['id'],{}).get('basics_attempted','')<cutoff)]
    if retry:return 'basics',sorted(retry,key=lambda g:entries.get(g['platform']+':'+g['id'],{}).get('basics_attempted',''))
    full_cutoff=(dt.datetime.now(dt.timezone.utc)-dt.timedelta(days=7)).isoformat()
    full=[g for g in games if (g['platform']+':'+g['id'],'full') not in seen and entries.get(g['platform']+':'+g['id'],{}).get('full_attempted','')<full_cutoff]
    if full:return 'full',full
    stale=[g for g in games if (g['platform']+':'+g['id'],'basics') not in seen and entries.get(g['platform']+':'+g['id'],{}).get('basics_attempted','')<cutoff]
    return 'basics',stale

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--minutes',type=float,default=50);ap.add_argument('--workers',type=int,default=4);ap.add_argument('--ids');ap.add_argument('--checkpoint-push',action='store_true');args=ap.parse_args()
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
            db.close();subprocess.run(['bash','scripts/checkpoint-enrichment.sh'],cwd=ROOT,check=True);db=sqlite3.connect(ROOT/'data/enrichment.sqlite')
    export(entries,db);db.close()
if __name__=='__main__':main()
