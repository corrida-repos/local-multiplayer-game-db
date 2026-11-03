"""Durable per-field source attempts; unresolved fields never leave recovery."""
import datetime as dt,hashlib,json,urllib.error
VERSION=3  # 2: tiered title matching; 3: NSO app listings, PSN edition names, Metacritic search, catalog-reserved titles
POLICY='portugal-minimum-v1'
FIELDS=('image','store','rating')
def utc():return dt.datetime.now(dt.timezone.utc)
def stamp():return utc().isoformat()
def revision(game,aliases):
    return hashlib.sha256(json.dumps({'v':VERSION,'game':game['title'],'platform':game['platform'],'aliases':sorted(set(aliases))},sort_keys=True).encode()).hexdigest()[:16]
def due(entry,source,fields,revision,clock=None):
    clock=clock or utc()
    for field in fields:
        check=entry.get('field_status',{}).get(field,{}).get('sources',{}).get(source,{})
        if check.get('revision')!=revision:return True
        try:next_attempt=dt.datetime.fromisoformat(check['next_attempt'])
        except (KeyError,ValueError,TypeError):return True
        if next_attempt<=clock:return True
    return False

def classify(exc):
    if isinstance(exc,urllib.error.HTTPError):
        if exc.code in [403,429]:return 'blocked'
        if exc.code in [404,410]:return 'not_found'
        if exc.code in [408,500,502,503,504]:return 'retryable_error'
    if isinstance(exc,(urllib.error.URLError,TimeoutError,ConnectionError,OSError)):return 'retryable_error'
    text=str(exc).lower()
    if any(x in text for x in ['identity','different game','wrong console','not a switch','ambiguous','does not match']):return 'identity_rejected'
    # A self-redirect loop is a bot-protection challenge, not a missing page; never bypassed, retried later.
    if any(x in text for x in ['403','429','forbidden','infinite loop']):return 'blocked'
    if any(x in text for x in ['timed out','timeout','503','502','504']):return 'retryable_error'
    return 'not_found'

def record(entry,source,fields,revision,status,reason='',url=None,clock=None,exc=None):
    clock=clock or utc();delay=dt.timedelta(hours=1 if status=='retryable_error' else 24)
    if status=='verified':delay=dt.timedelta(days=7 if source=='image_health' else 1)
    if isinstance(exc,urllib.error.HTTPError) and exc.headers:
        import email.utils
        value=exc.headers.get('Retry-After','')
        try:delay=max(delay,dt.timedelta(seconds=float(value)))
        except ValueError:
            try:delay=max(delay,email.utils.parsedate_to_datetime(value)-clock)
            except (ValueError,TypeError):pass
    for field in fields:
        sources=entry.setdefault('field_status',{}).setdefault(field,{}).setdefault('sources',{})
        previous=sources.get(source,{})
        sources[source]={**previous,'status':status,'last_attempt':clock.isoformat(),'next_attempt':(clock+delay).isoformat(),'revision':revision,'reason':str(reason)[:500]}
        if url:sources[source]['url']=url
        if status=='verified':sources[source]['last_success']=clock.isoformat()

def next_due(entry,fields):
    dates=[check.get('next_attempt','') for field in fields for check in entry.get('field_status',{}).get(field,{}).get('sources',{}).values()]
    return min(dates,default='')
