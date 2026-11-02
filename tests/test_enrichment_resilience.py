import copy,io,json,unittest,urllib.error
from unittest.mock import patch
from scripts import enrichment as e,composites as c

GAME={'title':'Example','platform':'Switch','id':'1'}
def critic(name,score):return {'name':name,'score':score,'url':f'https://{name.lower()}.test/review','platform':'Nintendo Switch'}
def user(name,score,count=100):return {'name':name,'score':score,'scale':10,'count':count,'platform':'Nintendo Switch'}
def response(body=b'{}'):
    r=io.BytesIO(body);r.geturl=lambda:'https://source.test/page';return r

class Transport(unittest.TestCase):
    def error(self,status,headers=None):return urllib.error.HTTPError('https://source.test/page',status,'error',headers or {},io.BytesIO())
    def test_transient_failure_retries_then_succeeds(self):
        with patch.object(e.urllib.request,'urlopen',side_effect=[self.error(503),TimeoutError('timeout'),response()]) as request,patch.object(e.time,'sleep'):
            self.assertEqual(e.get('https://source.test/page')[1],'{}');self.assertEqual(request.call_count,3)
    def test_retry_budget_is_bounded(self):
        with patch.object(e.urllib.request,'urlopen',side_effect=self.error(503)) as request,patch.object(e.time,'sleep'):
            with self.assertRaises(urllib.error.HTTPError):e.get('https://source.test/page')
            self.assertEqual(request.call_count,3)
    def test_not_found_and_forbidden_do_not_retry(self):
        for status in [403,404,410]:
            with self.subTest(status=status),patch.object(e.urllib.request,'urlopen',side_effect=self.error(status)) as request,patch.object(e.time,'sleep'):
                with self.assertRaises(urllib.error.HTTPError):e.get('https://source.test/page')
                self.assertEqual(request.call_count,1)
    def test_throttling_honors_retry_after_and_long_cooldown(self):
        self.assertEqual(e.retry_delay(self.error(429,{'Retry-After':'12'}),0),12)
        self.assertIsNone(e.retry_delay(self.error(429,{'Retry-After':'120'}),0))

class Refresh(unittest.TestCase):
    def test_full_refresh_keeps_sources_missing_from_new_response_and_updates_votes(self):
        previous={'title':'Example','platform':'Switch','ratings':{'critic':c.critic_composite([critic('A',90),critic('B',70)]),'user':c.user_composite([user('Metacritic users',8),user('Nintendo Life',6)]),'attempted':'2026-01-01'},'trailer':{'kind':'gameplay','id':'id'}}
        fresh={'critic':c.critic_composite([critic('A',90)]),'user':c.user_composite([user('Metacritic users',9,200)]),'attempted':'2026-02-01'}
        original=copy.deepcopy(previous)
        with patch.object(e.composites,'collect',return_value=fresh),patch.object(e,'nindie',side_effect=ValueError('unavailable')),patch.object(e,'slush_review',side_effect=ValueError('unavailable')):
            result=e.complete(GAME,previous,{}, {})
        self.assertEqual(result['ratings']['critic']['source_count'],2)
        self.assertEqual(result['ratings']['critic']['score'],80)
        self.assertEqual(result['ratings']['user']['source_count'],2)
        mc=next(s for s in result['ratings']['user']['sources'] if s['name']=='Metacritic users')
        self.assertEqual(mc['count'],200);self.assertEqual(mc['score'],9)
        self.assertEqual(previous,original)
    def test_complete_critic_index_can_replace_opaque_aggregate_without_double_counting(self):
        previous={'ratings':{'critic':c.critic_composite([{'name':'Metacritic aggregate','score':85,'url':'https://www.metacritic.com/game/example/'}])},'trailer':{'kind':'gameplay'}}
        fresh={'critic':c.critic_composite([{**critic('A',90),'via':'Metacritic review index'},{**critic('B',70),'via':'Metacritic review index'}]),'user':c.user_composite([]),'critic_index_complete':True}
        with patch.object(e.composites,'collect',return_value=fresh),patch.object(e,'nindie',side_effect=ValueError('none')),patch.object(e,'slush_review',side_effect=ValueError('none')):
            result=e.complete(GAME,previous,{}, {})
        self.assertEqual(result['ratings']['critic']['source_count'],2);self.assertEqual(result['ratings']['critic']['score'],80)
        self.assertFalse(e.opaque_critic(result['ratings']['critic']))
    def test_new_official_alias_reaches_full_and_basic_review_lookups(self):
        previous={'aliases':['Official Name'],'trailer':{'kind':'gameplay'},'ratings':{}}
        with patch.object(e.composites,'collect',return_value={'critic':c.critic_composite([]),'user':c.user_composite([])}) as collect,patch.object(e,'nindie',side_effect=ValueError('none')) as nindie,patch.object(e,'slush_review',side_effect=ValueError('none')):
            e.complete(GAME,previous,{}, {})
        self.assertIn('Official Name',collect.call_args.args[0]['aliases']);self.assertIn('Official Name',nindie.call_args.args[0]['aliases'])
    def test_just_discovered_product_alias_is_used_immediately_in_basics(self):
        with patch.object(e,'resolve_nintendo',return_value={'store':{'url':'https://official.test/game'},'image':{'url':'https://images.test/game'},'aliases':['Official Name']}),patch.object(e,'community',return_value=([],[],{})),patch.object(e,'nindie',return_value=([critic('A',75)],{},'')) as nindie:
            result=e.basics(GAME,{}, {},{},{},{},{})
        self.assertIn('Official Name',nindie.call_args.args[0]['aliases']);self.assertTrue(result['requirements']['rating'])
    def test_null_concept_default_product_is_not_a_pipeline_error(self):
        page='<script type="application/json">'+json.dumps({'cache':{'Concept:123':{'defaultProduct':None}}})+'</script>'
        self.assertIsNone(e.ratings.psn_product(page,'https://store.playstation.com/pt-pt/concept/123'))
    def test_empty_seed_fields_can_be_filled_from_verified_data(self):
        entries={'Switch:1':{'image':{'url':None},'store':{}}}
        e.seed([GAME],entries,{},{'Switch:1':{'url':'https://official.test/game'}},{},{},{'Example':{'url':'https://image.test/game'}},{})
        self.assertTrue(entries['Switch:1']['requirements']['image']);self.assertTrue(entries['Switch:1']['requirements']['store'])
    def test_incomplete_entries_retry_after_collector_upgrade(self):
        entry={'version':e.VERSION-1,'basics_attempted':e.now(),'full_attempted':e.now(),'image':{'url':'i'},'store':{'url':'s'}}
        phase,queue=e.select_work([GAME],{'Switch:1':entry},set());self.assertEqual(phase,'basics');self.assertEqual(queue,[GAME])
    def test_full_queue_resumes_oldest_attempt_instead_of_starting_at_a_each_run(self):
        a={**GAME,'id':'2','title':'A'};z={**GAME,'title':'Z'}
        def entry(stamp):return {'version':e.VERSION,'basics_attempted':e.now(),'full_attempted':stamp,'image':{'url':'i'},'store':{'url':'s'}}
        phase,queue=e.select_work([a,z],{'Switch:1':entry('2026-01-01'),'Switch:2':entry('2026-02-01')},set())
        self.assertEqual(phase,'full');self.assertEqual(queue[0],z)

class Lookups(unittest.TestCase):
    def test_product_suffix_order_does_not_hide_native_cross_gen_bundle(self):
        self.assertTrue(e.matches_name({'title':'Call of Duty: Black Ops Cold War'},'Call of Duty®: Black Ops Cold War - Cross-Gen Bundle PS4™ & PS5®'))
        self.assertFalse(e.matches_name({'title':'Call of Duty: Black Ops Cold War'},'Call of Duty®: Black Ops Cold War - Starter Pack PS4™ & PS5®'))
    def test_psn_locale_failure_does_not_block_english_search(self):
        game={'title':'Example','platform':'PS5','id':'1'};item={'__typename':'Product','id':'PID','name':'Example','platforms':['PS5']}
        with patch.object(e,'psn_search',side_effect=[OSError('PT search unavailable'),[item]]) as search,patch.object(e,'get',return_value=('https://store.playstation.com/pt-pt/product/PID','page')),patch.object(e,'psn_metadata',return_value={'store':{'url':'verified'}}):
            result=e.resolve_psn(game,{}, {})
        self.assertEqual(search.call_args.args[1:],('GB','en'));self.assertEqual(result['store']['url'],'verified')
    def test_nintendo_bad_candidate_does_not_skip_good_candidate(self):
        bad='https://www.nintendo.com/pt-pt/Jogos/Example-1.html';good='https://www.nintendo.com/pt-pt/Jogos/Example-2.html'
        docs=[{'title':'Example','system_type':['nintendoswitch_downloadsoftware'],'url':u} for u in [bad,good]]
        def get(url):
            if 'searching.nintendo' in url:return url,json.dumps({'response':{'docs':docs}})
            if url==good:return url,'<meta property="og:title" content="Example | Nintendo"><meta property="og:image" content="https://images.test/game">'
            raise OSError('dead product')
        with patch.object(e,'get',side_effect=get):result=e.resolve_nintendo(GAME,{})
        self.assertEqual(result['store']['url'],good);self.assertEqual(result['image']['url'],'https://images.test/game')
    def test_metacritic_and_community_collectors_use_official_aliases(self):
        game={**GAME,'aliases':['Official Name']}
        def get(url):
            if '/official-name/platform/' in url:
                if '/critic/' in url:return url,json.dumps({'data':{'totalResults':1,'items':[{'publicationName':'A','score':75,'url':'https://a.test/review','platform':'Nintendo Switch'}]}})
                return url,json.dumps({'data':{'item':{'score':8,'reviewCount':20}}})
            if '/official_name' in url:
                node={'@type':'VideoGame','gamePlatform':'Nintendo Switch','name':'Official Name','aggregateRating':{'ratingValue':9,'ratingCount':5,'bestRating':10}}
                return url,'<script type="application/ld+json">'+json.dumps(node)+'</script>'
            raise OSError('not found')
        with patch.object(c,'get',side_effect=get):result=c.collect(game,{})
        self.assertEqual(result['critic']['score'],75);self.assertEqual(result['user']['source_count'],2)
        self.assertTrue(result['critic_index_complete'])
