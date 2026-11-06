import copy
import datetime as dt
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from afternoon_tea.data import create_data, period
from afternoon_tea.html_validation import Structure, validate_html
from afternoon_tea.master import ROOT, dumps, extract_master, load_master
from afternoon_tea.pipeline import STAGING, build, protected_files, staging_directory
from afternoon_tea.validation import ValidationError, allowed_url, load_json, validate_data
from tests.samples import evidence, sample


class MasterTests(unittest.TestCase):
    def test_lossless_extraction(self):
        master = load_master()
        self.assertEqual(master, extract_master())
        self.assertEqual(master['counts'], {'shops': 70, 'by_category': {'cafe': 28, 'hotel': 24, 'lux': 18},
                                           'candidates': 5, 'out_of_scope': 16})
        text = (ROOT/'research_spec.md').read_text(encoding='utf-8')
        section = text.split('# 店舗マスター（店名｜駅｜出口）\n')[1].split('# 未検証の候補（')[0]
        expected = [line for line in section.splitlines() if line.startswith('- ')]
        actual = [shop['raw'] for a in master['areas'] for c in a['cats'].values() for shop in c['shops']]
        self.assertEqual(expected, actual)
        for a in master['areas']:
            self.assertEqual(a['raw'], f"{a['no']} {a['name']}：" + '、'.join(a['stations']))
        self.assertEqual(len(master['candidate_source_lines']), 3)
        self.assertEqual(master['out_of_scope_raw'], '／'.join(master['out_of_scope']))

    def test_unparsed_shop_is_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'spec.md'
            path.write_text((ROOT/'research_spec.md').read_text().replace(
                '- レゾナンス（東京ビルTOKIA 2F）｜', 'BROKEN レゾナンス｜'), encoding='utf-8')
            with self.assertRaises(ValueError):
                extract_master(path)

    def test_missing_category_is_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'spec.md'
            path.write_text((ROOT/'research_spec.md').read_text().replace(
                '【14 池袋・目白｜カフェ】（該当なし）', ''), encoding='utf-8')
            with self.assertRaises(ValueError):
                extract_master(path)

    def test_existing_html_full_structure_without_editing(self):
        parser=Structure()
        parser.feed((ROOT/'docs/index.html').read_text(encoding='utf-8'))
        parser.close()
        self.assertEqual(len(parser.stack),1)
        self.assertEqual(len(parser.root.nodes('article','card')),120)
        self.assertEqual(len(parser.root.nodes('section','area')),14)

    def test_jst_day_rollover_and_year_boundary(self):
        now = dt.datetime(2026, 12, 31, 15, 1, tzinfo=dt.timezone.utc)
        self.assertEqual(period(now=now), {'start': '2027-01-01', 'end': '2027-02-10'})
        self.assertEqual(period('2026-11-06')['end'], '2026-12-16')
        with self.assertRaises(ValueError):
            period(now=dt.datetime(2026, 11, 6))

    def test_skeleton_keeps_every_shop_unknown(self):
        data = create_data(load_master(), '2026-11-06')
        report = validate_data(data, load_master())
        self.assertEqual((report['shops'], report['unresearched'], report['expected_cards']), (70,70,0))
        self.assertFalse(report['publishable'])
        self.assertEqual(data['candidates'], [])
        self.assertEqual(len(data['notes']['pending_candidates']), 5)
        self.assertTrue(all(c['status']=='unchecked' for a in data['areas'] for c in a['cats'].values()))
        self.assertEqual(len(data['areas'][0]['cats']['hotel']['shops']), 9)
        self.assertEqual(load_master()['areas'][0]['cats']['lux']['shops'][0]['name'],
                         'フォーシーズンズホテル東京大手町（THE LOUNGE）')


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.master = load_master()
        self.data = sample()
        self.shop = self.data['areas'][0]['cats']['cafe']['shops'][0]
        self.plan = self.shop['plans'][0]

    def valid(self):
        return validate_data(self.data, self.master)

    def test_synthetic_data_valid(self):
        self.assertEqual(self.valid()['confirmed'], 3)

    def test_area_omission_duplicate_and_renaming(self):
        for mutation in ('missing','duplicate','rename'):
            with self.subTest(mutation=mutation):
                d=sample()
                if mutation=='missing': d['areas'].pop()
                if mutation=='duplicate': d['areas'][-1]=d['areas'][0]
                if mutation=='rename': d['areas'][0]['name']='unknown'
                with self.assertRaises(ValidationError): validate_data(d,self.master)

    def test_duplicate_shop(self):
        self.data['areas'][0]['cats']['cafe']['shops'].append(copy.deepcopy(self.shop))
        with self.assertRaisesRegex(ValidationError,'重複'): self.valid()

    def test_same_hotel_different_lounges_is_not_duplicate(self):
        hotel=self.data['areas'][0]['cats']['hotel']['shops'][0]
        lux=self.data['areas'][0]['cats']['lux']['shops'][0]
        lux['name']=hotel['name']
        lux['shop']='TEST_ONLY別ラウンジ'
        self.valid()

    def test_url_validation(self):
        bad=['https://tabelog.com.evil.example/x','https://evil.example/tabelog.com',
             'javascript:alert(1)','http://tabelog.com/x','https://user@tabelog.com/x',
             'https://tabelog.com:444/x','https://tabelog.com\\@evil.example/x',
             'https://foo.tabelog.com/x','https://tabelog.com/\nx','//tablecheck.com/x']
        for url in bad:
            with self.subTest(url=url), self.assertRaises(ValidationError): allowed_url(url)
        for site, url in [('ik','https://restaurant.ikyu.com/test'),('tb','https://tabelog.com/test'),
                          ('tc','https://www.tablecheck.com/test')]: allowed_url(url,site)
        with self.assertRaises(ValidationError): allowed_url('https://tabelog.com/test','ik')

    def test_multiple_and_duplicate_reservation_links(self):
        self.shop['links'] *= 2
        with self.assertRaisesRegex(ValidationError,'1件'): self.valid()
        self.shop['links']=self.shop['links'][:1]
        self.data['areas'][0]['cats']['hotel']['shops'][0]['links']=self.shop['links']
        with self.assertRaisesRegex(ValidationError,'URLの重複'): self.valid()

    def test_period_conflicts(self):
        mutations=[lambda d:d['period'].update(end='2026-12-15'),
                   lambda d:d.update(generated='2026-11-05'),
                   lambda d:d['areas'][0]['cats']['cafe']['shops'][0]['plans'][0].update(start='2026-12-17'),
                   lambda d:d['areas'][0]['cats']['cafe']['shops'][0]['plans'][0].update(end='2026-11-05'),
                   lambda d:d['areas'][0]['cats']['cafe']['shops'][0]['plans'][0].update(start='2026-02-30')]
        for mutate in mutations:
            d=sample();mutate(d)
            with self.subTest(data=d['period']), self.assertRaises(ValidationError): validate_data(d,self.master)

    def test_boundary_and_unknown_plan_dates(self):
        for start,end in [('2026-10-01','2026-11-06'),('2026-12-16','2027-01-01'),(None,None)]:
            self.plan.update(start=start,end=end)
            self.valid()

    def test_reverse_dates(self):
        self.plan.update(start='2026-12-01',end='2026-11-30')
        with self.assertRaisesRegex(ValidationError,'開始日'):self.valid()

    def test_plan_types(self):
        for field,bad in [('price_min',True),('price_min',-1),('price_min',5000.5),('wd','yes'),
                          ('theme',42),('sw',['invented']),('sw',['ichigo','ichigo']),('sw','ichigo'),('cc','us')]:
            d=sample();d['areas'][0]['cats']['cafe']['shops'][0]['plans'][0][field]=bad
            with self.subTest(field=field,bad=bad), self.assertRaises(ValidationError):validate_data(d,self.master)

    def test_bad_scores(self):
        for score in (True,2.99,5.1,float('nan'),'3.5'):
            self.shop['tabelog']=score
            with self.subTest(score=score),self.assertRaises(ValidationError): self.valid()

    def test_hotel_price_threshold(self):
        hotel=self.data['areas'][0]['cats']['hotel']['shops'][0]
        hotel['plans'][0]['price_min']=9000
        with self.assertRaisesRegex(ValidationError,'9000'):self.valid()
        hotel['plans'][0]['price_min']=None
        hotel['plans'][0]['price_text']=None
        self.valid()

    def test_uncertain_hotel_location_needs_confirmation(self):
        self.shop['research']['in_hotel']=None
        with self.assertRaises(ValidationError):self.valid()

    def test_missing_provenance(self):
        for key in ('/plans/0/theme','/plans/0/price_min','reservation','classification'):
            d=sample();d['areas'][0]['cats']['cafe']['shops'][0]['research']['evidence'].pop(key)
            with self.subTest(key=key),self.assertRaises(ValidationError):validate_data(d,self.master)

    def test_stale_evidence_is_rejected(self):
        self.shop['research']['evidence']['/plans/0/price_min']['checked_on']='2026-10-02'
        with self.assertRaisesRegex(ValidationError,'確認日'):self.valid()

    def test_master_omission_is_rejected(self):
        d=create_data(self.master,'2026-11-06')
        d['areas'][0]['cats']['cafe']['shops'].pop()
        with self.assertRaisesRegex(ValidationError,'欠落'):validate_data(d,self.master)

    def test_inferred_price_is_rejected(self):
        self.shop['research']['evidence']['/plans/0/price_min']['kind']='inferred'
        with self.assertRaisesRegex(ValidationError,'テーマ国のみ'):self.valid()

    def test_ikyu_dinner_and_menu_not_confirmed(self):
        reservation=self.shop['research']['evidence']['reservation']
        reservation['meal']='dinner'
        with self.assertRaisesRegex(ValidationError,'朝食'):self.valid()
        reservation['meal']='lunch';reservation['menu']=False
        with self.assertRaisesRegex(ValidationError,'メニュー'):self.valid()

    def test_invented_unknown_fields_rejected(self):
        d=create_data(self.master,'2026-11-06')
        s=d['areas'][0]['cats']['cafe']['shops'][0]
        s['plans'][0]['price_min']=12345
        with self.assertRaisesRegex(ValidationError,'確定情報'):validate_data(d,self.master)

    def test_master_exit_warning_cannot_disappear(self):
        d=create_data(self.master,'2026-11-06')
        d['areas'][0]['cats']['hotel']['shops'][-1]['exit']='東京駅1番出口'
        with self.assertRaisesRegex(ValidationError,'確定情報'):validate_data(d,self.master)

    def test_failed_research_distinct_from_unresearched(self):
        d=create_data(self.master,'2026-11-06')
        r=d['areas'][0]['cats']['cafe']['shops'][0]['research']
        r.update(status='failed',error='TEST_ONLY timeout',attempted_on='2026-11-06')
        d['areas'][0]['cats']['cafe']['shops'][0]['links_note']='取得失敗'
        report=validate_data(d,self.master)
        self.assertEqual((report['failed'],report['unresearched']),(1,69))
        r['error']=''
        with self.assertRaisesRegex(ValidationError,'失敗理由'):validate_data(d,self.master)

    def test_false_none_is_rejected(self):
        self.data['areas'][1]['cats']['hotel']['status']='none'
        with self.assertRaisesRegex(ValidationError,'厳格'):self.valid()

    def test_confirmed_none_requires_every_check(self):
        g=self.data['areas'][1]['cats']['hotel']
        g.update(status='none',research={'status':'confirmed','checks':{
            k:evidence('https://restaurant.ikyu.com/__TEST_ONLY__/list') for k in
            ['ikyu_area_list','tabelog_area_list','tabelog_station_search','hotel_list','hotel_openings','hotel_at_checks']}})
        self.valid()
        del g['research']['checks']['hotel_openings']
        with self.assertRaisesRegex(ValidationError,'厳格'):self.valid()

    def test_out_of_scope_name_or_genre(self):
        self.shop['research']['genres']=['フレンチ']
        with self.assertRaisesRegex(ValidationError,'対象外ジャンル'):self.valid()
        self.shop['research']['genres']=[];self.shop['name']='TEST_ONLY bills 銀座'
        with self.assertRaisesRegex(ValidationError,'対象外店舗'):self.valid()

    def test_test_data_cannot_claim_research(self):
        self.data['metadata']['purpose']='research'
        with self.assertRaisesRegex(ValidationError,'テスト店'):self.valid()

    def test_json_duplicate_keys_and_nonfinite(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'bad.json'
            for text in ('{"a":1,"a":2}','{"price":NaN}','{"price":Infinity}','{"broken":'):
                path.write_text(text)
                with self.subTest(text=text),self.assertRaises(ValidationError):load_json(path)

    def test_candidate_and_excluded_proof(self):
        c={'name':'TEST_ONLY候補','area':'中目黒','url':'https://tabelog.com/__TEST_ONLY__',
           'note':'TEST_ONLY 抜粋のみ確認','status':'unresolved',
           'evidence':evidence('https://tabelog.com/__TEST_ONLY__')}
        self.data['candidates']=[c];self.valid()
        c['url']='https://evil.example/'
        with self.assertRaises(ValidationError):self.valid()
        self.data['candidates']=[]
        self.data['excluded']=[{'name':'TEST_ONLY除外','reason':'TEST_ONLY 期間内のATなし（2026-11-06）',
                                'evidence':evidence('https://tabelog.com/__TEST_ONLY__')}]
        self.valid()


class BuildTests(unittest.TestCase):
    def setUp(self):
        STAGING.mkdir(exist_ok=True)
        self.directory=tempfile.TemporaryDirectory(dir=STAGING)
        self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name)

    def test_json_to_html_and_protected_files(self):
        before={p:(ROOT/p).read_bytes() for p in load_json(ROOT/'data/protected_hashes.json')}
        d=sample();original=copy.deepcopy(d)
        output=build(d,self.root)
        report=load_json(output/'validation.json')
        self.assertEqual(report['html']['cards'],3)
        self.assertEqual(report['validation'],'passed')
        self.assertFalse(report['publishable'])
        self.assertEqual(d,original)
        self.assertEqual(load_json(output/'data_2026-11-06.json'),original)
        for p,value in before.items():self.assertEqual((ROOT/p).read_bytes(),value)
        protected_files()

    def test_unresearched_build_has_zero_cards_and_retains_all_json(self):
        d=create_data(load_master(),'2026-11-06');output=build(d,self.root)
        report=load_json(output/'validation.json')
        self.assertEqual(report['html']['cards'],0)
        self.assertEqual(report['data']['unresearched'],70)
        self.assertIn('未確認', (output/'afternoon_tea_tokyo_2026-11-06.html').read_text())
        self.assertEqual((output/'afternoon_tea_tokyo_2026-11-06.html').read_text().count(
            '未確認（確認できた範囲では該当なし）'),42)
        self.assertEqual(d,load_json(output/'data_2026-11-06.json'))

    def test_unknown_fields_stay_unknown_in_html(self):
        d=sample();p=d['areas'][0]['cats']['cafe']['shops'][0]['plans'][0]
        p.update(price_min=None,price_text=None,start=None,end=None,theme=None,sw=[],wd='off',we='off')
        output=build(d,self.root)
        h=(output/'afternoon_tea_tokyo_2026-11-06.html').read_text()
        self.assertIn('期間不明',h)
        self.assertIn('曜日未確認',h)
        self.assertIn('data-pk="0"',h)

    def test_invalid_json_never_generates_output(self):
        d=sample();d['areas'].pop()
        with self.assertRaises(ValidationError):build(d,self.root)
        self.assertEqual(list(self.root.iterdir()),[])

    def test_process_failure_removes_partial_artifact(self):
        with patch('afternoon_tea.pipeline.subprocess.run',return_value=subprocess.CompletedProcess([],1,'','TEST_ONLY failure')):
            with self.assertRaisesRegex(ValidationError,'生成失敗'):build(sample(),self.root)
        self.assertEqual(list(self.root.iterdir()),[])

    def test_html_validation_failure_removes_artifact(self):
        with patch('afternoon_tea.pipeline.validate_html',side_effect=ValidationError('TEST_ONLY bad structure')):
            with self.assertRaises(ValidationError):build(sample(),self.root)
        self.assertEqual(list(self.root.iterdir()),[])

    def test_timeout_removes_artifact(self):
        with patch('afternoon_tea.pipeline.subprocess.run',side_effect=subprocess.TimeoutExpired([],60)):
            with self.assertRaises(subprocess.TimeoutExpired):build(sample(),self.root)
        self.assertEqual(list(self.root.iterdir()),[])

    def test_publication_path_forbidden(self):
        for path in (ROOT/'docs',ROOT,STAGING/'..'/'docs'):
            with self.subTest(path=path),self.assertRaisesRegex(ValidationError,'公開先'):build(sample(),path)

    def test_symlink_cannot_redirect_staging_to_docs(self):
        redirect=self.root/'redirect'
        redirect.symlink_to(ROOT/'docs',target_is_directory=True)
        with self.assertRaisesRegex(ValidationError,'公開先'):staging_directory(redirect)
        with patch('afternoon_tea.pipeline.STAGING',redirect):
            with self.assertRaisesRegex(ValidationError,'シンボリック'):staging_directory(redirect)

    def test_protected_hash_mismatch_blocks_execution(self):
        with patch('afternoon_tea.pipeline.load_json',return_value={'build_html.py':'wrong-hash'}):
            with self.assertRaisesRegex(ValidationError,'保護対象'):build(sample(),self.root)
        self.assertEqual(list(self.root.iterdir()),[])

    def test_html_corruption_is_rejected(self):
        d=sample();output=build(d,self.root)
        h=(output/'afternoon_tea_tokyo_2026-11-06.html').read_text()
        for bad in (h.replace('</article>','',1),h.replace('id="a14"','id="a1"'),
                    h.replace('https://restaurant.ikyu.com/__TEST_ONLY__/cafe','https://evil.example/'),
                    h.replace('data-pk="1"','data-pk="0"',1),h.replace('4,000<small>','4,001<small>',1),
                    h.replace('data-cat="cafe" data-wd','data-cat="hotel" data-wd',1),
                    h.replace('const st=', 'const changed=')):
            with self.subTest(bad=hashlib.sha256(bad.encode()).hexdigest()),self.assertRaises(ValidationError):validate_html(bad,d)

    def test_cli_end_to_end_and_fail_exit(self):
        path=self.root/'TEST_ONLY.json';path.write_text(dumps(sample()),encoding='utf-8')
        command=[sys.executable,'-m','afternoon_tea']
        result=subprocess.run(command+['validate',str(path)],cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        path.write_text('{}')
        result=subprocess.run(command+['build',str(path)],cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(result.returncode,1)
        self.assertIn('公開は行いません',result.stderr)


if __name__=='__main__':
    unittest.main()
