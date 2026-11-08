"""Screenshots and a guaranteed trailer for every game.

Screenshots: the game's own Portugal store page (PlayStation Store / Nintendo PT),
then Steam for multiplatform games. Trailer: the official trailer already chosen by
the enrichment pipeline, otherwise the best matching YouTube search result.
"""
import html,json,re,urllib.parse
from scripts.stores import normal
MAX_SHOTS=8
STEAM_HOSTS=('shared.akamai.steamstatic.com','cdn.akamai.steamstatic.com','shared.fastly.steamstatic.com','cdn.cloudflare.steamstatic.com')
YOUTUBE_SEARCH='https://www.youtube.com/results?search_query='
YOUTUBE_HEADERS={'Accept-Language':'en-GB,en;q=0.8','Cookie':'CONSENT=YES+cb; SOCS=CAI'}
REJECT=re.compile(r'\b(review|reaction|reacts?|walkthrough|let.?s play|playthrough|longplay|part \d|episode|ep\.? ?\d|mods?|fan.?made|fanmade|concept|comparison|vs\.?|versus|speedrun|tier list|tips|guide|tutorial|ending|boss|livestream|stream|unboxing|music|soundtrack|ost|theme song|dlc|expansion|season pass|costume|pack|interview|developer diary|behind the scenes|ranking|top \d+|meme|parody|shorts?|cutscenes?|movie|film|first \d+ minutes|minutes of|hours?)\b',re.I)
WANT=re.compile(r'trailer|gameplay|announce|reveal|launch|overview|teaser',re.I)

def _dedupe(urls,key=lambda u:u):
    seen=set();out=[]
    for url in urls:
        k=key(url)
        if url and k not in seen:seen.add(k);out.append(url)
    return out

def psn_screenshots(page,url):
    from scripts.ratings import psn_cache,psn_product
    cache=psn_cache(page);product=psn_product(page,url) or {}
    media=list(product.get('media') or [])
    concept=(product.get('concept') or {}).get('__ref')
    if concept:media+=cache.get(concept,{}).get('media') or []
    shots=[m.get('url','') for m in media if m.get('type')=='IMAGE' and m.get('role')=='SCREENSHOT']
    shots=[u for u in shots if urllib.parse.urlparse(u).hostname=='image.api.playstation.com']
    return [{'url':u,'source':'PlayStation Store'} for u in _dedupe(shots)[:MAX_SHOTS]]

def nintendo_gallery(page):
    items=[]
    for block in re.findall(r'_gItems\.push\(\{(.*?)\}\);',html.unescape(page),re.S):
        items.append({k:(quoted if quoted or not bare else bare) for k,quoted,bare in re.findall(r"'(\w+)'\s*:\s*(?:'([^']*)'|(\w+))",block)})
    return items

def nintendo_screenshots(page):
    shots=[item.get('image_url','') for item in nintendo_gallery(page) if item.get('isVideo')!='true']
    shots=[u for u in shots if re.fullmatch(r'https://www\.nintendo\.com/eu/media/images/\S+\.(?:jpg|jpeg|png|webp)',u,re.I)]
    return [{'url':u,'source':'Nintendo'} for u in _dedupe(shots)[:MAX_SHOTS]]

def nintendo_video(page,title,url):
    for item in nintendo_gallery(page):
        if item.get('isVideo')=='true' and item.get('type','').lower()=='youtube' and re.fullmatch(r'[\w-]{11}',item.get('video_id','')):
            return {'id':item['video_id'],'title':item.get('title') or title+' – trailer','kind':'trailer','source':url}
    return None

def name_variants(names):
    """Exact names plus the same name without a trailing edition label."""
    out=[]
    for name in names:
        out.append(name)
        trimmed=re.sub(r'[\s:\-–]+(?:XXL|HD|Remastered|Deluxe|Complete|Definitive|Ultimate|Anniversary|Enhanced|Special|Gold|GOTY|Game of the Year|Digital|Standard|Collector.?s|Nintendo Switch|Switch|PS5)(?:\s+(?:Edition|Version|Collection))?$','',name,flags=re.I).strip()
        if trimmed!=name and len(normal(trimmed))>=6:out.append(trimmed)
    return list(dict.fromkeys(out))

def steam_screenshots(game,names,get):
    """Exact-name Steam match only; Steam is a fallback picture source, never identity."""
    wanted={normal(name) for name in names if normal(name)}
    for name in names[:2]:
        _,body=get('https://store.steampowered.com/api/storesearch/?cc=pt&l=english&term='+urllib.parse.quote(name))
        items=json.loads(body).get('items') or []
        match=next((item for item in items if item.get('type')=='app' and normal(item.get('name',''))in wanted),None)
        if not match:continue
        _,body=get('https://store.steampowered.com/api/appdetails?cc=pt&filters=screenshots&appids=%d'%int(match['id']))
        data=(json.loads(body).get(str(match['id'])) or {}).get('data') or {}
        shots=[s.get('path_full','') for s in data.get('screenshots') or []]
        shots=[u for u in shots if urllib.parse.urlparse(u).hostname in STEAM_HOSTS]
        if shots:return [{'url':u,'source':'Steam','app':int(match['id'])} for u in shots[:MAX_SHOTS]]
    return []

def _text(node):
    if not isinstance(node,dict):return ''
    return node.get('simpleText') or ''.join(run.get('text','') for run in node.get('runs') or [])

def _video_renderers(node):
    stack=[node]
    while stack:
        cur=stack.pop()
        if isinstance(cur,dict):
            if isinstance(cur.get('videoRenderer'),dict):yield cur['videoRenderer']
            stack.extend(reversed(list(cur.values())))
        elif isinstance(cur,list):stack.extend(reversed(cur))

def youtube_results(page):
    match=re.search(r'(?:var ytInitialData|window\["ytInitialData"\])\s*=\s*',page)
    if not match:raise ValueError('YouTube results unavailable')
    try:data,_=json.JSONDecoder().raw_decode(page,match.end())
    except ValueError as exc:raise ValueError('YouTube results unreadable') from exc
    results=[]
    for video in _video_renderers(data):
        vid=video.get('videoId','')
        if not re.fullmatch(r'[\w-]{11}',vid):continue
        badges=json.dumps(video.get('ownerBadges') or [])
        results.append({'id':vid,'title':_text(video.get('title')),'channel':_text(video.get('ownerText')),'length':_text(video.get('lengthText')),'verified':'VERIFIED' in badges})
    return results

def _seconds(length):
    total=0
    for part in length.split(':'):
        if not part.isdigit():return 0
        total=total*60+int(part)
    return total

def name_parts(names):
    """The subtitle after a ' - ' or ':' separator, for titles shortened in video names.
    The part before it is usually a franchise name shared by other games, so it is never used alone."""
    parts=[]
    for name in names:
        piece=re.split(r'\s+[-–]\s+|:\s+',name)[-1].strip()
        if piece!=name and len(normal(piece))>=8 and len(piece.split())>=2:parts.append(piece)
    return [p for p in dict.fromkeys(parts) if p not in names]

NEUTRAL=re.compile(r"(?:official|launch|release|announce\w*|reveal|gameplay|trailer|teaser|overview|nintendo|switch|ps[45]|playstation|xbox|steam|pc|now|out|available|coming|new|the|game|video|demo|story|accolades|first|look|full|cinematic|early|access|release|date|is|arrives|coming|in|on|for|at|and|with|by|from|to|world|premiere|english|japanese|jp|us|eu|uk|4k|60fps|1080p|hd|trailers?|ps|ns|nsw|sw|ps5|ps4|xb1|xsx|official\w*|lançamento|launches|launching|gamescom|e3|showcase|direct|indie|world|partner|reveals?|announces?|announcement|official|teasers?|update|version|edition|day|one|deluxe|remastered|definitive|complete|ultimate|anniversary|enhanced|goty)",re.I)

def _other_subtitle(name,title):
    """'Ninja Gaiden: Ragebound' is another game when the catalogue name is 'Ninja Gaiden'."""
    words=re.findall(r'[^\W_]+',name)
    if not words:return False
    match=re.search(r'\W*'.join(map(re.escape,words)),title,re.I)
    if not match:return False
    rest=re.match(r'[\s:\-–|.,!()\[\]*"\']*([^\W_]+)',title[match.end():])
    return bool(rest) and not NEUTRAL.fullmatch(rest[1])

def choose_youtube(names,results,strict=True,match_names=None):
    match_names=match_names or names
    wanted=[normal(name) for name in match_names if len(normal(name))>=3]
    own=[normal(name) for name in names+match_names]
    ranked=[]
    for i,video in enumerate(results):
        title=video['title'];flat=normal(title);secs=_seconds(video['length'])
        hit=next((flat.index(name)+len(name) for name in wanted if name in flat),None)
        if hit is None or (strict and not WANT.search(title)):continue
        # A rejected word only counts when it is not part of the game's own name (e.g. 'Party Pack').
        if any(not any(normal(m.group()) in name for name in own) for m in REJECT.finditer(title)):continue
        # 'Game 2' / 'Game II' is a sequel unless the catalogue name already carries it.
        if flat[hit:hit+1].isdigit():continue
        roman=set(re.findall(r'\b(II|III|IV|V|VI)\b',title))-{w for name in names for w in re.findall(r'\b(II|III|IV|V|VI)\b',name)}
        if roman:continue
        if any(_other_subtitle(name,title) for name in match_names):continue
        if not 20<=secs<=600:continue
        official=video['verified'] or bool(re.search(r'playstation|nintendo|xbox|ign|gamespot|gametrailers|trailer',video['channel'],re.I)) or len(normal(video['channel']))>=4 and normal(video['channel']) in flat
        kind='gameplay' if re.search(r'gameplay|overview',title,re.I) else 'trailer' if WANT.search(title) else 'video'
        ranked.append(((not official,kind=='video',kind!='gameplay' and 'launch' not in title.lower(),i),video,kind))
    if not ranked:return None
    _,video,kind=min(ranked,key=lambda r:r[0])
    return {'id':video['id'],'title':video['title'],'kind':kind,'channel':video['channel'],'source':'YouTube search','url':'https://www.youtube.com/watch?v='+video['id']}

def youtube_trailer(game,names,get):
    names=name_variants(names);parts=name_parts(names)
    platform='Nintendo Switch' if game['platform']=='Switch' else 'PS5'
    pages=[]
    for query in [names[0]+' '+platform+' trailer',names[0]+' trailer']:
        for attempt in range(2):
            _,page=get(YOUTUBE_SEARCH+urllib.parse.quote(query),YOUTUBE_HEADERS)
            try:results=youtube_results(page);break
            except ValueError:
                if attempt:raise
        pages.append((query,results))
        video=choose_youtube(names,results)
        if video:return {**video,'query':query}
    # Looser tiers, best first: a shortened official title, then any short clip of the exact game.
    for strict,match in [(True,parts),(False,names)]:
        if not match:continue
        for query,results in pages:
            video=choose_youtube(names,results,strict,match)
            if video:return {**video,'query':query,'match':'partial-title' if match is parts else 'any-clip'}
    raise ValueError('No matching trailer in YouTube results for: '+' | '.join(q for q,_ in pages))
