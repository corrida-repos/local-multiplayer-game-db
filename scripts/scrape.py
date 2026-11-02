"""Incremental, rate-limited local co-op catalogue. Python standard library only."""
import argparse, datetime as dt, html, json, re, sqlite3, time, urllib.request, urllib.robotparser
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
BASE = 'https://www.co-optimus.com'
AGENT = 'SofaDuoCatalog/1.0 (+https://github.com/corrida-repos/local-multiplayer-game-db)'
last_request = 0
robots = None

def fetch(url):
    global last_request
    if robots and not robots.can_fetch(AGENT, url):
        raise ValueError('robots.txt disallows ' + url)
    time.sleep(max(0, 1.1 - (time.monotonic()-last_request)))
    last_request = time.monotonic()
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': AGENT}), timeout=40) as r:
                return r.read().decode('utf-8')
        except Exception:
            if attempt == 2: raise
            time.sleep(2 ** (attempt+1))

def clean(s):
    return html.unescape(re.sub('<[^>]+>', ' ', s)).strip()

def description_section(page, section_id, max_length=900):
    match=re.search(r'<div[^>]+id=["\']'+re.escape(section_id)+r'["\'][^>]*>(.*?)</div>',page,re.S|re.I)
    if not match:return None
    body=re.sub(r'<h[1-6][^>]*>.*?</h[1-6]>|<script[^>]*>.*?</script>','',match[1],flags=re.S|re.I)
    text=' '.join(clean(body).split())
    if not text:return None
    return text if len(text)<=max_length else text[:max_length].rsplit(' ',1)[0]+'…'

def ensure_detail_columns(db):
    columns={row[1] for row in db.execute('PRAGMA table_info(games)')}
    for column in ('synopsis','coop_description'):
        if column not in columns:db.execute('ALTER TABLE games ADD COLUMN '+column+' TEXT')
    db.commit()

def parse_game(page, url, today=None):
    platform = 'PS5' if '/playstation-5/' in url else 'Switch' if '/nintendo-switch/' in url else None
    if not platform: raise ValueError('Unsupported platform')
    title = re.search(r'<h1>\s*([^<]+)</h1>', page)
    local = re.search(r'<dt>Local Co-Op</dt>\s*<dd[^>]*>(.*?)</dd>', page, re.S)
    if not title or not local: raise ValueError('Unrecognized game page')
    count = re.search(r'(\d+)\s+Players?', clean(local[1]))
    if not count or int(count[1]) < 2: return None
    released = re.search(r'class="released">([^<]+)', page)
    if not released: return None
    try: date = dt.datetime.strptime(released[1].strip(), '%m/%d/%Y').date()
    except ValueError: return None
    if date > (today or dt.date.today()): return None
    genre = re.search(r'<strong>Genre:</strong>(.*?)</li>', page, re.S)
    return {'id': re.search(r'/game/(\d+)/',url)[1], 'title': clean(title[1]), 'platform': platform,
            'players': int(count[1]), 'mode': 'Cooperação', 'genre': clean(genre[1]) if genre else 'Outros',
            'release': date.isoformat(), 'url': url, 'source': 'Co-Optimus', 'synopsis': description_section(page,'description'), 'coop_description': description_section(page,'coop-exp',600), 'checked': dt.datetime.now(dt.timezone.utc).isoformat()}

def main():
    global robots
    ap=argparse.ArgumentParser(); ap.add_argument('--limit',type=int,default=300); args=ap.parse_args()
    (ROOT/'data').mkdir(exist_ok=True)
    db=sqlite3.connect(ROOT/'data/games.sqlite'); db.row_factory=sqlite3.Row
    db.executescript('''CREATE TABLE IF NOT EXISTS pages(url TEXT PRIMARY KEY, checked TEXT, error TEXT);
    CREATE TABLE IF NOT EXISTS games(id TEXT PRIMARY KEY,title TEXT,platform TEXT,players INTEGER CHECK(players>=2),mode TEXT,genre TEXT,release TEXT,url TEXT,source TEXT,checked TEXT);''')
    ensure_detail_columns(db)
    rules=fetch(BASE+'/robots.txt'); robots=urllib.robotparser.RobotFileParser(); robots.parse(rules.splitlines())
    maps=re.findall(r'<loc>(.*?)</loc>',fetch(BASE+'/sitemaps/siteMapGames_index.xml'))
    urls=[]
    for m in maps:
        urls += [u.replace('http:','https:') for u in re.findall(r'<loc>(.*?)</loc>',fetch(m)) if '/playstation-5/' in u or '/nintendo-switch/' in u]
    if len(urls)<100: raise RuntimeError('Discovery unexpectedly small; preserving previous catalogue')
    db.executemany('INSERT OR IGNORE INTO pages(url) VALUES(?)', [(u,) for u in urls]); db.commit()
    priorities=['it-takes-two','split-fiction','overcooked','unravel-two','sackboy','moving-out','stardew-valley','luigi','kirby','super-mario','teenage-mutant','cuphead','unrailed','rayman','lego','trine','untitled-goose','cat-quest','lovers-in-a-dangerous','tools-up']
    candidates=[dict(r) for r in db.execute('SELECT * FROM pages') if r['url'] in set(urls)]
    candidates.sort(key=lambda r:(r['checked'] is not None, r['checked'] or '', next((i for i,p in enumerate(priorities) if p in r['url']),999),r['url']))
    errors=[]; success=0
    for row in candidates[:args.limit]:
        u=row['url']
        try:
            game=parse_game(fetch(u),u)
            if game:
                keys=list(game); db.execute(f"INSERT OR REPLACE INTO games({','.join(keys)}) VALUES({','.join('?' for _ in keys)})", list(game.values()))
            else: db.execute('DELETE FROM games WHERE url=?',(u,))
            db.execute('UPDATE pages SET checked=?,error=NULL WHERE url=?',(dt.datetime.now(dt.timezone.utc).isoformat(),u)); success+=1
        except Exception as e:
            errors.append({'url':u,'error':str(e)[:200]}); db.execute('UPDATE pages SET error=? WHERE url=?',(str(e)[:200],u))
        db.commit()
    if success==0: raise RuntimeError('No pages successfully checked; preserving published JSON')
    curated=json.loads((ROOT/'data/competitive.json').read_text())
    for game in curated:
        keys=list(game); db.execute(f"INSERT OR REPLACE INTO games({','.join(keys)}) VALUES({','.join('?' for _ in keys)})", list(game.values()))
    db.commit()
    games=[dict(r) for r in db.execute('SELECT * FROM games ORDER BY title,platform')]
    report={'updated':dt.datetime.now(dt.timezone.utc).isoformat(),'discovered':len(set(urls)), 'checked':db.execute('SELECT count(*) FROM pages WHERE checked IS NOT NULL').fetchone()[0], 'errors':len(errors), 'games':games}
    (ROOT/'data/catalog.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    (ROOT/'data/last-run.json').write_text(json.dumps({'success':success,'errors':errors},indent=2)+'\n')
    db.close()
    print(f'{len(games)} editions; {success} checked; {len(errors)} errors; {report["discovered"]} discovered')
    if errors: raise RuntimeError('Partial scrape failure; successful records exported, inspect last-run.json')
if __name__=='__main__': main()
