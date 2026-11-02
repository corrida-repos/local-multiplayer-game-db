"""Console-specific composites, with per-publication deduplication and provenance."""
import argparse,datetime as dt,json,math,re,sqlite3,time,urllib.parse,urllib.request
from pathlib import Path
from scripts.ratings import MC_ALIASES,slug
ROOT=Path(__file__).resolve().parents[1]
VERSION=1
last={}
def get(url):
    host=urllib.parse.urlparse(url).hostname;time.sleep(max(0,1.1-(time.monotonic()-last.get(host,0))));last[host]=time.monotonic()
    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'TwoPlayerGamesFinder/1.0 (+https://github.com/corrida-repos/local-multiplayer-game-db)'}),timeout=18) as r:return r.geturl(),r.read().decode()
def walk(obj):
    if isinstance(obj,dict):
        yield obj
        for value in obj.values():yield from walk(value)
    elif isinstance(obj,list):
        for value in obj:yield from walk(value)
def outlet_key(url,name):
    host=(urllib.parse.urlparse(url).hostname or '').removeprefix('www.')
    return host or re.sub('[^a-z0-9]','',name.lower())
def critic_composite(reviews):
    unique={}
    for review in reviews:
        score=review.get('score');key=outlet_key(review.get('url',''),review['name'])
        if not isinstance(score,(int,float)) or not 0<=score<=100:continue
        if key not in unique or review.get('date','')>unique[key].get('date',''):unique[key]=review
    sources=sorted(unique.values(),key=lambda s:s['name'])
    return {'score':round(sum(s['score'] for s in sources)/len(sources),1) if sources else None,'scale':100,'sources':sources,'method':'equal-weight-unique-publications','source_count':len(sources)}
def user_composite(sources):
    valid=[]
    for source in sources:
        score,count,scale=source.get('score'),source.get('count'),source.get('scale')
        if not isinstance(score,(int,float)) or not isinstance(count,(int,float)) or count<=0 or not scale or not 0<=score<=scale:continue
        valid.append({**source,'weight':min(math.sqrt(count),math.sqrt(1000)),'normalized':score/scale*10})
    weight=sum(s['weight'] for s in valid)
    return {'score':round(sum(s['normalized']*s['weight'] for s in valid)/weight,2) if weight else None,'scale':10,'sources':valid,'source_count':len(valid),'method':'sqrt-votes-capped-at-1000-per-community'}
def community_data(page,url,game,expected):
    if urllib.parse.urlparse(url).path.split('/')[2] not in (['ps5'] if game['platform']=='PS5' else ['nintendo-switch','switch-eshop']):raise ValueError('Wrong console page')
    nodes=[]
    for text in re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',page,re.S|re.I):
        try:nodes.extend(walk(json.loads(text)))
        except ValueError:continue
    products=[n for n in nodes if n.get('@type')=='VideoGame' and n.get('gamePlatform')==expected]
    if not products:raise ValueError('Console-specific game identity unavailable')
    product=products[0];requested=MC_ALIASES.get(game['title'],slug(game['title'])).replace('-','')
    if slug(product.get('name','')).replace('-','')!=requested:raise ValueError('Different game/edition')
    name='Push Square' if game['platform']=='PS5' else 'Nintendo Life';users=[];critics=[]
    rating=product.get('aggregateRating') or {}
    if rating.get('ratingValue') is not None:users.append({'name':name,'score':float(rating['ratingValue']),'scale':float(rating.get('bestRating',10)),'count':int(rating.get('ratingCount',0)),'url':url,'platform':expected})
    for node in nodes:
        if node.get('@type')!='Review':continue
        item=node.get('itemReviewed',{});ref=item.get('@id') if isinstance(item,dict) else None
        if ref and ref!=product.get('@id'):continue
        rating=node.get('reviewRating') or {}
        if rating.get('ratingValue') is not None:critics.append({'name':name,'score':float(rating['ratingValue'])/float(rating.get('bestRating',10))*100,'url':node.get('url') or url,'platform':expected,'via':name})
    return critics,users

def collect(game,legacy):
    expected='PlayStation 5' if game['platform']=='PS5' else 'Nintendo Switch';platform='playstation-5' if game['platform']=='PS5' else 'nintendo-switch';name=MC_ALIASES.get(game['title'],slug(game['title']));critics=[];users=[];errors=[];complete=True;offset=0;total=None
    base='https://backend.metacritic.com/reviews/metacritic/'
    try:
        while total is None or offset<total:
            url=base+f'critic/games/{name}/platform/{platform}/web?offset={offset}&limit=10&filterBySentiment=all&sort=score'
            _,page=get(url);data=json.loads(page)['data'];total=int(data['totalResults']);items=data['items']
            if not items and offset<total:raise ValueError('Incomplete critic pagination')
            for r in items:
                if r.get('platform')!=expected:continue
                critics.append({'name':r['publicationName'],'score':r['score'],'url':r['url'],'date':r.get('date',''),'platform':expected,'via':'Metacritic review index'})
            offset+=len(items)
            if total==0:break
    except Exception as e:complete=False;errors.append('Metacritic critics: '+str(e)[:100])
    try:
        url=base+f'user/games/{name}/platform/{platform}/stats/web'
        _,page=get(url);data=json.loads(page)['data']['item']
        # Metacritic's unpublished averages are zero until four votes exist.
        if data.get('reviewCount',0)>=4 and data.get('score') is not None:users.append({'name':'Metacritic users','score':data['score'],'scale':10,'count':data['reviewCount'],'url':f'https://www.metacritic.com/game/{name}/user-reviews/?platform={platform}','platform':expected})
    except Exception as e:errors.append('Metacritic users: '+str(e)[:100])
    domain='www.pushsquare.com' if game['platform']=='PS5' else 'www.nintendolife.com'
    folders=['ps5'] if game['platform']=='PS5' else ['nintendo-switch','switch-eshop']
    for folder in folders:
        url=f'https://{domain}/games/{folder}/'+name.replace('-','_')
        try:
            final,page=get(url);c,u=community_data(page,final,game,expected);critics.extend(c);users.extend(u);break
        except Exception as e:errors.append(domain+'/'+folder+': '+str(e)[:100])
    raw=legacy.get('user') or {}
    if game['platform']=='PS5' and raw.get('source')=='PSN':users.append({'name':'PSN'+(' (PS4/PS5 shared product)' if 'PS4/PS5' in raw.get('scope','') else ''),'score':raw.get('score'),'scale':raw.get('scale'),'count':raw.get('count'),'url':raw.get('url'),'platform':expected})
    result=critic_composite(critics) if complete else critic_composite([])
    if not complete:
        # Never average just the top-scoring first page or double-count an aggregate.
        raw=legacy.get('critic') or {}
        if raw.get('score') is not None:result=critic_composite([{'name':'Metacritic aggregate (fallback)','score':raw['score'],'url':raw['url'],'platform':expected}]);result['method']='single-aggregate-fallback-incomplete-index'
        elif critics:result=critic_composite([c for c in critics if c.get('via')!='Metacritic review index'])
    return {'critic':result,'user':user_composite(users),'critic_index_complete':complete,'critic_index_review_count':total,'errors':errors,'platform':expected,'algorithm_version':VERSION,'attempted':dt.datetime.now(dt.timezone.utc).isoformat()}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--limit',type=int,default=60);ap.add_argument('--ids');ap.add_argument('--checkpoint-push',action='store_true');ap.add_argument('--minutes',type=int,default=170);args=ap.parse_args();started=time.monotonic()
    path=ROOT/'data/composites.json';output=json.loads(path.read_text()) if path.exists() else {'games':{}};entries=output['games'];games=json.loads((ROOT/'data/catalog.json').read_text())['games'];legacy=json.loads((ROOT/'data/ratings.json').read_text())['games']
    queue=sorted(games,key=lambda g:entries.get(g['platform']+':'+g['id'],{}).get('attempted',''))
    if args.ids:queue=[g for g in queue if g['platform']+':'+g['id'] in args.ids.split(',')]
    db=sqlite3.connect(ROOT/'data/composites.sqlite');db.execute('CREATE TABLE IF NOT EXISTS scores(game_key TEXT PRIMARY KEY,payload TEXT NOT NULL)')
    for index,g in enumerate(queue[:args.limit]):
        if time.monotonic()-started>args.minutes*60:break
        key=g['platform']+':'+g['id'];entries[key]=collect(g,legacy.get(key,{}));db.execute('INSERT OR REPLACE INTO scores VALUES(?,?)',(key,json.dumps(entries[key],ensure_ascii=False)));db.commit()
        output={'updated':dt.datetime.now(dt.timezone.utc).isoformat(),'algorithm_version':VERSION,'games':entries};path.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n');print(g['title'],g['platform'],entries[key]['critic']['score'],entries[key]['critic']['source_count'],entries[key]['user']['score'],entries[key]['user']['source_count'],flush=True)
        if args.checkpoint_push and ((index+1)%10==0 or index+1==len(queue[:args.limit])):
            import subprocess
            db.close();subprocess.run(['bash','scripts/checkpoint-composites.sh'],cwd=ROOT,check=True);db=sqlite3.connect(ROOT/'data/composites.sqlite')
    db.close()
if __name__=='__main__':main()
