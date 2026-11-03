"""Source adapters. Each returns normalized offer observations for known catalog games."""
import json
import re
import urllib.parse

from scripts import stores
from scripts.pricing import model
from scripts.pricing.http import SourceError

FULL_GAME_CLASSES = {'FULL_GAME', 'PREMIUM_EDITION', 'GAME_BUNDLE'}
CTA_KINDS = {}  # diagnostics: every PlayStation call-to-action type and branding seen in a run


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def base_offer(game, source_id, seller_id, retailer, clock):
    return {
        'game_key': model.game_key(game), 'platform': game['platform'], 'source_id': source_id,
        'seller_id': seller_id, 'retailer': retailer, 'seller_name': retailer, 'currency': 'EUR',
        'vat_included': True, 'fees_cents': 0, 'condition': 'new', 'access_type': 'purchase',
        'requirements': [], 'requires_base_game': False, 'checked_at': model.iso(clock),
    }


# ---------------------------------------------------------------- PlayStation Store Portugal

def psn_documents(page):
    """Every JSON block on a PlayStation Store page (product data is split across components)."""
    for content in re.findall(r'<script[^>]*type="application/json"[^>]*>(.*?)</script>', page, re.S):
        try:
            yield json.loads(content)
        except (ValueError, TypeError):
            continue


def psn_products(page):
    products = {}
    for document in psn_documents(page):
        for key, value in (document.get('cache') or {}).items():
            if key.startswith('Product:') and isinstance(value, dict):
                products.setdefault(value.get('id') or key[8:], {}).update({k: v for k, v in value.items() if k != 'webctas'})
    return products


def psn_ctas(page):
    """(sku, cta type, price) for every priced call-to-action, deduplicated."""
    seen, result = set(), []
    for document in psn_documents(page):
        for node in walk(document):
            if node.get('__typename') != 'GameCTA' or not isinstance(node.get('price'), dict):
                continue
            sku = next((p.get('value') for p in (node.get('action') or {}).get('param', []) if p.get('name') == 'skuId'), None)
            price = node['price']
            marker = (sku, node.get('type'), price.get('basePriceValue'), price.get('discountedValue'), price.get('endTime'))
            if sku and marker not in seen:
                seen.add(marker)
                result.append((sku, node.get('type') or '', price))
    return result


def psn_offers(game, names, page, url, clock):
    identities = {stores.identity(name) for name in names if name}
    match = re.search(r'/product/([^/?#]+)', url)
    main = match[1] if match else None
    products = psn_products(page)
    if not main:
        concept = re.search(r'/concept/(\d+)', url)
        for document in psn_documents(page):
            ref = ((document.get('cache') or {}).get('Concept:' + (concept[1] if concept else ''), {}).get('defaultProduct') or {}).get('__ref', '')
            if ref.startswith('Product:'):
                main = ref[8:]
                break
    offers = []
    for sku, kind, price in psn_ctas(page):
        product_id = re.sub(r'-[A-Z]\d{3}$', '', sku)
        product = products.get(product_id)
        if not product:
            continue
        name = product.get('name') or ''
        parts = model.split_title(name.replace('™', '').replace('®', ''))
        if product_id != main and (not parts or parts[0] not in identities):
            continue
        edition = parts[1] if parts and parts[0] in identities else ((product.get('edition') or {}).get('name') or 'Standard').strip() or 'Standard'
        base = price.get('basePriceValue')
        value = price.get('discountedValue')
        if not isinstance(value, int) or not isinstance(base, int) or price.get('currencyCode') != 'EUR':
            continue
        branding = set(price.get('serviceBranding') or [])
        marker = kind + '/' + '+'.join(sorted(branding))
        CTA_KINDS[marker] = CTA_KINDS.get(marker, 0) + 1
        requirements, note = [], None
        if kind == 'ADD_TO_CART' and branding <= {'NONE'}:
            pass
        elif re.match(r'^UPSELL_PS_PLUS_DISCOUNT', kind) and 'PS_PLUS' in branding and not price.get('isTiedToSubscription') and value > 0:
            requirements, note = ['PS_PLUS_PREMIUM'], 'Desconto PS Plus (incluído no Premium)'
        else:
            continue  # catalog access, trials, EA Play and other memberships are not purchase prices
        offer = base_offer(game, 'psn_pt', 'sony', 'PlayStation Store', clock)
        offer.update({
            'id': model.identifier('psn_pt', sku, kind), 'product_id': sku, 'name': name, 'edition': edition,
            'format': 'digital', 'delivery': 'download', 'item_cents': value, 'shipping_cents': 0,
            'native_platform_verified': 'PS5' in (product.get('platforms') or []),
            'full_game': product.get('storeDisplayClassification') in FULL_GAME_CLASSES or (product_id == main and product.get('topCategory') == 'GAME'),
            'stock': 'in_stock', 'account_region': 'PT', 'destination_confirmed': True,
            'purchase_url': 'https://store.playstation.com/pt-pt/product/' + product_id,
            'requirements': requirements, 'condition_note': '',
            'expires_at': model.iso(model.date(price['endTime'])) if price.get('endTime') else None,
            'reference': {'kind': 'official_regular', 'cents': base, 'format': 'digital', 'edition': edition, 'game_key': model.game_key(game), 'url': 'https://store.playstation.com/pt-pt/product/' + product_id, 'verified': True},
        })
        if note:
            offer['condition_label'] = note
        offers.append(offer)
    return offers


def collect_psn(client, games, names, enrichment, clock_fn):
    offers, errors, checked = [], [], 0
    for game in games:
        if game['platform'] != 'PS5':
            continue
        key = model.game_key(game)
        url = ((enrichment.get(key) or {}).get('store') or {}).get('url')
        if not url or not stores.portugal_url('PS5', url):
            continue
        try:
            _, page = client.get(url)
            checked += 1
            offers.extend(psn_offers(game, names[key], page, url, clock_fn()))
        except SourceError as exc:
            errors.append({'game_key': key, 'status': exc.status, 'message': str(exc)})
            if exc.status == 'blocked' and len(errors) > 20 and not offers:
                raise
    return offers, errors, checked


# ---------------------------------------------------------------- Nintendo eShop Portugal

def nintendo_offers(game, product, prices, clock):
    offers = []
    url = product['pt_url']
    for entry in prices:
        if entry.get('sales_status') != 'onsale':
            continue
        regular = model.cents((entry.get('regular_price') or {}).get('raw_value'))
        if regular is None or (entry.get('regular_price') or {}).get('currency') != 'EUR':
            continue
        item, expires = regular, None
        sale = entry.get('discount_price') or {}
        sale_cents = model.cents(sale.get('raw_value'))
        start, end = model.date(sale.get('start_datetime')), model.date(sale.get('end_datetime'))
        if sale_cents is not None and sale.get('currency') == 'EUR' and (not start or start <= clock) and end and end > clock:
            item, expires = sale_cents, model.iso(end)
        offer = base_offer(game, 'nintendo_pt', 'nintendo', 'Nintendo eShop', clock)
        offer.update({
            'id': model.identifier('nintendo_pt', entry.get('title_id'), 'eshop'), 'product_id': str(entry.get('title_id')),
            'name': product.get('pt_title') or game['title'], 'edition': 'Standard', 'format': 'digital', 'delivery': 'download',
            'item_cents': item, 'shipping_cents': 0, 'native_platform_verified': True, 'full_game': True,
            'stock': 'in_stock', 'account_region': 'PT', 'destination_confirmed': True, 'purchase_url': url,
            'condition_note': '', 'expires_at': expires,
            'reference': {'kind': 'official_regular', 'cents': regular, 'format': 'digital', 'edition': 'Standard', 'game_key': model.game_key(game), 'url': url, 'verified': True},
        })
        offers.append(offer)
    return offers


def collect_nintendo(client, games, names, enrichment, clock_fn, index):
    wanted = {}
    for game in games:
        if game['platform'] != 'Switch':
            continue
        key = model.game_key(game)
        url = ((enrichment.get(key) or {}).get('store') or {}).get('url') or ''
        match = re.search(r'-(\d+)\.html$', url)
        product = index.get(match[1]) if match and stores.portugal_url('Switch', url) else None
        if product and product.get('nsuids') and product.get('pt_url'):
            for nsuid in product['nsuids']:
                wanted.setdefault(str(nsuid), []).append((game, product))
    offers, errors, checked = [], [], 0
    ids = sorted(wanted)
    for start in range(0, len(ids), 50):
        batch = ids[start:start + 50]
        try:
            _, response = client.json('https://api.ec.nintendo.com/v1/price?' + urllib.parse.urlencode({'country': 'PT', 'lang': 'pt', 'ids': ','.join(batch)}))
        except SourceError as exc:
            errors.append({'batch': start // 50, 'status': exc.status, 'message': str(exc)})
            continue
        if response.get('country') != 'PT' or response.get('personalized'):
            errors.append({'batch': start // 50, 'status': 'unsupported', 'message': 'Unexpected Nintendo price response'})
            continue
        by_id = {str(entry.get('title_id')): entry for entry in response.get('prices', [])}
        clock = clock_fn()
        for nsuid in batch:
            for game, product in wanted[nsuid]:
                checked += 1
                if nsuid in by_id:
                    offers.extend(nintendo_offers(game, product, [by_id[nsuid]], clock))
    return offers, errors, checked


# ---------------------------------------------------------------- Shopify retailers (Darty Portugal)

def shopify_offers(product, source_id, source, platform, lookup, region, clock):
    seller_id = next(iter(source['sellers']))
    title = product.get('title') or ''
    parts = model.split_title(title)
    if not parts:
        return []
    keys = lookup.get((platform, parts[0]), set())
    if len(keys) != 1:
        return []  # unmatched or ambiguous titles need evidence before they can compete
    key = next(iter(keys))
    body = re.sub('<[^>]+>', ' ', product.get('body_html') or '')
    offers = []
    for variant in product.get('variants', []):
        item = model.cents(variant.get('price'))
        if item is None:
            continue
        shipping = model.shipping_for(source.get('shipping'), item, region, clock)
        offer = {
            'id': model.identifier(source_id, variant.get('id'), seller_id), 'game_key': key, 'platform': platform,
            'source_id': source_id, 'seller_id': seller_id, 'retailer': source['name'], 'seller_name': source['sellers'][seller_id]['name'],
            'product_id': str(variant.get('id')), 'name': title, 'edition': parts[1],
            'format': 'digital' if parts[2] == 'posted_code' else 'physical', 'delivery': parts[2],
            'item_cents': item, 'shipping_cents': shipping, 'fees_cents': 0, 'currency': 'EUR', 'vat_included': True,
            'condition': 'new' if source.get('new_only') and not model.BAD_CONDITION.search(title + ' ' + body) else 'unknown',
            'condition_note': title, 'stock': 'in_stock' if variant.get('available') else 'out_of_stock',
            'native_platform_verified': True, 'full_game': True, 'requires_base_game': False,
            'account_region': 'EU' if parts[2] == 'posted_code' else None, 'access_type': 'purchase', 'requirements': [],
            'destination_confirmed': shipping is not None,
            'purchase_url': 'https://' + source['domains'][0] + '/products/' + urllib.parse.quote(product.get('handle', '')),
            'checked_at': model.iso(clock), 'expires_at': None, 'ean': model_gtin(variant.get('barcode')),
        }
        offers.append(offer)
    return offers


def model_gtin(value):
    value = re.sub(r'\D', '', str(value or ''))
    return value if len(value) in [8, 12, 13, 14] else None


def collect_shopify(client, source_id, source, lookup, region, clock_fn):
    offers, errors, checked = [], [], 0
    for platform, collection in source['collections'].items():
        page = 1
        while page <= 40:
            url = 'https://' + source['domains'][0] + '/collections/' + collection + '/products.json?limit=250&page=' + str(page)
            try:
                _, response = client.json(url)
            except SourceError as exc:
                errors.append({'collection': collection, 'page': page, 'status': exc.status, 'message': str(exc)})
                break
            products = response.get('products') or []
            if not products:
                break
            clock = clock_fn()
            for product in products:
                checked += 1
                offers.extend(shopify_offers(product, source_id, source, platform, lookup, region, clock))
            page += 1
    return offers, errors, checked
