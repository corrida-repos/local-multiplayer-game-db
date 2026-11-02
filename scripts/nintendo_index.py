"""Complete daily PT/English Nintendo product index joined by official fs_id."""
import datetime as dt,functools,json,re,urllib.parse
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
@functools.lru_cache(maxsize=1)
def load():
    path=ROOT/'data/nintendo-index.json'
    return json.loads(path.read_text()) if path.exists() else {'products':{}}
def native(doc):return any(re.match(r'^nintendoswitch(?:_|$)',system) for system in doc.get('system_type',[]))
def fetch_language(get,language):
    docs=[];start=0;total=None
    while total is None or start<total:
        params={'q':'*:*','fq':'type:GAME AND system_type:nintendoswitch*','rows':500,'start':start,'wt':'json','fl':'fs_id,title,url,system_type,nsuid_txt,image_url_sq_s','sort':'fs_id asc'}
        _,page=get('https://searching.nintendo-europe.com/'+language+'/select?'+urllib.parse.urlencode(params));response=json.loads(page)['response'];total=int(response['numFound']);part=response['docs']
        if not part and start<total:raise ValueError('Incomplete Nintendo index')
        docs.extend(doc for doc in part if native(doc));start+=len(part)
        if not total:break
    if not docs:raise ValueError('Empty Nintendo product index')
    if len({doc['fs_id'] for doc in docs})!=len(docs):raise ValueError('Duplicate product IDs in Nintendo pagination')
    return docs

def combine(pt,en):
    products={}
    for language,docs in [('pt',pt),('en',en)]:
        for doc in docs:
            if not native(doc):continue
            product=products.setdefault(str(doc['fs_id']),{'names':[],'nsuids':[]})
            product['names']=list(dict.fromkeys(product['names']+[doc['title']]))
            product['nsuids']=list(dict.fromkeys(product['nsuids']+doc.get('nsuid_txt',[])))
            if language=='pt':product['pt_url']=urllib.parse.urljoin('https://www.nintendo.com',doc['url']);product['pt_title']=doc['title']
            if doc.get('image_url_sq_s'):product['image_url']=doc['image_url_sq_s']
    return products

def refresh(get):
    cutoff=(dt.datetime.now(dt.timezone.utc)-dt.timedelta(days=1)).isoformat()
    if load().get('updated','')>=cutoff:return
    try:
        products=combine(fetch_language(get,'pt'),fetch_language(get,'en'))
        path=ROOT/'data/nintendo-index.json';path.write_text(json.dumps({'updated':dt.datetime.now(dt.timezone.utc).isoformat(),'products':products},ensure_ascii=False,separators=(',',':'))+'\n');load.cache_clear();titles.cache_clear()
        print('Nintendo native Switch products',len(products),flush=True)
    except Exception as exc:print('Nintendo index refresh retained previous cache:',str(exc)[:160],flush=True)

@functools.lru_cache(maxsize=1)
def titles():
    from scripts.stores import identity
    index={}
    for pid,product in load().get('products',{}).items():
        for name in product['names']:index.setdefault(identity(name),set()).add(pid)
    return index

def candidates(game,names,store_evidence):
    from scripts.stores import identity,portugal_url
    products=load().get('products',{});ids=set()
    for name in names:ids.update(titles().get(identity(name),set()))
    return [{**products[pid],'id':pid} for pid in sorted(ids) if portugal_url('Switch',products[pid].get('pt_url',''))]
