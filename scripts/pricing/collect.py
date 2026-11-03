"""Daily Portugal price sweep: collect sources in parallel, merge, publish through one writer.

python -m scripts.pricing.collect [--sources psn_pt,nintendo_pt,darty] [--limit N]
The delivery postcode is read from PRICING_POSTCODE and never written anywhere.
"""
import argparse
import concurrent.futures
import json
import os
import sys
from pathlib import Path

from scripts import stores
from scripts.pricing import model, sources
from scripts.pricing.http import Client, SourceError, redact

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'data'
PUBLIC_PER_FORMAT = 4
HISTORY = 60


def read(name, default=None):
    path = DATA / name
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding='utf-8'))


def write(name, value):
    text = json.dumps(value, ensure_ascii=False, separators=(',', ':'), sort_keys=True) + '\n'
    postcode = os.environ.get('PRICING_POSTCODE', '').strip()
    if postcode and postcode in text:
        raise RuntimeError('Refusing to publish a file containing the delivery postcode')
    (DATA / name).write_text(text, encoding='utf-8')


def catalog_names(games, enrichment):
    names, lookup = {}, {}
    for game in games:
        key = model.game_key(game)
        values = [game['title']] + list((enrichment.get(key) or {}).get('aliases') or [])
        names[key] = list(dict.fromkeys(value for value in values if value))
        for value in names[key]:
            lookup.setdefault((game['platform'], stores.identity(value)), set()).add(key)
    return names, lookup


def attach_references(offers):
    """Physical offers use the matching edition's official digital regular price, disclosed as such."""
    official = {}
    for offer in offers:
        reference = offer.get('reference') or {}
        if reference.get('kind') == 'official_regular' and offer['format'] == 'digital' and offer.get('delivery') == 'download':
            slot = (offer['game_key'], offer['edition'])
            official[slot] = max(official.get(slot, 0), reference['cents'])
    for offer in offers:
        if offer.get('reference'):
            continue
        amount = official.get((offer['game_key'], offer['edition']))
        if amount:
            offer['reference'] = {'kind': 'official_regular', 'cents': amount, 'format': 'digital', 'edition': offer['edition'], 'game_key': offer['game_key'], 'verified': True}


def public_offer(offer):
    saving = model.discount(offer, offer.get('reference'))
    result = {
        'format': offer['format'], 'delivery': offer.get('delivery'), 'edition': offer['edition'],
        'retailer': offer['retailer'], 'seller': offer.get('seller_name') or offer['retailer'],
        'item_cents': offer['item_cents'], 'shipping_cents': offer['shipping_cents'], 'fees_cents': offer['fees_cents'],
        'total_cents': model.total(offer), 'url': offer['purchase_url'], 'checked_at': offer['checked_at'],
        'expires_at': offer.get('expires_at'), 'source_id': offer['source_id'],
    }
    if offer.get('condition_label'):
        result['condition'] = offer['condition_label']
    if saving:
        result['saving'] = {key: saving[key] for key in ['percent', 'reference_cents', 'label', 'reference_format', 'cross_format']}
    return result


def publish(games, offers, registry, run, clock):
    by_game = {}
    for offer in offers:
        offer['eligibility'] = model.eligible(offer, registry, clock) or 'eligible'
        by_game.setdefault(offer['game_key'], []).append(offer)
    public, audit_games = {}, {}
    for game in games:
        key = model.game_key(game)
        entries = by_game.get(key, [])
        valid = sorted((o for o in entries if o['eligibility'] == 'eligible'), key=lambda o: (model.total(o), o['source_id'], o['id']))
        if valid:
            kept = [o for kind in ['physical', 'digital'] for o in [x for x in valid if x['format'] == kind][:PUBLIC_PER_FORMAT]]
            best = model.select(valid, registry, clock)
            public[key] = {'best_total_cents': model.total(best[0]), 'offers': [public_offer(o) for o in kept]}
        reasons = {}
        for offer in entries:
            if offer['eligibility'] != 'eligible':
                reasons[offer['eligibility']] = reasons.get(offer['eligibility'], 0) + 1
        audit_games[key] = {'offers_seen': len(entries), 'eligible': len(valid), 'excluded': reasons} if entries else {'offers_seen': 0, 'eligible': 0, 'status': 'no_offer_found'}
    coverage = {
        'games': len(games), 'with_verified_price': len(public),
        'physical_winners': sum(1 for v in public.values() if any(o['format'] == 'physical' and o['total_cents'] == v['best_total_cents'] for o in v['offers'])),
        'digital_winners': sum(1 for v in public.values() if any(o['format'] == 'digital' and o['total_cents'] == v['best_total_cents'] for o in v['offers'])),
    }
    source_view = []
    for source_id, source in registry.items():
        info = {'id': source_id, 'name': source['name'], 'status': source['status']}
        if source['status'] == 'active':
            info.update(run.get(source_id, {}))
            info['offers'] = sum(1 for o in offers if o['source_id'] == source_id)
            info['eligible_offers'] = sum(1 for o in offers if o['source_id'] == source_id and o['eligibility'] == 'eligible')
        else:
            info['blocker'] = source.get('blocker')
        source_view.append(info)
    policy = {
        'label': 'Melhor preço verificado', 'max_age_hours': int(model.MAX_AGE.total_seconds() // 3600),
        'delivery_zone': run.get('_region') or 'unconfigured',
        'claim': 'Lowest verified delivered total among monitored sources; not an exhaustive market minimum.',
    }
    return public, audit_games, coverage, source_view, policy


def run_source(source_id, source, client, games, names, lookup, enrichment, index, region):
    clock_fn = model.now
    if source['adapter'] == 'psn':
        return sources.collect_psn(client, games, names, enrichment, clock_fn)
    if source['adapter'] == 'nintendo':
        return sources.collect_nintendo(client, games, names, enrichment, clock_fn, index)
    if source['adapter'] == 'shopify':
        return sources.collect_shopify(client, source_id, source, lookup, region, clock_fn)
    raise SourceError('unsupported', 'No adapter for ' + source_id)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--sources', default='')
    parser.add_argument('--limit', type=int, default=0, help='Diagnostics: only the first N catalog games')
    args = parser.parse_args(argv)
    registry = read('pricing-sources.json')['sources']
    games = read('catalog.json')['games']
    if args.limit:
        games = games[:args.limit]
    enrichment = read('enrichment-public.json', {}).get('games', {})
    index = read('nintendo-index.json', {}).get('products', {})
    names, lookup = catalog_names(games, enrichment)
    region = model.postcode_region(os.environ.get('PRICING_POSTCODE', ''))
    if region is None:
        print('PRICING_POSTCODE is not configured: physical offers stay unranked (delivery unverified).', flush=True)
    previous = read('pricing-offers.json', {'offers': []})
    old = previous.get('offers', [])
    wanted = [s for s in args.sources.split(',') if s] or [k for k, v in registry.items() if v['status'] == 'active']
    client = Client()
    started = model.iso()
    results, run = {}, {'_region': region}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(wanted) or 1) as pool:
        futures = {pool.submit(run_source, sid, registry[sid], client, games, names, lookup, enrichment, index, region): sid for sid in wanted}
        for future in concurrent.futures.as_completed(futures):
            sid = futures[future]
            try:
                offers, errors, checked = future.result()
                results[sid] = (offers, errors)
                status = 'ok' if not errors else 'partial'
                run[sid] = {'status': status, 'checked': checked, 'errors': len(errors), 'last_success': model.iso()}
                print(f'{sid}: {len(offers)} offers from {checked} checks, {len(errors)} errors', flush=True)
            except Exception as exc:  # a failed source keeps its previous observations and timestamps
                run[sid] = {'status': 'failed', 'checked': 0, 'errors': 1, 'message': redact(exc)[:200]}
                print(f'{sid}: FAILED {redact(exc)[:200]}', flush=True)
    prior_runs = {s['id']: s for s in (read('pricing-audit.json', {}) or {}).get('sources', [])}
    for sid, info in run.items():
        if sid != '_region' and 'last_success' not in info and prior_runs.get(sid, {}).get('last_success'):
            info['last_success'] = prior_runs[sid]['last_success']
    merged = []
    for offer in old:
        sid = offer['source_id']
        if sid not in results:
            merged.append(offer)  # not collected (failed or not requested): keep as observed
            continue
        failed_games = {e.get('game_key') for e in results[sid][1] if e.get('game_key')}
        if offer['game_key'] in failed_games:
            merged.append(offer)
    for sid, (offers, _) in results.items():
        merged.extend(offers)
    merged = [o for o in merged if o['source_id'] in registry]
    unique = {}
    for offer in merged:
        unique[offer['id']] = offer
    merged = list(unique.values())
    attach_references(merged)
    clock = model.now()
    public, audit_games, coverage, source_view, policy = publish(read('catalog.json')['games'] if not args.limit else games, merged, registry, run, clock)
    write('pricing-offers.json', {'version': model.VERSION, 'updated': model.iso(clock), 'offers': sorted(merged, key=lambda o: (o['game_key'], o['source_id'], o['id']))})
    write('pricing-public.json', {'version': model.VERSION, 'updated': model.iso(clock), 'policy': policy, 'coverage': coverage, 'sources': [{k: s[k] for k in s if k in ['id', 'name', 'status', 'last_success']} for s in source_view], 'games': public})
    audit = read('pricing-audit.json', {}) or {}
    history = (audit.get('history') or [])[-(HISTORY - 1):] + [{'started': started, 'finished': model.iso(clock), 'sources': {k: v for k, v in run.items() if k != '_region'}, 'coverage': coverage}]
    write('pricing-audit.json', {'version': model.VERSION, 'updated': model.iso(clock), 'policy': policy, 'coverage': coverage, 'sources': source_view, 'history': history, 'games': audit_games})
    if sources.CTA_KINDS:
        print('PlayStation CTA types:', json.dumps(sources.CTA_KINDS, sort_keys=True), flush=True)
    print(json.dumps(coverage), flush=True)
    failed = [sid for sid, info in run.items() if sid != '_region' and info['status'] == 'failed']
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
