"""Source excerpt regressions; no live HTTP or booking interactions."""
import ast
import json
from pathlib import Path
import shutil
import subprocess
import unittest
from afternoon_tea.extraction import apply_page,extract,venue_match
from afternoon_tea.data import create_data
from afternoon_tea.master import ROOT,load_master
from afternoon_tea.pipeline import build
from afternoon_tea.validation import validate_data

URL='https://www.tablecheck.com/ja/shops/hotel-chinzanso-tokyo-jardin/reserve'
RAW=(Path(__file__).parent/'fixtures/tablecheck_jardin_excerpt.html').read_text()
class Step9Tests(unittest.TestCase):
 def data(self,raw=RAW):
  m=load_master();d=create_data(m,'2026-11-06');d['metadata']['purpose']='research'
  return d,apply_page(d,m,raw,URL)
 def test_real_excerpt_promotes_with_unknown_price_period_days(self):
  d,r=self.data();self.assertEqual(r['status'],'confirmed')
  report=validate_data(d,load_master());self.assertEqual((report['confirmed'],report['unresearched']),(1,69))
  p=next(s for a in d['areas'] for g in a['cats'].values() for s in g['shops'] if s['research']['status']=='confirmed')['plans'][0]
  self.assertIsNone(p['price_min']);self.assertIsNone(p['start']);self.assertIsNone(p['end']);self.assertEqual(p['wd'],'off')
 def test_missing_booking_not_confirmed(self):
  d,r=self.data(RAW.replace('menu-item-order-select','unknown-selector'));self.assertNotEqual(r['status'],'confirmed')
 def test_missing_menu_not_confirmed(self):
  d,r=self.data(RAW.replace('menu-item-description','unknown-selector'));self.assertNotEqual(r['status'],'confirmed')
 def test_wrong_lounge_not_matched(self):
  d,r=self.data(RAW.replace('ル・ジャルダン','別ラウンジ'));self.assertNotEqual(r['status'],'confirmed')
 def test_missing_postal_corroboration_not_matched(self):
  d,r=self.data(RAW.replace('〒112-8664',''));self.assertNotEqual(r['status'],'confirmed')
 def test_no_duplicate_promotion(self):
  d,r=self.data();apply_page(d,load_master(),RAW,URL);self.assertEqual(validate_data(d,load_master())['confirmed'],1)
 def test_real_store_html_and_local_filters(self):
  d,r=self.data();out=build(d)
  try:
   report=json.loads((out/'validation.json').read_text());self.assertEqual(report['html']['cards'],1)
   html=(out/'afternoon_tea_tokyo_2026-11-06.html').read_text()
   self.assertIn('クリスマスアフタヌーンティー',html);self.assertIn(URL,html)
   self.assertNotIn('cafe VAVA',html);self.assertIn('期間不明',html)
   if not shutil.which('node'):self.skipTest('Node is needed for local JS execution')
   js=next(ast.literal_eval(n.value) for n in ast.parse((ROOT/'build_html.py').read_text()).body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='JS' for t in n.targets))
   harness='''const fs=require('fs'),vm=require('vm');const code=JSON.parse(fs.readFileSync(0,'utf8'));
function element(dataset,on){return {dataset,hidden:false,attrs:{'aria-pressed':String(on)},classList:{toggle(k,v){if(k==='hide')this.owner.hidden=v},add(){}},getAttribute(k){return this.attrs[k]},setAttribute(k,v){this.attrs[k]=String(v)},addEventListener(k,f){this.click=f}}}
const card=element({cat:'hotel',sw:'scone',wd:'0',we:'0',pk:'0'});card.classList.owner=card;
const cat=element({cat:'hotel'},true),sweet=element({sw:'scone'},false);
const doc={querySelectorAll(q){return q==='.card'?[card]:q==='.fb'?[cat,sweet]:[]},querySelector(){return null},getElementById(){return null}};
vm.runInNewContext(code,{document:doc,window:{}});sweet.click();if(card.hidden)throw Error('sweet filter');cat.click();if(!card.hidden)throw Error('category filter');cat.click();sweet.click();if(card.hidden)throw Error('restore');'''
   result=subprocess.run(['node','-e',harness],input=json.dumps(js),text=True,capture_output=True)
   self.assertEqual(result.returncode,0,result.stderr)
  finally:shutil.rmtree(out)
 def test_known_forbidden_genre_not_promoted(self):
  from tests.test_extraction import fixture
  m=load_master();source=m['areas'][0]['cats']['cafe']['shops'][0]
  d=create_data(m,'2026-11-06');d['metadata']['purpose']='research'
  raw=fixture().replace('TEST CAFE',source['name']).replace('<td>カフェ</td>','<td>イタリアン</td>')
  r=apply_page(d,m,raw,'https://tabelog.com/tokyo/A1302/A130202/12345678/party/123/')
  self.assertIn('excluded_genre',r['reasons']);self.assertEqual(validate_data(d,m)['confirmed'],0)
 def test_known_low_rating_rejected(self):
  from tests.test_extraction import fixture
  m=load_master();source=m['areas'][0]['cats']['cafe']['shops'][0]
  d=create_data(m,'2026-11-06');d['metadata']['purpose']='research'
  raw=fixture().replace('TEST CAFE',source['name'])+'<strong class="rdheader-rating__score-val-dtl">2.99</strong>'
  r=apply_page(d,m,raw,'https://tabelog.com/tokyo/A1302/A130202/12345678/party/123/')
  self.assertIn('known_rating_below_3',r['reasons'])
 def test_real_tabelog_forbidden_genre(self):
  raw=(Path(__file__).parent/'fixtures/tabelog_vava_excerpt.html').read_text()
  m=load_master();d=create_data(m,'2026-11-06');d['metadata']['purpose']='research'
  r=apply_page(d,m,raw,'https://tabelog.com/tokyo/A1302/A130202/13226051/party/232732756/')
  self.assertIn('excluded_genre',r['reasons'])
 def test_real_ikyu_overview_not_plan(self):
  raw=(Path(__file__).parent/'fixtures/ikyu_overview_excerpt.html').read_text()
  r=extract(raw,'https://restaurant.ikyu.com/101719/','2026-11-06')
  self.assertEqual(r['plans'],[])
