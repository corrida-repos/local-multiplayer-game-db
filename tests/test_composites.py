import json,math,unittest
from unittest.mock import patch
from scripts.composites import critic_composite,user_composite,community_data,collect
class Composites(unittest.TestCase):
    def test_duplicate_publication_is_counted_once(self):
        result=critic_composite([{'name':'A','score':90,'url':'https://www.outlet.test/a','date':'2024'},{'name':'A','score':80,'url':'https://outlet.test/b','date':'2023'},{'name':'B','score':70,'url':'https://b.test/review'}])
        self.assertEqual(result['score'],80);self.assertEqual(result['source_count'],2)
    def test_scales_and_capped_community_weight(self):
        result=user_composite([{'score':4,'scale':5,'count':1000000},{'score':6,'scale':10,'count':1000}])
        self.assertEqual(result['score'],7);self.assertEqual(result['sources'][0]['weight'],math.sqrt(1000))
    def test_no_invented_scores(self):
        self.assertIsNone(user_composite([{'score':0,'scale':10,'count':0}])['score']);self.assertIsNone(critic_composite([])['score'])
    def test_reject_other_console(self):
        page='<script type="application/ld+json">'+json.dumps({'@type':'VideoGame','gamePlatform':'PC','name':'Example'})+'</script>'
        with self.assertRaises(ValueError):community_data(page,'https://www.pushsquare.com/games/ps5/example',{'title':'Example','platform':'PS5'},'PlayStation 5')
    def test_incomplete_critic_index_does_not_average_high_scoring_prefix(self):
        first={'data':{'totalResults':20,'items':[{'platform':'PlayStation 5','publicationName':'A','score':100,'url':'https://a.test/review'}]}}
        def response(url):
            if 'offset=0&' in url:return url,json.dumps(first)
            raise OSError('source unavailable')
        with patch('scripts.composites.get',side_effect=response):result=collect({'title':'Example','platform':'PS5'},{'critic':{'score':72,'url':'https://metacritic.com/game/example'}})
        self.assertEqual(result['critic']['score'],72);self.assertFalse(result['critic_index_complete']);self.assertEqual(result['critic']['source_count'],1)
    def test_complete_pagination_and_platform_filter(self):
        calls=[]
        def response(url):
            calls.append(url)
            if 'offset=0&' in url:items=[{'platform':'PlayStation 5','publicationName':'A','score':100,'url':'https://a.test/r'}]
            elif 'offset=1&' in url:items=[{'platform':'PlayStation 5','publicationName':'B','score':60,'url':'https://b.test/r'},{'platform':'PC','publicationName':'PC outlet','score':10,'url':'https://pc.test/r'}]
            else:raise OSError('no community data')
            return url,json.dumps({'data':{'totalResults':3,'items':items}})
        with patch('scripts.composites.get',side_effect=response):result=collect({'title':'Example','platform':'PS5'},{})
        self.assertEqual(result['critic']['score'],80);self.assertEqual(result['critic']['source_count'],2);self.assertTrue(result['critic_index_complete'])
