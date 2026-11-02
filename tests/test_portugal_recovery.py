import copy,datetime as dt,io,json,unittest,urllib.error
from unittest.mock import patch
from scripts import enrichment as e,nintendo_index as ni,recovery_state as rs,direct_reviews as dr
PT='https://www.nintendo.com/pt-pt/Jogos/Example-123.html'
PS='https://store.playstation.com/pt-pt/product/EXAMPLE'
GAME={'id':'1','title':'Example','platform':'Switch'}
class Portugal(unittest.TestCase):
    def test_foreign_store_is_evidence_and_never_completeness(self):
        entry={'platform':'Switch','store':{'url':'https://www.nintendo.com/us/store/products/example-switch/','checked':e.now()},'image':{'url':'https://images.test/game.png'},'ratings':{'user':{'score':8,'scale':10}}}
        original=copy.deepcopy(entry);e.migrate_entry(GAME,entry)
        self.assertNotIn('store',entry);self.assertEqual(entry['store_evidence'][0],original['store']);self.assertFalse(e.requirements(entry)['store']);self.assertEqual(entry['ratings'],original['ratings'])
    def test_historically_verified_portuguese_store_migrates_idempotently(self):
        entry={'store':{'url':PT,'checked':'2026-01-01'}};e.migrate_entry(GAME,entry);again=copy.deepcopy(entry);e.migrate_entry(GAME,entry)
        self.assertTrue(e.requirements(entry)['store']);self.assertEqual(entry,again)
    def test_localized_official_titles_join_only_by_same_product_id(self):
        pt={'fs_id':'1','title':'Nome português','url':'/pt-pt/Jogos/Example-123.html','system_type':['nintendoswitch_downloadsoftware']}
        en={**pt,'title':'Example','url':'/en-gb/Games/Example-123.html'}
        products=ni.combine([pt],[en,{**en,'fs_id':'2','title':'Example 2','system_type':['nintendoswitch2_gamecard']}])
        self.assertEqual(set(products),{'1'});self.assertEqual(products['1']['names'],['Nome português','Example'])
        ni.titles.cache_clear()
        with patch.object(ni,'load',return_value={'products':products}):
            rows=ni.candidates(GAME,['Example'],{});self.assertEqual(rows[0]['pt_url'],PT)
        ni.titles.cache_clear()
    def test_portugal_redirect_to_foreign_store_is_rejected(self):
        doc={'pt_url':PT,'names':['Example'],'id':'1'}
        def get(url):
            if url==PT:return 'https://www.nintendo.com/en-gb/Games/Example-123.html','<title>Example | Nintendo</title>'
            return url,json.dumps({'response':{'docs':[]}})
        with patch.object(ni,'candidates',return_value=[doc]),patch.object(e,'get',side_effect=get):
            with self.assertRaises(ValueError):e.resolve_nintendo(GAME,{})
    def test_native_portuguese_product_verified_with_localized_title(self):
        doc={'pt_url':PT,'names':['Example','Nome português'],'id':'1'}
        with patch.object(ni,'candidates',return_value=[doc]),patch.object(e,'get',return_value=(PT,'<title>Nome português | Nintendo</title>')):
            value=e.resolve_nintendo(GAME,{})
        self.assertEqual(value['store']['region'],'PT');self.assertTrue(value['store']['verified'])
    def test_rating_recovery_does_not_refetch_completed_image_or_store(self):
        prev={'platform':'Switch','title':'Example','store':{'url':PT,'region':'PT','verified':True},'image':{'url':'https://images.test/game.png'}}
        with patch.object(e,'resolve_nintendo') as store,patch.object(e,'community',return_value=([],[{'name':'Nintendo Life','score':6,'scale':10,'count':1,'platform':'Nintendo Switch'}],{})),patch.object(e,'wikipedia_image') as image:
            result=e.basics(GAME,prev,{},{},{},{},{})
        store.assert_not_called();image.assert_not_called();self.assertEqual(result['ratings']['user']['score'],6);self.assertEqual(result['field_status']['rating']['sources']['community']['status'],'verified')
    def test_search_follows_pagination_to_full_game_after_first_page(self):
        def response(url,headers):
            variables=json.loads(e.urllib.parse.parse_qs(e.urllib.parse.urlparse(url).query)['variables'][0]);second=variables['pageOffset']>0
            return url,json.dumps({'data':{'universalSearch':{'results':[{'id':'full' if second else 'dlc'}],'next':None if second else 'cursor','pageInfo':{'isLast':second}}}})
        with patch.object(e,'get',side_effect=response):results=e.psn_search('Example')
        self.assertEqual([r['id'] for r in results],['dlc','full'])

class Attempts(unittest.TestCase):
    def test_missing_fields_remain_due_daily_and_upgrade_bypasses_cache(self):
        clock=dt.datetime(2026,1,1,tzinfo=dt.timezone.utc);entry={}
        rs.record(entry,'nintendo',['store'],'v1','not_found','No PT listing',clock=clock)
        self.assertFalse(rs.due(entry,'nintendo',['store'],'v1',clock+dt.timedelta(hours=23)))
        self.assertTrue(rs.due(entry,'nintendo',['store'],'v1',clock+dt.timedelta(days=1)))
        self.assertTrue(rs.due(entry,'nintendo',['store'],'v2',clock))
    def test_retries_are_field_specific_and_survive_json_roundtrip(self):
        clock=dt.datetime(2026,1,1,tzinfo=dt.timezone.utc);entry={};rs.record(entry,'community',['rating'],'v1','not_found',clock=clock);entry=json.loads(json.dumps(entry))
        self.assertTrue(rs.due(entry,'community',['image'],'v1',clock));self.assertFalse(rs.due(entry,'community',['rating'],'v1',clock))
    def test_transient_errors_retry_hourly_and_long_server_cooldown_is_kept(self):
        clock=dt.datetime(2026,1,1,tzinfo=dt.timezone.utc);entry={};rs.record(entry,'a',['rating'],'v1','retryable_error',clock=clock)
        self.assertTrue(rs.due(entry,'a',['rating'],'v1',clock+dt.timedelta(hours=1)))
        exc=urllib.error.HTTPError('https://source.test',429,'slow',{'Retry-After':'172800'},io.BytesIO());rs.record(entry,'b',['rating'],'v1','blocked',clock=clock,exc=exc)
        self.assertFalse(rs.due(entry,'b',['rating'],'v1',clock+dt.timedelta(days=1)))
    def test_exhausted_game_cannot_starve_an_unchecked_game(self):
        clock=rs.utc();first={'platform':'Switch','version':e.VERSION,'basics_attempted':e.now()}
        revision=rs.revision(GAME,[])
        for source,fields in e.source_registry(GAME).items():rs.record(first,source,list(fields),revision,'not_found',clock=clock)
        second={**GAME,'id':'2','title':'Other'}
        phase,queue=e.select_work([GAME,second],{'Switch:1':first},set());self.assertEqual(phase,'basics');self.assertEqual(queue,[second])

class ImageHealth(unittest.TestCase):
    def base(self):return {'platform':'Switch','image':{'url':'https://images.test/game.jpg','validation':'verified','validated_at':'2026-01-01'}}
    def response(self,kind='image/jpeg'):
        r=io.BytesIO(b'');r.headers={'Content-Type':kind,'Content-Length':'100'};r.geturl=lambda:'https://images.test/game.jpg';return r
    def test_actual_image_response_records_health(self):
        with patch.object(e.urllib.request,'urlopen',return_value=self.response()),patch.object(e.time,'sleep'):
            value=e.verify_image(GAME,self.base())
        self.assertEqual(value['image']['validation'],'verified');self.assertTrue(value['field_status']['image']['sources']['image_health']['last_success'])
    def test_html_and_404_invalidate_image_but_timeout_retains_last_good(self):
        for response in [self.response('text/html'),urllib.error.HTTPError('https://images.test/game.jpg',404,'gone',{},io.BytesIO()),TimeoutError('temporary')]:
            options={'side_effect':response} if isinstance(response,Exception) else {'return_value':response}
            with patch.object(e.urllib.request,'urlopen',**options),patch.object(e.time,'sleep'):value=e.verify_image(GAME,self.base())
            self.assertEqual(e.requirements(value)['image'],isinstance(response,TimeoutError))
    def test_invalidated_image_is_eligible_for_later_health_recheck(self):
        value=self.base();value['image']['validation']='invalid';self.assertTrue(e.image_health_due(value))

class Reviews(unittest.TestCase):
    def test_psu_console_review_uses_own_score(self):
        page=(__import__('pathlib').Path(__file__).parent/'fixtures/psu-console-review.html').read_text()
        url='https://www.psu.com/reviews/toy-story-3-complete-edition-review-ps5/'
        value=dr.data(page,url,{'title':'Toy Story 3 Complete Edition','platform':'PS5'},'psu');self.assertEqual(value['score'],70)
        with self.assertRaises(ValueError):dr.data(page,url,{'title':'Toy Story 3 Complete Edition','platform':'Switch'},'psu')
    def test_nwr_article_score_is_not_a_recommendation_card(self):
        page='<title>Coffee Talk Tokyo Review - Review - Nintendo World Report</title><div id="article"><div class="score"><div class="sc8">8</div></div>'
        url='https://www.nintendoworldreport.com/review/75580/coffee-talk-tokyo-switch-review';game={'title':'Coffee Talk Tokyo','platform':'Switch'}
        self.assertEqual(dr.data(page,url,game,'nwr')['score'],80)
        with self.assertRaises(ValueError):dr.data(page.replace('id="article"','id="recommendations"'),url,game,'nwr')
    def test_pure_review_requires_switch_one_and_own_explicit_scale(self):
        page='<title>Review: Example (Nintendo Switch)</title><span itemprop="reviewRating"><span itemprop="ratingValue">7.5</span><meta itemprop="bestRating" content="10"/></span>'
        url='https://purenintendo.com/review-example-nintendo-switch/';self.assertEqual(dr.data(page,url,GAME,'pure')['score'],75)
        with self.assertRaises(ValueError):dr.data(page.replace('(Nintendo Switch)','(Nintendo Switch 2)'),url,GAME,'pure')
        with self.assertRaises(ValueError):dr.data(page.replace('content="10"','content="0"'),url,GAME,'pure')
    def test_sequel_or_foreign_publication_is_rejected(self):
        self.assertIsNone(dr.review_title('pure','https://purenintendo.com/review-example-switch-2/'))
        self.assertIsNone(dr.review_title('psu','https://evil.test/reviews/example-review-ps5/'))
        page='<title>Review: Example 2 (Nintendo Switch)</title>'
        with self.assertRaises(ValueError):dr.data(page,'https://purenintendo.com/review-example-2-nintendo-switch/',GAME,'pure')
