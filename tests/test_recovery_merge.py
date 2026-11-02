import unittest
from scripts.apply_recoveries import merge_entry
from scripts import enrichment as e
class RecoveryMerge(unittest.TestCase):
    def base(self):return {'title':'Game','platform':'PS5','store':{'url':'https://official.test/new'},'ratings':{'critic':e.composites.critic_composite([{'name':'A','score':90,'url':'https://a.test/r'},{'name':'B','score':70,'url':'https://b.test/r'}]),'user':e.composites.user_composite([{'name':'PSN','score':4,'scale':5,'count':1000}])},'full_attempted':'2026-11-02'}
    def test_keeps_store_full_progress_and_richer_scores(self):
        current=self.base();new={'title':'Game','platform':'PS5','store':{'url':'https://official.test/old'},'image':{'url':'https://images.test/art'},'ratings':{'critic':e.composites.critic_composite([{'name':'A','score':90,'url':'https://a.test/r'}])}}
        result=merge_entry(current,new);self.assertEqual(result['store'],current['store']);self.assertEqual(result['ratings']['critic']['source_count'],2);self.assertEqual(result['full_attempted'],current['full_attempted']);self.assertTrue(result['requirements']['image'])
    def test_merging_twice_does_not_duplicate_votes_or_publications(self):
        current=self.base();result=merge_entry(merge_entry(current,current),current)
        self.assertEqual(result['ratings']['critic']['source_count'],2);self.assertEqual(result['ratings']['user']['source_count'],1);self.assertEqual(result['ratings']['user']['score'],8)
    def test_does_not_mix_an_opaque_aggregate_with_its_possible_constituents(self):
        current=self.base();current['ratings']['critic']=e.composites.critic_composite([{'name':'Metacritic aggregate','score':85,'url':'https://www.metacritic.com/game/game/'}]);result=merge_entry(current,self.base());self.assertEqual(result['ratings']['critic']['score'],85);self.assertEqual(result['ratings']['critic']['source_count'],1)
    def test_cannot_move_a_recovery_between_games_or_consoles(self):
        with self.assertRaises(ValueError):merge_entry(self.base(),{'platform':'Switch'})
        with self.assertRaises(ValueError):merge_entry(self.base(),{'title':'Other Game'})
    def test_older_community_snapshot_cannot_replace_newer_votes(self):
        current=self.base();current['ratings']['attempted']='2026-11-02T20:00:00Z';current['ratings']['user']=e.composites.user_composite([{'name':'Metacritic users','score':8,'scale':10,'count':1000}])
        incoming={'ratings':{'attempted':'2026-11-02T19:00:00Z','user':e.composites.user_composite([{'name':'Metacritic users','score':5,'scale':10,'count':5}])}}
        result=merge_entry(current,incoming);self.assertEqual(result['ratings']['user']['score'],8);self.assertEqual(result['ratings']['user']['sources'][0]['count'],1000)

    def test_recovery_replaces_broken_source_placeholder_with_real_image(self):
        current=self.base();current['image']={'url':'https://images.pushsquare.com//1280x720.jpg'}
        result=merge_entry(current,{'image':{'url':'https://image.api.playstation.com/game.png'}})
        self.assertEqual(result['image']['url'],'https://image.api.playstation.com/game.png')
