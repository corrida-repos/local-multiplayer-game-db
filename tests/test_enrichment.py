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
