"""Fixed design, saved JSON and local-only filter tests."""
import copy
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from afternoon_tea import routine_renderer as r
from afternoon_tea.routine_site import validate_site, ALLOWED


def fixture(category='hotel'):
    return {'schema_version':1,'generated_at':'2026-11-07T15:55:22+09:00',
            'period':{'start':'2026-11-07','end':'2026-12-17'},
            'shops':[{'name':'TEST ONLY lounge','area_no':1,'category':category,
                      'station':'TEST station','source_url':'https://www.tablecheck.com/ja/shops/test-only/reserve',
                      'plans':[{'plan_name':'TEST winter AT','start':None,'end':None,'price_yen':None}]}]}
FAILURES={'schema_version':1,'generated_at':None,'failures':[]}


class RoutineRendererTests(unittest.TestCase):
    def test_reference_css_is_preserved_exactly(self):
        ref=(r.ROOT/'afternoon_tea_tokyo_2026-11-06.html').read_text()
        for name,pattern in [('routine.css',r'<style>(.*?)</style>')]:
            self.assertEqual((r.TEMPLATES/name).read_text(),re.search(pattern,ref,re.S).group(1))
    def test_current_saved_data_renders_reproducibly_without_old_store_data(self):
        research=json.loads((r.ROOT/'site/research.json').read_text());failures=json.loads((r.ROOT/'site/search_failures.json').read_text())
        before=copy.deepcopy(research);result=r.render(research,failures)
        self.assertEqual(research,before)
        self.assertEqual(result,(r.ROOT/'site/index.html').read_text())
        self.assertEqual(r.render(research,failures),result)
    def test_zero_stores_and_all_14_areas(self):
        source=fixture();source['shops']=[];result=r.render(source,FAILURES)
        self.assertIn('今週は確認できた情報がありません',result)
        for no in range(1,15):
            self.assertIn('id="a'+str(no)+'"',result);self.assertIn('href="#a'+str(no)+'"',result)
        self.assertNotIn('<article ',result)
    def test_reference_card_and_plan_dom_and_unknown_values(self):
        result=r.render(fixture(),FAILURES)
        self.assertNotIn('cafe VAVA',result)
        for value in ['class="card c-unknown"','class="plan"','class="when"','class="price"','class="links"','class="meet"','class="top"','class="plans"','class="totop"']:
            self.assertIn(value,result)
        for value in ['料金 未確認','提供期間 未確認','平日 未確認','土日祝 未確認','提供時間・利用時間 未確認','スイーツ・季節分類 未確認']:
            self.assertIn(value,result)
    def test_categories_use_regular_price_even_with_stale_venue_categories(self):
        source=fixture();shop=source['shops'][0]
        source['shops']=[{**shop,'category':'lux','plans':[{'price_yen':price}]} for price in (6000,6001,10000,None)]
        result=r.render(source,FAILURES)
        for cat in ['cafe','hotel','lux']:self.assertIn(f'class="stat s-{cat}"><b>1</b>',result)
        self.assertIn('class="card c-unknown"',result)
    def test_multiple_plans_and_dynamic_sweet_counts(self):
        source=fixture();source['shops'][0]['sweets']=['scone','xmas']
        source['shops'][0]['plans']=[{'plan_name':'TEST 1','menu':'スコーン','price_yen':1000},{'plan_name':'TEST 2','price_yen':2000}]
        result=r.render(source,FAILURES)
        self.assertIn('プラン1／2',result);self.assertIn('プラン2／2',result)
        self.assertIn('data-sw="scone" aria-pressed="false">スコーン<span class="bc">1</span>',result)
        self.assertNotIn('data-sw="xmas" aria-pressed=',result)
    def test_outside_plan_is_omitted_without_mutating_evidence(self):
        source=fixture();source['shops'][0]['plans'] += [{'plan_name':'OUTSIDE ONLY','start':'2026-12-19','end':'2026-12-25'}]
        before=copy.deepcopy(source);result=r.render(source,FAILURES)
        self.assertNotIn('OUTSIDE ONLY',result);self.assertEqual(source,before)
    def test_research_notice_is_never_rendered_and_json_is_preserved(self):
        failures={'schema_version':1,'generated_at':None,'failures':[{
            'name':'TEST unresearched venue','area':'TEST area','checked_at':'2026-11-07T15:55:22+09:00',
            'sources':[],'status':'unresearched','reason':'TEST restriction audit only','retry':True}]}
        for count in (0,1):
            source=fixture();source['note']='TEST research note must remain in JSON only'
            source['shops']=source['shops'][:count]
            if count:source['shops'][0]['plans'].append({'plan_name':'OUTSIDE ONLY','start':'2026-12-19'})
            before=copy.deepcopy((source,failures))
            for _ in range(2):
                result=r.render(source,failures)
                for removed in ['<div class="aside">','<div class="box">',source['note'],
                                'TEST restriction audit only','未調査店舗','分類は原則として価格帯',
                                '掲載なしはAT提供なしを意味しません','プランは掲載対象から除きました']:
                    self.assertNotIn(removed,result)
                if count:
                    self.assertIn('class="card c-unknown"',result)
                    self.assertIn('料金 未確認',result)
                self.assertEqual((source,failures),before)
        template=(r.TEMPLATES/'routine.html').read_text()
        self.assertNotIn('$notice',template)
        self.assertNotIn('class="aside"',template)

    def test_card_evidence_display_is_omitted_but_links_and_json_remain(self):
        urls=['https://restaurant.ikyu.com/123456/plan111111',
              'https://www.tablecheck.com/ja/shops/test-only/reserve',
              'https://tabelog.com/tokyo/A1301/A130101/12345678/',
              'https://www.example.com/afternoon-tea/']
        for price,label in [(5000,'カフェ'),(7000,'ホテル'),(10000,'ホテル（高級）')]:
            data=fixture();base=data['shops'][0]
            data['shops']=[{**base,'name':'TEST venue '+str(i),'source_url':url,
                            'checked_at':'2026-11-06T09:00:00+09:00','evidence_quote':'TEST shop evidence',
                            'plans':[{'plan_name':'TEST plan','source_url':url,'booking_url_info_only':url,
                                      'checked_at':'2026-11-06T10:00:00+09:00','evidence_quote':'TEST plan evidence',
                                      'price_yen':price,'start':'2026-11-07','end':'2026-12-01',
                                      'weekday_available':True}]} for i,url in enumerate(urls)]
            before=copy.deepcopy(data)
            for _ in range(2):
                result=r.render(data,FAILURES)
                for removed in ['出典：','確認日時：','2026-11-06T09:00:00+09:00',
                                '2026-11-06T10:00:00+09:00','TEST shop evidence','TEST plan evidence']:
                    self.assertNotIn(removed,result)
                for url in urls:
                    self.assertEqual(result.count('href="'+url+'"'),2)
                self.assertEqual(result.count('<p class="rnote">'+label+'</p>'),4)
                self.assertIn('プランの予約・情報ページ',result)
                self.assertIn('2026/11/7〜2026/12/1',result)
                self.assertIn('data-wd="1"',result)
                self.assertEqual(data,before)

    def test_text_and_attribute_injection_is_escaped(self):
        source=fixture();source['shops'][0]['name']='</h4><script>alert(1)</script>'
        source['shops'][0]['plans'][0]['plan_name']='" onmouseover="alert(1)<img src=x>'
        result=r.render(source,FAILURES)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;',result)
        self.assertNotIn('<script>alert(1)</script>',result)
        self.assertIn('&lt;img src=x&gt;',result)
        self.assertEqual(result.count('<script>'),1)
    def test_unsafe_booking_link_is_rejected(self):
        for url in ['javascript:alert(1)','https://user:pass@tablecheck.com/x']:
            source=fixture();source['shops'][0]['source_url']=url
            with self.assertRaises(ValueError):r.render(source,FAILURES)
    def test_shop_time_is_not_assigned_to_each_plan(self):
        source=fixture();source['shops'][0]['time_note']='Store-wide note, not per-plan evidence'
        result=r.render(source,FAILURES)
        self.assertEqual(result.count('Store-wide note'),1)
        self.assertIn('提供時間・利用時間 未確認',result)
    def test_no_network_calls(self):
        with patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('network forbidden')):
            self.assertIn('TEST ONLY lounge',r.render(fixture(),FAILURES))
    def test_invalid_generation_preserves_previous_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'site').mkdir();(root/'data').mkdir()
            shutil.copy(r.ROOT/'data/store_master.json',root/'data/store_master.json')
            target=root/'site/index.html';target.write_text('previous page')
            (root/'site/research.json').write_text('{broken');(root/'site/search_failures.json').write_text(json.dumps(FAILURES))
            with patch.object(r,'ROOT',root),self.assertRaises(ValueError):r.generate()
            self.assertEqual(target.read_text(),'previous page')
    def test_generate_only_replaces_index_with_valid_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'site').mkdir();(root/'data').mkdir()
            shutil.copy(r.ROOT/'data/store_master.json',root/'data/store_master.json')
            (root/'site/research.json').write_text(json.dumps(fixture()));(root/'site/search_failures.json').write_text(json.dumps(FAILURES))
            before={p.name:p.read_bytes() for p in (root/'site').iterdir()}
            with patch.object(r,'ROOT',root):
                r.generate();first=target_text=(root/'site/index.html').read_text()
                r.generate();self.assertEqual((root/'site/index.html').read_text(),first)
                self.assertNotIn('<div class="aside">',target_text)
            for name,raw in before.items():self.assertEqual((root/'site'/name).read_bytes(),raw)
            self.assertEqual(set(p.name for p in (root/'site').iterdir()),{'index.html','research.json','search_failures.json'})
            self.assertEqual(validate_site({'site/'+p.name:p.read_bytes() for p in (root/'site').iterdir()})['shops'],1)
    def test_symlink_output_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'site').mkdir();protected=root/'protected.html';protected.write_text('protected')
            (root/'site/index.html').symlink_to(protected)
            with patch.object(r,'ROOT',root),self.assertRaises(ValueError):r.generate()
            self.assertEqual(protected.read_text(),'protected')
    def test_layout_has_reference_responsiveness_and_dark_mode(self):
        result=r.render(fixture(),FAILURES)
        for value in ['prefers-color-scheme:dark','max-width:820px','max-width:420px','grid-template-columns:1fr','minmax(330px,1fr)','IntersectionObserver']:
            self.assertIn(value,result)
    def test_simplified_filter_markup_survives_regeneration(self):
        source=fixture();before=copy.deepcopy(source)
        for _ in range(2):
            result=r.render(source,FAILURES)
            for removed in ['id="shop-search"','id="theme-search"','店舗・ホテル名','プラン名・テーマ',
                            'data-x="pk"','料金確認済','値段確認済','イベント・季節で絞り込み']:
                self.assertNotIn(removed,result)
            self.assertIn('日程条件',result)
            self.assertIn('data-x="wd" aria-pressed="false">平日</button>',result)
            self.assertIn('data-x="we" aria-pressed="false">土日祝</button>',result)
            self.assertNotIn('平日に行ける',result);self.assertNotIn('土日祝に行ける',result)
            self.assertIn('aria-expanded="false" aria-controls="area-links">詳細</button>',result)
            links=re.search(r'<div class="btns" id="area-links" hidden>(.*?)</div>',result,re.S).group(1)
            self.assertEqual(len(re.findall(r'href="#a\d+"',links)),15)
            self.assertEqual(len(re.findall(r'<button[^>]+data-sw=',result)),15)
            for key in ['xmas','valentine','whiteday','collab','season']:
                self.assertNotIn('data-sw="'+key+'" aria-pressed=',result)
            self.assertIn('TEST ONLY lounge',result);self.assertIn('TEST winter AT',result)
            self.assertEqual(source,before)

    def test_filter_javascript_runs_locally(self):
        if not shutil.which('node'):self.skipTest('Node is needed for local filter execution')
        result=r.render(fixture(),FAILURES);js=re.search(r'<script>(.*?)</script>',result,re.S).group(1)
        harness=r'''
const vm=require('vm'),fs=require('fs'),code=JSON.parse(fs.readFileSync(0,'utf8'));
function node(dataset={}){const n={dataset,hidden:false,value:'',textContent:'',attrs:{},events:{},classes:new Set(),getAttribute(k){return this.attrs[k]},setAttribute(k,v){this.attrs[k]=String(v)},addEventListener(k,f){this.events[k]=f}};n.classList={toggle(k,v){v?n.classes.add(k):n.classes.delete(k)},add(k){n.classes.add(k)}};return n}
function plan(name,price,sw,wd='0',we='0'){return node({price,sw,wd,we})}
function card(cat,name,sw,plans){const c=node({cat,sw});c.plans=plans;c.querySelectorAll=()=>plans;return c}
const a=card('hotel','Hotel A','scone',[plan('冬','7000','scone ichigo','1'),plan('夏','11000','choco','0','1')]),b=card('cafe','Cafe B','parfait',[plan('unknown','','parfait','0','1')]);const cards=[a,b];
const buttons=[];for(const cat of ['hotel','cafe','lux','unknown']){const n=node({cat});buttons.push(n)}for(const x of ['wd','we'])buttons.push(node({x}));for(const sw of ['ichigo','scone','choco','parfait','melon'])buttons.push(node({sw}));
const groups=['hotel','cafe','lux'].map(cat=>{const g=node({cat});g.querySelectorAll=()=>cards.filter(c=>c.dataset.cat===cat&&!c.classes.has('hide'));g.querySelector=()=>({textContent:''});return g});
const area=node();area.querySelector=()=>({textContent:''});area.querySelectorAll=()=>cards.filter(c=>!c.classes.has('hide'));
const ids={};for(const id of ['price-filter','filter-status','no-results','reset-filters','area-toggle','area-links'])ids[id]=node();ids['price-filter'].value='all';
const document={getElementById(id){if(['shop-search','theme-search'].includes(id))throw Error('removed input reference');return ids[id]||null},querySelector(){return null},querySelectorAll(q){return q==='.card'?cards:q==='.cat'?groups:q==='.fb'?buttons:q==='section.area'?[area]:[]}};
const pageEvents={},pending=[];
const window={addEventListener(name,fn){pageEvents[name]=fn}};
// Simulate browser-restored form values and pressed buttons before script execution.
ids['price-filter'].value='high';
buttons.forEach(b=>b.attrs['aria-pressed']=b.dataset.cat?'false':'true');
vm.runInNewContext(code,{document,window,setTimeout(fn){pending.push(fn)}});
function flush(){while(pending.length)pending.shift()()}
function assertReset(label){
 if(ids['price-filter'].value!=='all')throw Error(label+' fields');
 if(buttons.some(b=>b.attrs['aria-pressed']!==(b.dataset.cat?'true':'false')))throw Error(label+' buttons');
 if(cards.some(c=>c.classes.has('hide')||c.plans.some(p=>p.hidden)))throw Error(label+' visibility');
 if(ids['filter-status'].textContent!=='表示 2店舗・3プラン')throw Error(label+' counts');
}
assertReset('first load / reload');
function assert(v,m){if(!v)throw Error(m)}
function input(id,value,event='change'){ids[id].value=value;ids[id].events[event]()}
function click(key,value){buttons.find(b=>b.dataset[key]===value).events.click()}
function visible(){return cards.flatMap(c=>c.plans).filter(p=>!p.hidden).length}
assert(ids['area-links'].hidden&&ids['area-toggle'].attrs['aria-expanded']==='false','area initially closed');
if(process.env.TEST_EARLY_CHOICE){
 click('sw','scone');pageEvents.pageshow({persisted:false});flush();assert(visible()===1,'early choice preserved');ids['reset-filters'].events.click();
}else{pageEvents.pageshow({persisted:false});ids['price-filter'].value='high';flush();assertReset('late initial restoration')}
click('sw','scone');assert(visible()===1&&!a.plans[0].hidden&&a.plans[1].hidden,'single sweet count');
const status=ids['filter-status'].textContent;
ids['area-toggle'].events.click();assert(!ids['area-links'].hidden&&ids['area-toggle'].attrs['aria-expanded']==='true'&&ids['area-toggle'].textContent==='閉じる','expand areas');
assert(visible()===1&&ids['filter-status'].textContent===status,'disclosure leaves filters unchanged');
ids['area-toggle'].events.click();assert(ids['area-links'].hidden&&ids['area-toggle'].textContent==='詳細','collapse areas');
click('sw','ichigo');assert(visible()===1,'OR overlap counted once');
click('sw','choco');assert(visible()===2&&!a.classes.has('hide')&&b.classes.has('hide'),'OR different plans');
input('price-filter','high');assert(visible()===1&&!a.plans[1].hidden,'price AND sweets on same plan');
click('x','wd');assert(visible()===0&&!ids['no-results'].hidden,'weekday AND price');
ids['reset-filters'].events.click();assertReset('manual reset');
click('x','we');assert(visible()===2&&a.plans[0].hidden,'weekend');
click('x','wd');assert(visible()===3,'weekday OR weekend includes either day');
click('sw','scone');assert(visible()===1&&!a.plans[0].hidden,'day OR AND sweets');
click('sw','choco');assert(visible()===2,'both OR groups combine');
input('price-filter','high');assert(visible()===1&&!a.plans[1].hidden,'day OR AND price');
ids['reset-filters'].events.click();
const dayUnknown=plan('日程未確認','7000','scone'),bothDays=plan('毎日','7000','scone','1','1');
a.plans.push(dayUnknown,bothDays);ids['reset-filters'].events.click();
assert(visible()===5,'no day selection includes unconfirmed');
click('x','wd');assert(visible()===2&&!bothDays.hidden&&dayUnknown.hidden,'weekday and daily plans');
click('x','we');assert(visible()===4&&!bothDays.hidden&&dayUnknown.hidden,'OR overlap counted once and unknown excluded');
click('x','wd');assert(visible()===3&&a.plans[0].hidden,'turning weekday off leaves weekend');
click('x','we');assert(visible()===5&&!dayUnknown.hidden,'turning both off restores all');
a.plans.splice(-2);ids['reset-filters'].events.click();

ids['reset-filters'].events.click();input('price-filter','unknown');assert(visible()===1&&!b.plans[0].hidden,'unknown price retained');
ids['reset-filters'].events.click();click('cat','hotel');assert(a.classes.has('hide')&&visible()===1,'category');
ids['reset-filters'].events.click();click('sw','melon');assert(visible()===0,'zero sweet');click('sw','scone');assert(visible()===1,'OR zero sweet');
pageEvents.pageshow({persisted:true});assertReset('history return');
ids['price-filter'].value='high';flush();assertReset('late history restoration');
pageEvents.pageshow({persisted:true});click('sw','choco');flush();assert(visible()===1&&!a.plans[1].hidden,'new choice survives queued reset');
ids['reset-filters'].events.click();assertReset('manual after history');
const unknown=card('unknown','Unknown facility','',[plan('不明','','')]);cards.push(unknown);
buttons.find(b=>b.dataset.cat==='unknown').events.click();assert(unknown.classes.has('hide'),'unknown category can filter');
ids['reset-filters'].events.click();assert(!unknown.classes.has('hide')&&!unknown.plans[0].hidden,'reset includes unknown category');
cards.pop();ids['reset-filters'].events.click();assertReset('all categories restored');
cards.length=0;buttons.find(b=>b.dataset.sw==='ichigo').events.click();assert(!ids['no-results'].hidden,'zero-store selected option');
ids['reset-filters'].events.click();assert(ids['no-results'].hidden,'zero-store reset');
'''
        for early in ('','1'):
            proc=subprocess.run(['node','-e',harness],input=json.dumps(js),text=True,capture_output=True,env={**os.environ,'TEST_EARLY_CHOICE':early})
            self.assertEqual(proc.returncode,0,proc.stderr)

class OtherAreaTests(unittest.TestCase):
    def test_verified_other_area_does_not_absorb_unknown_location(self):
        source=fixture(); source['shops'][0]['area_no']=15
        result=r.render(source,FAILURES)
        self.assertIn('href="#a15"',result)
        self.assertIn('その他のエリア',result)
        self.assertIn('TEST ONLY lounge',result.split('id="a15"')[1])
        source['shops'][0]['area_no']=None
        self.assertIn('id="a0"',r.render(source,FAILURES))
