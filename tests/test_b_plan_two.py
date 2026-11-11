"""B案PR2: build once, render saved values, direct prices, code-only flags."""
import copy
import datetime as dt
import importlib
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from afternoon_tea.common import ROOT
from afternoon_tea.collection.weekly import candidates
from afternoon_tea.processing.dates import period, JST
from afternoon_tea.processing.enrichment import enrich_plan
from afternoon_tea.publication.renderer import render
from afternoon_tea.publication.site import validate_site, json_bytes
from tests.html_nodes import Document

builder=importlib.import_module('afternoon_tea.build')


def current(prices=(5000,5001,8000,8001,None)):
    now=dt.datetime.now(JST)
    row=candidates()[0]
    return {'schema_version':1,'generated_at':now.isoformat(),'period':period(now=now),
            'shops':[{'name':'TEST ONLY','area_no':int(row['エリア番号']),'list_url':row['予約ページURL'],
                      'station':'日本橋駅','address':None,'source_site':row['予約サイト'],
                      'plans':[{'plan_name':'PLAN '+str(i),'price_yen':price,'checked_at':now.isoformat(),
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
            self.assertEqual(plan['sweets'],['scone'])
            self.assertEqual(plan['cc'],'fr')
        html=render(out)
        self.assertEqual(html.count('🇫🇷 フランス'),5)
        validate_site({'site/research.json':json_bytes(out),'site/index.html':html.encode()})

    def test_prices_are_direct_inputs_and_discount_never_replaces_regular(self):
        plan={'plan_name':'AT','price_yen':9000,'discount_price_yen':4500,
              'price_note':'50%OFF、通常価格12,000円','evidence_quote':'通常価格 20,000円 50%OFF 10,000円'}
        out=enrich_plan(plan,{})
        self.assertEqual((out['price_yen'],out['discount_price_yen']),(9000,4500))
        self.assertEqual(out['price_note'],plan['price_note'])
        plan.update(price_yen=None)
        self.assertIsNone(enrich_plan(plan,{})['price_yen'])
        del plan['price_yen']
        self.assertIsNone(enrich_plan(plan,{})['price_yen'])

    def test_invalid_country_codes_do_not_stop_build(self):
        for value in ('zz','uk',1,True,'JPN','',None):
            data=current((8001,));p=data['shops'][0]['plans'][0]
            p.update(cc=value,country='TEST old name',country_basis='TEST reason',
                     country_input_hash='old',country_decision_hash='old',notes={'status':'テーマ国推測：TEST'})
            out=builder.build(data);p=out['shops'][0]['plans'][0]
            self.assertIsNone(p['cc'])
            self.assertFalse(any(key.startswith('country') or key=='notes' for key in p))
            self.assertNotIn('country-theme',re.search(r'<main>(.*?)</main>',render(out),re.S).group(1))

    def test_fresh_carry_is_kept_old_future_and_outside_period_are_removed(self):
        data=current((9000,));now=dt.datetime.now(JST)
        previous=copy.deepcopy(data)
        p=previous['shops'][0]['plans'][0]
        p.update(plan_name='CARRIED',checked_at=(now-dt.timedelta(days=13)).isoformat())
        previous['shops'][0]['plans'] += [{**p,'plan_name':'OLD','checked_at':(now-dt.timedelta(days=15)).isoformat()},
                                         {**p,'plan_name':'FUTURE','checked_at':(now+dt.timedelta(days=1)).isoformat()},
                                         {**p,'plan_name':'OUTSIDE','end':(dt.date.fromisoformat(data['period']['start'])-dt.timedelta(days=1)).isoformat()}]
        out=builder.build(data,previous,now=now)
        plans={p['plan_name']:p for p in out['shops'][0]['plans']}
        self.assertEqual(set(plans),{'CARRIED','PLAN 0'})
        self.assertEqual(plans['CARRIED']['checked_at'],p['checked_at'])

    def test_renderer_does_not_recompute_saved_classification_or_sweets(self):
        data=builder.build(current((9000,)))
        data['shops'][0]['category']='cafe'
        data['shops'][0]['plans'][0].update(menu='チョコレート',sweets=['scone'])
        before=copy.deepcopy(data)
        with patch('afternoon_tea.processing.classification.classify',side_effect=AssertionError('render must use saved category')), \
             patch('afternoon_tea.processing.sweets.extract',side_effect=AssertionError('render must use saved sweets')), \
             patch('afternoon_tea.processing.enrichment.enrich',side_effect=AssertionError('render must not build')):
            html=render(data)
        self.assertIn('class="card c-cafe"',html)
        plans=[n for n in Document(html).root.find('div') if n.attrs.get('class')=='plan']
        self.assertEqual(plans[0].attrs['data-sw'],'scone')
        self.assertEqual(data,before)

    def test_zero_is_a_valid_build_result(self):
        data=current();data['shops']=[]
        out=builder.build(data)
        html=render(out)
        self.assertNotIn('<article ',html)
        self.assertEqual(validate_site({'site/research.json':json_bytes(out),'site/index.html':html.encode()})['plans'],0)


class BuildCommandTests(unittest.TestCase):
    def run_in_root(self,data,html='previous HTML'):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);root=Path(tmp.name)
        (root/'site').mkdir();(root/'data').mkdir()
        shutil.copyfile(ROOT/'data/store_master.json',root/'data/store_master.json')
        (root/'site/research.json').write_bytes(json_bytes(data))
        (root/'site/index.html').write_text(html)
        return root

    def test_build_command_writes_json_and_html_and_does_not_fetch(self):
        renderer=importlib.import_module('afternoon_tea.publication.renderer')
        for count in (1,0):
            data=current((8001,));data['shops']=data['shops'][:count]
            root=self.run_in_root(data)
            with patch.object(builder,'ROOT',root),patch.object(renderer,'ROOT',root), \
                 patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('offline')), \
                 patch('sys.stdout',new=io.StringIO()):
                self.assertEqual(builder.main(),0)
            written=json.loads((root/'site/research.json').read_text())
            self.assertEqual(len(written['shops']),count)
            self.assertEqual((root/'site/index.html').read_text(),render(written))

    def test_validation_failure_keeps_existing_files(self):
        renderer=importlib.import_module('afternoon_tea.publication.renderer')
        data=current();data['period']['end']='invalid'
        root=self.run_in_root(data);before=(root/'site/research.json').read_bytes()
        with patch.object(builder,'ROOT',root),patch.object(renderer,'ROOT',root),self.assertRaises(ValueError):
            builder.main()
        self.assertEqual((root/'site/research.json').read_bytes(),before)
        self.assertEqual((root/'site/index.html').read_text(),'previous HTML')


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
    def test_numbers_live_in_the_procedure_and_safety_source_only(self):
        for name in ('README.md','CLAUDE.md'):
            text=(ROOT/name).read_text()
            for value in ('1500','1,500','200要求','60秒','3秒','5,000','8,000','14日','07:17'):
                self.assertNotIn(value,text,name)
        procedure=(ROOT/'docs/weekly_procedure.md').read_text()
        for value in ('1,500秒','200要求','60秒','3秒','5,000円以下','5,001〜8,000円','8,001円以上','14日以内','07:17'):
            self.assertEqual(procedure.count(value),1,value)
        self.assertEqual((ROOT/'AGENTS.md').read_text().count('3秒'),1)
        self.assertNotIn('python3 -m unittest',procedure)
        self.assertIn('pip install -r requirements-browser.txt',procedure)
        self.assertIn('失敗してもGETだけで続ける',procedure)
        self.assertEqual(procedure.count('トークン'),1)
