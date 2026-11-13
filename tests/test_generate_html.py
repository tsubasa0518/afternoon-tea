"""Fixed design, saved JSON and local-only filter tests."""
import copy
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
import afternoon_tea.generate_html as r
from pathlib import Path
from unittest.mock import patch
from afternoon_tea.publication_checks import validate_site
from afternoon_tea.prepare_listings import enrich


def plan(**values):
    """A displayable plan: a name, the page it was read from and when it was read."""
    return {'plan_name': 'TEST plan', 'checked_at': '2026-11-07T10:00:00+09:00',
            'source_url': 'https://example.com/test-only/plan', **values}


def fixture(category='unknown'):
    return {'schema_version': 2,
         'generated_at': '2026-11-07T15:55:22+09:00',
         'period': {'start': '2026-11-07',
         'end': '2026-12-17'},
         'shops': [{'name': 'TEST ONLY lounge',
         'area_no': 1,
         'category': category,
         'station': 'TEST station',
         'info_url': 'https://www.tablecheck.com/ja/shops/test-only/reserve',
         'plans': [{'plan_name': 'TEST winter AT', 'checked_at': '2026-11-07T10:00:00+09:00',
         'source_url': 'https://example.com/test-only/plan',
         'start': None,
         'end': None,
         'price_yen': None}]}]}

class RoutineRendererTests(unittest.TestCase):


    def test_current_saved_data_renders_reproducibly_without_old_store_data(self):
        research = json.loads((r.ROOT / 'website/listings_and_progress.json').read_text())
        before = copy.deepcopy(research)
        result = r.render(research)
        self.assertEqual(research, before)
        self.assertEqual(r.render(research), result)

    def test_zero_stores_and_all_14_areas(self):
        source = fixture()
        source['shops'] = []
        result = r.render(source)
        self.assertIn('確認できた情報はありません', result)
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
        for value in ['料金 未確認', '提供期間 未確認', '平日 未確認', '土日祝 未確認', '提供時間・利用時間 未確認']:
            self.assertIn(value, result)

    def test_categories_use_regular_price_not_stale_categories_or_names(self):
        source = fixture()
        shop = source['shops'][0]
        source['shops'] = [{**shop, 'name': 'TEST ホテル', 'category': 'lux', 'plans': [plan(price_yen=price)]}
                           for price in (5000, 8000, 8001, None)]
        result = r.render(enrich(source))
        for cat in ['cafe', 'hotel', 'lux']:
            self.assertIn(f'class="stat s-{cat}"><b>1</b>', result)
        self.assertIn('class="card c-unknown"', result)

    def test_multiple_plans_keep_menu_and_season_display(self):
        source = fixture()
        source['shops'][0]['plans'] = [plan(plan_name='TEST 1', menu='スコーン', season=['xmas'], price_yen=1000), plan(plan_name='TEST 2', price_yen=2000)]
        result = r.render(enrich(source))
        self.assertIn('プラン1／2', result)
        self.assertIn('プラン2／2', result)
        self.assertIn('メニュー：スコーン', result)
        self.assertIn('季節・イベント', result)
        self.assertIn('クリスマス', result)
        self.assertNotIn('data-sw=', result)
        self.assertNotIn('スイーツ', result)

    def test_outside_plan_is_omitted_without_mutating_evidence(self):
        source = fixture()
        source['shops'][0]['plans'] += [{'plan_name': 'OUTSIDE ONLY', 'start': '2026-12-19', 'end': '2026-12-25'}]
        before = copy.deepcopy(source)
        result = r.render(source)
        self.assertNotIn('OUTSIDE ONLY', result)
        self.assertEqual(source, before)

    def test_research_notice_is_never_rendered_and_json_is_preserved(self):
        failures = {'schema_version': 2,
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
        template = (r.TEMPLATES / 'page_template.html').read_text()
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
                 'info_url': url,
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
                self.assertIn('プランの情報ページ', result)
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
        # Only the trusted filter script and, when enabled, the click decoration script.
        self.assertEqual(result.count('<script>'), 1 + bool(r.click_sparkles()[1]))

    def test_unsafe_booking_link_is_rejected(self):
        for url in ['javascript:alert(1)', 'https://user:pass@tablecheck.com/x']:
            source = fixture()
            source['shops'][0]['info_url'] = url
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
            (root / 'website').mkdir()
            (root / 'research_inputs').mkdir()
            shutil.copy(r.ROOT / 'research_inputs/tokyo_areas.json', root / 'research_inputs/tokyo_areas.json')
            target = root / 'website/index.html'
            target.write_text('previous page')
            (root / 'website/listings_and_progress.json').write_text('{broken')
            with patch.object(r, 'ROOT', root), self.assertRaises(ValueError):
                r.generate()
            self.assertEqual(target.read_text(), 'previous page')

    def test_generate_only_replaces_index_with_valid_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'website').mkdir()
            (root / 'research_inputs').mkdir()
            shutil.copy(r.ROOT / 'research_inputs/tokyo_areas.json', root / 'research_inputs/tokyo_areas.json')
            (root / 'website/listings_and_progress.json').write_text(json.dumps(fixture()))
            before = {p.name: p.read_bytes() for p in (root / 'website').iterdir()}
            with patch.object(r, 'ROOT', root):
                r.generate()
                first = target_text = (root / 'website/index.html').read_text()
                r.generate()
                self.assertEqual((root / 'website/index.html').read_text(), first)
                self.assertNotIn('<div class="aside">', target_text)
            for (name, raw) in before.items():
                self.assertEqual((root / 'website' / name).read_bytes(), raw)
            self.assertEqual(set((p.name for p in (root / 'website').iterdir())), {'index.html', 'listings_and_progress.json'})
            self.assertEqual(validate_site({'website/' + p.name: p.read_bytes() for p in (root / 'website').iterdir()})['shops'], 1)

    def test_symlink_output_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'website').mkdir()
            protected = root / 'protected.html'
            protected.write_text('protected')
            (root / 'website/index.html').symlink_to(protected)
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
            self.assertNotIn('スイーツで絞り込み', result)
            self.assertNotIn('data-sw=', result)
            self.assertIn('TEST ONLY lounge', result)
            self.assertIn('TEST winter AT', result)
            self.assertEqual(source, before)

    def test_filter_javascript_runs_locally(self):
        if not shutil.which('node'):
            self.skipTest('Node is needed for local filter execution')
        result = r.render(fixture())
        js = re.search('<script>(.*?)</script>', result, re.S).group(1)
        harness = (Path(__file__).parent / 'helpers/test_page_filters.js').read_text()
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

class CanonicalFieldTests(unittest.TestCase):
    def test_only_canonical_station_and_plan_fields_are_displayed(self):
        source=fixture()
        shop=source['shops'][0]
        shop.update(station='日本橋駅／東京駅／日本橋駅',exit='銀座駅 B4出口 徒歩5分',
                    access='新橋駅 直結',time_note='OLD SHOP TIME')
        plan=shop['plans'][0]
        plan.update(price_yen=5000,price_note=None,time_note=None,plan_name='TEST plan',
                    price_text='OLD PRICE',time_text='OLD TIME',theme='OLD TITLE',
                    note='OLD NOTE',booking_url_info_only='https://example.com/old-plan',
                    weekday=True,wd=True)
        text=r.render(source)
        self.assertIn('<span class="mk">最寄駅</span>日本橋駅／東京駅',text)
        for old in ('銀座駅','新橋駅','B4出口','徒歩5分','直結','OLD SHOP TIME','OLD PRICE','OLD TIME','OLD TITLE','OLD NOTE','https://example.com/old-plan'):
            self.assertNotIn(old,text)
        self.assertIn('data-wd="0"',text)
        self.assertIn('提供時間・利用時間 未確認',text)


def sparkle_folder(test, **changes):
    """A temporary copy of the click decoration folder with edited settings."""
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    folder = Path(tmp.name) / 'click_sparkles'
    shutil.copytree(r.CLICK_SPARKLES, folder)
    values = json.loads((folder / 'settings.json').read_text())
    values.update(changes)
    (folder / 'settings.json').write_text(json.dumps(values, indent=2) + '\n')
    return folder


def render_with(folder, source):
    with patch.object(r, 'CLICK_SPARKLES', folder):
        return r.render(source)


class ClickSparklesSettingsTests(unittest.TestCase):
    """The decoration is switched by one line in its own settings.json."""

    def test_committed_settings_are_on_1500ms_six_marks_and_one_line_toggles(self):
        path = r.CLICK_SPARKLES / 'settings.json'
        text = path.read_text()
        self.assertEqual(json.loads(text), {'enabled': True, 'duration_ms': 1500, 'particle_count': 6})
        self.assertEqual([line.strip() for line in text.splitlines() if 'enabled' in line], ['"enabled": true,'])
        tmp = sparkle_folder(self)
        (tmp / 'settings.json').write_text(text.replace('"enabled": true', '"enabled": false'))
        self.assertEqual(r.click_sparkles(tmp), ('', ''))
        (tmp / 'settings.json').write_text(text)
        self.assertTrue(all(r.click_sparkles(tmp)))

    def test_enabled_inserts_only_the_effect_blocks_and_disabled_inserts_nothing(self):
        source = fixture()
        on = render_with(sparkle_folder(self, enabled=True), source)
        off = render_with(sparkle_folder(self, enabled=False), source)
        (style, script) = r.click_sparkles(sparkle_folder(self, enabled=True))
        self.assertEqual(on.count(style), 1)
        self.assertEqual(on.count(script), 1)
        self.assertIn('"duration_ms": 1500', script)
        self.assertIn('"particle_count": 6', script)
        self.assertNotIn(r.CLICK_SPARKLES_TOKEN, on)
        # Nothing else changes: no switch, setting panel, demo button or sample content is added to the page.
        self.assertEqual(on.replace(style, '').replace(script, ''), off)
        for text in (off,):
            for word in ('click-sparkle', 'addEventListener(\'pointerdown\'', 'click-sparkles-float', 'prefers-reduced-motion: reduce'):
                self.assertNotIn(word, text)
        self.assertEqual(off.count('<script>'), 1)
        self.assertEqual(on.count('<script>'), 2)
        self.assertLess(on.index('</style>'), on.index(style))
        self.assertLess(on.index('<script>'), on.index(script))
        for text in (on, off):
            self.assertEqual(validate_site({'website/listings_and_progress.json': json.dumps(source).encode(),
                                            'website/index.html': text.encode()})['shops'], 1)

    def test_saved_listings_render_the_same_cards_either_way(self):
        research = json.loads((r.ROOT / 'website/listings_and_progress.json').read_text())
        before = copy.deepcopy(research)
        on = render_with(sparkle_folder(self, enabled=True), research)
        off = render_with(sparkle_folder(self, enabled=False), research)
        self.assertEqual(research, before)
        strip = lambda t: re.sub('<(script|style)>.*?</\\1>', '', t, flags=re.S)
        self.assertEqual(strip(on), strip(off))
        self.assertGreater(on.count('<article class="card '), 0)

    def test_invalid_settings_stop_generation(self):
        for change in ({'enabled': 'false'}, {'enabled': 0}, {'duration_ms': '1500'}, {'duration_ms': 0},
                       {'particle_count': 0}, {'particle_count': 1.5}, {'extra': 1}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                r.click_sparkles(sparkle_folder(self, **change))
        broken = sparkle_folder(self)
        (broken / 'settings.json').write_text('{"enabled": tru')
        with self.assertRaises(ValueError):
            r.click_sparkles(broken)


SPARKLE_HARNESS = r'''
const vm=require('vm'),js=JSON.parse(require('fs').readFileSync(0,'utf8'));
function assert(v,m){if(!v)throw Error(m)}
function el(tag){return {tag,children:[],parentNode:null,className:'',textContent:'',attrs:{},
 style:{props:{},setProperty(k,v){this.props[k]=v}},setAttribute(k,v){this.attrs[k]=String(v)},
 appendChild(c){c.parentNode=this;this.children.push(c);return c},
 removeChild(c){this.children.splice(this.children.indexOf(c),1);c.parentNode=null;return c}}}
const body=el('body'),listeners={},pageListeners={};let reduced=false,failCreate=false,now=0,timers=[];
let selection={isCollapsed:true,toString(){return ''}};
const document={body,createElement(t){if(failCreate)throw Error('boom');return el(t)},
 addEventListener(n,f,o){listeners[n]={f,o}}};
const window={matchMedia(q){assert(q==='(prefers-reduced-motion: reduce)','media query');return {get matches(){return reduced}}},
 getSelection(){return selection},addEventListener(n,f){pageListeners[n]=f}};
function setTimeout(f,ms){timers.push({f,at:now+ms});return timers.length}
function clearTimeout(id){if(timers[id-1])timers[id-1].f=null}
function advance(ms){now+=ms;for(const t of timers){if(t.f&&t.at<=now){const f=t.f;t.f=null;f()}}}
vm.runInNewContext(js,{document,window,setTimeout,clearTimeout});
assert(listeners.click&&listeners.click.o.passive===true,'passive click listener');
assert(listeners.pointerdown&&listeners.pointerdown.o.passive===true,'passive pointer listener');
const calls=[];
function ev(v){return Object.assign({button:0,detail:1,clientX:200,clientY:300,isPrimary:true,
 preventDefault(){calls.push('preventDefault')},stopPropagation(){calls.push('stopPropagation')},
 stopImmediatePropagation(){calls.push('stopImmediatePropagation')}},v)}
function click(v){const e=ev(v);listeners.pointerdown.f(e);listeners.click.f(e)}
function layer(){return body.children.find(c=>c.className==='click-sparkles-layer')}
function count(){const l=layer();return l?l.children.length:0}
click();
const l=layer();assert(l&&l.attrs['aria-hidden']==='true','hidden layer');
assert(l.children.length===6,'six marks: '+l.children.length);
for(const s of l.children){
 assert(s.className==='click-sparkle','class');
 assert(['✨','⭐','🌟','💫','✦'].includes(s.textContent),'mark '+s.textContent);
 const size=parseFloat(s.style.fontSize);assert(size>=12&&size<24,'size '+size);
 assert(s.style.left==='200px'&&s.style.top==='300px','start at the click point');
 const tx=parseFloat(s.style.props['--tx']),ty=parseFloat(s.style.props['--ty']);
 const dist=Math.hypot(tx,ty+80);assert(dist>=50-1e-9&&dist<=110+1e-9,'spread '+dist);
 assert(s.style.animationDuration==='1500ms','duration');
}
const ups=l.children.map(s=>parseFloat(s.style.props['--ty'])).reduce((a,b)=>a+b,0)/6;
assert(ups< -40,'floats upward overall: '+ups);
advance(1499);assert(count()===6,'still shown before 1.5s');
advance(1);assert(count()===0&&!layer(),'removed at 1.5s');
click({detail:0});assert(count()===0,'keyboard Enter makes no marks');
click({button:1});click({button:2});assert(count()===0,'middle/right make no marks');
const drag=ev({clientX:260});listeners.pointerdown.f(ev({}));listeners.click.f(drag);assert(count()===0,'drag makes no marks');
selection={isCollapsed:false,toString(){return 'selected text'}};click();assert(count()===0,'text selection makes no marks');
selection={isCollapsed:true,toString(){return ''}};
reduced=true;click();assert(count()===0,'reduced motion makes no marks');reduced=false;
for(let i=0;i<100;i++){click({clientX:i});assert(count()<=48,'bounded: '+count())}
advance(1500);assert(count()===0&&!layer(),'all removed after rapid clicks');
assert(timers.every(t=>t.f===null),'no pending timers');
click();pageListeners.pagehide();assert(count()===0&&!layer(),'cleared on pagehide');
failCreate=true;click();failCreate=false;
assert(calls.length===0,'never blocks the page: '+calls.join());
click();assert(count()===6,'works again after an error');
process.stdout.write('ok');
'''


class ClickSparklesScriptTests(unittest.TestCase):
    def test_effect_script_behaviour_in_node(self):
        if not shutil.which('node'):
            self.fail('Node is required for the existing offline script tests')
        script = r.click_sparkles(sparkle_folder(self, enabled=True))[1]
        js = script[len('<script>'):-len('</script>')]
        proc = subprocess.run(['node', '-e', SPARKLE_HARNESS], input=json.dumps(js), text=True, capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, 'ok')

    def test_effect_never_blocks_links_or_uses_forbidden_calls(self):
        source = (r.CLICK_SPARKLES / 'effect.js').read_text()
        code = re.sub(r'/\*.*?\*/|//[^\n]*', '', source, flags=re.S)
        for word in ('preventDefault', 'stopPropagation', 'location', 'href', 'target', 'window.open', 'tabindex',
                     'focus(', 'scrollTo', 'Audio', 'setInterval', 'requestAnimationFrame', 'mousemove', 'pointermove'):
            self.assertNotIn(word, code)
        css = (r.CLICK_SPARKLES / 'effect.css').read_text()
        self.assertIn('pointer-events:none', css)
        self.assertIn('1.5s ease-out', css)
        self.assertIn('rotate(360deg) scale(0);opacity:0', css)
        self.assertIn('prefers-reduced-motion:reduce', css)
        for word in ('touch-action', 'overflow:hidden}html', 'body{', 'html{'):
            self.assertNotIn(word, css)


try:
    import playwright.sync_api  # noqa: F401
    HAVE_PLAYWRIGHT = True
except ImportError:
    HAVE_PLAYWRIGHT = False

PAGE = 'https://afternoon-tea.test/'
LINK = 'https://link-target.test/shop'


@unittest.skipUnless(HAVE_PLAYWRIGHT, 'Playwright is not installed')
class ClickSparklesBrowserTests(unittest.TestCase):
    """Real headless browser on a generated local page; every request is answered locally."""

    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        from afternoon_tea.research_browser import _launch
        cls.pw = sync_playwright().start()
        cls.browser = _launch(cls.pw)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def page(self, enabled=True, init=None, **options):
        source = fixture('cafe')
        source['shops'][0]['info_url'] = LINK
        source['shops'][0]['plans'][0].update(source_url=LINK + '/plan', price_yen=4000, weekday_available=True)
        html = render_with(sparkle_folder(self, enabled=enabled), source)
        context = self.browser.new_context(**options)
        self.addCleanup(context.close)
        requests = []

        def answer(route):
            url = route.request.url
            requests.append(url)
            if url == PAGE:
                route.fulfill(status=200, content_type='text/html; charset=utf-8', body=html)
            elif url.startswith(LINK):
                route.fulfill(status=200, content_type='text/html; charset=utf-8', body='<title>LOCAL TEST LINK</title>LOCAL TEST LINK')
            else:
                route.abort()
        context.route('**/*', answer)
        if init:
            context.add_init_script(init)
        page = context.new_page()
        page.goto(PAGE)
        self.assertTrue(all(u == PAGE or u.startswith(LINK) or 'fonts.g' in u for u in requests), requests)
        return context, page

    def loaded(self, tab):
        tab.wait_for_load_state()
        self.assertEqual(tab.title(), 'LOCAL TEST LINK')
        return tab.url

    def marks(self, page):
        return page.locator('.click-sparkle').count()

    def blank_point(self, page):
        box = page.locator('.hero h1').bounding_box()
        return box['x'] + box['width'] + 20, box['y'] + 10

    def filters_work(self, page):
        page.click('button[data-x="wd"]')
        self.assertEqual(page.get_attribute('button[data-x="wd"]', 'aria-pressed'), 'true')
        page.select_option('#price-filter', 'high')
        self.assertTrue(page.locator('#no-results').is_visible())
        page.click('#reset-filters')
        self.assertEqual(page.text_content('#filter-status'), '表示 1店舗・1プラン')
        page.click('#area-toggle')
        self.assertEqual(page.get_attribute('#area-toggle', 'aria-expanded'), 'true')
        page.click('#area-toggle')
        self.assertEqual(page.get_attribute('#area-toggle', 'aria-expanded'), 'false')

    def test_click_shows_six_rising_marks_for_1500ms_then_removes_them(self):
        (context, page) = self.page()
        size = page.evaluate('[document.documentElement.scrollWidth,document.documentElement.scrollHeight,scrollY]')
        (x, y) = self.blank_point(page)
        page.mouse.click(x, y)
        self.assertEqual(self.marks(page), 6)
        info = page.evaluate('''() => [...document.querySelectorAll('.click-sparkle')].map(e => {const s = getComputedStyle(e);
            return [e.textContent, s.animationDuration, s.animationTimingFunction, s.pointerEvents, parseFloat(s.fontSize)]})''')
        for (mark, duration, easing, pointer, font) in info:
            self.assertIn(mark, ['✨', '⭐', '🌟', '💫', '✦'])
            self.assertEqual((duration, easing, pointer), ('1.5s', 'ease-out', 'none'))
            self.assertTrue(12 <= font <= 24, font)
        layer = page.evaluate('''(() => {const l = document.querySelector('.click-sparkles-layer'), s = getComputedStyle(l);
            return [l.getAttribute('aria-hidden'), s.pointerEvents, s.position, l.tabIndex]})()''')
        self.assertEqual(layer, ['true', 'none', 'fixed', -1])
        page.wait_for_timeout(700)
        mid = page.evaluate('''[...document.querySelectorAll('.click-sparkle')].map(e => [parseFloat(getComputedStyle(e).opacity),
            new DOMMatrix(getComputedStyle(e).transform).f])''')
        self.assertTrue(all(0 < o < 1 for (o, _) in mid), mid)
        self.assertLess(sum(dy for (_, dy) in mid) / len(mid), 0)
        self.assertEqual(page.evaluate('[document.documentElement.scrollWidth,document.documentElement.scrollHeight,scrollY]'), size)
        page.wait_for_timeout(900)
        self.assertEqual(self.marks(page), 0)
        self.assertEqual(page.locator('.click-sparkles-layer').count(), 0)

    def test_links_and_buttons_work_through_and_under_the_marks(self):
        (context, page) = self.page()
        link = page.locator('.card .links a').first
        self.assertEqual((link.get_attribute('href'), link.get_attribute('target'), link.get_attribute('rel')),
                         (LINK, '_blank', 'noopener noreferrer'))
        link.scroll_into_view_if_needed()
        box = link.bounding_box()
        (cx, cy) = (box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
        page.mouse.click(cx, cy - box['height'] / 2 - 4)
        self.assertEqual(page.evaluate(f'document.elementFromPoint({cx},{cy}).closest("a") !== null'), True)
        page.evaluate('''window.__prevented = []; addEventListener('click', e => __prevented.push(e.defaultPrevented));
            addEventListener('auxclick', e => __prevented.push(e.defaultPrevented))''')
        with context.expect_page() as opened:
            page.mouse.click(cx, cy)
        self.assertEqual(self.loaded(opened.value), LINK)
        opened.value.close()
        # Six from the click beside the link and six from the link click itself.
        self.assertEqual(self.marks(page), 12)
        modifier = 'Meta' if __import__('sys').platform == 'darwin' else 'Control'
        # Ctrl/Command+click and middle click: headless Chromium opens a background tab but does not load it,
        # with or without the effect, so the browser's own new-tab action and the uncancelled events are checked.
        with context.expect_page() as opened:
            link.click(modifiers=[modifier])
        opened.value.close()
        with context.expect_page() as opened:
            link.click(button='middle')
        opened.value.close()
        page.wait_for_timeout(1600)
        link.focus()
        with context.expect_page() as opened:
            page.keyboard.press('Enter')
        self.assertEqual(self.loaded(opened.value), LINK)
        opened.value.close()
        self.assertEqual(self.marks(page), 0)
        prevented = page.evaluate('__prevented')
        self.assertGreaterEqual(len(prevented), 4)
        self.assertEqual(prevented, [False] * len(prevented))
        self.filters_work(page)

    def test_same_tab_link_navigates_while_marks_are_shown(self):
        (context, page) = self.page()
        page.evaluate(f'''(() => {{const a = document.createElement('a'); a.id = 'same'; a.href = '{LINK}/same';
            a.textContent = 'LOCAL SAME TAB LINK'; document.querySelector('main').prepend(a)}})()''')
        page.click('#same')
        page.wait_for_url(LINK + '/same')
        self.assertEqual(page.title(), 'LOCAL TEST LINK')

    def test_no_marks_for_drag_selection_scroll_or_reduced_motion(self):
        (context, page) = self.page()
        box = page.locator('.hero h1').bounding_box()
        page.mouse.move(box['x'] + 2, box['y'] + box['height'] / 2)
        page.mouse.down()
        page.mouse.move(box['x'] + box['width'] - 2, box['y'] + box['height'] / 2, steps=8)
        page.mouse.up()
        self.assertTrue(page.evaluate('String(getSelection()).length > 0'))
        page.mouse.wheel(0, 600)
        page.wait_for_timeout(200)
        page.mouse.move(*self.blank_point(page))
        self.assertEqual(self.marks(page), 0)
        (context, page) = self.page(reduced_motion='reduce')
        page.mouse.click(*self.blank_point(page))
        self.assertEqual(self.marks(page), 0)
        self.filters_work(page)

    def test_one_tap_makes_one_burst_on_a_phone_and_layout_does_not_overflow(self):
        (context, page) = self.page(viewport={'width': 375, 'height': 740}, has_touch=True, is_mobile=True, device_scale_factor=2)
        page.touchscreen.tap(20, 20)
        self.assertEqual(self.marks(page), 6)
        page.touchscreen.tap(368, 30)
        self.assertEqual(self.marks(page), 12)
        self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
        page.wait_for_timeout(1600)
        self.assertEqual(self.marks(page), 0)

    def test_rapid_clicks_stay_bounded_and_clean_up(self):
        (context, page) = self.page()
        (x, y) = self.blank_point(page)
        for i in range(40):
            page.mouse.click(x + i % 5, y)
        self.assertLessEqual(self.marks(page), 48)
        page.wait_for_timeout(1600)
        self.assertEqual(self.marks(page), 0)

    def test_effect_failure_or_disabled_effect_leaves_page_working(self):
        for (enabled, init) in ((True, 'window.matchMedia = () => { throw Error("TEST failure") }'),
                                (True, 'const make = Document.prototype.createElement; Document.prototype.createElement = function (t) {'
                                       ' if (t === "span") throw Error("TEST failure"); return make.call(this, t) }'),
                                (False, None)):
            with self.subTest(enabled=enabled, init=bool(init)):
                (context, page) = self.page(enabled=enabled, init=init)
                page.mouse.click(*self.blank_point(page))
                self.assertEqual(self.marks(page), 0)
                self.filters_work(page)
                with context.expect_page() as opened:
                    page.locator('.card .links a').first.click()
                self.assertEqual(self.loaded(opened.value), LINK)
                if not enabled:
                    self.assertEqual(page.locator('style').count(), 1)
                    self.assertEqual(page.locator('script').count(), 1)
