"""One-time, writer-locked rebaseline to the explicit Portugal completeness policy."""
import json,sqlite3
from scripts import enrichment as e,recovery_state

def migrate():
    document=e.read('enrichment.json');entries=document['games']
    if document.get('coverage_policy')==recovery_state.POLICY:return False
    games=e.read('catalog.json')['games'];keys=set(entries)
    previous=document.get('coverage',{})
    e.seed(games,entries,e.read('ratings.json')['games'],e.read('stores.json')['games'],e.read('composites.json')['games'],e.read('trailers.json')['games'],e.read('images.json',{}),e.read('psplus.json')['games'])
    assert keys.issubset(entries),'Migration must preserve existing game records'
    db=sqlite3.connect(e.ROOT/'data/enrichment.sqlite');db.execute('CREATE TABLE IF NOT EXISTS enrichment(game_key TEXT PRIMARY KEY,payload TEXT NOT NULL)');e.export(entries,db);db.close()
    current=e.read('enrichment.json')['coverage']
    baseline={'policy':recovery_state.POLICY,'created':e.now(),'previous_definition':'Official stores in any region','previous_coverage':previous,'definition':'Verified official Portuguese product listing, usable game image, and at least one console-specific rating','coverage':current}
    (e.ROOT/'data/coverage-baseline.json').write_text(json.dumps(baseline,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('PORTUGAL BASELINE',json.dumps(current),flush=True);return True
if __name__=='__main__':migrate()
