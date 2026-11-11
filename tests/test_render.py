"""Fixed design, saved JSON and local-only filter tests."""
import copy
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
import afternoon_tea.render as r
from pathlib import Path
from unittest.mock import patch
from afternoon_tea.check import validate_site
from afternoon_tea.build import enrich
from html.parser import HTMLParser


def fixture(category='unknown'):
    return {'schema_version': 1,
         'generated_at': '2026-11-07T15:55:22+09:00',
         'period': {'start': '2026-11-07',
         'end': '2026-12-17'},
         'shops': [{'name': 'TEST ONLY lounge',
         'area_no': 1,
         'category': category,
         'station': 'TEST station',
         'list_url': 'https://www.tablecheck.com/ja/shops/test-only/reserve',
         'plans': [{'plan_name': 'TEST winter AT', 'checked_at': dt.datetime.now(dt.timezone.utc).isoformat(),
         'start': None,
         'end': None,
         'price_yen': None}]}]}

class RoutineRendererTests(unittest.TestCase):

    def test_template_css_snapshot(self):
        import hashlib
        self.assertEqual(hashlib.sha256((r.TEMPLATES / 'site.css').read_bytes()).hexdigest(),
             'a2d0725640fed7b8f7134693c8059a889bc33de029ffc24100b741938ccddd3d')

    def test_current_saved_data_renders_reproducibly_without_old_store_data(self):
        research = json.loads((r.ROOT / 'site/research.json').read_text())
        before = copy.deepcopy(research)
        result = r.render(research)
        self.assertEqual(research, before)
        self.assertEqual(result, (r.ROOT / 'site/index.html').read_text())
        self.assertEqual(r.render(research), result)

    def test_zero_stores_and_all_14_areas(self):
        source = fixture()
        source['shops'] = []
        result = r.render(source)
        self.assertIn('今週は確認できた情報がありません', result)
        for no in range(1, 15):
            self.assertIn('id="a' + str(no) + '"', result)
            self.assertIn('href="#a' + str(no) + '"', result)
        self.assertNotIn('<article ', result)

    def test_reference_card_and_plan_dom_and_unknown_values(self):
        data = fixture()
        data['shops'][0]['hotel_name'] = 'TEST ホテル'
        result = r.render(data)
        self.assertNotIn('cafe VAVA', result)
        for value in ['class="card c-unknown"',
             'class="plan"',
             'class="when"',
             'class="price"',
             'class="links"',
             'class="meet"',
             'class="top"',
             'class="plans"',
             'class="totop"']:
            self.assertIn(value, result)
        for value in ['料金 未確認', '提供期間 未確認', '平日 未確認', '土日祝 未確認', '提供時間・利用時間 未確認', 'スイーツ・季節分類 未確認']:
            self.assertIn(value, result)

    def test_categories_use_regular_price_not_stale_categories_or_names(self):
        source = fixture()
        shop = source['shops'][0]
        source['shops'] = [{**shop, 'name': 'TEST ホテル', 'category': 'lux', 'plans': [{'price_yen': price}]}
                           for price in (5000, 8000, 8001, None)]
        result = r.render(enrich(source))
        for cat in ['cafe', 'hotel', 'lux']:
            self.assertIn(f'class="stat s-{cat}"><b>1</b>', result)
        self.assertIn('class="card c-unknown"', result)

    def test_multiple_plans_and_dynamic_sweet_counts(self):
        source = fixture()
        source['shops'][0]['sweets'] = ['scone', 'xmas']
        source['shops'][0]['plans'] = [{'plan_name': 'TEST 1', 'menu': 'スコーン', 'price_yen': 1000}, {'plan_name': 'TEST 2', 'price_yen': 2000}]
        result = r.render(enrich(source))
        self.assertIn('プラン1／2', result)
        self.assertIn('プラン2／2', result)
        self.assertIn('data-sw="scone" aria-pressed="false">スコーン<span class="bc">1</span>', result)
        self.assertNotIn('data-sw="xmas" aria-pressed=', result)

    def test_outside_plan_is_omitted_without_mutating_evidence(self):
        source = fixture()
        source['shops'][0]['plans'] += [{'plan_name': 'OUTSIDE ONLY', 'start': '2026-12-19', 'end': '2026-12-25'}]
        before = copy.deepcopy(source)
        result = r.render(source)
        self.assertNotIn('OUTSIDE ONLY', result)
        self.assertEqual(source, before)

    def test_research_notice_is_never_rendered_and_json_is_preserved(self):
        failures = {'schema_version': 1,
             'generated_at': None,
             'failures': [{'name': 'TEST unresearched venue',
             'area': 'TEST area',
             'checked_at': '2026-11-07T15:55:22+09:00',
             'sources': [],
             'status': 'unresearched',
             'reason': 'TEST restriction audit only',
             'retry': True}]}
        for count in (0, 1):
            source = fixture()
            source['note'] = 'TEST research note must remain in JSON only'
            source['shops'] = source['shops'][:count]
            if count:
                source['shops'][0]['hotel_name'] = 'TEST ホテル'
                source['shops'][0]['plans'].append({'plan_name': 'OUTSIDE ONLY', 'start': '2026-12-19'})
            before = copy.deepcopy((source, failures))
            for _ in range(2):
                result = r.render(source)
                for removed in ['<div class="aside">',
                     '<div class="box">',
                     source['note'],
                     'TEST restriction audit only',
                     '未調査店舗',
                     '分類は原則として価格帯',
                     '掲載なしはAT提供なしを意味しません',
                     'プランは掲載対象から除きました']:
                    self.assertNotIn(removed, result)
                if count:
                    self.assertIn('class="card c-unknown"', result)
                    self.assertIn('料金 未確認', result)
                self.assertEqual((source, failures), before)
        template = (r.TEMPLATES / 'site.html').read_text()
        self.assertNotIn('$notice', template)
        self.assertNotIn('class="aside"', template)

    def test_card_evidence_display_is_omitted_but_links_and_json_remain(self):
        urls = ['https://restaurant.ikyu.com/123456/plan111111',
             'https://www.tablecheck.com/ja/shops/test-only/reserve',
             'https://tabelog.com/tokyo/A1301/A130101/12345678/',
             'https://www.example.com/afternoon-tea/']
        for (name, price, label) in [('TEST venue', 5000, 'カフェ'), ('TEST venue', 8000, 'ホテル'),
                                     ('TEST venue', 8001, 'ホテル（高級）')]:
            data = fixture()
            base = data['shops'][0]
            data['shops'] = [{**base,
                 'name': name + ' ' + str(i),
                 'list_url': url,
                 'checked_at': '2026-11-06T09:00:00+09:00',
                 'evidence_quote': 'TEST shop evidence',
                 'plans': [{'plan_name': 'TEST plan',
                 'source_url': url,
                 'booking_url_info_only': url,
                 'checked_at': '2026-11-06T10:00:00+09:00',
                 'evidence_quote': 'TEST plan evidence',
                 'price_yen': price,
                 'start': '2026-11-07',
                 'end': '2026-12-01',
                 'weekday_available': True}]} for (i,
                 url) in enumerate(urls)]
            data = enrich(data)
            before = copy.deepcopy(data)
            for _ in range(2):
                result = r.render(data)
                for removed in ['出典：', '確認日時：', '2026-11-06T09:00:00+09:00', '2026-11-06T10:00:00+09:00', 'TEST shop evidence', 'TEST plan evidence']:
                    self.assertNotIn(removed, result)
                for url in urls:
                    self.assertEqual(result.count('href="' + url + '"'), 2)
                self.assertEqual(result.count('<p class="rnote">' + label + '</p>'), 4)
                self.assertIn('プランの予約・情報ページ', result)
                self.assertIn('2026/11/7〜2026/12/1', result)
                self.assertIn('data-wd="1"', result)
                self.assertEqual(data, before)

    def test_text_and_attribute_injection_is_escaped(self):
        source = fixture()
        source['shops'][0]['name'] = '</h4><script>alert(1)</script>'
        source['shops'][0]['plans'][0]['plan_name'] = '" onmouseover="alert(1)<img src=x>'
        result = r.render(source)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', result)
        self.assertNotIn('<script>alert(1)</script>', result)
        self.assertIn('&lt;img src=x&gt;', result)
        self.assertEqual(result.count('<script>'), 1)

    def test_unsafe_booking_link_is_rejected(self):
        for url in ['javascript:alert(1)', 'https://user:pass@tablecheck.com/x']:
            source = fixture()
            source['shops'][0]['list_url'] = url
            with self.assertRaises(ValueError):
                r.render(source)

    def test_shop_time_is_not_assigned_to_each_plan(self):
        source = fixture()
        source['shops'][0]['time_note'] = 'Store-wide note, not per-plan evidence'
        result = r.render(source)
        self.assertNotIn('Store-wide note', result)
        self.assertIn('提供時間・利用時間 未確認', result)

    def test_no_network_calls(self):
        with patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('network forbidden')):
            self.assertIn('TEST ONLY lounge', r.render(fixture()))

    def test_invalid_generation_preserves_previous_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'site').mkdir()
            (root / 'data').mkdir()
            shutil.copy(r.ROOT / 'data/areas.json', root / 'data/areas.json')
            target = root / 'site/index.html'
            target.write_text('previous page')
            (root / 'site/research.json').write_text('{broken')
            with patch.object(r, 'ROOT', root), self.assertRaises(ValueError):
                r.generate()
            self.assertEqual(target.read_text(), 'previous page')

    def test_generate_only_replaces_index_with_valid_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'site').mkdir()
            (root / 'data').mkdir()
            shutil.copy(r.ROOT / 'data/areas.json', root / 'data/areas.json')
            (root / 'site/research.json').write_text(json.dumps(fixture()))
            before = {p.name: p.read_bytes() for p in (root / 'site').iterdir()}
            with patch.object(r, 'ROOT', root):
                r.generate()
                first = target_text = (root / 'site/index.html').read_text()
                r.generate()
                self.assertEqual((root / 'site/index.html').read_text(), first)
                self.assertNotIn('<div class="aside">', target_text)
            for (name, raw) in before.items():
                self.assertEqual((root / 'site' / name).read_bytes(), raw)
            self.assertEqual(set((p.name for p in (root / 'site').iterdir())), {'index.html', 'research.json'})
            self.assertEqual(validate_site({'site/' + p.name: p.read_bytes() for p in (root / 'site').iterdir()})['shops'], 1)

    def test_symlink_output_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'site').mkdir()
            protected = root / 'protected.html'
            protected.write_text('protected')
            (root / 'site/index.html').symlink_to(protected)
            with patch.object(r, 'ROOT', root), self.assertRaises(ValueError):
                r.generate()
            self.assertEqual(protected.read_text(), 'protected')

    def test_layout_has_reference_responsiveness_and_dark_mode(self):
        result = r.render(fixture())
        for value in ['prefers-color-scheme:dark',
             'max-width:820px',
             'max-width:420px',
             'grid-template-columns:1fr',
             'minmax(330px,1fr)',
             'IntersectionObserver']:
            self.assertIn(value, result)

    def test_simplified_filter_markup_survives_regeneration(self):
        source = fixture()
        before = copy.deepcopy(source)
        for _ in range(2):
            result = r.render(source)
            for removed in ['id="shop-search"', 'id="theme-search"', '店舗・ホテル名', 'プラン名・テーマ', 'data-x="pk"', '料金確認済', '値段確認済', 'イベント・季節で絞り込み']:
                self.assertNotIn(removed, result)
            self.assertIn('日程条件', result)
            self.assertIn('data-x="wd" aria-pressed="false">平日</button>', result)
            self.assertIn('data-x="we" aria-pressed="false">土日祝</button>', result)
            self.assertNotIn('平日に行ける', result)
            self.assertNotIn('土日祝に行ける', result)
            self.assertIn('aria-expanded="false" aria-controls="area-links">詳細</button>', result)
            links = re.search('<div class="btns" id="area-links" hidden>(.*?)</div>', result, re.S).group(1)
            self.assertEqual(len(re.findall('href="#a\\d+"', links)), 14)
            self.assertEqual(len(re.findall('<button[^>]+data-sw=', result)), 15)
            for key in ['xmas', 'valentine', 'whiteday', 'collab', 'season']:
                self.assertNotIn('data-sw="' + key + '" aria-pressed=', result)
            self.assertIn('TEST ONLY lounge', result)
            self.assertIn('TEST winter AT', result)
            self.assertEqual(source, before)

    def test_filter_javascript_runs_locally(self):
        if not shutil.which('node'):
            self.skipTest('Node is needed for local filter execution')
        result = r.render(fixture())
        js = re.search('<script>(.*?)</script>', result, re.S).group(1)
        harness = (
            "\nconst vm=require('vm'),fs=require('fs'),code=JSON.parse(fs.readFileSync(0,"
            "'utf8'));\nfunction node(dataset={}){const n={dataset,hidden:false,value:'',"
            "textContent:'',attrs:{},events:{},classes:new Set(),getAttribute(k){return "
            'this.attrs[k]},setAttribute(k,v){this.attrs[k]=String(v)},addEventListener('
            'k,f){this.events[k]=f}};n.classList={toggle(k,v){v?n.classes.add(k):n.class'
            'es.delete(k)},add(k){n.classes.add(k)}};return n}\nfunction plan(name,price,'
            "sw,wd='0',we='0'){return node({price,sw,wd,we})}\nfunction card(cat,name,sw,"
            'plans){const c=node({cat,sw});c.plans=plans;c.querySelectorAll=()=>plans;re'
            "turn c}\nconst a=card('hotel','Hotel A','scone',[plan('冬','7000','scone ichi"
            "go','1'),plan('夏','11000','choco','0','1')]),b=card('cafe','Cafe B','parfai"
            "t',[plan('unknown','','parfait','0','1')]);const cards=[a,b];\nconst buttons"
            "=[];for(const cat of ['hotel','cafe','lux','unknown']){const n=node({cat});"
            "buttons.push(n)}for(const x of ['wd','we'])buttons.push(node({x}));for(cons"
            "t sw of ['ichigo','scone','choco','parfait','melon'])buttons.push(node({sw}"
            "));\nconst groups=['hotel','cafe','lux'].map(cat=>{const g=node({cat});g.que"
            "rySelectorAll=()=>cards.filter(c=>c.dataset.cat===cat&&!c.classes.has('hide"
            "'));g.querySelector=()=>({textContent:''});return g});\nconst area=node();ar"
            "ea.querySelector=()=>({textContent:''});area.querySelectorAll=()=>cards.fil"
            "ter(c=>!c.classes.has('hide'));\nconst ids={};for(const id of ['price-filter"
            "','filter-status','no-results','reset-filters','area-toggle','area-links'])"
            "ids[id]=node();ids['price-filter'].value='all';\nconst document={getElementB"
            "yId(id){if(['shop-search','theme-search'].includes(id))throw Error('removed"
            " input reference');return ids[id]||null},querySelector(){return null},query"
            "SelectorAll(q){return q==='.card'?cards:q==='.cat'?groups:q==='.fb'?buttons"
            ":q==='section.area'?[area]:[]}};\nconst pageEvents={},pending=[];\nconst wind"
            'ow={addEventListener(name,fn){pageEvents[name]=fn}};\n// Simulate browser-re'
            "stored form values and pressed buttons before script execution.\nids['price-"
            "filter'].value='high';\nbuttons.forEach(b=>b.attrs['aria-pressed']=b.dataset"
            ".cat?'false':'true');\nvm.runInNewContext(code,{document,window,setTimeout(f"
            'n){pending.push(fn)}});\nfunction flush(){while(pending.length)pending.shift'
            "()()}\nfunction assertReset(label){\n if(ids['price-filter'].value!=='all')th"
            "row Error(label+' fields');\n if(buttons.some(b=>b.attrs['aria-pressed']!==("
            "b.dataset.cat?'true':'false')))throw Error(label+' buttons');\n if(cards.som"
            "e(c=>c.classes.has('hide')||c.plans.some(p=>p.hidden)))throw Error(label+' "
            "visibility');\n if(ids['filter-status'].textContent!=='表示 2店舗・3プラン')throw Er"
            "ror(label+' counts');\n}\nassertReset('first load / reload');\nfunction assert"
            "(v,m){if(!v)throw Error(m)}\nfunction input(id,value,event='change'){ids[id]"
            '.value=value;ids[id].events[event]()}\nfunction click(key,value){buttons.fin'
            'd(b=>b.dataset[key]===value).events.click()}\nfunction visible(){return card'
            "s.flatMap(c=>c.plans).filter(p=>!p.hidden).length}\nassert(ids['area-links']"
            ".hidden&&ids['area-toggle'].attrs['aria-expanded']==='false','area initiall"
            "y closed');\nif(process.env.TEST_EARLY_CHOICE){\n click('sw','scone');pageEve"
            "nts.pageshow({persisted:false});flush();assert(visible()===1,'early choice "
            "preserved');ids['reset-filters'].events.click();\n}else{pageEvents.pageshow("
            "{persisted:false});ids['price-filter'].value='high';flush();assertReset('la"
            "te initial restoration')}\nclick('sw','scone');assert(visible()===1&&!a.plan"
            "s[0].hidden&&a.plans[1].hidden,'single sweet count');\nconst status=ids['fil"
            "ter-status'].textContent;\nids['area-toggle'].events.click();assert(!ids['ar"
            "ea-links'].hidden&&ids['area-toggle'].attrs['aria-expanded']==='true'&&ids["
            "'area-toggle'].textContent==='閉じる','expand areas');\nassert(visible()===1&&i"
            "ds['filter-status'].textContent===status,'disclosure leaves filters unchang"
            "ed');\nids['area-toggle'].events.click();assert(ids['area-links'].hidden&&id"
            "s['area-toggle'].textContent==='詳細','collapse areas');\nclick('sw','ichigo')"
            ";assert(visible()===1,'OR overlap counted once');\nclick('sw','choco');asser"
            "t(visible()===2&&!a.classes.has('hide')&&b.classes.has('hide'),'OR differen"
            "t plans');\ninput('price-filter','high');assert(visible()===1&&!a.plans[1].h"
            "idden,'price AND sweets on same plan');\nclick('x','wd');assert(visible()==="
            "0&&!ids['no-results'].hidden,'weekday AND price');\nids['reset-filters'].eve"
            "nts.click();assertReset('manual reset');\nclick('x','we');assert(visible()=="
            "=2&&a.plans[0].hidden,'weekend');\nclick('x','wd');assert(visible()===3,'wee"
            "kday OR weekend includes either day');\nclick('sw','scone');assert(visible()"
            "===1&&!a.plans[0].hidden,'day OR AND sweets');\nclick('sw','choco');assert(v"
            "isible()===2,'both OR groups combine');\ninput('price-filter','high');assert"
            "(visible()===1&&!a.plans[1].hidden,'day OR AND price');\nids['reset-filters'"
            "].events.click();\nconst dayUnknown=plan('日程未確認','7000','scone'),bothDays=pl"
            "an('毎日','7000','scone','1','1');\na.plans.push(dayUnknown,bothDays);ids['res"
            "et-filters'].events.click();\nassert(visible()===5,'no day selection include"
            "s unconfirmed');\nclick('x','wd');assert(visible()===2&&!bothDays.hidden&&da"
            "yUnknown.hidden,'weekday and daily plans');\nclick('x','we');assert(visible("
            ")===4&&!bothDays.hidden&&dayUnknown.hidden,'OR overlap counted once and unk"
            "nown excluded');\nclick('x','wd');assert(visible()===3&&a.plans[0].hidden,'t"
            "urning weekday off leaves weekend');\nclick('x','we');assert(visible()===5&&"
            "!dayUnknown.hidden,'turning both off restores all');\na.plans.splice(-2);ids"
            "['reset-filters'].events.click();\n\nids['reset-filters'].events.click();inpu"
            "t('price-filter','unknown');assert(visible()===1&&!b.plans[0].hidden,'unkno"
            "wn price retained');\nids['reset-filters'].events.click();click('cat','hotel"
            "');assert(a.classes.has('hide')&&visible()===1,'category');\nids['reset-filt"
            "ers'].events.click();click('sw','melon');assert(visible()===0,'zero sweet')"
            ";click('sw','scone');assert(visible()===1,'OR zero sweet');\npageEvents.page"
            "show({persisted:true});assertReset('history return');\nids['price-filter'].v"
            "alue='high';flush();assertReset('late history restoration');\npageEvents.pag"
            "eshow({persisted:true});click('sw','choco');flush();assert(visible()===1&&!"
            "a.plans[1].hidden,'new choice survives queued reset');\nids['reset-filters']"
            ".events.click();assertReset('manual after history');\nconst unknown=card('un"
            "known','Unknown facility','',[plan('不明','','')]);cards.push(unknown);\nbutto"
            "ns.find(b=>b.dataset.cat==='unknown').events.click();assert(unknown.classes"
            ".has('hide'),'unknown category can filter');\nids['reset-filters'].events.cl"
            "ick();assert(!unknown.classes.has('hide')&&!unknown.plans[0].hidden,'reset "
            "includes unknown category');\ncards.pop();ids['reset-filters'].events.click("
            ");assertReset('all categories restored');\ncards.length=0;buttons.find(b=>b."
            "dataset.sw==='ichigo').events.click();assert(!ids['no-results'].hidden,'zer"
            "o-store selected option');\nids['reset-filters'].events.click();assert(ids['"
            "no-results'].hidden,'zero-store reset');\n"
        )
        for early in ('', '1'):
            proc = subprocess.run(['node', '-e', harness], input=json.dumps(js), text=True, capture_output=True, env={**os.environ, 'TEST_EARLY_CHOICE': early})
            self.assertEqual(proc.returncode, 0, proc.stderr)

class OtherAreaTests(unittest.TestCase):

    def test_verified_other_area_does_not_absorb_unknown_location(self):
        source = fixture()
        source['shops'][0]['area_no'] = 15
        result = r.render(source)
        for area in (15, None, 0, 16, '1'):
            source['shops'][0]['area_no'] = area
            result = r.render(source)
            self.assertNotIn('その他のエリア', result)
            self.assertNotIn('TEST ONLY lounge', result)
            self.assertNotIn('id="a0"', result)

SWEETS = ['いちご', 'メロン', '桃', 'マンゴー', 'ぶどう・マスカット', '栗・マロン', '芋・かぼちゃ', '柿・洋梨・いちじく', '柑橘', 'チョコレート', '抹茶・和', 'マカロン', 'パフェ', 'スコーン', 'その他']
EVENTS = ['クリスマス', 'バレンタイン', 'ホワイトデー', 'コラボ企画', '季節の味覚']

class Buttons(HTMLParser):

    def __init__(self, source):
        super().__init__()
        self.buttons = []
        self.current = None
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'button' and 'data-sw' in attrs:
            self.current = {'key': attrs['data-sw'], 'text': '', 'attrs': attrs}

    def handle_data(self, text):
        if self.current is not None:
            self.current['text'] += text

    def handle_endtag(self, tag):
        if tag == 'button' and self.current is not None:
            self.buttons.append(self.current)
            self.current = None

class AllFilterOptionsTests(unittest.TestCase):

    def test_all_fifteen_sweet_options_in_reference_order_for_two_and_zero_stores(self):
        for count in (2, 0):
            data = fixture()
            data['shops'] = [{**data['shops'][0], 'name': 'TEST ' + str(i)} for i in range(count)]
            buttons = Buttons(r.render(data)).buttons
            self.assertEqual(len(buttons), 15)
            self.assertEqual([re.sub('\\d+$', '', b['text']) for b in buttons], SWEETS)
            self.assertTrue(all((b['text'].endswith('0') for b in buttons)))
            self.assertTrue(all(('disabled' not in b['attrs'] for b in buttons)))
            self.assertNotIn('halloween', [b['key'] for b in buttons])

    def test_sweet_counts_are_distinct_plans_and_store_sweets_are_not_inherited(self):
        data = fixture()
        a = data['shops'][0]
        data['shops'] = [{**a,
             'sweets': ['ichigo',
             'xmas'],
             'plans': [{'menu': 'scone scone'},
             {'menu': 'chocolate scone'}]},
             {**a,
             'sweets': ['ichigo'],
             'plans': [{'menu': 'parfait',
             'season': ['xmas']}]}]
        buttons = {b['key']: b['text'] for b in Buttons(r.render(enrich(data))).buttons}
        for (key, count) in {'scone': 2, 'choco': 1, 'parfait': 1, 'ichigo': 0, 'melon': 0, 'macaron': 0}.items():
            self.assertTrue(buttons[key].endswith(str(count)), (key, buttons[key]))

    def test_zero_badge_is_styled_without_hiding_the_button(self):
        result = r.render(fixture())
        self.assertIn('class="bc zero">0</span>', result)
        self.assertIn('.fb .bc.zero{color:var(--sub)}', result)
        self.assertIn('word-break:keep-all', result)


class CanonicalFieldTests(unittest.TestCase):
    def test_only_canonical_station_and_plan_fields_are_displayed(self):
        source=fixture()
        shop=source['shops'][0]
        shop.update(station='日本橋駅／東京駅／日本橋駅',exit='銀座駅 B4出口 徒歩5分',
                    access='新橋駅 直結',time_note='OLD SHOP TIME')
        plan=shop['plans'][0]
        plan.update(price_yen=5000,price_note=None,time_note=None,plan_name=None,
                    price_text='OLD PRICE',time_text='OLD TIME',theme='OLD TITLE',
                    note='OLD NOTE',booking_url_info_only='https://example.com/old-plan',
                    weekday=True,wd=True)
        text=r.render(source)
        self.assertIn('<span class="mk">最寄駅</span>日本橋駅／東京駅',text)
        for old in ('銀座駅','新橋駅','B4出口','徒歩5分','直結','OLD SHOP TIME','OLD PRICE','OLD TIME','OLD TITLE','OLD NOTE','https://example.com/old-plan'):
            self.assertNotIn(old,text)
        self.assertIn('data-wd="0"',text)
        self.assertIn('提供時間・利用時間 未確認',text)
