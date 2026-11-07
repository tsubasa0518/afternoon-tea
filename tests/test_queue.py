"""Queue/persistence/discovery regressions; no live HTTP requests."""
import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock,patch
from afternoon_tea.master import load_master
from afternoon_tea.research_store import create_queue,new_state,load_state,save_state,atomic_json,add_discovery,differences
from afternoon_tea.research_queue import process,public_links
from afternoon_tea.discovery import listing_links
from afternoon_tea.extraction import extract,apply_page
from afternoon_tea.structured import identity

TC='https://www.tablecheck.com/ja/shops/test/reserve'
SPLIT='''<!-- TEST_ONLY synthetic plan blocks -->
<div class="menu-category-section"><div class="menu-item"><div class="menu-item-name">秋のアフタヌーンティー Stones</div><div class="menu-item-description">スコーンとケーキ</div>提供期間: 2026年9月1日～11月30日</div>
<div class="menu-item"><div class="menu-item-name">アフタヌーンティー Stones</div><div class="menu-item-order-select">選択する</div></div></div>'''
class QueueTests(unittest.TestCase):
 def test_all_75_registered(self):
  q=create_queue(load_master());self.assertEqual(len(q),75);self.assertEqual(len({x['id'] for x in q}),75)
  self.assertEqual(sum(x['kind']=='candidate' for x in q),5);self.assertEqual({x['area'] for x in q},set(range(1,15)))
 def test_resume_same_day_preserves_processed_status(self):
  m=load_master();s=new_state(m,'2026-11-07');s['items'][0].update(status='failed',reason='TEST_ONLY timeout')
  with tempfile.TemporaryDirectory() as tmp:
   save_state(tmp,s,m);r=load_state(tmp,m,'2026-11-07');self.assertEqual(r['items'][0]['status'],'failed');self.assertEqual(r['items'][0]['reason'],'TEST_ONLY timeout')
 def test_next_day_resets_current_confirmation_and_keeps_history(self):
  m=load_master();s=new_state(m,'2026-11-06');s['items'][0]['status']='confirmed'
  r=new_state(m,'2026-11-07',s);self.assertEqual(r['items'][0]['status'],'unresearched');self.assertEqual(r['items'][0]['history'][-1]['status'],'confirmed')
  self.assertEqual(sum(x['research']['status']=='confirmed' for a in r['data']['areas'] for g in a['cats'].values() for x in g['shops']),0)
 def test_new_discovery_dedup_and_next_day(self):
  m=load_master();s=new_state(m,'2026-11-07');u='https://restaurant.ikyu.com/123456'
  self.assertTrue(add_discovery(s,u,'TEST_ONLY cafe',1,u,'2026-11-07T10:00:00+09:00'))
  self.assertFalse(add_discovery(s,u+'/', 'TEST_ONLY cafe',1,u,'2026-11-07T10:00:00+09:00'))
  self.assertEqual(len(new_state(m,'2026-11-08',s)['items']),76)
 def test_failed_atomic_write_preserves_previous_file(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'state.json';atomic_json(p,{'original':True})
   with patch('afternoon_tea.research_store.os.replace',side_effect=OSError('TEST_ONLY disk failure')):
    with self.assertRaises(OSError):atomic_json(p,{'original':False})
   self.assertEqual(json.loads(p.read_text()),{'original':True})
 def test_priority_stops_after_first_confirmed_site(self):
  m=load_master();s=new_state(m,'2026-11-07');item=s['items'][0]
  item['sources']={k:['https://'+host+'/123456/'] for k,host in [('ik','restaurant.ikyu.com'),('tb','tabelog.com'),('tc','www.tablecheck.com')]}
  b=Mock();b.fetch.return_value='<p>TEST_ONLY</p>'
  result={'status':'confirmed','master_id':item['id'],'identity':{},'reasons':[]}
  with tempfile.TemporaryDirectory() as tmp,patch('afternoon_tea.research_queue.extract',return_value=result),patch('afternoon_tea.research_queue.match_master',return_value=True),patch('afternoon_tea.research_queue.apply_page',return_value=result):
   process(item,s,m,b,tmp,time.monotonic()+10)
  self.assertEqual(b.fetch.call_count,1);self.assertEqual(item['attempts'][0]['site'],'ik')
 def test_access_failure_not_absence_or_exclusion(self):
  m=load_master();s=new_state(m,'2026-11-07');item=s['items'][0];item['sources']['ik']=['https://restaurant.ikyu.com/123456/']
  b=Mock();b.fetch.side_effect=RuntimeError('HTTP_403')
  original=copy.deepcopy(s['data'])
  with tempfile.TemporaryDirectory() as tmp:process(item,s,m,b,tmp,time.monotonic()+10)
  self.assertEqual(item['status'],'failed');self.assertEqual(s['data'],original)
 def test_ikyu_plan_discovery_requires_one_lunch_at_context(self):
  raw='<div>ランチ アフタヌーンティー<a href="/123456/plan99999">詳細をみる</a></div>'
  self.assertIn(('https://restaurant.ikyu.com/123456/plan99999','詳細をみる'),public_links(raw,'https://restaurant.ikyu.com/123456/'))
  self.assertFalse(public_links(raw.replace('ランチ','ディナー'),'https://restaurant.ikyu.com/123456/'))
 def test_split_description_and_selection(self):
  p=extract(SPLIT,TC,'2026-11-07')['plans'][-1]
  self.assertTrue(p['eligible_document']);self.assertEqual(p['plan']['end'],'2026-11-30')
 def test_other_category_does_not_supply_menu(self):
  raw=SPLIT.replace('<div class="menu-item"><div class="menu-item-name">アフタヌーンティー Stones','</div><div class="menu-category-section"><div class="menu-item"><div class="menu-item-name">アフタヌーンティー Stones')
  self.assertFalse(extract(raw,TC,'2026-11-07')['plans'][-1]['eligible_document'])
 def test_expired_split_plan_keeps_explicit_expired_dates(self):
  p=extract(SPLIT.replace('2026年9月1日～11月30日','2025年9月1日～11月30日'),TC,'2026-11-07')['plans'][-1]
  self.assertEqual(p['plan']['end'],'2025-11-30')
 def test_public_list_new_store_without_guest_query(self):
  raw='<h1>日本橋 アフタヌーンティー</h1><a href="/123456?num_guests=2">TEST_ONLY cafe</a><a href="/123456/confirm">confirm</a>'
  stores,_=listing_links(raw,'https://restaurant.ikyu.com/t/test/tokyo/')
  self.assertEqual(stores,[('https://restaurant.ikyu.com/123456/','TEST_ONLY cafe')])
 def test_json_ld_is_parsed_without_script_execution(self):
  url='https://restaurant.ikyu.com/123456/'
  raw='<script>throw new Error("TEST_ONLY never run")</script><script type="application/ld+json">'+json.dumps({'@type':'Restaurant','url':url,'name':'TEST_ONLY cafe','address':{'postalCode':'1000001','addressRegion':'東京都'}})+'</script>'
  self.assertEqual(identity(raw,url)['name'],'TEST_ONLY cafe')
 def test_json_ld_ambiguous_entities_not_used(self):
  url='https://restaurant.ikyu.com/123456/';obj={'@type':'Restaurant','url':url,'name':'TEST_ONLY','address':{}}
  self.assertIsNone(identity('<script type="application/ld+json">'+json.dumps([obj,obj])+'</script>',url))
 def test_lower_priority_after_failure_is_audited(self):
  m=load_master();s=new_state(m,'2026-11-07');item=s['items'][0]
  item['sources']={'ik':['https://restaurant.ikyu.com/123456/'],'tb':['https://tabelog.com/tokyo/123456/'],'tc':[]}
  b=Mock();b.fetch.side_effect=[RuntimeError('HTTP_403'),'<p>TEST_ONLY</p>']
  result={'status':'confirmed','master_id':item['id'],'identity':{},'reasons':[]}
  with tempfile.TemporaryDirectory() as tmp,patch('afternoon_tea.research_queue.extract',return_value=result),patch('afternoon_tea.research_queue.match_master',return_value=True),patch('afternoon_tea.research_queue.apply_page',return_value=result):
   process(item,s,m,b,tmp,time.monotonic()+10)
  self.assertEqual(b.fetch.call_count,2);self.assertEqual([a['site'] for a in item['attempts']],['ik','tb']);self.assertEqual(item['attempts'][0]['status'],'failed')
 def test_wrong_master_source_cannot_mutate_dataset(self):
  m=load_master();s=new_state(m,'2026-11-07');item=s['items'][0];item['sources']['ik']=['https://restaurant.ikyu.com/123456/']
  b=Mock();b.fetch.return_value='<p>TEST_ONLY</p>';original=copy.deepcopy(s['data'])
  r={'status':'unresolved','identity':{},'plans':[],'reasons':[]}
  with tempfile.TemporaryDirectory() as tmp,patch('afternoon_tea.research_queue.extract',return_value=r),patch('afternoon_tea.research_queue.match_master',return_value=False),patch('afternoon_tea.research_queue.apply_page') as promote:
   process(item,s,m,b,tmp,time.monotonic()+10)
  promote.assert_not_called();self.assertEqual(s['data'],original)
 def test_expired_plan_not_promoted(self):
  from afternoon_tea.data import create_data
  m=load_master();d=create_data(m,'2026-11-07');d['metadata']['purpose']='research'
  raw='<title>ザ パレス ラウンジ - パレスホテル東京 - TableCheck</title><div class="modal-body">ザ パレス ラウンジ パレスホテル東京 〒100-0005 東京都千代田区丸の内1-1-1</div>'+SPLIT.replace('2026年9月1日','2025年9月1日')
  result=apply_page(d,m,raw,TC);self.assertIn('no_eligible_plan_document',result['reasons'])
 def test_date_tampering_cannot_relabel_old_dataset(self):
  m=load_master();s=new_state(m,'2026-11-06');s['day']='2026-11-07'
  with tempfile.TemporaryDirectory() as tmp:
   with self.assertRaisesRegex(ValueError,'date_mismatch'):save_state(tmp,s,m)
 def test_jsonld_bilingual_exact_alias_and_venue(self):
  from afternoon_tea.extraction import venue_match
  url='https://www.tablecheck.com/en/shops/test/reserve'
  obj={'@type':'Restaurant','url':url,'name':'Le Jardin / Hotel Chinzanso Tokyo','alternateName':'ル・ジャルダン / ホテル椿山荘東京','address':{'postalCode':'1128664','addressRegion':'東京都','addressLocality':'文京区','streetAddress':'関口2-10-8'}}
  raw='<title>Le Jardin / Hotel Chinzanso Tokyo - TableCheck</title><script type="application/ld+json">'+json.dumps(obj)+'</script>'
  r=extract(raw,url,'2026-11-07');source=next(s for a in load_master()['areas'] for g in a['cats'].values() for s in g['shops'] if s['id']=='master-070')
  self.assertTrue(venue_match(r,source));self.assertIn('1128664',r['identity']['施設情報原文'])
 def test_missing_queue_item_cannot_be_silently_dropped(self):
  m=load_master();s=new_state(m,'2026-11-07');s['items'].pop()
  with tempfile.TemporaryDirectory() as tmp:
   atomic_json(Path(tmp)/'state.json',s)
   with self.assertRaisesRegex(ValueError,'incomplete'):load_state(tmp,m,'2026-11-07')
 def test_store_rejects_missing_master_data(self):
  m=load_master();s=new_state(m,'2026-11-07');s['data']['areas'][0]['cats']['cafe']['shops'].pop()
  with tempfile.TemporaryDirectory() as tmp:
   with self.assertRaisesRegex(ValueError,'incomplete'):save_state(tmp,s,m)
 def test_same_hotel_different_lounge_seed_urls_are_not_mixed(self):
  from afternoon_tea.research_queue import attach_seeds
  m=load_master();s=new_state(m,'2026-11-07')
  raw='<article><h4>パレスホテル東京</h4><p class="shop">ザ パレス ラウンジ（1F）</p><a href="https://restaurant.ikyu.com/123456/">source</a></article>'
  attach_seeds(s,raw);items={x['id']:x for x in s['items']}
  self.assertTrue(items['master-010']['sources']['ik']);self.assertFalse(items['master-012']['sources']['ik'])
 def test_city_index_is_a_get_document_only(self):
  from afternoon_tea.read_only import check_url,ForbiddenOperation
  check_url('https://restaurant.ikyu.com/s-tokyo/')
  with self.assertRaises(ForbiddenOperation):check_url('https://restaurant.ikyu.com/s-tokyo/?num_guests=2')
  with self.assertRaises(ForbiddenOperation):check_url('https://restaurant.ikyu.com/s-tokyo/','POST')
 def test_tea_only_plan_is_not_followed_even_with_lunch_navigation(self):
  raw='<div>ティー アフタヌーンティー<a href="/123456/plan99999">詳細をみる</a></div><nav>ランチ</nav>'
  self.assertFalse(public_links(raw,'https://restaurant.ikyu.com/123456/'))
 def test_previous_day_snapshot_is_preserved_on_new_run(self):
  m=load_master();s=new_state(m,'2026-11-06');s['items'][0].update(status='failed',reason='TEST_ONLY old failure')
  with tempfile.TemporaryDirectory() as tmp:
   save_state(tmp,s,m);p=Path(tmp)/'runs/2026-11-06/snapshot.json';before=p.read_bytes()
   today=load_state(tmp,m,'2026-11-07');save_state(tmp,today,m)
   self.assertEqual(p.read_bytes(),before);self.assertEqual(today['items'][0]['history'][-1]['reason'],'TEST_ONLY old failure')
 def test_partial_discovery_does_not_erase_prior_area_progress(self):
  from afternoon_tea.discovery import reconcile_areas
  s=new_state(load_master(),'2026-11-07');s['discovery_runs']=[{'area':2,'fetch':'success','checked_at':'2026-11-07T01:00:00+09:00'}]
  reconcile_areas(s);self.assertEqual(s['areas'][1]['discovery_status'],'incomplete');self.assertEqual(s['areas'][12]['discovery_status'],'unresolved')
 def test_service_host_alias_is_deduped_without_rewriting_request_url(self):
  s=new_state(load_master(),'2026-11-07');u='https://www.tablecheck.com/ja/shops/test/reserve'
  self.assertTrue(add_discovery(s,u,'TEST_ONLY',1,u,'2026-11-07T01:00:00+09:00'))
  self.assertFalse(add_discovery(s,u.replace('www.',''),'TEST_ONLY',1,u,'2026-11-07T01:00:00+09:00'))
  self.assertEqual(s['items'][-1]['sources']['tc'],[u])
 def test_store_writer_lock_is_released_and_blocks_overlap(self):
  from afternoon_tea.research_store import store_lock
  with tempfile.TemporaryDirectory() as tmp:
   with store_lock(tmp):
    with self.assertRaisesRegex(RuntimeError,'holds_store_lock'):
     with store_lock(tmp):pass
   with store_lock(tmp):pass
 def test_failed_evidence_save_cannot_commit_new_data(self):
  m=load_master();s=new_state(m,'2026-11-07');item=s['items'][0];item['sources']['ik']=['https://restaurant.ikyu.com/123456/']
  b=Mock();b.fetch.return_value='<p>TEST_ONLY</p>';original=copy.deepcopy(s['data'])
  result={'status':'confirmed','master_id':item['id'],'identity':{},'reasons':[]}
  def mutate(candidate,*args):
   candidate['notes']['status']='TEST_ONLY staged mutation';return result
  with tempfile.TemporaryDirectory() as tmp,patch('afternoon_tea.research_queue.extract',return_value=result),patch('afternoon_tea.research_queue.match_master',return_value=True),patch('afternoon_tea.research_queue.apply_page',side_effect=mutate),patch('afternoon_tea.research_queue.atomic_json',side_effect=OSError('TEST_ONLY no disk')):
   process(item,s,m,b,tmp,time.monotonic()+10)
  self.assertEqual(s['data'],original);self.assertEqual(item['status'],'failed')
 def test_real_confirmation_is_not_carried_into_next_day(self):
  from tests.test_step9 import RAW,URL
  m=load_master();s=new_state(m,'2026-11-06');r=apply_page(s['data'],m,RAW,URL)
  self.assertEqual(r['status'],'confirmed');next(x for x in s['items'] if x['id']=='master-070')['status']='confirmed'
  with tempfile.TemporaryDirectory() as tmp:
   save_state(tmp,s,m);old=(Path(tmp)/'runs/2026-11-06/snapshot.json').read_bytes()
   today=load_state(tmp,m,'2026-11-07');save_state(tmp,today,m)
   self.assertEqual(sum(shop['research']['status']=='confirmed' for a in today['data']['areas'] for g in a['cats'].values() for shop in g['shops']),0)
   self.assertIn({'id':'master-070','change':'no_current_confirmation'},differences(today))
   self.assertEqual((Path(tmp)/'runs/2026-11-06/snapshot.json').read_bytes(),old)
