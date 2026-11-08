import json, sqlite3, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from scripts import score_filter, scrape

def user(score, scale=10, attempted='2026-11-01'):
    return {'ratings': {'attempted': attempted, 'user': {'score': score, 'scale': scale}}}

class LowUserScore(unittest.TestCase):
    def sources(self, enrichment=None, composites=None, ratings=None):
        return {'enrichment': enrichment or {}, 'composites': composites or {}, 'ratings': ratings or {}}

    def test_threshold_is_inclusive_on_both_scales(self):
        s = self.sources(enrichment={'PS5:1': user(4.0), 'PS5:2': user(4.01), 'PS5:3': user(2, 5), 'PS5:4': user(2.1, 5)})
        self.assertEqual([score_filter.is_low_rated(k, s) for k in ['PS5:1', 'PS5:2', 'PS5:3', 'PS5:4']], [True, False, True, False])

    def test_games_without_user_score_are_kept(self):
        s = self.sources(enrichment={'PS5:1': user(None)})
        self.assertFalse(score_filter.is_low_rated('PS5:1', s))
        self.assertFalse(score_filter.is_low_rated('PS5:404', s))

    def test_resolution_matches_website(self):
        # A newer legacy composite wins over older enrichment ratings, as in website/app.js ratingFor.
        newer = {'attempted': '2026-11-05', 'user': {'score': 8, 'scale': 10}}
        s = self.sources(enrichment={'Switch:1': user(3, attempted='2026-11-01')}, composites={'Switch:1': newer})
        self.assertFalse(score_filter.is_low_rated('Switch:1', s))
        # Legacy single-source rating is the last fallback.
        s = self.sources(ratings={'Switch:2': {'user': {'score': 1.5, 'scale': 5}}})
        self.assertTrue(score_filter.is_low_rated('Switch:2', s))

    def test_export_removes_low_rated_games_from_database_and_catalog(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root/'data').mkdir()
            (root/'data/enrichment-public.json').write_text(json.dumps({'games': {'PS5:1': user(3.9), 'PS5:2': user(7.5)}}))
            db = sqlite3.connect(':memory:'); db.row_factory = sqlite3.Row
            db.executescript("CREATE TABLE games(id TEXT PRIMARY KEY,title TEXT,platform TEXT); CREATE TABLE pages(url TEXT,checked TEXT);"
                             "INSERT INTO games VALUES('1','Bad','PS5'),('2','Good','PS5'),('3','Unrated','PS5');")
            with patch.object(scrape, 'ROOT', root): result = scrape.export_catalog(db, [], [])
            self.assertEqual([g['title'] for g in result['games']], ['Good', 'Unrated'])
            self.assertEqual(result['excluded_low_user_score'], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM games WHERE id='1'").fetchone()[0], 0)
            self.assertEqual(json.loads((root/'data/catalog.json').read_text(encoding='utf-8'))['excluded_low_user_score'], 1)
            db.close()

if __name__ == '__main__': unittest.main()
