import datetime, unittest
from scripts.scrape import parse_game, description_section, ensure_detail_columns
import sqlite3
URL='https://www.co-optimus.com/game/123/playstation-5/test.html'
def page(local='2 Players', date='01/01/2024'):
    return f'<h1>Game &amp; Duo</h1><dt>Local Co-Op</dt><dd><em>{local}</em></dd><span class="released">{date}</span><strong>Genre:</strong> Puzzle</li>'
class Eligibility(unittest.TestCase):
    def test_local(self): self.assertEqual(parse_game(page(),URL)['players'],2)
    def test_online_only(self): self.assertIsNone(parse_game(page('Not Supported'),URL))
    def test_single_player(self): self.assertIsNone(parse_game(page('1 Player'),URL))
    def test_unreleased(self): self.assertIsNone(parse_game(page(date='01/01/2099'),URL))
    def test_unknown_date(self): self.assertIsNone(parse_game(page(date='TBA'),URL))
    def test_switch2(self):
        with self.assertRaises(ValueError): parse_game(page(),URL.replace('playstation-5','nintendo-switch2'))
    def test_changed_html(self):
        with self.assertRaises(ValueError): parse_game('<h1>Oops</h1>',URL)

class Details(unittest.TestCase):
    def test_extracts_plain_synopsis_without_heading(self):
        source='<div id="description"><h3>Description</h3><p>A &amp; B play <strong>together</strong>.</p></div>'
        self.assertEqual(description_section(source,'description'),'A & B play together .')
    def test_missing_synopsis(self):
        self.assertIsNone(description_section('<div id="other">Text</div>','description'))
    def test_detail_columns_preserve_existing_games(self):
        db=sqlite3.connect(':memory:');db.execute('CREATE TABLE games(id TEXT PRIMARY KEY,title TEXT)');db.execute("INSERT INTO games VALUES('1','Existing game')")
        ensure_detail_columns(db);ensure_detail_columns(db)
        self.assertEqual(db.execute('SELECT title,synopsis,coop_description FROM games').fetchone(),('Existing game',None,None))
        db.close()

class CoverageQueue(unittest.TestCase):
    def test_all_franchises_get_a_turn(self):
        from scripts.scrape import select_candidates
        rows=[{'url':'https://game/baldurs-gate','checked':None,'attempted':None},{'url':'https://game/mario','checked':None,'attempted':None}]
        self.assertEqual(select_candidates(rows,[r['url'] for r in rows])[0]['url'],rows[0]['url'])
    def test_failed_pages_do_not_starve_unseen_games(self):
        from scripts.scrape import select_candidates
        rows=[{'url':'a','checked':None,'attempted':'2026-11-02'},{'url':'b','checked':None,'attempted':None},{'url':'c','checked':'2026-11-01','attempted':'2026-11-01'}]
        self.assertEqual([r['url'] for r in select_candidates(rows,['a','b','c'],True)],['b','a'])
    def test_baldurs_gate_ps5_split_screen_is_eligible(self):
        from pathlib import Path
        source=(Path(__file__).parent/'fixtures/bg3-ps5.html').read_text()
        game=parse_game(source,'https://www.co-optimus.com/game/13370/playstation-5/baldur-s-gate-iii.html')
        self.assertEqual((game['platform'],game['players']),('PS5',2))
