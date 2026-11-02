import unittest
from scripts.enrichment_report import report,failure_kind
class Reporting(unittest.TestCase):
    def test_new_catalog_entries_are_gaps_not_regressions(self):
        ready={'image':{'url':'https://images.test/game.jpg'},'platform':'PS5','store':{'url':'https://store.playstation.com/pt-pt/product/GAME','region':'PT','verified':True},'ratings':{'user':{'score':8,'scale':10}}}
        before={'games':{'PS5:1':ready}};after={'games':{'PS5:1':ready,'Switch:2':{'errors':{'community':'HTTP Error 503'}}}}
        summary,regressions=report(before,after)
        self.assertEqual(regressions,[]);self.assertIn('1 / 2',summary);self.assertIn('1 new entries',summary);self.assertIn('temporary network failure',summary)
    def test_reports_recovered_fields_and_fails_actual_losses(self):
        before={'games':{'PS5:1':{'image':{'url':'https://images.test/game.jpg'}}}};after={'games':{'PS5:1':{'platform':'PS5','store':{'url':'https://store.playstation.com/pt-pt/product/GAME','region':'PT','verified':True}}}}
        summary,regressions=report(before,after)
        self.assertEqual(regressions,[('PS5:1','image')]);self.assertIn('| store | 1 | +1 | 0 |',summary)
    def test_network_and_identity_failures_have_distinct_diagnostics(self):
        self.assertEqual(failure_kind('HTTP Error 403: Forbidden'),'blocked or throttled')
        self.assertEqual(failure_kind('Different game/edition'),'identity or console rejected')
        self.assertEqual(failure_kind('No review profile indexed for this game'),'not found or no published score')

    def test_new_upstream_image_removal_is_reported_without_hiding_code_regressions(self):
        url='https://images.test/game.jpg';before={'games':{'PS5:1':{'image':{'url':url}}}}
        after={'games':{'PS5:1':{'image':{'url':url,'validation':'invalid'},'invalidations':[{'field':'image','url':url,'at':'2026-01-01'}]}}}
        summary,regressions=report(before,after);self.assertEqual(regressions,[]);self.assertIn('Confirmed upstream removals: 1',summary)
        before['games']['PS5:1']['invalidations']=after['games']['PS5:1']['invalidations']
        _,regressions=report(before,after);self.assertEqual(regressions,[('PS5:1','image')])
    def test_store_policy_migration_does_not_excuse_lost_images(self):
        before={'coverage_policy':'old','games':{'PS5:1':{'image':{'url':'https://images.test/game.jpg'}}}}
        after={'coverage_policy':'new','games':{'PS5:1':{}}}
        summary,regressions=report(before,after);self.assertIn('new baseline',summary);self.assertEqual(regressions,[('PS5:1','image')])
