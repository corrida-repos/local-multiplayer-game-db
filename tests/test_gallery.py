import json,unittest
from scripts import gallery

def video(title,vid='abcdefghijk',channel='Some Channel',length='1:30',verified=False):
    return {'id':vid,'title':title,'channel':channel,'length':length,'verified':verified}

class YouTubeChoice(unittest.TestCase):
    def test_picks_matching_trailer(self):
        result=gallery.choose_youtube(['Sonic Mania'],[video('Sonic Mania Launch Trailer - Nintendo Switch')])
        self.assertEqual(result['kind'],'trailer');self.assertEqual(result['source'],'YouTube search')
    def test_rejects_sequels(self):
        self.assertIsNone(gallery.choose_youtube(['Monaco'],[video('Monaco 2 - Official Launch Trailer')]))
        self.assertIsNone(gallery.choose_youtube(['Double Dragon'],[video('Double Dragon II Trailer')]))
    def test_rejects_other_game_with_subtitle(self):
        self.assertIsNone(gallery.choose_youtube(['Ninja Gaiden'],[video('NINJA GAIDEN: Ragebound - Launch Trailer')]))
        self.assertIsNone(gallery.choose_youtube(['Ninja Gaiden'],[video('Ninja Gaiden Master Collection - Announcement Trailer')]))
    def test_accepts_neutral_suffixes(self):
        self.assertIsNotNone(gallery.choose_youtube(['Party Hard'],[video('Party Hard - Nintendo Switch Launch Trailer')]))
        self.assertIsNotNone(gallery.choose_youtube(['Maze Blaze'],[video('Maze Blaze | Trailer (Nintendo Switch)')]))
    def test_rejects_reviews_shorts_and_long_videos(self):
        self.assertIsNone(gallery.choose_youtube(['Chippy'],[video('Chippy Trailer Reaction')]))
        self.assertIsNone(gallery.choose_youtube(['Chippy'],[video('Chippy Trailer',length='0:12')]))
        self.assertIsNone(gallery.choose_youtube(['Chippy'],[video('Chippy Trailer',length='45:00')]))
    def test_rejected_word_inside_game_name_is_allowed(self):
        self.assertIsNotNone(gallery.choose_youtube(['The Jackbox Party Pack 3'],[video('The Jackbox Party Pack 3 - Official Trailer')]))
    def test_prefers_official_channel(self):
        result=gallery.choose_youtube(['Barony'],[video('Barony trailer',vid='aaaaaaaaaaa'),video('Barony Launch Trailer',vid='bbbbbbbbbbb',verified=True)])
        self.assertEqual(result['id'],'bbbbbbbbbbb')
    def test_name_helpers(self):
        self.assertIn('Monster Prom 3: Monster Roadtrip',gallery.name_variants(['Monster Prom 3: Monster Roadtrip XXL']))
        self.assertEqual(gallery.name_parts(['Bud Spencer and Terence Hill - Slaps And Beans']),['Slaps And Beans'])
        self.assertEqual(gallery.name_parts(['Borderlands: Handsome']),[])

class Parsing(unittest.TestCase):
    def test_youtube_results(self):
        data={'contents':[{'videoRenderer':{'videoId':'abcdefghijk','title':{'runs':[{'text':'Game Trailer'}]},'ownerText':{'runs':[{'text':'Studio'}]},'lengthText':{'simpleText':'1:02'},'ownerBadges':[{'metadataBadgeRenderer':{'style':'BADGE_STYLE_TYPE_VERIFIED'}}]}}]}
        page='<script>var ytInitialData = '+json.dumps(data)+';</script>'
        self.assertEqual(gallery.youtube_results(page),[{'id':'abcdefghijk','title':'Game Trailer','channel':'Studio','length':'1:02','verified':True}])
    def test_nintendo_gallery(self):
        item="_gItems.push({\n'isVideo': %s,\n'video_id': '%s',\n'image_url': '%s',\n'type': '%s',\n});"
        page=item%('false','','https://www.nintendo.com/eu/media/images/assets/game/Game_01.jpg','limelight')+item%('true','abcdefghijk','','youtube')+item%('false','','https://evil.example/x.jpg','limelight')
        self.assertEqual([s['url'] for s in gallery.nintendo_screenshots(page)],['https://www.nintendo.com/eu/media/images/assets/game/Game_01.jpg'])
        self.assertEqual(gallery.nintendo_video(page,'Game','https://www.nintendo.com/pt-pt/x')['id'],'abcdefghijk')
    def test_psn_screenshots(self):
        cache={'Product:P1':{'id':'P1','concept':{'__ref':'Concept:1'},'media':[{'type':'IMAGE','role':'SCREENSHOT','url':'https://image.api.playstation.com/a'},{'type':'IMAGE','role':'MASTER','url':'https://image.api.playstation.com/m'}]},'Concept:1':{'media':[{'type':'IMAGE','role':'SCREENSHOT','url':'https://image.api.playstation.com/a'},{'type':'IMAGE','role':'SCREENSHOT','url':'https://image.api.playstation.com/b'}]}}
        page='<script type="application/json">'+json.dumps({'cache':cache})+'</script>'
        self.assertEqual([s['url'] for s in gallery.psn_screenshots(page,'https://store.playstation.com/pt-pt/product/P1')],['https://image.api.playstation.com/a','https://image.api.playstation.com/b'])

if __name__=='__main__':unittest.main()
