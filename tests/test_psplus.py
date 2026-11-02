import datetime,json,unittest
from scripts.psplus import parse_catalog
URL='https://store.playstation.com/pt-pt/product/GAMEID'
def page(kind='UPSELL_PS_PLUS_GAME_CATALOG',membership='PS_PLUS',value=0,tied=True,platform='PS5',pid='GAMEID',end=None):
    product={'id':'GAMEID','platforms':[platform]}
    price={'membershipType':membership,'discountedValue':value,'isTiedToSubscription':tied,'tierLabel':'TIER_20','endTime':end}
    cache={'Product:GAMEID':product,'GameCTA:'+kind+':ADD_TO_CART:'+pid+'-E003:SUB':{'__typename':'GameCTA','type':kind,'price':price}}
    return '<script type="application/json">'+json.dumps({'cache':cache})+'</script>'
class PortugalCatalog(unittest.TestCase):
    def test_verified_full_game(self):
        result=parse_catalog(page(),URL);self.assertTrue(result['in_catalog']);self.assertEqual(result['tier'],'Extra')
    def test_ea_play_is_not_psplus(self):self.assertFalse(parse_catalog(page(kind='UPSELL_EA_ACCESS_FREE',membership='EA_ACCESS'),URL)['in_catalog'])
    def test_discount_is_not_catalogue(self):self.assertFalse(parse_catalog(page(value=1999),URL)['in_catalog'])
    def test_trial_is_not_catalogue(self):self.assertFalse(parse_catalog(page(kind='UPSELL_PS_PLUS_GAME_TRIAL'),URL)['in_catalog'])
    def test_other_product_offer_is_not_used(self):self.assertFalse(parse_catalog(page(pid='ANOTHERGAME'),URL)['in_catalog'])
    def test_expired_offer(self):self.assertFalse(parse_catalog(page(end='1000000'),URL)['in_catalog'])
    def test_ps4_only_does_not_qualify(self):
        with self.assertRaises(ValueError):parse_catalog(page(platform='PS4'),URL)
    def test_portugal_only(self):
        with self.assertRaises(ValueError):parse_catalog(page(),URL.replace('pt-pt','en-us'))
