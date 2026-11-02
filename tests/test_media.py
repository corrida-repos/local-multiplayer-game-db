import unittest,json
from scripts.stores import official_url,nintendo_match
from scripts.trailers import choose_video,videos_from_official_page
class OfficialStores(unittest.TestCase):
    def test_ps5_uses_playstation_store(self):
        self.assertTrue(official_url('PS5','https://store.playstation.com/pt-pt/product/EP0006-PPSA02343_00-ITTAKESTWORETAIL'))
        self.assertFalse(official_url('Switch','https://store.playstation.com/pt-pt/concept/123'))
    def test_no_switch2_or_search_page(self):
        self.assertFalse(official_url('Switch','https://www.nintendo.com/us/store/products/game-switch-2/'))
        self.assertFalse(official_url('PS5','https://store.playstation.com/pt-pt/search/game'))
    def test_exact_game_title(self):
        page='<meta property="og:title" content="Moving Out 2 for Nintendo Switch - Nintendo Official Site">'
        self.assertTrue(nintendo_match(page,'Moving Out 2'))
        self.assertFalse(nintendo_match(page,'Moving Out'))
    def test_editorial_og_title_can_use_exact_document_title(self):
        page='<title>Mario + Rabbids&reg; Kingdom Battle | Nintendo Switch games | Games | Nintendo UK</title><meta property="og:title" content="Team up with Mario and the Rabbids!">'
        self.assertTrue(nintendo_match(page,'Mario + Rabbids Kingdom Battle'));self.assertFalse(nintendo_match(page,'Mario + Rabbids Sparks of Hope'))
        self.assertFalse(official_url('Switch','https://www.nintendo.com/en-gb/Games/Nintendo-Switch-2-games/Example-123.html'))
    def test_nintendo_trademarks(self):
        page='<meta property="og:title" content="Kirby’s Return to Dreamland™ Deluxe for the Nintendo Switch system™ – Official Site">'
        self.assertTrue(nintendo_match(page,"Kirby's Return to Dream Land Deluxe"))
class OfficialTrailers(unittest.TestCase):
    def test_prefers_gameplay_to_official_trailer(self):
        trailer={'id':'abcdefghijk','kind':'trailer'};gameplay={'id':'12345678901','kind':'gameplay'}
        self.assertIs(choose_video(trailer,[trailer,gameplay]),gameplay)
        self.assertIs(choose_video(gameplay,[trailer]),gameplay)
    def test_falls_back_to_official_trailer(self):
        trailer={'id':'abcdefghijk','kind':'trailer'}
        self.assertIs(choose_video(None,[trailer]),trailer)
        self.assertIsNone(choose_video(None,[]))
    def test_source_page_requires_same_game(self):
        video={'@type':'VideoObject','name':'Another Game Gameplay Trailer','contentUrl':'https://www.youtube.com/watch?v=abcdefghijk'}
        page='<script type="application/ld+json">'+json.dumps([video])+'</script>'
        self.assertEqual(videos_from_official_page(page,'My Game','https://www.playstation.com/en-us/games/my-game/'),[])
