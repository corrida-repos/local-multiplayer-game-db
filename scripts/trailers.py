"""Prefer official gameplay videos; fall back to official trailers for the same game."""
import argparse,datetime as dt,json,re,sqlite3,time,urllib.request
from pathlib import Path
from scripts.stores import normal,slug
from scripts.ratings import PS_ALIASES
ROOT=Path(__file__).resolve().parents[1]
AGENT='SofaDuoCatalog/1.0 (+https://github.com/corrida-repos/local-multiplayer-game-db)'

def videos_from_official_page(page,title,url):
    videos=[]
    for content in re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',page,re.S|re.I):
        try:obj=json.loads(content)
        except ValueError:continue
        nodes=obj if isinstance(obj,list) else [obj]
        for video in nodes:
            if not isinstance(video,dict) or video.get('@type')!='VideoObject':continue
            name=video.get('name','');content_url=video.get('contentUrl','')
            if normal(title) not in normal(name):continue
            if re.search(r'behind.the.scenes|working.from.home|interview|dlc|costume|season.pass',name,re.I):continue
            match=re.search(r'(?:youtube\.com/watch\?v=|youtu\.be/)([\w-]{11})(?:[^\w-]|$)',content_url)
            if not match:continue
            if not re.search(r'trailer|gameplay|overview|announce|reveal',name,re.I):continue
            kind='gameplay' if re.search(r'gameplay|overview|jogabilidade',name,re.I) else 'trailer'
            videos.append({'id':match[1],'title':name,'kind':kind,'source':url})
    return sorted(videos,key=lambda v:(v['kind']!='gameplay','launch' not in v['title'].lower()))

def choose_video(curated,discovered):
    if curated and curated.get('kind')=='gameplay':return curated
    gameplay=next((v for v in discovered if v['kind']=='gameplay'),None)
    return gameplay or curated or next(iter(discovered),None)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--limit',type=int,default=60);args=parser.parse_args()
    games=json.loads((ROOT/'data/catalog.json').read_text(encoding='utf-8'))['games'];curated=json.loads((ROOT/'data/trailers-curated.json').read_text(encoding='utf-8'))
    path=ROOT/'data/trailers.json';data=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'games':{}};entries=data['games']
    queue=sorted(games,key=lambda g:entries.get(g['platform']+':'+g['id'],{}).get('attempted',''))
    db=sqlite3.connect(ROOT/'data/games.sqlite');db.execute('CREATE TABLE IF NOT EXISTS trailers(game_key TEXT PRIMARY KEY,payload TEXT NOT NULL)');cache={}
    for game in queue[:args.limit]:
        title=game['title'];key=game['platform']+':'+game['id']
        if title not in cache:
            selected=curated.get(title);error=None
            if not selected or selected.get('kind')!='gameplay':
                url='https://www.playstation.com/en-us/games/'+PS_ALIASES.get(title,slug(title))+'/'
                try:
                    time.sleep(1.1)
                    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':AGENT}),timeout=15) as response:page=response.read().decode()
                    selected=choose_video(selected,videos_from_official_page(page,title,url))
                except Exception as e:error=str(e)[:140]
            cache[title]=(selected,error)
        video,error=cache[title];entry=dict(entries.get(key,{}))
        if video:entry={**video,'url':'https://www.youtube.com/watch?v='+video['id'],'checked':dt.datetime.now(dt.timezone.utc).isoformat()}
        entry['attempted']=dt.datetime.now(dt.timezone.utc).isoformat();entry['error']=None if entry.get('id') else error or 'No official game trailer identified'
        entries[key]=entry;db.execute('INSERT OR REPLACE INTO trailers VALUES(?,?)',(key,json.dumps(entry,ensure_ascii=False)));db.commit()
        path.write_text(json.dumps({'updated':entry['attempted'],'games':entries},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(title,entry.get('kind'),entry.get('id'),flush=True)
    db.close()
if __name__=='__main__':main()
