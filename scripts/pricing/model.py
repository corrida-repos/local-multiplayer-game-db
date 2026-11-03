"""Money, matching, delivery and eligibility shared by collectors, publisher and tests."""
import datetime as dt
import decimal
import hashlib
import re
import urllib.parse

from scripts import stores

VERSION = 1
MAX_AGE = dt.timedelta(hours=36)
# PS Plus Premium is the owner's active membership; it includes Essential and Extra discounts.
ALLOWED_REQUIREMENTS = {'PS_PLUS_PREMIUM', 'public_coupon', 'public_payment_method'}
BAD_CONDITION = re.compile(r'\bused\b|second.hand|refurb|recondicion|seminovo|\busad[oa]s?\b|open.box|exposi[çc][aã]o|reembalad|devolvid|\bretoma\b', re.I)
NOT_A_GAME = re.compile(r'\bSwitch\s*2\b|upgrade|season pass|passe de temporada|\bDLC\b|expans[aã]o|expansion pass|wallet|gift card|cart[aã]o.{0,12}(?:saldo|presente|oferta)|voucher|\bamiibo\b|\bconsola\b|\bconsole\b|comando|controller|\bcapa\b|\bcase\b|steelbook\s+only|figura|\bfigure\b|bundle\s+consola', re.I)
EDITION = re.compile(r'\s*[-:–—]?\s*((?:digital\s+)?(?:deluxe|ultimate|complete|gold|premium|standard|definitive|special|legendary|collector[\'’]?s|game of the year|goty)(?:\s+edition|\s+edi[çc][aã]o)?|edi[çc][aã]o\s+(?:deluxe|standard|especial|completa|gold|definitiva|ultimate))\s*$', re.I)
PLATFORM_WORDS = re.compile(r'\b(?:PS5|PS4|PlayStation\s*[45]|Nintendo\s+Switch(?:\s*1)?|Switch)\b', re.I)
CODE_IN_BOX = re.compile(r'code[- ]in[- ](?:a[- ])?box|c[oó]digo.{0,15}caixa|c[oó]digo\s+de\s+download|download\s+code|c[oó]digo\s+digital', re.I)


def now():
    return dt.datetime.now(dt.timezone.utc)


def iso(value=None):
    return (value or now()).isoformat(timespec='seconds')


def date(value):
    if value in (None, ''):
        return None
    try:
        if isinstance(value, (int, float)) or str(value).isdigit():
            number = int(value)
            return dt.datetime.fromtimestamp(number / 1000 if number > 10**11 else number, dt.timezone.utc)
        parsed = dt.datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def cents(value):
    """Parse a public price into integer cents; anything unclear is None, never zero."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value * 100 if value >= 0 else None
    text = str(value).strip().replace('\xa0', '').replace(' ', '').replace('€', '').replace('EUR', '')
    if not text:
        return None
    if ',' in text:
        text = text.replace('.', '').replace(',', '.')
    try:
        number = decimal.Decimal(text)
    except decimal.InvalidOperation:
        return None
    if not number.is_finite() or number < 0:
        return None
    return int((number * 100).quantize(decimal.Decimal('1'), rounding=decimal.ROUND_HALF_UP))


def game_key(game):
    return game['platform'] + ':' + str(game['id'])


def split_title(title):
    """Return (identity, edition, delivery) for a retailer product title, or None if not a full game."""
    title = re.sub(r'\s+', ' ', title or '').strip()
    if not title or NOT_A_GAME.search(title):
        return None
    if re.search(r'\bPS4\b', title, re.I) and not re.search(r'\bPS5\b|PlayStation\s*5', title, re.I):
        return None
    delivery = 'posted_code' if CODE_IN_BOX.search(title) else 'physical_copy'
    value = CODE_IN_BOX.sub(' ', title)
    value = re.sub(r'^\s*(?:jogo|game|videojogo)\s+', '', value, flags=re.I)
    value = re.sub(r'[\(\[]\s*(?:PS5|PS4\s*/\s*PS5|Nintendo\s+Switch|Switch)\s*[\)\]]', ' ', value, flags=re.I)
    value = PLATFORM_WORDS.sub(' ', value)
    value = re.sub(r'[\(\[]\s*[\)\]]', ' ', BAD_CONDITION.sub(' ', value))  # condition is judged separately
    value = re.sub(r'^\s*(?:jogo|game)\s+', '', value, flags=re.I)
    value = re.sub(r'\s+', ' ', value).strip(' -–—:|/')
    edition = 'Standard'
    match = EDITION.search(value)
    if match:
        found = re.sub(r'\s+', ' ', match[1]).strip()
        if not re.match(r'^(?:standard(?:\s+edition)?|edi[çc][aã]o\s+standard)$', found, re.I):
            edition = found.title()
        value = value[:match.start()].strip(' -–—:|/')
    ident = stores.identity(value)
    return (ident, edition, delivery) if ident else None


def postcode_region(postcode):
    """Portuguese postcode → delivery zone without exposing the postcode itself."""
    match = re.fullmatch(r'\s*(\d)\d{3}-?\d{3}\s*', postcode or '')
    if not match:
        return None
    return 'islands' if match[1] == '9' else 'mainland'


def shipping_for(rule, item_cents, region, clock=None):
    """Delivery fee for one copy under a verified retailer policy, or None when unknown."""
    if not rule or not rule.get('verified') or region is None or item_cents is None:
        return None
    if region not in rule.get('regions', []):
        return None
    clock = clock or now()
    for promo in rule.get('promotions', []):
        start, end = date(promo.get('from')), date(promo.get('to'))
        if start and end and start <= clock < end:
            threshold = promo['free_from_cents']
            if item_cents >= threshold if promo.get('inclusive') else item_cents > threshold:
                return 0
    threshold = rule.get('free_over_cents')
    if threshold is not None and (item_cents >= threshold if rule.get('free_inclusive') else item_cents > threshold):
        return 0
    fee = rule.get('cents')
    return fee if isinstance(fee, int) and fee >= 0 else None


def eligible(offer, registry, clock=None):
    """None when the offer may compete as a verified delivered total, else the exclusion reason."""
    clock = clock or now()
    source = registry.get(offer.get('source_id'), {})
    if source.get('status') != 'active':
        return 'source_unverified'
    seller = source.get('sellers', {}).get(offer.get('seller_id'), {})
    if not seller.get('verified') or seller.get('kind') not in ['direct', 'professional']:
        return 'seller_unverified'
    parsed = urllib.parse.urlparse(offer.get('purchase_url', ''))
    if parsed.scheme != 'https' or parsed.hostname not in source.get('domains', []):
        return 'invalid_purchase_url'
    if offer.get('platform') not in ['PS5', 'Switch'] or not offer.get('native_platform_verified'):
        return 'wrong_console'
    if not offer.get('full_game') or offer.get('requires_base_game'):
        return 'incomplete_game'
    if offer.get('condition') != 'new' or BAD_CONDITION.search(offer.get('condition_note', '') or ''):
        return 'condition_unverified'
    if offer.get('stock') != 'in_stock':
        return 'not_in_stock'
    if offer.get('format') not in ['physical', 'digital']:
        return 'format_unverified'
    if offer.get('format') == 'digital' and offer.get('account_region') not in ['PT', 'EU', 'worldwide']:
        return 'activation_unverified'
    if not set(offer.get('requirements', [])).issubset(ALLOWED_REQUIREMENTS):
        return 'ineligible_condition'
    if offer.get('access_type') != 'purchase':
        return 'not_purchase'
    if offer.get('currency') != 'EUR' or not offer.get('vat_included'):
        return 'tax_or_currency_unverified'
    if not offer.get('destination_confirmed'):
        return 'delivery_unverified'
    for field in ['item_cents', 'shipping_cents', 'fees_cents']:
        value = offer.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return 'total_unverified'
    checked = date(offer.get('checked_at'))
    if not checked or checked > clock + dt.timedelta(minutes=5) or clock - checked > MAX_AGE:
        return 'stale'
    if offer.get('expires_at'):
        expiry = date(offer.get('expires_at'))
        if not expiry or expiry <= clock:
            return 'expired'
    return None


def total(offer):
    return sum(offer[field] for field in ['item_cents', 'shipping_cents', 'fees_cents'])


def discount(offer, reference):
    """Saving against a verified MSRP or official regular price, on the item price only."""
    if not reference or reference.get('kind') not in ['msrp', 'official_regular'] or not reference.get('verified'):
        return None
    if reference.get('game_key') != offer.get('game_key') or reference.get('edition') != offer.get('edition'):
        return None
    if reference.get('kind') == 'msrp' and reference.get('format') != offer.get('format'):
        return None
    amount = reference.get('cents')
    item = offer.get('item_cents')
    if not isinstance(amount, int) or not isinstance(item, int) or amount <= 0 or amount <= item:
        return None
    value = (decimal.Decimal(amount - item) * 100 / decimal.Decimal(amount)).quantize(decimal.Decimal('.1'), rounding=decimal.ROUND_HALF_UP)
    return {
        'percent': str(value), 'reference_cents': amount, 'kind': reference['kind'],
        'reference_format': reference.get('format'), 'reference_url': reference.get('url'),
        'label': 'PVP recomendado' if reference['kind'] == 'msrp' else 'preço regular oficial',
        'cross_format': reference.get('format') != offer.get('format'),
    }


def select(offers, registry, clock=None):
    """Cheapest verified delivered total; one physical and one digital winner when they tie."""
    valid = [offer for offer in offers if eligible(offer, registry, clock) is None]
    if not valid:
        return []
    minimum = min(map(total, valid))
    tied = [offer for offer in valid if total(offer) == minimum]
    result = []
    for kind in ['physical', 'digital']:
        group = [offer for offer in tied if offer['format'] == kind]
        if group:
            group.sort(key=lambda o: (registry[o['source_id']]['sellers'][o['seller_id']]['kind'] != 'direct', -date(o['checked_at']).timestamp(), o.get('retailer', ''), o['id']))
            result.append(group[0])
    return result


def identifier(source, product, seller):
    return hashlib.sha256((source + ':' + str(product) + ':' + seller).encode()).hexdigest()[:24]
