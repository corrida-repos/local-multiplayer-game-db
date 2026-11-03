import json,unittest
from unittest.mock import patch
from scripts import enrichment as e, nintendo_index as ni, recovery_state as rs
from scripts.stores import name_keys,edition_key,nintendo_match

def clear():
    for cache in [ni.titles,ni.variants,ni.editions]:cache.cache_clear()

class PlatformLabels(unittest.TestCase):
    def test_platform_port_labels_identify_the_same_product(self):
        self.assertTrue(e.matches_name({'title':'The Quarry','platform':'PS5'},'The Quarry para a PS5™'))
        self.assertTrue(e.matches_name({'title':'Samurai Aces','platform':'Switch'},'Samurai Aces for Nintendo Switch™'))
        self.assertTrue(e.matches_name({'title':'ANIMALITY','platform':'Switch'},'ANIMALITY Nintendo Switch™ Version'))
        self.assertTrue(e.matches_name({'title':'Zero Gunner 2','platform':'Switch'},'ZERO GUNNER 2- for Nintendo Switch'))
    def test_descriptive_qualifiers_are_dropped_but_numbered_ones_are_not(self):
        self.assertTrue(e.matches_name({'title':'Quake (Enhanced)','platform':'PS5'},'Quake'))
        self.assertTrue(e.matches_name({'title':'Gourmet Warriors','platform':'Switch'},'Gourmet Warriors (QUByte Classics)'))
        self.assertFalse(e.matches_name({'title':'Capcom Arcade Stadium','platform':'Switch'},'Capcom Arcade Stadium Pack 1: Dawn of the Arcade (’84 – ’88)'))
        self.assertFalse(e.matches_name({'title':'DOOM','platform':'Switch'},'DOOM (1993)'))
    def test_variants_never_merge_sequels_editions_or_other_words(self):
        self.assertFalse(e.matches_name({'title':'Quake','platform':'PS5'},'Quake II'))
        self.assertFalse(e.matches_name({'title':'Nintendo Switch Sports','platform':'Switch'},'Sports'))
        self.assertFalse(e.matches_name({'title':'The Quarry','platform':'PS5'},'The Quarry — edição deluxe para PS4™ e PS5™'))
        self.assertFalse(e.matches_name({'title':'Mercenary Kings','platform':'Switch'},'Mercenary Kings: Reloaded Edition'))
        self.assertEqual(name_keys('Nintendo Switch Sports'),['nintendoswitchsports'])
    def test_exact_psn_product_is_tried_before_variant_product(self):
        exact={'__typename':'Product','name':'Quake','id':'EXACT','platforms':['PS5']}
        variant={'__typename':'Product','name':'Quake for PS5','id':'VARIANT','platforms':['PS5']}
        seen=[]
        def get(url):seen.append(url);raise OSError('stop')
        with patch.object(e,'psn_search',return_value=[variant,exact]),patch.object(e,'get',side_effect=get):
            with self.assertRaises(ValueError):e.resolve_psn({'title':'Quake','platform':'PS5'},{},{})
        self.assertTrue(seen[0].endswith('/EXACT'))

class NintendoIndex(unittest.TestCase):
    PT='https://www.nintendo.com/pt-pt/Jogos/Aplicacoes-de-download-da-Nintendo-Switch/'
    def products(self,*names):return {str(i):{'names':[name],'pt_url':self.PT+'P-'+str(i)+'.html'} for i,name in enumerate(names,1)}
    def ids(self,products,title):
        clear()
        with patch.object(ni,'load',return_value={'products':products}):result=[row['id'] for row in ni.candidates({'title':title},[title],{})]
        clear();return result
    def test_exact_title_beats_variant_and_edition(self):
        self.assertEqual(self.ids(self.products('Moon Raider','Moon Raider: Anniversary Edition'),'Moon Raider'),['1'])
    def test_platform_label_variant(self):
        self.assertEqual(self.ids(self.products('TENGAI for Nintendo Switch','Other'),'TENGAI'),['1'])
    def test_unique_standard_edition_only(self):
        self.assertEqual(self.ids(self.products('CastleStorm','Unrelated'),'CastleStorm: Definitive Edition'),['1'])
        self.assertEqual(self.ids(self.products('Game Deluxe','Game: Complete Edition'),'Game'),[])
        self.assertEqual(self.ids(self.products('Shadow of the Ninja Reborn'),'Shadow of the Ninja'),[])
        self.assertEqual(edition_key('Diablo IV: Lord of Hatred - Deluxe Edition'),'diablo4lordofhatred')
    def test_localized_subtitle_verified_by_official_product_id(self):
        game={'title':"Let's Sing 2026",'platform':'Switch'};url=self.PT+'Let-s-Sing-2026-com-Exitos-Internacionais-2929097.html'
        doc={'pt_url':url,'names':["Let's Sing 2026"],'id':'2929097'}
        page="<title>Let's Sing 2026 com Êxitos Internacionais | Jogos para a Nintendo Switch | Jogos | Nintendo</title>"
        with patch.object(ni,'candidates',return_value=[doc]),patch.object(e,'get',return_value=(url,page)):
            self.assertEqual(e.resolve_nintendo(game,{})['store']['url'],url)
        with patch.object(ni,'candidates',return_value=[{**doc,'id':'1'}]),patch.object(e,'get',return_value=(url,page)):
            with self.assertRaises(ValueError):e.resolve_nintendo(game,{})
    def test_page_title_with_platform_label(self):
        self.assertTrue(nintendo_match('<title>ANIMALITY Nintendo Switch™ Version | Nintendo</title>','ANIMALITY'))
        self.assertFalse(nintendo_match('<title>ANIMALITY 2 | Nintendo</title>','ANIMALITY'))

class Classification(unittest.TestCase):
    def test_bot_protection_redirect_loop_is_blocked_not_missing(self):
        self.assertEqual(rs.classify(ValueError('No exact Portuguese Switch listing verified: HTTP Error 302: The HTTP server returned a redirect error that would lead to an infinite loop.')),'blocked')

if __name__=='__main__':unittest.main()
