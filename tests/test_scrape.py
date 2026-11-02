import datetime, unittest
from scripts.scrape import parse_game
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
