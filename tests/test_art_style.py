import unittest
from scripts import art_style

class PixelArt(unittest.TestCase):
    def test_steam_tag_needs_a_few_votes(self):
        self.assertTrue(art_style.pixel_from_tags({'Indie': 161, 'Pixel Graphics': 134}))
        self.assertTrue(art_style.pixel_from_tags({'Action': 821, 'Pixel Graphics': 84}))
        self.assertFalse(art_style.pixel_from_tags({'Indie': 30, 'Pixel Graphics': 3}))
        self.assertFalse(art_style.pixel_from_tags({'Indie': 100, 'Action': 90}))

    def test_description_mentions(self):
        game = lambda text: {'synopsis': text, 'coop_description': None}
        self.assertTrue(art_style.pixel_from_text(game('Enjoy its pixel art and epic music.')))
        self.assertTrue(art_style.pixel_from_text(game('Brought to you in 16-bit pixelated glory')))
        self.assertTrue(art_style.pixel_from_text(game('A retro 8-bit platformer')))
        self.assertFalse(art_style.pixel_from_text(game('Features a 16-bit soundtrack')))
        self.assertFalse(art_style.pixel_from_text(game('A colourful 3D party game')))

    def test_override_beats_evidence_and_either_source_counts(self):
        pixel_text = {'synopsis': 'pixel art', 'coop_description': ''}
        self.assertEqual(art_style.classify({'steam_tags': {'Pixel Graphics': 100}}, pixel_text, False), (False, 'manual'))
        self.assertEqual(art_style.classify({'steam_tags': {'Pixel Graphics': 100}}, {'synopsis': '3D'}, None), (True, 'Steam tags'))
        self.assertEqual(art_style.classify({'steam_tags': {'3D': 100}}, pixel_text, None), (True, 'description'))
        self.assertEqual(art_style.classify({'steam_tags': {'3D': 100}}, {'synopsis': '3D'}, None), (False, 'Steam tags'))
        self.assertEqual(art_style.classify({}, pixel_text, None), (True, 'description'))
        self.assertEqual(art_style.classify({}, {'synopsis': '3D'}, None), (False, 'no evidence'))

if __name__ == '__main__':
    unittest.main()
