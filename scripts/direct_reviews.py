"""Public console-specific critic archives with resumable discovery."""
import datetime as dt,functools,html,json,re,urllib.parse,xml.etree.ElementTree as ET
from pathlib import Path
from scripts import stores
ROOT=Path(__file__).resolve().parents[1]
SOURCES={'nwr':{'name':'Nintendo World Report','host':'www.nintendoworldreport.com','platform':'Switch','delay':1.1},'pure':{'name':'Pure Nintendo','host':'purenintendo.com','platform':'Switch','delay':10},'psu':{'name':'PlayStation Universe','host':'www.psu.com','platform':'PS5','delay':5}}
def for_platform(platform):return [source for source,config in SOURCES.items() if config['platform']==platform]
def clean(text):return ' '.join(html.unescape(re.sub('<[^>]+>',' ',text)).split())
def review_title(source,url):
    parsed=urllib.parse.urlparse(url);config=SOURCES[source]
    if parsed.scheme!='https' or parsed.hostname!=config['host']:return None
    slug=parsed.path.rstrip('/').split('/')[-1]
    if source=='nwr':
        if not re.match(r'^/review/\d+/',parsed.path):return None
        match=re.fullmatch(r'(.+)-switch(?:-review(?:-mini)?)?',slug)
    elif source=='pure':match=re.fullmatch(r'review-(.+?)-(?:nintendo-)?switch',slug)
    else:
        if not parsed.path.startswith('/reviews/'):return None
        match=re.match(r'(.+?)-(?:review-ps5|ps5-review)(?:-|$)',slug)
    return match[1].replace('-',' ') if match else None

def data(page,url,game,source):
    config=SOURCES[source];slug_title=review_title(source,url)
    if config['platform']!=game['platform'] or not slug_title:raise ValueError('Wrong console review URL')
    title=re.search(r'<title[^>]*>(.*?)</title>',page,re.S|re.I)
    if not title:raise ValueError('Review title missing')
    title=clean(title[1])
    if source=='psu':match=re.match(r'(.+?)\s+(?:Review\s*\(PS5\)|\(PS5\)\s*Review|PS5\s+Review)(?:\s*[-–|].*)?$',title,re.I)
    elif source=='pure':match=re.fullmatch(r'Review:\s*(.+?)\s*\((?:Nintendo\s+)?Switch\)(?:\s*[-–|].*)?',title,re.I)
    else:match=re.fullmatch(r'(.+?)\s+Review\s*[-–]\s*Review\s*[-–]\s*Nintendo World Report',title,re.I)
    names={stores.identity(name) for name in [game['title']]+game.get('aliases',[]) if name}
    if not match or stores.identity(match[1]) not in names:raise ValueError('Different game or console in review heading')
    raw=scale=None
    if source=='psu':
        def walk(value):
            if isinstance(value,dict):
                yield value
                for item in value.values():yield from walk(item)
            elif isinstance(value,list):
                for item in value:yield from walk(item)
        for text in re.findall(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',page,re.S|re.I):
            try:nodes=walk(json.loads(text))
            except ValueError:continue
            for node in nodes:
                if node.get('@type')=='Review' and stores.identity(node.get('name','')) in names:
                    rating=node.get('reviewRating') or {};raw=rating.get('ratingValue');scale=rating.get('bestRating')
    elif source=='pure':
        panel=re.search(r'itemprop=["\']reviewRating["\'](.{0,2000}?)itemprop=["\']bestRating["\'][^>]*content=["\']([0-9.]+)',page,re.S|re.I)
        if panel:
            rating=re.search(r'itemprop=["\']ratingValue["\'][^>]*>\s*([0-9.]+)',panel[1],re.I)
            if rating:raw=rating[1];scale=panel[2]
    else:
        panel=re.search(r'<div[^>]*id=["\']article["\'][^>]*>\s*<div class=["\']score["\']>\s*<div class=["\']sc[0-9.]+["\']>\s*([0-9.]+)\s*</div>',page,re.S|re.I)
        if panel:raw=panel[1];scale=10
    try:raw=float(raw);scale=float(scale)
    except (TypeError,ValueError):raise ValueError('No published overall review score')
    if not 0<=raw<=scale or scale<=0:raise ValueError('Invalid review score scale')
    return {'name':config['name'],'score':raw/scale*100,'url':url,'platform':'PlayStation 5' if game['platform']=='PS5' else 'Nintendo Switch','original_score':raw,'original_scale':scale,'via':'Direct console-specific review'}

@functools.lru_cache(maxsize=1)
def load():
    path=ROOT/'data/direct-review-index.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'sources':{}}
def xml_entries(page):
    root=ET.fromstring(page);entries=[]
    for item in root:
        fields={child.tag.rsplit('}',1)[-1]:(child.text or '').strip() for child in item}
        if fields.get('loc'):entries.append(fields)
    return root.tag.rsplit('}',1)[-1],entries

def refresh(get,max_pages=12):
    cache=load();cutoff=(dt.datetime.now(dt.timezone.utc)-dt.timedelta(days=1)).isoformat();budget=max_pages
    for source,config in SOURCES.items():
        state=cache.setdefault('sources',{}).setdefault(source,{'games':{},'pending':[],'fetched':{}})
        try:
            if state.get('updated','')<cutoff:
                if source=='nwr':
                    state['pending']=list(dict.fromkeys(state['pending']+['https://'+config['host']+'/review/?system=Switch']+['https://'+config['host']+'/review/?'+urllib.parse.urlencode({'system':'Switch','letter':letter}) for letter in '_ABCDEFGHIJKLMNOPQRSTUVWXYZ']))
                else:
                    _,page=get('https://'+config['host']+'/sitemap_index.xml');_,children=xml_entries(page)
                    for item in sorted(children,key=lambda item:item.get('lastmod',''),reverse=True):
                        url=item['loc'];parsed=urllib.parse.urlparse(url)
                        if parsed.hostname==config['host'] and re.fullmatch(r'/(?:post|psu_review)-sitemap\d*\.xml',parsed.path) and state['fetched'].get(url)!=item.get('lastmod',cutoff):
                            if url not in state['pending']:state['pending'].append(url)
                            state.setdefault('versions',{})[url]=item.get('lastmod',cutoff)
                state['updated']=dt.datetime.now(dt.timezone.utc).isoformat()
            for _ in range(min(4,len(state['pending']),budget)):
                url=state['pending'][0];_,page=get(url)
                if source=='nwr':urls=[urllib.parse.urljoin(url,html.unescape(link)) for link in re.findall(r'href=["\']([^"\']+)',page)]
                else:_,items=xml_entries(page);urls=[item['loc'] for item in items]
                for candidate in urls:
                    title=review_title(source,candidate)
                    if title:
                        key=stores.identity(title);known=state['games'].setdefault(key,[])
                        if candidate not in known:known.append(candidate)
                state['pending'].pop(0);state['fetched'][url]=state.get('versions',{}).get(url,state['updated']);budget-=1
            state['complete']=not state['pending'];state.pop('error',None)
        except Exception as exc:state['error']=str(exc)[:250];state['complete']=False
    (ROOT/'data/direct-review-index.json').write_text(json.dumps(cache,ensure_ascii=False,separators=(',',':'))+'\n',encoding='utf-8');load.cache_clear()

def collect(game,source,get):
    state=load().get('sources',{}).get(source,{});urls=[]
    for name in [game['title']]+game.get('aliases',[]):urls.extend(state.get('games',{}).get(stores.identity(name),[]))
    errors=[]
    for url in dict.fromkeys(urls):
        try:final,page=get(url);return data(page,final,game,source)
        except Exception as exc:errors.append(str(exc))
    if errors:raise ValueError('; '.join(errors[:2]))
    if state.get('error'):raise OSError('Review index unavailable: '+state['error'])
    if not state.get('complete'):raise OSError('Review archive discovery still queued; exact profile not indexed yet')
    raise ValueError('No exact console review indexed')
