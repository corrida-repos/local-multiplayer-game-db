"""Merge verified recovery batches under the enrichment workflow's writer lock."""
import copy,hashlib,json,sqlite3
from pathlib import Path
from scripts import enrichment as e
ROOT=Path(__file__).resolve().parents[1]

def critic_merge(current,incoming):
    if not e.has_score(incoming):return current
    if not e.has_score(current):return incoming
    if e.opaque_critic(current) or e.opaque_critic(incoming):
        # Do not combine an aggregate with potentially overlapping publications.
        return current
    return e.composites.critic_composite(current.get('sources',[])+incoming.get('sources',[]))

def user_merge(current,incoming):
    if not e.has_score(incoming):return current
    if not e.has_score(current):return incoming
    unique={}
    for source in current.get('sources',[])+incoming.get('sources',[]):
        name=source.get('name') or source.get('source','');key='PSN' if name.startswith('PSN') else name.lower()
        old=unique.get(key)
        if old is None or source.get('checked','')>=old.get('checked',''):unique[key]=source
    merged=e.composites.user_composite(list(unique.values()))
    return merged if e.has_score(merged) else current

def merge_entry(current,incoming):
    if incoming.get('platform') and current.get('platform')!=incoming['platform']:raise ValueError('Recovery belongs to another console')
    if incoming.get('title') and current.get('title')!=incoming['title']:raise ValueError('Recovery belongs to another game')
    result=copy.deepcopy(current)
    for field in ['store','image','user','psplus']:
        value=incoming.get(field)
        if not value:continue
        previous=result.get(field,{})
        if field in ['store','image']:
            if value.get('url') and not previous.get('url'):result[field]=value
        elif value.get('checked','')>=previous.get('checked',''):result[field]=value
    if incoming.get('ratings'):
        ratings=copy.deepcopy(result.get('ratings',{}));new=incoming['ratings']
        ratings['critic']=critic_merge(ratings.get('critic',{}),new.get('critic',{}))
        ratings['user']=user_merge(ratings.get('user',{}),new.get('user',{}))
        ratings['attempted']=max(ratings.get('attempted',''),new.get('attempted',''))
        result['ratings']=ratings
    if incoming.get('version'):result['version']=max(result.get('version',0),incoming['version'])
    if incoming.get('basics_attempted'):result['basics_attempted']=max(result.get('basics_attempted',''),incoming['basics_attempted'])
    result['requirements']=e.requirements(result)
    errors=result.setdefault('errors',{})
    if result.get('store',{}).get('url'):errors.pop('store',None)
    if result.get('image',{}).get('url'):errors.pop('image',None)
    return result

def apply_pending():
    path=ROOT/'data/verified-recoveries.json'
    if not path.exists():return
    digest=hashlib.sha256(path.read_bytes()).hexdigest();state_path=ROOT/'data/recovery-state.json'
    state=json.loads(state_path.read_text()) if state_path.exists() else {'applied':[]}
    if digest in state['applied']:return
    entries=e.read('enrichment.json')['games'];before={k:e.requirements(v) for k,v in entries.items()};batch=json.loads(path.read_text());keys=set(entries)
    for group in batch.get('entry_passes',[]):
        for key,value in group.items():
            if key in entries:entries[key]=merge_entry(entries[key],value)
    for key,value in batch.get('store_results',{}).items():
        if key in entries and value.get('store'):entries[key]=merge_entry(entries[key],value)
    for key,artwork in batch.get('artwork',{}).items():
        if key in entries:entries[key]=merge_entry(entries[key],{'image':artwork})
    for key,entry in entries.items():
        if not e.opaque_critic(entry.get('ratings',{}).get('critic',{})):
            sources=e.curated_critics({'platform':entry['platform'],'title':entry['title']})
            if sources:entries[key]=merge_entry(entry,{'ratings':{'critic':e.composites.critic_composite(sources)}})
    assert set(entries)==keys,'Recovery must not delete or add catalog entries'
    after={k:e.requirements(v) for k,v in entries.items()};delta={field:sum(not before[k][field] and after[k][field] for k in entries) for field in ['image','store','rating']};delta['newly_complete']=sum(not all(before[k].values()) and all(after[k].values()) for k in entries)
    db=sqlite3.connect(ROOT/'data/enrichment.sqlite');db.execute('CREATE TABLE IF NOT EXISTS enrichment(game_key TEXT PRIMARY KEY,payload TEXT NOT NULL)');e.export(entries,db);db.close()
    state['applied'].append(digest);state.setdefault('batches',[]).append({'id':batch['id'],'applied':e.now(),'improvement':delta});state_path.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n');print('RECOVERY APPLIED',json.dumps(delta),flush=True)

if __name__=='__main__':apply_pending()
