"""Categories by the lowest regular price: <=5000 cafe / 5001-8000 hotel / >=8001 lux."""
import copy
import unittest
import afternoon_tea.prepare_listings as c
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import tempfile
import afternoon_tea.publication_checks as site_tools
import afternoon_tea.prepare_listings as e
import afternoon_tea.generate_html as renderer
import importlib
import io
from afternoon_tea.prepare_listings import classify
from afternoon_tea.prepare_listings import enrich
from afternoon_tea.prepare_listings import enrich_plan
from afternoon_tea.prepare_listings import period
from afternoon_tea.prepare_listings import review
from afternoon_tea.prepare_listings import JST
from afternoon_tea.generate_html import render
from tests.test_generate_html import fixture
from tests.test_generate_html import plan as valid_plan
from tests.html_test_helpers import Document
from unittest.mock import patch
from pathlib import Path
from tests.test_publication_checks import files
from afternoon_tea.read_public_pages import ROOT
from afternoon_tea.research_settings import candidates
from afternoon_tea.publication_checks import validate_site
from afternoon_tea.publication_checks import json_bytes


class PriceCategoryTests(unittest.TestCase):

    def test_boundaries_and_unknown_prices(self):
        for (price, category) in [(1, 'cafe'), (5000, 'cafe'), (5000.5, 'hotel'), (5001, 'hotel'), (8000, 'hotel'),
                                  (8000.5, 'lux'), (8001, 'lux'), (30000, 'lux'),
                                  (None, 'unknown'), (True, 'unknown'), (0, 'unknown'), (-1, 'unknown'),
                                  ('5000', 'unknown'), (float('inf'), 'unknown')]:
            self.assertEqual(classify([{'price_yen': price}])[0], category, price)
        self.assertEqual(classify([{'discount_price_yen': 5000, 'price_min': 5000}]), ('unknown', None))

    def test_venue_name_and_old_categories_do_not_matter(self):
        for name in ('アマン東京', 'TEST ホテル', 'cafe'):
            data = fixture()
            data['shops'][0].update(name=name, category='cafe')
            for price, expected in ((13000, 'lux'), (4950, 'cafe'), (None, 'unknown')):
                data['shops'][0]['plans'][0]['price_yen'] = price
                self.assertEqual(enrich(data)['shops'][0]['category'], expected)

    def test_minimum_ignores_outside_plans(self):
        data = fixture('cafe')
        shop = data['shops'][0]
        shop['plans'] = [valid_plan(price_yen=10000), valid_plan(price_yen=7000), valid_plan(price_yen=1000, end='2026-11-06'),
                         valid_plan(price_yen=500, start='2026-12-18')]
        before = copy.deepcopy(data)
        enriched = enrich(data)
        self.assertEqual(data, before)
        self.assertEqual(enriched['shops'][0]['category'], 'hotel')
        self.assertEqual(enriched['shops'][0]['category_price_yen'], 7000)
        self.assertIn('class="stat s-hotel"><b>1</b>', render(enriched))
        self.assertEqual(enrich(enriched), enriched)

    def test_explicit_regular_price_and_discount_are_kept_separate(self):
        data = fixture()
        data['shops'][0]['plans'] = [{'price_yen': 10000, 'discount_price_yen': 5000,
                                      'evidence_quote': 'different price block must not override direct input'}]
        shop = enrich(data)['shops'][0]
        self.assertEqual(shop['category'], 'lux')
        self.assertEqual(shop['plans'][0]['discount_price_yen'], 5000)
        data['shops'][0]['plans'][0].update(price_yen=None, discount_price_yen=5000)
        self.assertEqual(enrich(data)['shops'][0]['category'], 'unknown')

    def test_plan_information_links_and_official_site(self):
        data = fixture()
        shop = data['shops'][0]
        shop['source_url'] = 'https://www.example.com/afternoon-tea/'
        shop['plans'] = [{'plan_name': 'First',
             'source_url': 'https://restaurant.ikyu.com/123456/plan111111',
             'price_yen': 5000,
             'checked_at': '2026-11-06T10:00:00+09:00'},
             {'plan_name': 'Second',
             'source_url': 'https://www.example.com/winter-tea/',
             'checked_at': '2026-11-06T10:00:00+09:00',
             'price_yen': 10000}]
        result = render(data)
        for value in ['プラン1／2', 'プラン2／2', 'https://www.example.com/winter-tea/', '提供期間 未確認']:
            self.assertIn(value, result)

    def test_json_and_html_agree_for_each_category(self):
        for (price, expected) in [(5000, 'cafe'), (5001, 'hotel'), (8000, 'hotel'), (8001, 'lux'), (None, 'unknown')]:
            data = fixture()
            data['shops'][0]['plans'][0]['price_yen'] = price
            enriched = enrich(data)
            self.assertEqual(enriched['shops'][0]['category'], expected)
            self.assertEqual(enriched['shops'][0]['category_price_yen'], price)
            self.assertEqual(enrich(enriched), enriched)
            self.assertIn('class="card c-' + expected + '"', render(enriched))


class CountryThemesTests(unittest.TestCase):
    def test_every_assigned_code_has_a_flag(self):
        self.assertGreater(len(c.registry()),240)
        for cc in c.registry():
            result=c.normalize_plan({'cc':cc.upper()})
            self.assertEqual(result,{'cc':cc})
            self.assertEqual(''.join(chr(ord(ch)-127462+ord('a')) for ch in c.flag(cc)),cc)
        self.assertEqual(c.flag('GB'),'🇬🇧')
        self.assertEqual(c.flag('fr'),'🇫🇷')
        self.assertEqual(c.flag('jp'),'🇯🇵')

    def test_invalid_or_missing_codes_become_null(self):
        for value in (None,'zz','uk','',1,True,['jp'],'日本',' jp','JPN','KZ'):
            result=c.normalize_plan({'cc':value})
            self.assertIsNone(result['cc'])
            c.validate_country(result)
            self.assertIsNone(c.display(result))
        self.assertEqual(c.normalize_plan({}),{'cc':None})

    def test_country_code_alone_displays_flag_without_a_country_filter(self):
        data=fixture();data['shops'][0]['plans'][0]['cc']='fr'
        before=copy.deepcopy(data);html=render(data)
        self.assertIn('🇫🇷 フランス',html)
        self.assertNotIn('data-country',html)
        self.assertNotIn('country-filter',html)
        self.assertEqual(data,before)

    def test_old_rationale_hash_and_inferred_notes_are_removed(self):
        plan={'plan_name':'AT','price_yen':9000,'cc':'jp','country':'日本','country_source_type':'inferred',
              'country_basis':'TEST reason','country_input_hash':'a'*64,'country_decision_hash':'b'*64,
              'notes':{'status':'テーマ国推測：TEST'}}
        before=copy.deepcopy(plan);out=c.normalize_plan(plan)
        self.assertEqual(out,{'plan_name':'AT','price_yen':9000,'cc':'jp'})
        self.assertEqual(plan,before)
        self.assertFalse(any(hasattr(c,key) for key in ('prepare','finalize','content_hash','identity')))

    def test_no_country_is_inferred_from_food_or_old_country_name(self):
        for plan in ({'menu':'抹茶とスコーン'},{'country':'フランス','menu':'マカロン'}):
            self.assertIsNone(c.normalize_plan(plan)['cc'])
        with patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('offline')):
            self.assertEqual(c.display({'cc':'uy'}),'🇺🇾 ウルグアイ')


def data(first=None, last=None):
    return {'generated_at': '2026-11-07T15:55:22+09:00',
         'period': {'start': '2026-11-07',
         'end': '2026-12-17'},
         'shops': [{'name': 'TEST ONLY', 'plans': [{'start': first,
         'end': last}]}]}

class WeeklyReviewTests(unittest.TestCase):

    def test_december_19_start_is_outside_december_17_window(self):
        result = review(data('2026-12-19', '2026-12-25'))
        self.assertEqual(len(result['outside_plans']), 1)
        self.assertEqual(result['errors'][0]['reason'], 'outside_research_period')

    def test_inclusive_boundary_overlap(self):
        for (first, last) in [('2026-12-17', '2026-12-25'), ('2026-10-01', '2026-11-07'), ('2026-11-07', '2026-12-17')]:
            self.assertEqual(review(data(first, last))['errors'], [])

    def test_expired_plan_is_outside(self):
        self.assertTrue(review(data('2026-10-01', '2026-11-06'))['outside_plans'])

    def test_unknown_dates_remain_unknown_without_mutation(self):
        for (first, last) in [(None, None), (None, '2026-12-20'), ('2026-12-01', None)]:
            source = data(first, last)
            before = copy.deepcopy(source)
            result = review(source)
            self.assertEqual(result['errors'], [])
            self.assertEqual(result['unknown_periods'], 1)
            self.assertEqual(source, before)

    def test_known_endpoint_can_prove_outside(self):
        for (first, last) in [('2026-12-19', None), (None, '2026-11-06')]:
            self.assertTrue(review(data(first, last))['outside_plans'])

    def test_invalid_dates_and_inversion_are_not_silently_corrected(self):
        for (first, last) in [('2026-02-30', None), ('2026-12-10', '2026-12-01'), ('20261201', None)]:
            self.assertEqual(review(data(first, last))['errors'][0]['reason'], 'invalid_plan_period')

    def test_wrong_40_day_window_rejected(self):
        source = data()
        source['period']['end'] = '2026-12-19'
        self.assertEqual(review(source)['errors'][0]['reason'], 'invalid_research_period')

    def test_jst_midnight_and_year_leap_boundaries(self):
        self.assertEqual(period(now=dt.datetime(2026, 11, 6, 16, tzinfo=dt.timezone.utc)), {'start': '2026-11-07', 'end': '2026-12-17'})
        self.assertEqual(period('2026-12-20')['end'], '2027-01-29')
        self.assertEqual(period('2028-02-01')['end'], '2028-03-12')

    def test_generated_timestamp_compared_in_jst(self):
        source = data()
        source['generated_at'] = '2026-11-06T16:00:00+00:00'
        self.assertEqual(review(source)['errors'], [])
        source['generated_at'] = '2026-11-06T14:59:00+00:00'
        self.assertTrue(review(source)['errors'])

    def test_no_shops_or_plans_is_not_a_review_failure(self):
        source = data()
        source['shops'] = []
        self.assertEqual(review(source)['errors'], [])

    def test_outside_period_plan_is_not_rendered(self):
        from afternoon_tea.generate_html import render
        from tests.test_generate_html import fixture
        sample = fixture()
        sample['shops'][0]['plans'][0].update(start='2026-12-19', end=None, plan_name='OUTSIDE ONLY')
        self.assertTrue(review(sample)['outside_plans'])
        self.assertNotIn('OUTSIDE ONLY', render(sample))

    def test_date_review_is_not_a_new_automatic_publication_gate(self):
        # The pre-PR helper reports an error; the existing automation is unchanged.
        content = files(0)
        sample = {'schema_version': 2, **data('2026-12-19', None)}
        sample['shops'][0].update(area_no=1)
        sample['shops'][0]['plans'][0]['checked_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
        sample['shops'][0]['plans'][0].update(plan_name='TEST plan', source_url='https://example.com/plan')
        content['website/listings_and_progress.json'] = site_tools.json_bytes(sample)
        self.assertTrue(review(json.loads(content['website/listings_and_progress.json']))['errors'])
        # The review error does not stop validation; a plan starting after the window is not listed.
        self.assertEqual(site_tools.validate_site(content)['shops'], 0)

    def test_actions_summary_is_optional_and_reports_real_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'summary.md'
            with patch.dict(os.environ, {'GITHUB_STEP_SUMMARY': str(path), 'GITHUB_RUN_ID': '123'}):
                site_tools.write_summary('自動マージ成功・公開開始要求済み',
                     {'shops': 2,
                     'plans': 8,
                     'pr': '20',
                     'unresearched_shops': 73,
                     'search_statuses': {'unresearched': 74}})
            text = path.read_text()
            self.assertIn('2', text)
            self.assertIn('8', text)
            self.assertIn('/pull/20', text)
            self.assertIn('/actions/runs/123', text)
            self.assertNotIn('Pages公開確認成功', text)


STAMP = '2026-11-07T17:50:14+09:00'
URL = 'https://restaurant.ikyu.com/123456/plan123456'

class EnrichmentTests(unittest.TestCase):

    def test_weekday_christmas_and_menu_text_are_preserved(self):
        p = {'plan_name': 'TEST ONLY クリスマスAT（平日）', 'menu': 'スコーン・マカロン・苺・栗・かぼちゃ', 'evidence_quote': 'Christmas afternoon tea'}
        result = e.enrich_plan(p)
        self.assertTrue(result['weekday_available'])
        self.assertFalse(result['weekend_available'])
        self.assertEqual(result['season'], ['xmas'])
        self.assertEqual(result['menu'], p['menu'])

    def test_null_and_mixed_optional_tags_never_stop_html_generation(self):
        for existing in (None, [], [None, 1, 'xmas'], 'xmas'):
            plan = {**valid_plan(), 'plan_name': 'TEST ONLY クリスマスAT（平日）', 'menu': 'マカロン', 'season': existing, 'structured_evidence': None}
            result = e.enrich_plan(plan)
            self.assertEqual(result['season'], ['xmas'])
            self.assertTrue(result['weekday_available'])
            d = fixture()
            d['shops'][0]['plans'] = [result]
            self.assertIn('マカロン', renderer.render(d))

    def test_unknown_and_negated_text_do_not_invent_availability_or_tags(self):
        for p in ({'plan_name': 'TEST ONLY AT'}, {'plan_name': '平日限定ではありません'}, {'menu': 'マカロンは含まれません'}):
            result = e.enrich_plan(p)
            self.assertNotIn('weekday_available', result)

    def test_weekend_and_every_day_conditions(self):
        for (title, wd, we) in [('土日祝限定', False, True), ('全日提供', True, True), ('平日限定 土日祝限定', None, None)]:
            result = e.enrich_plan({'plan_name': title})
            self.assertEqual(result.get('weekday_available'), wd)
            self.assertEqual(result.get('weekend_available'), we)

    def test_regular_and_discount_prices_are_separate_and_idempotent(self):
        p = {'price_yen': 9200, 'discount_price_yen': 7200, 'price_note': '税サ込（通常9,200円）。', 'evidence_quote': '最大21%OFF 9,200円 税サ込7,200円'}
        result = e.enrich_plan(p)
        self.assertEqual(result['price_yen'], 9200)
        self.assertEqual(result['discount_price_yen'], 7200)
        self.assertEqual(e.enrich_plan(result), result)

    def test_discount_only_does_not_reverse_calculate_regular_price(self):
        p = {'price_yen': None, 'discount_price_yen': 6000, 'evidence_quote': '20%OFF 税サ込6,000円'}
        result = e.enrich_plan(p)
        self.assertIsNone(result['price_yen'])
        self.assertEqual(result['discount_price_yen'], 6000)
        self.assertEqual(e.enrich_plan(result), result)


    def test_zero_and_two_shops_still_generate_valid_html(self):
        for count in (0, 2):
            d = fixture()
            d['shops'] = d['shops'] * count
            d = e.enrich(d)
            html = renderer.render(d)
            self.assertEqual(html.count('<article '), count)
            self.assertEqual(validate_site({'website/index.html': html.encode(),
                 'website/listings_and_progress.json': json_bytes(d),
})['shops'],
                 count)


builder=importlib.import_module('afternoon_tea.prepare_listings')


def current(prices=(5000,5001,8000,8001,None)):
    now=dt.datetime.now(JST)
    row=candidates()[0]
    return {'schema_version': 2,'generated_at':now.isoformat(),'period':period(now=now),
            'shops':[{'id':'c'+row['No'],'name':'TEST ONLY','area_no':int(row['エリア番号']),'genre':'ラウンジ',
                      'station':'日本橋駅','address':None,'source_site':row['優先して調べるサイト'],
                      'plans':[{'plan_name':'PLAN '+str(i),'price_yen':price,'checked_at':now.isoformat(),
                                'source_url':'https://example.com/plan/'+str(i),
                                'start':None,'end':None,'menu':'スコーン','cc':'FR'} for i,price in enumerate(prices)]}]}


class BuildTests(unittest.TestCase):
    def test_build_is_non_mutating_and_creates_display_values_once(self):
        data=current();before=copy.deepcopy(data)
        out=builder.build(data)
        self.assertEqual(data,before)
        self.assertEqual(out['shops'][0]['category'],'cafe')
        for old,plan in zip(data['shops'][0]['plans'],out['shops'][0]['plans']):
            self.assertEqual(plan['checked_at'],old['checked_at'])
            self.assertEqual(plan['price_yen'],old['price_yen'])
            self.assertEqual(plan['cc'],'fr')
        html=render(out)
        self.assertEqual(html.count('🇫🇷 フランス'),5)
        validate_site({'website/listings_and_progress.json':json_bytes(out),'website/index.html':html.encode()})

    def test_prices_are_direct_inputs_and_discount_never_replaces_regular(self):
        plan={'plan_name':'AT','price_yen':9000,'discount_price_yen':4500,
              'price_note':'50%OFF、通常価格12,000円','evidence_quote':'通常価格 20,000円 50%OFF 10,000円'}
        out=enrich_plan(plan)
        self.assertEqual((out['price_yen'],out['discount_price_yen']),(9000,4500))
        self.assertEqual(out['price_note'],plan['price_note'])
        plan.update(price_yen=None)
        self.assertIsNone(enrich_plan(plan)['price_yen'])
        del plan['price_yen']
        self.assertIsNone(enrich_plan(plan)['price_yen'])

    def test_invalid_country_codes_do_not_stop_build(self):
        for value in ('zz','uk',1,True,'JPN','',None):
            data=current((8001,));p=data['shops'][0]['plans'][0]
            p.update(cc=value,country='TEST old name',country_basis='TEST reason',
                     country_input_hash='old',country_decision_hash='old',notes={'status':'テーマ国推測：TEST'})
            out=builder.build(data);p=out['shops'][0]['plans'][0]
            self.assertIsNone(p['cc'])
            self.assertFalse(any(key.startswith('country') or key=='notes' for key in p))
            self.assertNotIn('country-theme',re.search(r'<main>(.*?)</main>',render(out),re.S).group(1))

    def test_old_plans_are_kept_with_their_dates_and_only_ended_or_broken_ones_go(self):
        data=current((9000,));now=dt.datetime.now(JST)
        p=data['shops'][0]['plans'][0]
        old=(now-dt.timedelta(days=40)).isoformat()
        data['shops'][0]['plans'] += [{**p,'plan_name':'OLD','checked_at':old},
                                      {**p,'plan_name':'ENDED','end':(dt.date.fromisoformat(data['period']['start'])-dt.timedelta(days=1)).isoformat()}]
        out=builder.build(data,now=now)
        plans={p['plan_name']:p for p in out['shops'][0]['plans']}
        self.assertEqual(set(plans),{'OLD','PLAN 0'})
        self.assertEqual(plans['OLD']['checked_at'],old)
        html=render(out)
        self.assertIn('過去の確認情報',html)
        self.assertIn('現在の提供状況は未確認です',html)
        future=current((9000,));future['shops'][0]['plans'][0]['checked_at']=(now+dt.timedelta(days=1)).isoformat()
        with self.assertRaisesRegex(ValueError,'future'):
            builder.build(future,now=now)
        naive=current((9000,));naive['shops'][0]['plans'][0]['checked_at']='2026-11-01T10:00:00'
        with self.assertRaisesRegex(ValueError,'timezone'):
            builder.build(naive,now=now)

    def test_build_and_rebuild_never_change_checked_at(self):
        data=current((9000,5000))
        once=builder.build(data)
        twice=builder.build(once)
        self.assertEqual(once,twice)
        self.assertEqual([p['checked_at'] for p in twice['shops'][0]['plans']],
                         [p['checked_at'] for p in data['shops'][0]['plans']])

    def test_renderer_does_not_recompute_saved_classification(self):
        data=builder.build(current((9000,)))
        data['shops'][0]['category']='cafe'
        data['shops'][0]['plans'][0].update(menu='チョコレート')
        before=copy.deepcopy(data)
        with patch('afternoon_tea.prepare_listings.classify',side_effect=AssertionError('render must use saved category')), \
             patch('afternoon_tea.prepare_listings.enrich',side_effect=AssertionError('render must not build')):
            html=render(data)
        self.assertIn('class="card c-cafe"',html)
        self.assertEqual(data,before)

    def test_zero_is_a_valid_build_result(self):
        data=current();data['shops']=[]
        out=builder.build(data)
        html=render(out)
        self.assertNotIn('<article ',html)
        self.assertEqual(validate_site({'website/listings_and_progress.json':json_bytes(out),'website/index.html':html.encode()})['plans'],0)


class BuildCommandTests(unittest.TestCase):
    def run_in_root(self,data,html='previous HTML'):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);root=Path(tmp.name)
        (root/'website').mkdir();(root/'research_inputs').mkdir()
        shutil.copyfile(ROOT/'research_inputs/tokyo_areas.json',root/'research_inputs/tokyo_areas.json')
        shutil.copyfile(ROOT/'research_inputs/country_codes.json',root/'research_inputs/country_codes.json')
        (root/'website/listings_and_progress.json').write_bytes(json_bytes(data))
        (root/'website/index.html').write_text(html)
        return root

    def test_build_command_writes_json_and_html_and_does_not_fetch(self):
        renderer=importlib.import_module('afternoon_tea.generate_html')
        for count in (1,0):
            data=current((8001,));data['shops']=data['shops'][:count]
            root=self.run_in_root(data)
            with patch.object(builder,'ROOT',root),patch.object(renderer,'ROOT',root), \
                 patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('offline')), \
                 patch('sys.stdout',new=io.StringIO()):
                self.assertEqual(builder.main(),0)
            written=json.loads((root/'website/listings_and_progress.json').read_text())
            self.assertEqual(len(written['shops']),count)
            self.assertEqual((root/'website/index.html').read_text(),render(written))

    def test_validation_failure_keeps_existing_files(self):
        renderer=importlib.import_module('afternoon_tea.generate_html')
        data=current();data['period']['end']='invalid'
        root=self.run_in_root(data);before=(root/'website/listings_and_progress.json').read_bytes()
        with patch.object(builder,'ROOT',root),patch.object(renderer,'ROOT',root),self.assertRaises(ValueError):
            builder.main()
        self.assertEqual((root/'website/listings_and_progress.json').read_bytes(),before)
        self.assertEqual((root/'website/index.html').read_text(),'previous HTML')


class PriceFilterTests(unittest.TestCase):
    def test_real_filter_boundaries(self):
        if not shutil.which('node'):
            self.fail('Node is required for the existing offline filter tests')
        html=render(builder.build(current()))
        self.assertIn('5,000円以下',html);self.assertIn('5,001〜8,000円',html);self.assertIn('8,001円以上',html)
        self.assertNotIn('6,000円以下',html)
        plans=[n for n in Document(html).root.find('div') if n.attrs.get('class')=='plan']
        payload={'js':re.search('<script>(.*?)</script>',html,re.S).group(1),
                 'plans':[{'name':'PLAN '+str(i),'dataset':{k[5:]:v for k,v in n.attrs.items() if k.startswith('data-')}} for i,n in enumerate(plans)]}
        harness=r'''
const vm=require('vm'),fs=require('fs'),p=JSON.parse(fs.readFileSync(0,'utf8'));
function node(dataset={}){const n={dataset,hidden:false,value:'',textContent:'',attrs:{},events:{},classes:new Set(),getAttribute(k){return this.attrs[k]},setAttribute(k,v){this.attrs[k]=String(v)},addEventListener(k,f){this.events[k]=f}};n.classList={toggle(k,v){v?n.classes.add(k):n.classes.delete(k)}};return n}
const plans=p.plans.map(x=>Object.assign(node(x.dataset),{name:x.name}));const card=node({cat:'cafe'});card.querySelectorAll=()=>plans;
const buttons=['cafe','hotel','lux','unknown'].map(cat=>node({cat})),ids={};for(const x of ['price-filter','filter-status','no-results','reset-filters','area-toggle','area-links'])ids[x]=node();
const document={getElementById(id){return ids[id]},querySelector(){return null},querySelectorAll(q){return q==='.fb'?buttons:q==='.card'?[card]:[]}};
vm.runInNewContext(p.js,{document,window:{addEventListener(){}},setTimeout(){}});
for(const [choice,wanted] of [['low',['PLAN 0']],['mid',['PLAN 1','PLAN 2']],['high',['PLAN 3']],['unknown',['PLAN 4']],['all',['PLAN 0','PLAN 1','PLAN 2','PLAN 3','PLAN 4']]]){
ids['price-filter'].value=choice;ids['price-filter'].events.change();const actual=plans.filter(x=>!x.hidden).map(x=>x.name);if(JSON.stringify(actual)!==JSON.stringify(wanted))throw Error(choice+': '+JSON.stringify(actual));
}
process.stdout.write('price boundaries passed');'''
        result=subprocess.run(['node','-e',harness],input=json.dumps(payload),capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)


class DocumentationTests(unittest.TestCase):
    DOCS = ('AGENTS.md', 'CLAUDE.md', 'README.md', 'guides/weekly_research_guide.md')

    def test_one_instruction_source_with_the_seven_items(self):
        agents = (ROOT / 'AGENTS.md').read_text()
        for no in range(1, 8):
            self.assertEqual(agents.count('\n## %d. ' % no), 1)
        claude = (ROOT / 'CLAUDE.md').read_text()
        self.assertIn('AGENTS.md', claude)
        self.assertIn('guides/weekly_research_guide.md', claude)

    def test_limits_live_in_the_settings_file_not_in_instructions(self):
        values = json.loads((ROOT / 'research_inputs/research_limits.json').read_text())
        for key in ('total_seconds', 'max_navigations', 'shop_seconds', 'min_interval_seconds', 'recheck_after_days'):
            self.assertIn(key, values)
        for name in self.DOCS:
            text = (ROOT / name).read_text()
            for value in ('1,500秒', '1500秒', '200要求', '60秒', '3秒以上', '14日以内', '40秒', 'クリック5回'):
                self.assertNotIn(value, text, name)

    def test_retired_restrictions_are_not_reapplied_by_any_document(self):
        retired = ('No.1から順', 'No順に読み', '探し直し', 'リスト外の探索はしない', '検索はしない', 'GETだけで続ける',
                   'GETでプランが見えない場合だけ', 'リダイレクトを追わず', '店名を失敗記録へ残さない', 'CSVのURLそのもの',
                   '同じ店舗のプラン詳細だけ', '96店舗', '候補CSVのURLと一致しない')
        for name in self.DOCS:
            text = (ROOT / name).read_text()
            for phrase in retired:
                self.assertNotIn(phrase, text, (name, phrase))

    def test_procedure_starts_from_names_and_keeps_display_rules(self):
        procedure = (ROOT / 'guides/weekly_research_guide.md').read_text()
        self.assertIn('pip install -r requirements-browser.txt', procedure)
        self.assertIn('店舗名・ホテル名＋「アフタヌーンティー」', procedure)
        for value in ('5,000円以下', '5,001〜8,000円', '8,001円以上', '07:17'):
            self.assertEqual(procedure.count(value), 1, value)
        self.assertNotIn('python3 -m unittest', procedure)


class PlanPrivacyTests(unittest.TestCase):
    def test_only_sensitive_plans_are_removed_and_no_values_are_logged(self):
        examples=('ghp_'+'x'*36,'-----BEGIN PRIVATE KEY-----','name@example.test',
                  '090-1234-5678','4111 1111 1111 1111')
        for secret in examples:
            with self.subTest(kind=examples.index(secret)):
                data=current((4000,9000))
                data['shops'][0]['plans'][0]['menu']=secret
                before=copy.deepcopy(data)
                out=builder.build(data)
                self.assertEqual(data,before)
                self.assertEqual([p['plan_name'] for p in out['shops'][0]['plans']],['PLAN 1'])
                self.assertEqual(out['shops'][0]['category'],'lux')
                self.assertEqual(sum(out['excluded_sensitive_plans'].values()),1)
                self.assertNotIn(secret,json_bytes(out).decode())
                html=render(out)
                self.assertNotIn(secret,html)
                self.assertEqual(validate_site({'website/listings_and_progress.json':json_bytes(out),'website/index.html':html.encode()})['plans'],1)

    def test_sensitive_only_shop_is_omitted_and_zero_is_publishable(self):
        data=current((5000,))
        data['shops'][0].update(name='EXCLUDED SHOP ONLY')
        data['shops'][0]['plans'][0]['menu']='name@example.test'
        out=builder.build(data)
        self.assertEqual(out['shops'],[])
        self.assertNotIn('EXCLUDED SHOP ONLY',json_bytes(out).decode())
        self.assertEqual(out['excluded_sensitive_plans']['current'],1)
        self.assertEqual(validate_site({'website/listings_and_progress.json':json_bytes(out),'website/index.html':render(out).encode()})['plans'],0)
        with self.assertRaises(site_tools.ZeroListing):
            site_tools.publishable(out)

    def test_rebuild_count_is_stable(self):
        data=current((4000,9000))
        data['shops'][0]['plans'][1]['menu']='old@example.test'
        out=builder.build(data)
        self.assertEqual(sum(out['excluded_sensitive_plans'].values()),1)
        self.assertEqual(builder.build(out),out)

    def test_unrelated_validation_error_is_not_silently_dropped(self):
        data=current((4000,));data['shops'][0]['plans'][0]['start']='invalid'
        with self.assertRaisesRegex(ValueError,'invalid_plan_period'):
            builder.build(data)
        data=current((4000,));data['shops'][0]['address']='person@example.test'
        with self.assertRaises(site_tools.SensitiveDataError):
            builder.build(data)

    def test_build_command_writes_only_safe_data_and_report_has_only_a_count(self):
        data=current((4000,9000));data['shops'][0]['plans'][0]['menu']='hidden@example.test'
        root=BuildCommandTests.run_in_root(self,data)
        import afternoon_tea.manage_research as collect
        with patch.object(builder,'ROOT',root),patch.object(renderer,'ROOT',root),patch('sys.stdout',new=io.StringIO()) as stdout:
            self.assertEqual(builder.main(),0)
        self.assertNotIn('hidden@example.test',stdout.getvalue())
        self.assertEqual(json.loads(stdout.getvalue())['excluded_sensitive_plans'],1)
        result=json.loads((root/'website/listings_and_progress.json').read_text())
        state={'started_iso':data['generated_at'],'browser_pages':0,'browser_unavailable':None,
               'blocked_operations':0,'blocked_resources':0,'navigations':0,'blocked_hosts':{}}
        text=collect.report(state=state,data=result)
        self.assertIn('秘密情報・個人情報の検査で除外したプラン数: 1',text)
        for path in (root/'website').iterdir():
            self.assertNotIn('hidden@example.test',path.read_text())
        self.assertNotIn('hidden@example.test',text)

    def test_retired_digest_shapes_do_not_hide_card_numbers(self):
        disguised='a'*24+'4111111111111111'+'a'*24
        for menu in (disguised,{'document_id':disguised},[disguised]):
            data=current((4000,9000));data['shops'][0]['plans'][0]['menu']=menu
            out=builder.build(data)
            self.assertEqual(out['excluded_sensitive_plans']['current'],1)
            self.assertEqual([p['plan_name'] for p in out['shops'][0]['plans']],['PLAN 1'])
            self.assertNotIn('4111111111111111',json_bytes(out).decode())
