import json,unittest
from unittest.mock import patch
from scripts import enrichment as e, nintendo_index as ni

PT='https://www.nintendo.com/pt-pt/Jogos/Aplicacoes-de-download-da-Nintendo-Switch/'
NSO_PAGE='''<ul><li class="page-list-group-item" data-nsuid="1" data-nt-item-title-master="Pop'n TwinBee"><img data-xs="https://www.nintendo.com/eu/media/images/SNES_PopNTwinBee.jpg" alt=""><p>Pop'n TwinBee</p></li>
<li class="page-list-group-item" data-nsuid="1" data-nt-item-title-master="Kunio-kun no Dodgeball da yo Zen'in Shūgō!**"><img data-xs="https://www.nintendo.com/eu/media/images/SNES_Kunio.jpg"></li></ul>'''

def clear():
    for cache in [ni.titles,ni.variants,ni.editions]:cache.cache_clear()

class NintendoSwitchOnline(unittest.TestCase):
    def setUp(self):e.nso_cache.clear()
    def tearDown(self):e.nso_cache.clear()
    def products(self):return {'1632515':{'names':['Super Nintendo Entertainment System – Nintendo Classics'],'pt_url':PT+'Super-Nintendo-Entertainment-System-Nintendo-Classics-1632515.html','pt_title':'Super Nintendo Entertainment System – Nintendo Classics'}}
    def resolve(self,title,page=NSO_PAGE,final=None):
        url=self.products()['1632515']['pt_url']
        with patch.object(ni,'load',return_value={'products':self.products()}),patch.object(e,'get',return_value=(final or url,page)):
            return e.resolve_nso({'title':title,'platform':'Switch'})
    def test_listed_classic_links_to_official_app_with_its_own_artwork(self):
        result=self.resolve("Pop'n Twinbee")
        self.assertTrue(result['store']['verified']);self.assertEqual(result['store']['region'],'PT')
        self.assertIn('Super Nintendo Entertainment System',result['store']['note'])
        self.assertTrue(result['image']['url'].endswith('SNES_PopNTwinBee.jpg'))
        self.assertEqual(self.resolve('Kunio-kun no Dodge Ball da yo: Zenin Shūgo')['store']['nso_title'],"Kunio-kun no Dodgeball da yo Zen'in Shūgō!")
    def test_unlisted_game_and_foreign_redirect_are_rejected(self):
        with self.assertRaises(ValueError):self.resolve('TwinBee 2')
        e.nso_cache.clear()
        with self.assertRaises(ValueError):self.resolve("Pop'n Twinbee",final='https://www.nintendo.com/en-gb/Games/SNES-1632515.html')

class CatalogReserved(unittest.TestCase):
    def test_loose_tiers_never_claim_a_product_named_after_another_catalog_game(self):
        products={'1':{'names':['Gelly Break Deluxe'],'pt_url':PT+'Gelly-Break-Deluxe-1.html'}}
        clear()
        with patch.object(ni,'load',return_value={'products':products}):
            self.assertEqual([r['id'] for r in ni.candidates({'title':'Gelly Break'},['Gelly Break'],{})],['1'])
            self.assertEqual(ni.candidates({'title':'Gelly Break'},['Gelly Break'],{},frozenset({'gellybreakdeluxe'})),[])
        clear()
    def test_wrong_existing_link_is_released(self):
        products={'1476593':{'names':['Gelly Break Deluxe'],'pt_url':PT+'Gelly-Break-Deluxe-1476593.html'}}
        entry={'store':{'url':PT+'Gelly-Break-Deluxe-1476593.html','region':'PT','verified':True},'aliases':['Gelly Break','Gelly Break Deluxe'],'field_status':{'store':{}}}
        with patch.object(ni,'load',return_value={'products':products}):
            self.assertTrue(e.release_reserved_store({'title':'Gelly Break','platform':'Switch'},entry,frozenset({'gellybreakdeluxe'})))
            kept={'store':{'url':PT+'Gelly-Break-Deluxe-1476593.html'}}
            self.assertFalse(e.release_reserved_store({'title':'Gelly Break Deluxe','platform':'Switch'},kept,frozenset({'gellybreak'})))
        self.assertNotIn('store',entry);self.assertEqual(entry['aliases'],['Gelly Break']);self.assertIn('store_released',entry)

class PsnEditions(unittest.TestCase):
    def tier(self,title,name,reserved=frozenset()):
        with patch.object(e,'reserved_titles',return_value=reserved):return e.psn_edition_tier({'title':title,'platform':'PS5'},name)
    def test_edition_names_of_the_same_title(self):
        self.assertTrue(self.tier("Don't Starve Together","Don't Starve Together: Console Edition"))
        self.assertTrue(self.tier('The Last Oricru','The Last Oricru - Final Cut'))
        self.assertTrue(self.tier('Nikoderiko: The Magical World','Nikoderiko: The Magical World - Versão do Diretor'))
        self.assertTrue(self.tier('Tesla vs Lovecraft Game of the Year Edition','Tesla vs Lovecraft'))
    def test_expansions_sequels_and_reserved_titles_are_not_editions(self):
        self.assertFalse(self.tier('Diablo IV','Diablo IV: Lord of Hatred - Deluxe Edition'))
        self.assertFalse(self.tier('Sea of Stars','Sea of Stars: Throes of the Watchmaker'))
        self.assertFalse(self.tier('Quake','Quake II'))
        self.assertFalse(self.tier('Game','Game: Deluxe Edition',frozenset({'gamedeluxeedition'})))
    def test_exact_match_never_reaches_edition_tier(self):
        self.assertFalse(e.matches_name({'title':'Diablo IV'},'Diablo IV: Lord of Hatred - Deluxe Edition'))

class MetacriticSearch(unittest.TestCase):
    def test_search_slug_requires_title_and_exact_console(self):
        items=[{'slug':'chef-chen','title':'Chef Chen','platforms':[{'name':'Nintendo Switch'}]},
               {'slug':'chef-chen-2','title':'Chef Chen 2','platforms':[{'name':'Nintendo Switch'}]},
               {'slug':'chef-chen-pc','title':'Chef Chen','platforms':[{'name':'PC'}]}]
        with patch.object(e,'get',return_value=('u',json.dumps({'data':{'items':items}}))):
            self.assertEqual(e.metacritic_search({'title':'Chef Chen: Fantasy Cook','platform':'Switch','aliases':['Chef Chen']},'Nintendo Switch'),['chef-chen'])

if __name__=='__main__':unittest.main()
