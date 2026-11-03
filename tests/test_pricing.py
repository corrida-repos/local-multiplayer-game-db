import datetime as dt
import json
import os
import unittest
from unittest import mock

from scripts.pricing import collect, model, sources
from scripts.pricing.http import redact

CLOCK = dt.datetime(2026, 11, 3, 12, tzinfo=dt.timezone.utc)
REGISTRY = {
    'psn_pt': {'name': 'PlayStation Store', 'status': 'active', 'domains': ['store.playstation.com'], 'sellers': {'sony': {'name': 'PlayStation Store', 'kind': 'direct', 'verified': True}}},
    'shop': {'name': 'Loja', 'status': 'active', 'domains': ['loja.pt'], 'new_only': True, 'sellers': {'loja': {'name': 'Loja', 'kind': 'direct', 'verified': True}, 'mystery': {'name': '?', 'kind': 'unknown', 'verified': False}},
             'shipping': {'verified': True, 'regions': ['mainland'], 'cents': 270, 'free_over_cents': 4900, 'free_inclusive': False}},
    'pending': {'name': 'Candidate', 'status': 'candidate', 'domains': ['c.pt'], 'sellers': {}},
}


def offer(**changes):
    base = {
        'id': 'a', 'game_key': 'PS5:1', 'platform': 'PS5', 'source_id': 'shop', 'seller_id': 'loja', 'retailer': 'Loja',
        'purchase_url': 'https://loja.pt/p/1', 'native_platform_verified': True, 'full_game': True, 'requires_base_game': False,
        'condition': 'new', 'condition_note': '', 'stock': 'in_stock', 'format': 'physical', 'delivery': 'physical_copy', 'edition': 'Standard',
        'requirements': [], 'access_type': 'purchase', 'currency': 'EUR', 'vat_included': True, 'destination_confirmed': True,
        'item_cents': 3999, 'shipping_cents': 270, 'fees_cents': 0, 'checked_at': (CLOCK - dt.timedelta(hours=2)).isoformat(), 'expires_at': None,
    }
    base.update(changes)
    return base


def digital(**changes):
    values = {'id': 'd', 'source_id': 'psn_pt', 'seller_id': 'sony', 'retailer': 'PlayStation Store', 'format': 'digital', 'delivery': 'download',
              'purchase_url': 'https://store.playstation.com/pt-pt/product/X', 'shipping_cents': 0, 'account_region': 'PT'}
    values.update(changes)
    return offer(**values)


class Money(unittest.TestCase):
    def test_portuguese_and_dot_prices(self):
        self.assertEqual(model.cents('1.299,90 €'), 129990)
        self.assertEqual(model.cents('14.99'), 1499)
        self.assertEqual(model.cents('39,99'), 3999)

    def test_unclear_price_is_never_zero(self):
        for value in [None, '', 'Grátis?', '-1', True]:
            self.assertIsNone(model.cents(value))


class Delivery(unittest.TestCase):
    RULE = REGISTRY['shop']['shipping']

    def test_flat_fee_and_free_threshold_for_one_copy(self):
        self.assertEqual(model.shipping_for(self.RULE, 3999, 'mainland', CLOCK), 270)
        self.assertEqual(model.shipping_for(self.RULE, 4900, 'mainland', CLOCK), 270)  # "superior a 49 €"
        self.assertEqual(model.shipping_for(self.RULE, 4901, 'mainland', CLOCK), 0)

    def test_promotion_window_is_inclusive_only_while_active(self):
        rule = dict(self.RULE, promotions=[{'from': '2026-10-29T00:00:00+00:00', 'to': '2026-12-02T00:00:00+00:00', 'free_from_cents': 4900, 'inclusive': True}])
        self.assertEqual(model.shipping_for(rule, 4900, 'mainland', CLOCK), 0)
        self.assertEqual(model.shipping_for(rule, 4900, 'mainland', CLOCK + dt.timedelta(days=60)), 270)

    def test_unknown_region_or_unverified_policy(self):
        self.assertIsNone(model.shipping_for(self.RULE, 3999, 'islands', CLOCK))
        self.assertIsNone(model.shipping_for(self.RULE, 3999, None, CLOCK))
        self.assertIsNone(model.shipping_for(dict(self.RULE, verified=False), 3999, 'mainland', CLOCK))

    def test_postcode_region(self):
        self.assertEqual(model.postcode_region('4780-023'), 'mainland')
        self.assertEqual(model.postcode_region('9500-100'), 'islands')
        self.assertIsNone(model.postcode_region(''))

    def test_delivery_cost_reverses_the_winner(self):
        cheap_item = offer(id='p', item_cents=3800, shipping_cents=270)
        digital_offer = digital(item_cents=3999)
        self.assertEqual(model.select([cheap_item, digital_offer], REGISTRY, CLOCK)[0]['id'], 'd')


class Eligibility(unittest.TestCase):
    def reason(self, **changes):
        return model.eligible(offer(**changes), REGISTRY, CLOCK)

    def test_verified_offer(self):
        self.assertIsNone(self.reason())

    def test_exclusions(self):
        cases = {
            'source_unverified': {'source_id': 'pending'}, 'seller_unverified': {'seller_id': 'mystery'},
            'invalid_purchase_url': {'purchase_url': 'https://evil.example/p'}, 'wrong_console': {'native_platform_verified': False},
            'incomplete_game': {'requires_base_game': True}, 'condition_unverified': {'condition': 'unknown'},
            'not_in_stock': {'stock': 'out_of_stock'}, 'ineligible_condition': {'requirements': ['PS_PLUS_EXTRA_TRIAL']},
            'not_purchase': {'access_type': 'subscription'}, 'tax_or_currency_unverified': {'currency': 'GBP'},
            'delivery_unverified': {'destination_confirmed': False}, 'total_unverified': {'shipping_cents': None},
            'stale': {'checked_at': (CLOCK - dt.timedelta(hours=37)).isoformat()},
            'expired': {'expires_at': (CLOCK - dt.timedelta(minutes=1)).isoformat()},
        }
        for expected, changes in cases.items():
            with self.subTest(expected):
                self.assertEqual(self.reason(**changes), expected)

    def test_used_wording_in_condition_note(self):
        self.assertEqual(self.reason(condition_note='Jogo PS5 usado - como novo'), 'condition_unverified')

    def test_premium_discount_is_allowed(self):
        self.assertIsNone(model.eligible(digital(requirements=['PS_PLUS_PREMIUM']), REGISTRY, CLOCK))


class Selection(unittest.TestCase):
    def test_exact_tie_returns_both_formats(self):
        winners = model.select([offer(item_cents=3729), digital(item_cents=3999)], REGISTRY, CLOCK)
        self.assertEqual([w['format'] for w in winners], ['physical', 'digital'])

    def test_expired_promotion_falls_back_to_next_minimum(self):
        promo = digital(id='promo', item_cents=999, expires_at=(CLOCK - dt.timedelta(hours=1)).isoformat())
        self.assertEqual(model.select([promo, offer()], REGISTRY, CLOCK)[0]['id'], 'a')

    def test_no_verified_offer(self):
        self.assertEqual(model.select([offer(stock='out_of_stock')], REGISTRY, CLOCK), [])


class Discount(unittest.TestCase):
    REF = {'kind': 'official_regular', 'cents': 5999, 'format': 'digital', 'edition': 'Standard', 'game_key': 'PS5:1', 'verified': True}

    def test_item_only_percentage_with_one_decimal(self):
        result = model.discount(offer(item_cents=3999), self.REF)
        self.assertEqual(result['percent'], '33.3')
        self.assertTrue(result['cross_format'])
        self.assertEqual(result['label'], 'preço regular oficial')

    def test_no_saving_without_matching_reference(self):
        self.assertIsNone(model.discount(offer(edition='Deluxe Edition'), self.REF))
        self.assertIsNone(model.discount(offer(item_cents=6999), self.REF))
        self.assertIsNone(model.discount(offer(), None))
        self.assertIsNone(model.discount(offer(), dict(self.REF, kind='strikethrough')))

    def test_msrp_must_match_format(self):
        msrp = dict(self.REF, kind='msrp', format='physical')
        self.assertEqual(model.discount(offer(item_cents=3999), msrp)['label'], 'PVP recomendado')
        self.assertIsNone(model.discount(digital(item_cents=3999), msrp))


class Titles(unittest.TestCase):
    def test_retail_titles(self):
        self.assertEqual(model.split_title('Jogo PS5 F1 2021')[1:], ('Standard', 'physical_copy'))
        self.assertEqual(model.split_title('Commandos: Origins - Deluxe Edition - PS5')[1], 'Deluxe Edition')
        self.assertEqual(model.split_title('Lego City Undercover - Code in a Box - Nintendo Switch')[2], 'posted_code')

    def test_rejected_products(self):
        for title in ['Mario Kart World - Nintendo Switch 2', 'Jogo PS4 FIFA 23', 'Season Pass - PS5', 'Cartão Presente PlayStation 20€', 'Comando DualSense PS5']:
            with self.subTest(title):
                self.assertIsNone(model.split_title(title))


def psn_page(ctas, platforms=('PS4', 'PS5'), classification='FULL_GAME', name='Test Game', top='GAME'):
    product = {'id': 'EP1-PPSA1_00-GAME', '__typename': 'Product', 'name': name, 'platforms': list(platforms), 'storeDisplayClassification': classification, 'topCategory': top, 'edition': {'name': '', 'type': 'STANDARD'}}
    nodes = [{'__typename': 'GameCTA', 'type': kind, 'price': price, 'action': {'param': [{'name': 'skuId', 'value': 'EP1-PPSA1_00-GAME-E001'}]}} for kind, price in ctas]
    return '<script type="application/json">' + json.dumps({'cache': {'Product:EP1-PPSA1_00-GAME': product}}) + '</script><script type="application/json">' + json.dumps({'props': {'ctas': nodes}}) + '</script>'


def price(base, value, branding=('NONE',), tied=False, end=None):
    return {'basePriceValue': base, 'discountedValue': value, 'serviceBranding': list(branding), 'isTiedToSubscription': tied, 'endTime': end, 'currencyCode': 'EUR'}


class PlayStation(unittest.TestCase):
    GAME = {'id': '1', 'platform': 'PS5', 'title': 'Test Game'}
    URL = 'https://store.playstation.com/pt-pt/product/EP1-PPSA1_00-GAME'

    def offers(self, *ctas, **kwargs):
        return sources.psn_offers(self.GAME, ['Test Game'], psn_page(ctas, **kwargs), self.URL, CLOCK)

    def test_public_sale_with_expiry_and_official_reference(self):
        [result] = self.offers(('ADD_TO_CART', price(3999, 1999, end='1762300000000')))
        self.assertEqual((result['item_cents'], result['reference']['cents']), (1999, 3999))
        self.assertTrue(result['expires_at'])

    def test_premium_discount_kept_catalog_trial_and_ea_play_rejected(self):
        found = self.offers(('ADD_TO_CART', price(3999, 3999)), ('UPSELL_PS_PLUS_DISCOUNT', price(3999, 2799, ('PS_PLUS',))),
                            ('UPSELL_PS_PLUS_GAME_CATALOG', price(3999, 0, ('PS_PLUS',), tied=True)), ('UPSELL_EA_ACCESS_FREE', price(3999, 0, ('EA_ACCESS',), tied=True)),
                            ('DOWNLOAD_TRIAL', price(0, 0)))
        self.assertEqual(sorted((o['item_cents'], tuple(o['requirements'])) for o in found), [(2799, ('PS_PLUS_PREMIUM',)), (3999, ())])

    def test_ps4_only_product_is_wrong_console(self):
        [result] = self.offers(('ADD_TO_CART', price(1999, 1999)), platforms=('PS4',))
        self.assertEqual(model.eligible(dict(result, checked_at=CLOCK.isoformat()), REGISTRY, CLOCK), 'wrong_console')

    def test_add_on_is_incomplete(self):
        [result] = self.offers(('ADD_TO_CART', price(999, 999)), classification='ADD_ON_PACK', top='ADD_ON')
        self.assertEqual(model.eligible(dict(result, checked_at=CLOCK.isoformat()), REGISTRY, CLOCK), 'incomplete_game')


class Nintendo(unittest.TestCase):
    GAME = {'id': '2', 'platform': 'Switch', 'title': 'Switch Game'}
    PRODUCT = {'pt_url': 'https://www.nintendo.com/pt-pt/Jogos/Jogos-Nintendo-Switch/Switch-Game-1.html', 'pt_title': 'Switch Game'}

    def test_active_sale_and_regular_reference(self):
        entry = {'title_id': 7001, 'sales_status': 'onsale', 'regular_price': {'raw_value': '29.99', 'currency': 'EUR'},
                 'discount_price': {'raw_value': '14.99', 'currency': 'EUR', 'start_datetime': '2026-11-01T00:00:00Z', 'end_datetime': '2026-11-10T23:59:59Z'}}
        [result] = sources.nintendo_offers(self.GAME, self.PRODUCT, [entry], CLOCK)
        self.assertEqual((result['item_cents'], result['reference']['cents']), (1499, 2999))
        self.assertEqual(model.discount(result, result['reference'])['percent'], '50.0')

    def test_finished_sale_uses_regular_price_and_unlisted_is_skipped(self):
        entry = {'title_id': 7001, 'sales_status': 'onsale', 'regular_price': {'raw_value': '29.99', 'currency': 'EUR'},
                 'discount_price': {'raw_value': '14.99', 'currency': 'EUR', 'start_datetime': '2026-10-01T00:00:00Z', 'end_datetime': '2026-10-10T23:59:59Z'}}
        self.assertEqual(sources.nintendo_offers(self.GAME, self.PRODUCT, [entry], CLOCK)[0]['item_cents'], 2999)
        self.assertEqual(sources.nintendo_offers(self.GAME, self.PRODUCT, [{'title_id': 1, 'sales_status': 'not_found'}], CLOCK), [])


class Shopify(unittest.TestCase):
    SOURCE = dict(REGISTRY['shop'])
    LOOKUP = {('PS5', 'testgame'): {'PS5:1'}, ('PS5', 'twin'): {'PS5:2', 'PS5:3'}}

    def offers(self, title, available=True, value='39.99', region='mainland'):
        product = {'title': title, 'handle': 'x', 'body_html': '', 'variants': [{'id': 9, 'price': value, 'available': available, 'barcode': ''}]}
        return sources.shopify_offers(product, 'shop', self.SOURCE, 'PS5', self.LOOKUP, region, CLOCK)

    def test_match_shipping_and_stock(self):
        [result] = self.offers('Test Game - PS5')
        self.assertEqual((result['game_key'], result['shipping_cents'], result['stock']), ('PS5:1', 270, 'in_stock'))
        self.assertEqual(self.offers('Test Game - PS5', available=False)[0]['stock'], 'out_of_stock')

    def test_ambiguous_or_unmatched_titles_do_not_compete(self):
        self.assertEqual(self.offers('Twin - PS5'), [])
        self.assertEqual(self.offers('Another Game - PS5'), [])

    def test_used_and_unknown_delivery(self):
        self.assertEqual(self.offers('Test Game - PS5 (Usado)')[0]['condition'], 'unknown')
        self.assertFalse(self.offers('Test Game - PS5', region=None)[0]['destination_confirmed'])

    def test_code_in_box_is_digital(self):
        self.assertEqual(self.offers('Test Game - Code in a Box - PS5')[0]['format'], 'digital')


class Publication(unittest.TestCase):
    def test_postcode_redaction(self):
        with mock.patch.dict(os.environ, {'PRICING_POSTCODE': '1234-567'}):
            self.assertNotIn('1234-567', redact('quote failed for 1234-567 and 9999-000'))

    def test_writer_refuses_postcode(self):
        with mock.patch.dict(os.environ, {'PRICING_POSTCODE': '1234-567'}):
            with self.assertRaises(RuntimeError):
                collect.write('never-written.json', {'note': '1234-567'})
        self.assertFalse((collect.DATA / 'never-written.json').exists())

    def test_public_feed_keeps_candidates_and_saving(self):
        games = [{'id': '1', 'platform': 'PS5', 'title': 'Test Game'}]
        ref = {'kind': 'official_regular', 'cents': 5999, 'format': 'digital', 'edition': 'Standard', 'game_key': 'PS5:1', 'verified': True}
        offers = [offer(reference=ref), digital(item_cents=4999, reference=ref), offer(id='old', stock='out_of_stock')]
        public, audit, coverage, _, _ = collect.publish(games, offers, REGISTRY, {}, CLOCK)
        self.assertEqual(public['PS5:1']['best_total_cents'], 4269)
        self.assertEqual(len(public['PS5:1']['offers']), 2)
        self.assertEqual(public['PS5:1']['offers'][0]['saving']['percent'], '33.3')
        self.assertEqual(audit['PS5:1']['excluded'], {'not_in_stock': 1})
        self.assertEqual(coverage['with_verified_price'], 1)


if __name__ == '__main__':
    unittest.main()
