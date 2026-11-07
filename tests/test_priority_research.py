"""Offline priority queues and mock-only evidence: never contact booking sites."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from afternoon_tea import priority_research as p, routine_renderer
from afternoon_tea.routine_site import ALLOWED, json_bytes, validate_site
from tests.test_routine_renderer import fixture

NOW = '2026-11-07T20:00:00+09:00'
RUN = 'test-only-run'
URL = 'https://www.tablecheck.com/ja/shops/test-only/reserve'


def inputs():
    return (p.read(p.ROOT/'data/priority_sources.json'),
            p.read(p.ROOT/'data/store_master.json'),
            p.read(p.ROOT/'data/priority_master_matches.json'))


def queue(previous=None):
    return p.prepare(*inputs(), RUN, NOW, previous)


def tasks(q):
    return [s for a in q['areas'] for s in a['tasks']]


class PriorityTests(unittest.TestCase):
    def test_attachment_is_preserved_byte_for_byte(self):
        raw = (p.ROOT/'data/priority_sources.json').read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         '6034ae0626ae7be67c748f0a86b4a2887df2dfb6462e3d8efca83300fa308cf5')
    def test_134_records_and_14_areas_with_name_url_correspondence(self):
        source, master, _ = inputs(); rows = p.priority_entries(source, master)
        original = [(s['name'], a['area'], s['historical_url']) for a in source['areas'] for s in a['shops']]
        original += [(s['name'], s['area'], s['historical_url']) for s in source['candidates']]
        self.assertEqual(len(rows), 134)
        self.assertEqual([(s['name'], s['area'], s['historical_url']) for s in rows], original)
        self.assertEqual(len({s['id'] for s in rows}), 134)
        self.assertEqual(len({s['area_no'] for s in rows}), 14)
    def test_corrupt_counts_missing_url_wrong_area_and_duplicate_row_rejected(self):
        source, master, _ = inputs()
        for mutate in [lambda d: d['counts'].update(historical_listed_shops=119),
                       lambda d: d['areas'][0]['shops'][0].update(historical_url=''),
                       lambda d: d['areas'][0].update(area='unknown'),
                       lambda d: d['areas'][0]['shops'][0].update(source_row=2),
                       lambda d: d['candidates'].pop()]:
            bad=copy.deepcopy(source);mutate(bad)
            with self.assertRaises(ValueError): p.priority_entries(bad, master)
    def test_all_75_masters_candidates_survive_deduplication(self):
        q=queue(); rows=tasks(q)
        self.assertEqual(len(rows), 156)
        self.assertEqual(len([s for s in rows if s['priority']=='A']), 134)
        mids=[mid for s in rows for mid in s['master_ids']]
        self.assertEqual(len(mids), 75); self.assertEqual(len(set(mids)), 75)
        self.assertEqual(q['master_matches'], 53)
        self.assertEqual(sum(mid.startswith('master-candidate') for s in rows if s['priority']=='A' for mid in s['master_ids']),3)
    def test_full_venue_aliases_merge_but_lounges_in_same_hotel_stay_separate(self):
        rows={s['id']: s for s in tasks(queue())}
        self.assertIn('master-010',rows['priority-018']['master_ids'])
        self.assertIn('master-012',rows['priority-020']['master_ids'])
        self.assertNotEqual(rows['priority-018']['id'],rows['priority-020']['id'])
        self.assertIn('master-candidate-04',rows['priority-078']['master_ids'])
        self.assertIn('master-candidate-01',rows)  # Nakameguro != Omotesando
    def test_changed_or_duplicate_reviewed_identity_requires_review(self):
        source, master, aliases=inputs()
        for field in ('master_name','priority_name','area'):
            bad=copy.deepcopy(aliases);bad['matches'][0][field]='test-only-mismatch'
            with self.assertRaises(ValueError):p.prepare(source,master,bad,RUN,NOW)
        aliases['matches'].append(aliases['matches'][0])
        with self.assertRaises(ValueError):p.prepare(source,master,aliases,RUN,NOW)
    def test_14_area_assignments_follow_nine_groups_and_include_stations(self):
        q=queue(); self.assertEqual([a['no'] for a in q['areas']],list(range(1,15)))
        for a in q['areas']:
            self.assertIn(a['no'],p.GROUPS[a['group']-1]);self.assertTrue(a['stations'])
            self.assertTrue(all(s['area_no']==a['no'] for s in a['tasks']))
        self.assertEqual(sum(len(a['tasks']) for a in q['areas']),156)
    def test_past_assessments_never_confirm_or_exclude_current_queue(self):
        q=queue();self.assertTrue(all(s['status']=='unresearched' for s in tasks(q)))
        self.assertTrue(any(s.get('historical_assessment','').startswith('外す候補') for s in tasks(q)))
        self.assertTrue(all(not f['sources'] and not f['attempts'] for f in q['failures_template']['failures']))
    def test_previous_status_is_only_hint_and_unresearched_is_prioritized(self):
        previous={'failures':[{'priority_id':'priority-002','status':'unresearched','checked_at':NOW},
                              {'priority_id':'priority-001','status':'confirmed','checked_at':NOW}]}
        q=queue(previous); area=q['areas'][0]
        self.assertEqual(area['tasks'][0]['id'],'priority-002')
        self.assertTrue(all(t['status']=='unresearched' for t in tasks(q)))
        self.assertEqual(next(t for t in tasks(q) if t['id']=='priority-001')['previous_status'],'confirmed')
    def test_legacy_previous_master_name_is_supported_without_promoting(self):
        m=inputs()[1];s=m['areas'][0]['cats']['cafe']['shops'][0]
        q=queue({'failures':[{'name':s['name'],'area':'1 丸の内・日本橋','status':'confirmed'}]})
        row=next(t for t in tasks(q) if t['id']=='priority-001')
        self.assertEqual(row['previous_status'],'confirmed');self.assertEqual(row['status'],'unresearched')
    def test_restricted_seed_is_never_fetched_or_host_rewritten(self):
        with patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('network forbidden')):
            q=queue()
        blocked=next(s for s in tasks(q) if s['id']=='priority-candidate-07')
        self.assertIn('ssl.tabelog.com',blocked['historical_url'])
        self.assertFalse(blocked['seed_policy']['allowed_by_read_only_url_policy'])
        self.assertEqual(blocked['status'],'unresearched')
        for url in (URL+'?date=2026-11-09','https://tabelog.com/confirm'):
            self.assertFalse(p.seed_policy(url)['allowed_by_read_only_url_policy'])
    def test_new_discovery_deduplicates_full_name_only_and_is_not_confirmed(self):
        q=queue();a=p.add_discovery(q,'TEST ONLY hotel / lounge A',1,URL,NOW)
        self.assertIs(a,p.add_discovery(q,'test only hotel / lounge a',1,URL,NOW))
        b=p.add_discovery(q,'TEST ONLY hotel / lounge B',1,URL,NOW)
        self.assertNotEqual(a['id'],b['id']);self.assertTrue(a['new'])
        self.assertEqual(a['status'],'unresearched');self.assertEqual(len(tasks(q)),158)
    def test_all_unresearched_is_valid_tracking_and_not_attempted(self):
        q=queue();r=p.report(q,{'shops':[]},q['failures_template'])
        self.assertEqual(r['errors'],[]);self.assertEqual(r['tracked'],134)
        self.assertEqual(r['statuses']['unresearched'],134)
        self.assertEqual(r['attempted_with_evidence'],0)
    def test_missing_duplicate_identity_or_unknown_status_is_reported(self):
        for mutate in [lambda d:d['failures'].pop(0),
                       lambda d:d['failures'].append(d['failures'][0]),
                       lambda d:d['failures'][0].update(name='changed'),
                       lambda d:d['failures'][0].update(status='ATなし')]:
            q=queue();f=copy.deepcopy(q['failures_template']);mutate(f)
            self.assertTrue(p.report(q,{'shops':[]},f)['errors'])
    def test_confirmation_without_current_shop_and_evidence_is_not_counted(self):
        q=queue();f=q['failures_template'];f['failures'][0]['status']='confirmed'
        r=p.report(q,{'shops':[]},f)
        self.assertTrue(r['errors']);self.assertEqual(r['statuses']['confirmed'],0)
        self.assertEqual(r['attempted_with_evidence'],0)
    def test_current_evidence_counts_confirmed_and_excluded_with_backward_compatible_json(self):
        q=queue();f=q['failures_template'];research=fixture()
        for i,status in enumerate(('confirmed','excluded','access_denied','site_restriction','no_results','information_insufficient')):
            f['failures'][i].update(status=status,evidence_url=URL,evidence_quote='TEST ONLY evidence',verified_at=NOW,
                attempts=[{'url':URL,'checked_at':NOW,'result':status,'reason':'TEST ONLY local mock'}])
        pid=f['failures'][0]['priority_id']
        research['shops'][0].update(priority_ids=[pid],source_url=URL,checked_at=NOW)
        r=p.report(q,research,f)
        self.assertEqual(r['errors'],[]);self.assertEqual(r['attempted_with_evidence'],6)
        self.assertEqual(r['statuses']['confirmed'],1);self.assertEqual(r['statuses']['excluded'],1)
        for record in f['failures']:record['reason']='TEST ONLY mock'
        html=routine_renderer.render(research,f)
        content={'site/index.html':html.encode(),'site/research.json':json_bytes(research),'site/search_failures.json':json_bytes(f)}
        self.assertEqual(validate_site(content)['shops'],1)
        research['shops'][0]['checked_at']='2026-11-06T20:00:00+09:00'
        self.assertTrue(p.report(q,research,f)['errors'])
    def test_zero_and_two_store_rendering_never_outputs_unverified_queue_cards(self):
        for count in (0,2):
            q=queue();d=fixture();d['shops']=d['shops']*count
            html=routine_renderer.render(d,q['failures_template'])
            self.assertEqual(html.count('<article '),count)
            self.assertNotIn('cafe VAVA',html)
            self.assertEqual(set(ALLOWED),{'site/index.html','site/research.json','site/search_failures.json'})
    def test_cli_prepare_and_report_leave_site_and_workflows_unchanged(self):
        protected=list((p.ROOT/'site').glob('*'))+list((p.ROOT/'.github/workflows').glob('*'))+[p.ROOT/'AGENTS.md',p.ROOT/'build_html.py',p.ROOT/'research_spec.md']
        before={f:f.read_bytes() for f in protected if f.is_file()}
        (p.ROOT/'.staging').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=p.ROOT/'.staging') as tmp:
            result=subprocess.run(['python3','-m','afternoon_tea.priority_research','prepare','--workdir',tmp,'--run-id',RUN],capture_output=True,text=True,cwd=p.ROOT)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(len(list(Path(tmp).glob('area-*.json'))),14)
            result=subprocess.run(['python3','-m','afternoon_tea.priority_research','report','--workdir',tmp,'--failures',str(Path(tmp)/'failures_template.json')],capture_output=True,text=True,cwd=p.ROOT)
            self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(before,{f:f.read_bytes() for f in before})
