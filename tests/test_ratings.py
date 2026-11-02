import json,unittest
from scripts.ratings import mc_critic,mc_user,psn_rating
class Scores(unittest.TestCase):
    def test_platform_specific_critic(self):
        a=[{'slug':1,'platforms':2,'criticScoreSummary':8},'game',[3,4],{'name':5,'criticScoreSummary':7},{'name':6,'criticScoreSummary':8},'PlayStation 5','Nintendo Switch',{'score':9},{'score':10},88,82]
        page='<script id="__NUXT_DATA__">'+json.dumps(a)+'</script>'
        self.assertEqual(mc_critic(page,'game','Nintendo Switch'),82)
        self.assertEqual(mc_critic(page,'game','PlayStation 5'),88)
        self.assertIsNone(mc_critic(page,'another-game','PlayStation 5'))
    def test_user_requires_platform_and_scale(self):
        a=[{'max':1,'score':2,'reviewCount':3,'url':4},10,8.4,500,'/game/game/user-reviews/?platform=nintendo-switch']
        page='<script id="__NUXT_DATA__">'+json.dumps(a)+'</script>'
        self.assertEqual(mc_user(page,'game','nintendo-switch'),8.4)
        self.assertIsNone(mc_user(page,'game','playstation-5'))
        a[3]=2
        self.assertIsNone(mc_user('<script id="__NUXT_DATA__">'+json.dumps(a)+'</script>','game','nintendo-switch'))
    def psn(self,platforms):
        return '<script type="application/json">'+json.dumps({'cache':{'concept':{'__typename':'Concept','defaultProduct':{'__ref':'game'}},'game':{'platforms':platforms,'starRating':{'averageRating':4.54,'totalRatingsCount':100}}}})+'</script>'
    def test_psn_scale(self):self.assertEqual(psn_rating(self.psn(['PS5']))['score'],4.54)
    def test_psn_no_ps4_only_substitution(self):self.assertIsNone(psn_rating(self.psn(['PS4'])))
    def test_shared_psn_rating_label(self):self.assertIn('PS4/PS5',psn_rating(self.psn(['PS4','PS5']))['scope'])
