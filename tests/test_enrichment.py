import json,unittest
from pathlib import Path
from unittest.mock import patch
from scripts import enrichment as e, ratings
URL='https://store.playstation.com/pt-pt/product/EP8311-PPSA13840_00-0277389480637871'
GAME={'id':'13238','title':'#WomenUp, Super Puzzles Dream','platform':'PS5'}
class Enrichment(unittest.TestCase):
    def setUp(self):self.page=(Path(__file__).parent/'fixtures/psn-product.html').read_text()
    def test_product_page_merges_platform_and_rating_blocks(self):
        result=e.psn_metadata(GAME,URL,self.page)
        self.assertEqual(result['user']['score'],1.52);self.assertEqual(result['user']['count'],23);self.assertEqual(result['store']['url'],URL);self.assertTrue(result['image']['url'].startswith('https://image.api.playstation.com/'))
    def test_product_identity_does_not_fall_back_to_related_game(self):
        self.assertIsNone(ratings.psn_rating(self.page,URL.replace('EP8311','OTHER')))
        with self.assertRaises(ValueError):e.psn_metadata({**GAME,'title':'A different puzzle game'},URL,self.page)
    def test_ps4_only_and_zero_votes_rejected(self):
        self.assertIsNone(ratings.psn_rating(self.page.replace('"PS5"','"PS4"'),URL))
        self.assertIsNone(ratings.psn_rating(self.page.replace('"totalRatingsCount": 23','"totalRatingsCount": 0'),URL))
    def test_one_user_or_critic_score_satisfies_requirement(self):
        for kind in ['user','critic']:
            entry={'image':{'url':'https://images.test/a'},'store':{'url':URL},'ratings':{kind:{'score':1,'scale':10}}}
            self.assertTrue(all(e.requirements(entry).values()))
        self.assertFalse(e.requirements({'ratings':{'user':{'score':None,'scale':10}}})['rating'])
    def test_new_basics_beat_existing_extra_source_collection(self):
        new={'id':'2','title':'New','platform':'PS5'};old={'id':'1','title':'Old','platform':'PS5'}
        phase,queue=e.select_work([old,new],{'PS5:1':{'basics_attempted':'2026','image':{'url':'x'},'store':{'url':'x'},'ratings':{'user':{'score':5,'scale':10}}}},set())
        self.assertEqual(phase,'basics');self.assertEqual(queue,[new])
    def test_source_search_requires_correct_console_and_exact_title(self):
        with patch.object(e,'psn_search',return_value=[{'__typename':'Product','name':GAME['title'],'id':'wrong','platforms':['PS4']}]),patch.object(e,'get') as get:
            with self.assertRaises(ValueError):e.resolve_psn(GAME,{}, {})
            get.assert_not_called()
    def test_null_legacy_scores_never_become_zero(self):
        entries={};e.seed([GAME],entries,{'PS5:13238':{'user':{'score':None,'scale':5}}},{},{},{},{},{})
        self.assertIsNone(entries['PS5:13238']['ratings']['user']['score']);self.assertFalse(e.requirements(entries['PS5:13238'])['rating'])
    def test_switch_eshop_folder_supported_without_cross_console(self):
        data={'@type':'VideoGame','name':GAME['title'],'gamePlatform':'Nintendo Switch','aggregateRating':{'ratingValue':5,'ratingCount':2,'bestRating':10}}
        page='<script type="application/ld+json">'+json.dumps(data)+'</script>'
        c,u=e.composites.community_data(page,'https://www.nintendolife.com/games/switch-eshop/womenup_super_puzzles_dream',{**GAME,'platform':'Switch'},'Nintendo Switch')
        self.assertEqual(u[0]['score'],5)

    def test_direct_single_switch_review_qualifies(self):
        page=(Path(__file__).parent/'fixtures/nindie-aloof.html').read_text()
        critics,image,store=e.nindie_data(page,'https://www.nindiespotlight.com/game_profile.cfm?game=aloof-switch',{'title':'ALOOF','platform':'Switch'})
        self.assertEqual(critics[0]['score'],64);self.assertEqual(critics[0]['name'],'Nindie Spotlight');self.assertTrue(store.endswith('/aloof-switch/'))
        with self.assertRaises(ValueError):e.nindie_data(page,'https://www.nindiespotlight.com/game_profile.cfm?game=aloof-switch',{'title':'Aloof','platform':'PS5'})
        with self.assertRaises(ValueError):e.nindie_data(page.replace('Nintendo Switch -','Nintendo Switch 2 -'),'https://www.nindiespotlight.com/game_profile.cfm?game=aloof-switch',{'title':'Aloof','platform':'Switch'})
    def test_console_name_and_ampersand_normalization(self):
        self.assertTrue(e.matches_name({'title':'Baby Shark: Sing & Swim Party'},'Baby Shark: Sing and Swim Party'))
        self.assertFalse(e.matches_name({'title':'Example'},''))
        self.assertEqual(e.stores.slug('Sing & Swim'),'sing-and-swim')
    def test_official_european_index_keeps_game_and_console_identity(self):
        doc=json.loads((Path(__file__).parent/'fixtures/nintendo-eu-aero.json').read_text())
        game={'title':'Aero Fighters','platform':'Switch'}
        self.assertTrue(e.nintendo_index_match(game,doc));self.assertFalse(e.nintendo_index_match({**game,'title':'Aero Fighters 2'},doc))
        self.assertFalse(e.nintendo_index_match(game,{**doc,'system_type':['nintendoswitch2_downloadsoftware']}))
        self.assertTrue(e.stores.official_url('Switch','https://www.nintendo.com/pt-pt/Jogos/Aplicacoes-de-download-da-Nintendo-Switch/Arcade-Archives-AERO-FIGHTERS-2495521.html'))
    def test_one_review_works_before_metacritic_publishes_aggregate(self):
        game={'title':'Example','platform':'Switch','id':'1'}
        def response(url):
            if '/user/' in url:return url,json.dumps({'data':{'item':{'score':0,'reviewCount':0}}})
            return url,json.dumps({'data':{'totalResults':1,'items':[{'publicationName':'A','score':75,'url':'https://review.test/a','platform':'Nintendo Switch'}]}})
        with patch.object(e,'resolve_nintendo',return_value={'image':{'url':'https://images.test/a'},'store':{'url':'https://www.nintendo.com/us/store/products/example-switch/'}}),patch.object(e,'community',return_value=([],[],{})),patch.object(e,'nindie',side_effect=ValueError('No review')),patch.object(e,'get',side_effect=response):
            entry=e.basics(game,{}, {},{},{},{},{})
        self.assertEqual(entry['ratings']['critic']['score'],75);self.assertTrue(entry['requirements']['rating'])
    def test_trademarks_and_standard_product_names_match(self):
        self.assertTrue(e.matches_name({'title':'Arcade Paradise'},'Arcade Paradise PS4™ & PS5™'))
        self.assertTrue(e.matches_name({'title':'Diablo IV'},'Diablo® IV - Standard Edition'))
        self.assertFalse(e.matches_name({'title':'Diablo IV'},'Diablo IV: Lord of Hatred - Deluxe Edition'))
        self.assertEqual(e.identity('Assault Android Cactus+'),e.identity('Assault Android Cactus Plus'))
    def test_localized_psn_search_binds_same_portugal_product(self):
        game={'title':'Asterix and Obelix XXL 3 - The Crystal Menhir','platform':'PS5','id':'13549'}
        pid='EP4295-PPSA07498_00-ASTERIXXXL3PS5EU'
        page=(Path(__file__).parent/'fixtures/psn-localized.html').read_text()
        pt={'__typename':'Product','id':pid,'name':'Astérix e Obélix XXL3: O Menir de Cristal','platforms':['PS5']}
        gb={**pt,'name':'Asterix & Obelix XXL3: The Crystal Menhir'}
        with patch.object(e,'psn_search',side_effect=[[pt],[gb]]) as search,patch.object(e,'get',return_value=('https://store.playstation.com/pt-pt/product/'+pid,page)):
            result=e.resolve_psn(game,{}, {})
        self.assertEqual(search.call_args_list[-1].args[1:],('GB','en'));self.assertIn('/pt-pt/',result['store']['url']);self.assertTrue(result['user']['score']>0)
    def test_explicit_switch_edition_alias_stays_console_specific(self):
        self.assertTrue(e.matches_name({'platform':'Switch','title':'99Vidas'},'99Vidas - Definitive Edition'))
        self.assertFalse(e.matches_name({'platform':'PS5','title':'99Vidas'},'99Vidas - Definitive Edition'))
        self.assertTrue(e.matches_name({'platform':'Switch','title':'9th Dawn III: Shadow of Erthil'},'9th Dawn III'))
    def test_wikipedia_image_requires_unique_game_article(self):
        game={'title':'64th. Street: A Detective Story','platform':'Switch'}
        entry={'title':'64th Street','thumbnail':{'source':'https://upload.wikimedia.org/wikipedia/en/example.png'},'categories':[{'title':'Category:1992 video games'}]}
        result=e.wikipedia_image_data({'query':{'pages':{'1':entry}}},game)
        self.assertIn('64th_Street',result['source'])
        with self.assertRaises(ValueError):e.wikipedia_image_data({'query':{'pages':{'1':{**entry,'categories':[{'title':'Category:Streets'}]}}}},game)
        with self.assertRaises(ValueError):e.wikipedia_image_data({'query':{'pages':{'1':entry,'2':{**entry,'title':'64th Street (2026 video game)'}}}},game)
    def test_retro_brand_names_do_not_borrow_other_platforms(self):
        self.assertTrue(e.matches_name({'title':'Bomb Jack Twin','platform':'PS5'},'Arcade Archives 2 BOMB JACK TWIN'))
        self.assertTrue(e.matches_name({'title':'Bubble Bobble','platform':'PS5'},'Console Archives BUBBLE BOBBLE'))
        self.assertFalse(e.matches_name({'title':'Balloon Fight','platform':'Switch'},'Balloon Flight'))
        self.assertFalse(e.matches_name({'title':'Donkey Kong Country','platform':'Switch'},'Donkey Kong Country Returns HD'))
        self.assertNotEqual(e.identity('Croixleur Σ'),e.identity('Croixleur'))
        self.assertEqual(e.identity('Croixleur Σ'),e.identity('Croixleur Sigma'))
