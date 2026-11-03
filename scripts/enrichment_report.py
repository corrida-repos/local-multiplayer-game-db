"""Publish coverage changes and source failures in the Actions run summary."""
import argparse,collections,json,os,datetime as dt
from pathlib import Path
from scripts.enrichment import requirements

def failure_kind(reason):
    text=str(reason).lower()
    if any(word in text for word in ['403','429','forbidden','too many requests']):return 'blocked or throttled'
    if any(word in text for word in ['timed out','timeout','502','503','504','connection','urlopen error']):return 'temporary network failure'
    if any(word in text for word in ['404','410','not found','no review','no scored','not indexed']):return 'not found or no published score'
    if any(word in text for word in ['identity','console','different game','not a switch','does not match']):return 'identity or console rejected'
    return 'other lookup failure'

def report(before,after):
    old=before.get('games',{});new=after.get('games',{});keys=set(new);shared=keys & set(old)
    rows=[];regressions=[];upstream=[]
    policy_changed=before.get('coverage_policy')!=after.get('coverage_policy')
    for field in ['image','store','rating']:
        gained=sum(not requirements(old.get(k,{}))[field] and requirements(new[k])[field] for k in keys)
        lost=[k for k in shared if requirements(old[k])[field] and not requirements(new[k])[field]]
        for key in lost:
            known=any(item.get('field')==field and item not in old[key].get('invalidations',[]) and item.get('url')==old[key].get(field,{}).get('url') for item in new[key].get('invalidations',[]))
            if known:upstream.append((key,field))
            elif not (policy_changed and field=='store'):regressions.append((key,field))
        rows.append(f'| {field} | {sum(requirements(new[k])[field] for k in keys)} | +{gained} | {len(lost)} |')
    failures=collections.Counter((source,failure_kind(reason)) for entry in new.values() if not all(requirements(entry).values()) for source,reason in entry.get('errors',{}).items())
    lines=['## Enrichment coverage',f"{sum(all(requirements(new[k]).values()) for k in keys)} / {len(keys)} entries meet the minimum; {len(keys-set(old))} new entries this run.",'','| Field | Present | Recovered | Lost |','| --- | ---: | ---: | ---: |',*rows,'','### Remaining lookup failures','']
    if policy_changed:lines+=['','Coverage definition changed; this run establishes a new baseline. Previous figures are not directly comparable.']
    if upstream:lines+=['','Confirmed upstream removals: '+str(len(upstream))+'. These fields remain in recovery.']
    overdue=sum(bool(e.get('next_attempt')) and e['next_attempt']<dt.datetime.now(dt.timezone.utc).isoformat() for entry in new.values() for field in entry.get('field_status',{}).values() for e in field.get('sources',{}).values())
    lines+=['','Overdue source checks: '+str(overdue)+'. Unresolved fields retain daily retries.']
    lines.extend(f'- {source}: {kind} — {count}' for (source,kind),count in failures.most_common(15))
    if regressions:lines+=['','### Coverage regressions',*['- '+key+': '+field for key,field in regressions[:30]]]
    return '\n'.join(lines)+'\n',regressions

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--before',required=True);args=ap.parse_args()
    before=json.loads(Path(args.before).read_text(encoding='utf-8'));after=json.loads(Path('data/enrichment.json').read_text(encoding='utf-8'));summary,regressions=report(before,after)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as out:out.write(summary)
    print(summary)
    if regressions:raise SystemExit('Enrichment lost previously verified minimum data; inspect the coverage regressions above.')
if __name__=='__main__':main()
