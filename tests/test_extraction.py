import unittest
from afternoon_tea.extraction import extract,match_master,apply_page
from afternoon_tea.data import create_data
from afternoon_tea.master import load_master
from afternoon_tea.validation import validate_data

URL='https://tabelog.com/tokyo/A1302/A130202/12345678/party/123/'
def fixture(price='通常価格 税サ込 6,000円',extra=''):
 return '''<html><table><tr><th>店名</th><td>TEST CAFE</td></tr><tr><th>交通手段</th><td>日本橋駅</td></tr><tr><th>ジャンル</th><td>カフェ</td></tr></table><div class="course-dtl"><h3 class="course-dtl__course-title">TEST アフタヌーンティー</h3><div class="course-dtl__desc">マカロンとスコーン</div><span class="course-dtl__price-num">'''+price+'''</span><table><tr><th>利用可能時間</th><td>14:00～16:00</td></tr><tr><th>利用可能曜日</th><td>平日</td></tr></table><div class="course-dtl__reserve-btn"><a>このコースを予約する</a></div>'''+extra+'</div></html>'
class ExtractionTests(unittest.TestCase):
 def test_tabelog(self):
  p=extract(fixture(),URL,'2026-11-06')['plans'][0]
  self.assertTrue(p['eligible_document']);self.assertEqual(p['plan']['price_min'],6000)
 def test_discount_and_exclusive_unknown(self):
  for text in ('割引 税サ込 4,000円','4,500円（税抜）','税込 4,950円'):
   self.assertIsNone(extract(fixture(text),URL,'2026-11-06')['plans'][0]['plan']['price_min'])
 def test_period_not_booking_window(self):
  p=extract(fixture(extra='予約受付期間 2026-11-01～2026-12-30'),URL,'2026-11-06')['plans'][0]
  self.assertIsNone(p['plan']['start'])
  p=extract(fixture(extra='提供期間 2026-11-01～2026-12-30'),URL,'2026-11-06')['plans'][0]
  self.assertEqual(p['plan']['start'],'2026-11-01')
 def test_changed_structure_fails_closed(self):self.assertFalse(extract('<p>アフタヌーンティー予約 6000円</p>',URL,'2026-11-06')['plans'])
 def test_duplicate_plan(self):
  self.assertEqual(len(extract(fixture()+fixture(),URL,'2026-11-06')['plans']),1)
 def test_no_similar_name_match(self):
  r=extract(fixture(),URL,'2026-11-06');self.assertFalse(match_master(r,{'name':'OTHER CAFE','station':'日本橋駅'}))
 def test_tablecheck(self):
  raw='<title>TEST CAFE - TableCheck</title><div class="menu-item"><div class="menu-item-name">アフタヌーンティー</div><div class="menu-item-description">スコーン</div><div class="menu-item-price">6,000円 税サ込</div><div class="menu-item-order-select">選択する</div></div>'
  p=extract(raw,'https://www.tablecheck.com/ja/shops/test/reserve','2026-11-06')['plans'][0];self.assertTrue(p['eligible_document'])
 def test_ikyu_only_lunch(self):
  for meal,expected in [('ランチ',True),('朝食',True),('ディナー',False),('ティー',False)]:
   raw='<h1>TEST CAFE</h1>'+meal+' <h1>アフタヌーンティー</h1> 税サ込6,000円 メニュー スコーン プラン紹介 <button>このプランを予約する</button>'
   self.assertEqual(extract(raw,'https://restaurant.ikyu.com/123/plan456/','2026-11-06')['plans'][0]['eligible_document'],expected)
 def test_missing_menu_not_confirmed(self):
  self.assertFalse(extract(fixture().replace('マカロンとスコーン','メニュー不明'),URL,'2026-11-06')['plans'][0]['eligible_document'])
 def test_promotion_reextracts_and_preserves_unknown(self):
  master=load_master();source=master['areas'][0]['cats']['cafe']['shops'][0]
  raw=fixture().replace('TEST CAFE',source['name'])
  d=create_data(master,'2026-11-06');d['metadata']['purpose']='research'
  r=apply_page(d,master,raw,URL);self.assertEqual(r['status'],'confirmed')
  self.assertEqual(validate_data(d,master)['confirmed'],1)
 def test_similar_suffix_and_wrong_station_rejected(self):
  r=extract(fixture(),URL,'2026-11-06')
  self.assertFalse(match_master(r,{'name':'TEST','station':'日本橋駅'}))
  self.assertFalse(match_master(r,{'name':'TEST CAFE','station':'新宿駅'}))
 def test_multiple_prices_not_guessed(self):
  p=extract(fixture('通常価格 税サ込 6,000円 割引後 4,000円'),URL,'2026-11-06')['plans'][0]
  self.assertIsNone(p['plan']['price_min'])
 def test_options_not_added_to_base_sweets(self):
  p=extract(fixture().replace('マカロンとスコーン','追加料金のマカロンとスコーン'),URL,'2026-11-06')['plans'][0]
  self.assertEqual(p['plan']['sw'],[])
 def test_missing_identity_cannot_promote(self):
  d=create_data(load_master(),'2026-11-06');d['metadata']['purpose']='research'
  r=apply_page(d,load_master(),fixture(),URL)
  self.assertNotEqual(r['status'],'confirmed');self.assertEqual(validate_data(d,load_master())['confirmed'],0)
 def test_other_time_not_store_hours(self):
  p=extract(fixture().replace('利用可能時間','営業時間'),URL,'2026-11-06')['plans'][0]
  self.assertIsNone(p['plan']['time_text'])
