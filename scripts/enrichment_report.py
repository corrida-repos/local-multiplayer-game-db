"""Publish coverage changes and source failures in the Actions run summary."""
import argparse,collections,json,os
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
    rows=[];regressions=[]
    for field in ['image','store','rating']:
        gained=sum(not requirements(old.get(k,{}))[field] and requirements(new[k])[field] for k in keys)
        lost=[k for k in shared if requirements(old[k])[field] and not requirements(new[k])[field]]
        regressions.extend((k,field) for k in lost)
        rows.append(f'| {field} | {sum(requirements(new[k])[field] for k in keys)} | +{gained} | {len(lost)} |')
    failures=collections.Counter((source,failure_kind(reason)) for entry in new.values() if not all(requirements(entry).values()) for source,reason in entry.get('errors',{}).items())
    lines=['## Enrichment coverage',f"{sum(all(requirements(new[k]).values()) for k in keys)} / {len(keys)} entries meet the minimum; {len(keys-set(old))} new entries this run.",'','| Field | Present | Recovered | Lost |','| --- | ---: | ---: | ---: |',*rows,'','### Remaining lookup failures','']
    lines.extend(f'- {source}: {kind} — {count}' for (source,kind),count in failures.most_common(15))
    if regressions:lines+=['','### Coverage regressions',*['- '+key+': '+field for key,field in regressions[:30]]]
    return '\n'.join(lines)+'\n',regressions

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--before',required=True);args=ap.parse_args()
    before=json.loads(Path(args.before).read_text());after=json.loads(Path('data/enrichment.json').read_text());summary,regressions=report(before,after)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as out:out.write(summary)
    print(summary)
    if regressions:raise SystemExit('Enrichment lost previously verified minimum data; inspect the coverage regressions above.')
if __name__=='__main__':main()
