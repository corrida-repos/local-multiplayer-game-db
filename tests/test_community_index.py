import json,unittest
from pathlib import Path
from unittest.mock import patch
from scripts import community_index as ci,composites as c
URL='https://www.nintendolife.com/games/switch-eshop/arcade_archives_64th_street'
GAME={'title':'64th. Street: A Detective Story','platform':'Switch','aliases':['64th Street']}
class Community(unittest.TestCase):
    def setUp(self):self.page=(Path(__file__).parent/'fixtures/community-visible-rating.html').read_text()
    def test_actual_visible_rating_qualifies_without_schema_aggregate(self):
        critics,users=c.community_data(self.page,URL,GAME,'Nintendo Switch')
        self.assertEqual(critics,[]);self.assertEqual(users[0]['score'],4.67);self.assertEqual(users[0]['count'],3);self.assertEqual(users[0]['scale'],10)
    def test_single_visible_vote_is_valid_but_zero_or_missing_votes_are_not(self):
        page=self.page.replace('User Ratings: 3','User Ratings: 1')
        self.assertEqual(c.community_data(page,URL,GAME,'Nintendo Switch')[1][0]['count'],1)
        for count in ['0','N/A','']:
            with self.subTest(count=count):self.assertEqual(c.community_data(self.page.replace('User Ratings: 3','User Ratings: '+count),URL,GAME,'Nintendo Switch')[1],[])
    def test_recommendations_outside_own_panel_cannot_supply_score(self):
        page=self.page.replace('class="user-rating"','class="recommendations"')
        self.assertEqual(c.community_data(page,URL,GAME,'Nintendo Switch')[1],[])
    def test_identity_and_console_are_verified_before_visible_score(self):
        for game,expected in [({**GAME,'title':'Another Game','aliases':[]},'Nintendo Switch'),({**GAME,'platform':'PS5'},'PlayStation 5')]:
            with self.assertRaises(ValueError):c.community_data(self.page,URL,game,expected)
    def test_unrelated_structured_recommendation_cannot_validate_other_profile(self):
        with self.assertRaises(ValueError):c.community_data(self.page,URL.replace('64th_street','another_game'),GAME,'Nintendo Switch')
    def test_structured_average_and_panel_are_counted_once(self):
        page=self.page.replace('"@type": "VideoGame"','"aggregateRating": {"ratingValue": 5, "ratingCount": 30, "bestRating": 10}, "@type": "VideoGame"')
        users=c.community_data(page,URL,GAME,'Nintendo Switch')[1]
        self.assertEqual(len(users),1);self.assertEqual(users[0]['score'],5)
    def test_critic_panel_needs_explicit_score_and_scale(self):
        page=self.page.replace('Our Review: N/A','Our Review: 7/10')
        self.assertEqual(c.community_data(page,URL,GAME,'Nintendo Switch')[0][0]['score'],70)
    def test_exact_sitemap_match_keeps_native_console_only(self):
        urls=[URL,URL.replace('switch-eshop','switch-2-eshop'),URL.replace('www.nintendolife.com','evil.test'),URL+'/reviews',URL.replace('https:','http:')]
        page='<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+''.join('<url><loc>'+u+'</loc></url>' for u in urls)+'</urlset>'
        self.assertEqual(ci.parse_sitemap(page,'Switch'),{'64thstreet':[URL]})
        self.assertEqual(ci.parse_sitemap(page,'PS5'),{})
    def test_index_url_precedes_guessed_slug_but_does_not_expand_title_fuzzily(self):
        index={'platforms':{'Switch':{'games':{'64thstreet':[URL],'anothergame':[URL.replace('64th_street','another_game')]}}}}
        with patch.object(ci,'load',return_value=index):urls=ci.candidates(GAME)
        self.assertEqual(urls[0],URL);self.assertNotIn(URL.replace('64th_street','another_game'),urls)
