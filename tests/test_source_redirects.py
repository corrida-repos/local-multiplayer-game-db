import io,json,unittest,urllib.error
from unittest.mock import patch
from scripts import enrichment as e
class Redirects(unittest.TestCase):
    def response(self):
        response=io.BytesIO(b'{"ok":true}');response.geturl=lambda:'https://backend.metacritic.com/reviews/metacritic/user/games/airheart/platform/nintendo-switch/stats/web';return response
    def error(self,platform):
        return urllib.error.HTTPError('https://backend.metacritic.com',301,'Moved',{},io.BytesIO(json.dumps({'errors':[{'context':{'availableOn':[{'slug':'airheart/'+platform}]}}]}).encode()))
    def test_canonical_slug_uses_requested_console(self):
        url='https://backend.metacritic.com/reviews/metacritic/user/games/airheart-tales-of-broken-wings/platform/nintendo-switch/stats/web'
        with patch.object(e.urllib.request,'urlopen',side_effect=[self.error('nintendo-switch'),self.response()]) as request,patch.object(e.time,'sleep'):
            final,page=e.get(url)
        self.assertIn('/games/airheart/platform/nintendo-switch/',request.call_args.args[0].full_url);self.assertEqual(json.loads(page),{'ok':True})
    def test_never_redirects_to_pc_or_another_console(self):
        url='https://backend.metacritic.com/reviews/metacritic/user/games/airheart-tales-of-broken-wings/platform/nintendo-switch/stats/web'
        with patch.object(e.urllib.request,'urlopen',side_effect=self.error('pc')) as request,patch.object(e.time,'sleep'):
            with self.assertRaises(urllib.error.HTTPError):e.get(url)
        self.assertEqual(request.call_count,1)
