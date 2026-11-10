"""Plan-level keyword extraction shared by JSON, HTML and OR filtering."""
import copy
import unittest
from afternoon_tea.processing.sweets import tags
from afternoon_tea.processing.enrichment import enrich_plan
from afternoon_tea.publication.renderer import render
from tests.test_routine_renderer import fixture,FAILURES
from tests.test_all_filter_options import Buttons
from tests.html_nodes import Document


class SweetKeywordTests(unittest.TestCase):
    def test_all_fifteen_groups_and_japanese_english_variants(self):
        examples={'ichigo':['いちご','苺','ストロベリー','STRAWBERRY','strawberries'],
                  'melon':['メロン','melon'],'peach':['桃','ピーチ','peaches'],
                  'mango':['マンゴー','mango'],'grape':['葡萄','グレープ','シャインマスカット','grapes','muscat'],
                  'kuri':['栗','マロン','モンブラン','marron','chestnut'],
                  'imo':['芋','さつまいも','紫芋','かぼちゃ','パンプキン','pumpkin','sweet potato'],
                  'kaki':['柿','洋梨','梨','ペアムース','pear','いちじく','fig'],
                  'citrus':['柑橘','オレンジ','orange','みかん','レモン','lemon','ゆず','グレープフルーツ','grapefruit'],
                  'choco':['チョコ','チョコレート','ショコラ','chocolate','cacao'],
                  'wa':['抹茶','ほうじ茶','玄米茶','あずき','あんこ','きなこ','和風','matcha'],
                  'macaron':['マカロン','macaron'],'parfait':['パフェ','parfait'],
                  'scone':['スコーン','scone'],'other':['チーズケーキ','ティラミス','プリン','baklava']}
        for tag,words in examples.items():
            for word in words:
                with self.subTest(word=word):self.assertEqual(tags({'menu':word}),[tag])
        self.assertEqual(tags({'menu':'ペアプラン appearance figures'}),[])
        self.assertEqual(tags({'menu':'ＳＴＲＡＷＢＥＲＲＹ'}),['ichigo'])

    def test_all_plan_fields_multiple_tags_and_repeated_words(self):
        for field,word,tag in [('plan_name','いちご','ichigo'),('theme','メロン','melon'),('theme_name','桃','peach'),
                               ('menu','マカロン','macaron'),('description','スコーン','scone'),
                               ('explanation','マンゴー','mango'),('evidence_quote','パフェ','parfait'),('note','チョコ','choco')]:
            self.assertEqual(tags({field:word}),[tag])
        self.assertEqual(tags({'menu':'苺のタルト、メロンムース、桃のジュレ 苺 苺'}),['ichigo','melon','peach'])
        self.assertEqual(tags({'menu':'マロンモンブラン、マカロン、ショコラケーキ'}),['choco','kuri','macaron'])
        self.assertEqual(tags({'menu':'シャインマスカットのパフェ'}),['grape','parfait'])
        self.assertEqual(tags({'menu':['いちご',{'sweets':'マカロン'}]}),['ichigo','macaron'])
        self.assertEqual(tags({'notes':{'status':'推測 スコーン'}}),[])

    def test_local_negation_options_and_unrelated_operational_notes(self):
        for menu,expected in [
            ('いちごタルト、マカロンは含まれません、メロンムース',['ichigo','melon']),
            ('時間制限なしの苺タルト',['ichigo']),
            ('スコーンはありません、苺タルト',['ichigo']),
            ('マカロンは含まれていません、メロン',['melon']),
            ('苺タルト（アルコールはありません）',['ichigo']),
            ('スコーンは付いていません',[]),
            ('マカロン（アルコールは含まれません）',['macaron']),
            ('乳製品不使用の苺タルト',['ichigo']),
            ('マカロンは含まれない、スコーン',['scone']),
            ('苺タルトは追加料金なし',['ichigo']),
            ('追加料金なしのスコーン',['scone']),
            ('マカロンはオプションではありません',['macaron']),
            ('苺タルト（提供期間は未確認）',['ichigo']),
            ('スコーンなしでも苺タルト付き',['ichigo']),
            ('苺は提供しませんがメロンムースを提供',['melon']),
            ('マカロン不使用、追加料金の苺パフェ、チョコケーキ',['choco']),
            ('【オプション】\n苺パフェ\n【スイーツ】\nマカロン',['macaron']),
            ('オプション：苺パフェ、チョコケーキ',[]),
            ('通常ランチのチョコケーキ。他のプランのスコーン。いちごムース',['ichigo']),
            ('単品パフェ、別売のスコーン、without macarons',[]),
            ('マカロンは含まれませんが、苺のタルト',['ichigo'])]:
            with self.subTest(menu=menu):self.assertEqual(tags({'menu':menu}),expected)

    def test_unknown_menu_is_not_other_and_stale_tags_are_replaced(self):
        for plan in ({'plan_name':'AT','menu':None},{'menu':'メニュー未確認'}, {'menu':'スイーツ数種'},
                     {'menu':None,'sweets':['ichigo'],'notes':{'status':'マカロン'}}):
            self.assertEqual(enrich_plan(plan,{})['sweets'],[])
        self.assertEqual(tags({'menu':'ティラミスとスコーン'}),['scone'])
        plan={'menu':'マカロン','sweets':['ichigo'],'note':'既存メモ','evidence_quote':'マカロン',
              'checked_at':'2026-11-07T12:00:00+09:00'}
        before=copy.deepcopy(plan);out=enrich_plan(plan,{})
        self.assertEqual(out['sweets'],['macaron']);self.assertEqual(plan,before)
        for key in ('menu','note','evidence_quote','checked_at'):self.assertEqual(out[key],plan[key])
        self.assertEqual(enrich_plan(out,{}),out)
        out['menu']=None;out['evidence_quote']='ATの情報のみ'
        out=enrich_plan(out,{})
        self.assertEqual(out['sweets'],[])
        self.assertNotIn('sweets',out.get('structured_evidence',{}))

    def test_plan_counts_html_tags_and_json_tags_agree_and_ignore_store_tags(self):
        data=fixture();shop=data['shops'][0];shop['sweets']=['choco','scone']
        shop['plans']=[{'plan_name':'A いちご','menu':'メロン、桃、苺 苺'},
                       {'plan_name':'B 苺','menu':'マロン、マカロン'},
                       {'plan_name':'C メロン','menu':'スコーン'},
                       {'plan_name':'outside 苺','start':'2026-12-18'}]
        for p in shop['plans']:p.update(enrich_plan(p,shop))
        html=render(data,FAILURES)
        counts={b['key']:int(__import__('re').search(r'\d+$',b['text']).group()) for b in Buttons(html).buttons}
        for key,value in {'ichigo':2,'melon':2,'peach':1,'kuri':1,'macaron':1,'scone':1,'choco':0}.items():self.assertEqual(counts[key],value)
        plans=[n for n in Document(html).root.find('div') if n.attrs.get('class')=='plan']
        self.assertEqual(len(plans),3)
        for node,p in zip(plans,shop['plans']):self.assertEqual(set(node.attrs['data-sw'].split()),set(p['sweets']))
        self.assertEqual(sum('ichigo' in n.attrs['data-sw'].split() or 'scone' in n.attrs['data-sw'].split() for n in plans),3)

    def test_real_filter_script_matches_plan_counts_and_or_unions(self):
        import json,re,shutil,subprocess
        from pathlib import Path
        if not shutil.which('node'):self.skipTest('Node required for filter execution')
        data=fixture();base=data['shops'][0]
        def plan(name,price,wd=False,season=None):
            return {'plan_name':name,'price_yen':price,'weekday_available':wd,'season':season or []}
        data['shops']=[{**base,'name':'First','sweets':['ichigo'],'plans':[
            plan('A 苺',7000,True,['xmas']),plan('B スコーン',8000),plan('C 苺 スコーン',9000,True,['xmas']),
            plan('D メロン',8000),plan('E マスカット チョコ',8000),plan('F マスカット',8000)]},
            {**base,'name':'Second','sweets':['scone'],'plans':[plan('G チョコ',11000),plan('H いちご',12000,False,['collab'])]}]
        html=render(data,FAILURES)
        records=[]
        for card in Document(html).root.find('article'):
            records.append({'name':card.find('h4')[0].text,
                            'dataset':{k[5:]:v for k,v in card.attrs.items() if k.startswith('data-')},
                            'plans':[{'name':next(n.text for n in p.find('p') if n.attrs.get('class')=='theme'),
                                      'dataset':{k[5:]:v for k,v in p.attrs.items() if k.startswith('data-')}}
                                     for p in card.find('div') if p.attrs.get('class')=='plan']})
        buttons=[{'key':b['key'],'count':int(re.search(r'\d+$',b['text']).group())} for b in Buttons(html).buttons]
        payload={'js':re.search(r'<script>(.*?)</script>',html,re.S).group(1),'cards':records,'buttons':buttons,
                 'eventKeys':list(__import__('afternoon_tea.publication.renderer',fromlist=['EVENTS']).EVENTS)}
        harness=Path(__file__).parent/'fixtures/sweet_filter_harness.js'
        proc=subprocess.run(['node',str(harness)],input=json.dumps(payload),text=True,capture_output=True)
        self.assertEqual(proc.returncode,0,proc.stderr)
