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
    def test_reference_css_and_base_js_are_preserved_exactly(self):
        ref=(r.ROOT/'afternoon_tea_tokyo_2026-11-06.html').read_text()
        for name,pattern in [('routine.css',r'<style>(.*?)</style>'),('routine.js',r'<script>(.*?)</script>')]:
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
        self.assertIn('class="card c-unknown"',result);self.assertIn('分類未確認：1店舗',result)
    def test_multiple_plans_and_dynamic_sweet_counts(self):
        source=fixture();source['shops'][0]['sweets']=['scone','xmas']
        source['shops'][0]['plans']=[{'plan_name':'TEST 1','price_yen':1000},{'plan_name':'TEST 2','price_yen':2000}]
        result=r.render(source,FAILURES)
        self.assertIn('プラン1／2',result);self.assertIn('プラン2／2',result)
        self.assertIn('data-sw="scone" aria-pressed="false">スコーン<span class="bc">1</span>',result)
        self.assertIn('data-sw="xmas" aria-pressed="false">クリスマス<span class="bc">1</span>',result)
    def test_outside_plan_is_omitted_without_mutating_evidence(self):
        source=fixture();source['shops'][0]['plans'] += [{'plan_name':'OUTSIDE ONLY','start':'2026-12-19','end':'2026-12-25'}]
        before=copy.deepcopy(source);result=r.render(source,FAILURES)
        self.assertNotIn('OUTSIDE ONLY',result);self.assertIn('1プランは掲載対象から除きました',result);self.assertEqual(source,before)
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
            with patch.object(r,'ROOT',root):r.generate()
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
    def test_filter_javascript_runs_locally(self):
        if not shutil.which('node'):self.skipTest('Node is needed for local filter execution')
        result=r.render(fixture(),FAILURES);js=re.search(r'<script>(.*?)</script>',result,re.S).group(1)
        harness=r'''
const vm=require('vm'),fs=require('fs'),code=JSON.parse(fs.readFileSync(0,'utf8'));
function node(dataset={}){const n={dataset,hidden:false,value:'',textContent:'',attrs:{},events:{},classes:new Set(),getAttribute(k){return this.attrs[k]},setAttribute(k,v){this.attrs[k]=v},addEventListener(k,f){this.events[k]=f}};n.classList={toggle(k,v){v?n.classes.add(k):n.classes.delete(k)},add(k){n.classes.add(k)}};return n}
function plan(name,price,wd='0',we='0'){const p=node({price,pk:price===''?'0':'1',wd,we});p.querySelector=()=>({textContent:name});return p}
function card(cat,name,sw,plans){const c=node({cat,sw,shopSw:sw,wd:'1',we:'1',pk:'1'});c.plans=plans;c.querySelector=()=>({textContent:name});c.querySelectorAll=()=>plans;return c}
const a=card('hotel','Hotel A','scone xmas',[plan('冬', '7000','1'),plan('夏','11000','0','1')]),b=card('cafe','Cafe B','parfait',[plan('unknown','','0','1')]);const cards=[a,b];a.plans[0].dataset.tagsSpecified='1';a.plans[0].dataset.sw='scone xmas';a.plans[1].dataset.tagsSpecified='1';a.plans[1].dataset.sw='choco';
const buttons=[];for(const cat of ['hotel','cafe','lux']){const x=node({cat});x.attrs['aria-pressed']='true';buttons.push(x)}for(const x of ['wd','we','pk']){const n=node({x});n.attrs['aria-pressed']='false';buttons.push(n)}for(const sw of ['ichigo','scone','xmas']){const n=node({sw});n.attrs['aria-pressed']='false';buttons.push(n)}
const groups=['hotel','cafe','lux'].map(cat=>{const g=node({cat});g.querySelectorAll=()=>cards.filter(c=>c.dataset.cat===cat&&!c.classes.has('hide'));g.querySelector=()=>({textContent:''});return g});
const area=node();area.querySelector=()=>({textContent:''});area.querySelectorAll=()=>cards.filter(c=>!c.classes.has('hide'));
const ids={};for(const id of ['shop-search','theme-search','price-filter','filter-status','no-results','reset-filters'])ids[id]=node();ids['price-filter'].value='all';
const document={getElementById(id){return ids[id]||null},querySelector(){return null},querySelectorAll(q){return q==='.card'?cards:q==='.cat'?groups:q==='.fb'?buttons:q==='section.area'?[area]:[]}};
vm.runInNewContext(code,{document,window:{}});
function assert(v,m){if(!v)throw Error(m)}function input(id,value,event='input'){ids[id].value=value;ids[id].events[event]()}
assert(ids['filter-status'].textContent==='表示 2店舗・3プラン','initial');
input('shop-search','ＨＯＴＥＬ Ａ');assert(b.classes.has('hide')&&!a.classes.has('hide'),'name');
input('theme-search','冬');input('price-filter','high','change');assert(a.classes.has('hide'),'same plan AND');
ids['reset-filters'].events.click();buttons.find(b=>b.dataset.x==='wd').events.click();assert(b.classes.has('hide')&&!a.classes.has('hide'),'weekday');
ids['reset-filters'].events.click();input('price-filter','unknown','change');assert(a.classes.has('hide')&&!b.classes.has('hide'),'unknown price');
ids['reset-filters'].events.click();buttons.find(b=>b.dataset.sw==='scone').events.click();buttons.find(b=>b.dataset.sw==='xmas').events.click();assert(!a.classes.has('hide')&&b.classes.has('hide'),'sweet and event');
input('price-filter','high','change');assert(a.classes.has('hide')&&!ids['no-results'].hidden,'sweets/event and price must match same plan');input('price-filter','all','change');
buttons.find(b=>b.dataset.cat==='hotel').events.click();assert(a.classes.has('hide')&&!ids['no-results'].hidden,'category/no results');
ids['reset-filters'].events.click();assert(!a.classes.has('hide')&&!b.classes.has('hide'),'reset');
buttons.find(b=>b.dataset.sw==='ichigo').events.click();assert(a.classes.has('hide')&&b.classes.has('hide')&&!ids['no-results'].hidden,'zero option');
buttons.find(b=>b.dataset.sw==='scone').events.click();assert(!a.classes.has('hide')&&b.classes.has('hide'),'sweet OR including zero option');
buttons.find(b=>b.dataset.sw==='xmas').events.click();assert(!a.classes.has('hide')&&b.classes.has('hide'),'sweet OR and event AND');
ids['reset-filters'].events.click();cards.length=0;buttons.find(b=>b.dataset.sw==='ichigo').events.click();assert(!ids['no-results'].hidden,'zero-store selected option');
ids['reset-filters'].events.click();assert(ids['no-results'].hidden,'zero-store reset');
'''
        proc=subprocess.run(['node','-e',harness],input=json.dumps(js),text=True,capture_output=True)
        self.assertEqual(proc.returncode,0,proc.stderr)
