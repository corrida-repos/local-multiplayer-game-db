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

class CheckpointRecovery(unittest.TestCase):
    def test_batch_pulled_during_checkpoint_survives_next_in_memory_export(self):
        import contextlib,io,json,sys,tempfile
        from pathlib import Path
        from unittest.mock import patch
        from scripts import apply_recoveries as recovery
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'data').mkdir();game={'id':'1','title':'Game','platform':'PS5'}
            (root/'data/catalog.json').write_text(json.dumps({'games':[game]}))
            entry={'title':'Game','platform':'PS5','image':{'url':'https://images.test/game.png'},'store':{'url':'https://official.test/game'},'ratings':{'user':e.composites.user_composite([{'name':'PSN','score':4,'scale':5,'count':10}])},'version':e.VERSION,'basics_attempted':e.now(),'full_attempted':e.now(),'full_version':e.VERSION}
            calls=[]
            def checkpoint(*args,**kwargs):
                calls.append(args)
                if len(calls)==1:
                    critic=e.composites.critic_composite([{'name':'New review','score':95,'url':'https://review.test/game'}])
                    (root/'data/verified-recoveries.json').write_text(json.dumps({'id':'new-during-run','entry_passes':[{'PS5:1':{'title':'Game','platform':'PS5','ratings':{'critic':critic}}}]}))
            with patch.object(e,'ROOT',root),patch.object(recovery,'ROOT',root),patch.object(e,'refresh_review_index'),patch.object(e.community_index,'refresh'),patch.object(e.community_index.load,'cache_clear'),patch.object(e.composites,'get'),patch.object(e,'basics',return_value=entry),patch.object(e.subprocess,'run',side_effect=checkpoint),patch.object(sys,'argv',['enrichment','--minutes','0.1','--workers','1','--checkpoint-push']),contextlib.redirect_stdout(io.StringIO()):
                e.main()
            saved=json.loads((root/'data/enrichment.json').read_text())['games']['PS5:1']
            self.assertEqual(saved['ratings']['critic']['score'],95)
            self.assertEqual(saved['ratings']['user']['score'],8)
            self.assertEqual(len(calls),2)
            self.assertEqual(len(json.loads((root/'data/recovery-state.json').read_text())['applied']),1)
