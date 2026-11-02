import unittest
from scripts.enrichment_report import report,failure_kind
class Reporting(unittest.TestCase):
    def test_new_catalog_entries_are_gaps_not_regressions(self):
        ready={'image':{'url':'https://images.test/game.jpg'},'store':{'url':'s'},'ratings':{'user':{'score':8,'scale':10}}}
        before={'games':{'PS5:1':ready}};after={'games':{'PS5:1':ready,'Switch:2':{'errors':{'community':'HTTP Error 503'}}}}
        summary,regressions=report(before,after)
        self.assertEqual(regressions,[]);self.assertIn('1 / 2',summary);self.assertIn('1 new entries',summary);self.assertIn('temporary network failure',summary)
    def test_reports_recovered_fields_and_fails_actual_losses(self):
        before={'games':{'PS5:1':{'image':{'url':'https://images.test/game.jpg'}}}};after={'games':{'PS5:1':{'store':{'url':'s'}}}}
        summary,regressions=report(before,after)
        self.assertEqual(regressions,[('PS5:1','image')]);self.assertIn('| store | 1 | +1 | 0 |',summary)
    def test_network_and_identity_failures_have_distinct_diagnostics(self):
        self.assertEqual(failure_kind('HTTP Error 403: Forbidden'),'blocked or throttled')
        self.assertEqual(failure_kind('Different game/edition'),'identity or console rejected')
        self.assertEqual(failure_kind('No review profile indexed for this game'),'not found or no published score')
