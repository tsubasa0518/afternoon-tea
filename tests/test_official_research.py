"""No external access: collection follows only mocked safe public documents."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from urllib.error import HTTPError
from afternoon_tea.official_research import links, collect
from afternoon_tea.research import Browser
from afternoon_tea.read_only import ForbiddenOperation
from tests.test_current_run import Response

HOST = 'official.example.com'
BASE = 'https://' + HOST

class OfficialResearchTests(unittest.TestCase):
    def browser(self, pages, max_requests=100):
        b = Browser(delay=0, max_requests=max_requests, public_hosts=[HOST])
        def request(req, timeout):
            url = req.full_url
            if url.endswith('/robots.txt'):
                return Response(url, 'User-agent: *\nAllow: /')
            value = pages.get(url, '')
            if isinstance(value, Exception):
                raise value
            return Response(url, value)
        b.transport.opener.open = Mock(side_effect=request)
        return b

    def run_collection(self, b, sources=None, **kwargs):
        sources = sources or [dict(id='one', url=BASE+'/', areas=[1], purpose='existing')]
        with tempfile.TemporaryDirectory() as d:
            report = collect(sources, [dict(no=i, name=str(i)) for i in range(1,15)], d, b, **kwargs)
            self.assertEqual(json.loads((Path(d)/'report.json').read_text()), report)
            for p in report['pages']:
                self.assertTrue((Path(d)/p['text_file']).exists())
            return report

    def test_official_links_labels_fragments_priority_and_actions(self):
        raw = '''<script><a href='/fake'>afternoon tea</a></script>
        <a href='/dining'>飲食</a><a href='/tea#menu'>Afternoon Tea</a>
        <a href='/reserve'>予約</a><a href='/menu?date=20261109'>Menu</a>
        <a href='https://other.example.com/tea'>アフタヌーンティー</a>'''
        p, found, candidates, rejected = links(raw, BASE+'/', [HOST])
        self.assertEqual([u for r,u,l in found], [BASE+'/tea', BASE+'/dining'])
        self.assertEqual(len(candidates),1)
        self.assertEqual(len(rejected),1)

    def test_top_to_at_to_plan_saves_menu_no_auto_confirmation(self):
        b=self.browser({BASE+'/':"<a href='/dining'>Restaurant</a>",
                        BASE+'/dining':"<a href='/afternoon-tea'>アフタヌーンティー</a>",
                        BASE+'/afternoon-tea':"<title>Afternoon tea</title><a href='/plan/joie'>詳細</a>",
                        BASE+'/plan/joie':'<h1>Holiday Afternoon Tea</h1>9,400円 苺、スコーン'})
        r=self.run_collection(b)
        self.assertEqual(len(r['pages']),4)
        self.assertEqual(r['verified_plans'],0)
        self.assertEqual(r['http_requests'],5)
        self.assertEqual(len(r['areas']),14)
        self.assertEqual(r['areas'][1]['discovery_attempts'],0)
        self.assertEqual({e['stage'] for e in r['network_events']},{'robots','document'})

    def test_denial_stops_host_external_not_fetched_no_service_fallback(self):
        b=self.browser({BASE+'/':"<a href='/tea'>afternoon tea</a><a href='/news'>news</a><a href='https://other.example.com/menu'>menu</a>",
                        BASE+'/tea':HTTPError(BASE+'/tea',403,'denied',{},None)})
        r=self.run_collection(b)
        urls=[c.args[0].full_url for c in b.transport.opener.open.call_args_list]
        self.assertEqual(urls,[BASE+'/robots.txt',BASE+'/',BASE+'/tea'])
        self.assertEqual(r['network_events'][-1]['http_status'],403)
        self.assertEqual(len(r['external_candidates']),1)

    def test_forbidden_redirect_stops_all_collection_and_persists_audit(self):
        b=self.browser({BASE+'/':"<a href='/tea'>afternoon tea</a><a href='/news'>news</a>",
                        BASE+'/tea':ForbiddenOperation('redirect_blocked_before_follow')})
        r=self.run_collection(b)
        self.assertEqual(r['stop_reason'],'forbidden_operation')
        self.assertEqual([c.args[0].full_url for c in b.transport.opener.open.call_args_list],
                         [BASE+'/robots.txt',BASE+'/',BASE+'/tea'])
        self.assertTrue(r['communication_audit']['complete'])
        self.assertTrue(r['communication_audit']['violations'])
        self.assertEqual(r['attempts'][-1]['status'],'forbidden')
        self.assertIn(BASE+'/news', r['sources'][0]['pending_urls'])

    def test_robots_crawl_delay_not_overridden_by_default(self):
        from urllib.robotparser import RobotFileParser
        from unittest.mock import patch
        b=self.browser({})
        robots=RobotFileParser();robots.parse(['User-agent: *','Crawl-delay: 10','Allow: /'])
        b.robots[HOST]=robots;b.last_request[HOST]=100
        with patch('afternoon_tea.research.time.monotonic', return_value=103), patch('afternoon_tea.research.time.sleep') as sleep:
            b._rate_limit(HOST)
        sleep.assert_called_once_with(7)

    def test_robots_404_is_unknown_not_permission(self):
        b=self.browser({})
        b.transport.opener.open.side_effect=HTTPError(BASE+'/robots.txt',404,'not found',{},None)
        r=self.run_collection(b)
        self.assertEqual(b.transport.opener.open.call_count,1)
        self.assertEqual(r['network_events'][0]['stage'],'robots')
        self.assertEqual(r['network_events'][0]['http_status'],404)
        self.assertEqual(len(r['pages']),0)

    def test_challenge_detection_unchanged_logged_and_host_stopped(self):
        b=self.browser({BASE+'/':'captcha'})
        r=self.run_collection(b)
        self.assertEqual(r['network_events'][-1]['matched_markers'],['captcha'])
        self.assertIn(HOST,b.blocked_hosts)
        self.assertEqual(len(r['pages']),0)

    def test_request_budget_round_robin_no_store_count_cap(self):
        sources=[dict(id=str(i),url=BASE+'/'+str(i),areas=[i],purpose='existing') for i in range(1,15)]
        b=self.browser({BASE+'/'+str(i):"<a href='/tea'>Afternoon tea</a>" for i in range(1,15)},max_requests=15)
        r=self.run_collection(b,sources)
        self.assertEqual([a['source_id'] for a in r['attempts']],[str(i) for i in range(1,15)])
        self.assertEqual(r['stop_reason'],'budget_or_deadline')
        self.assertTrue(all(s['pending_urls'] for s in r['sources']))

    def test_path_scope_and_unique_links(self):
        raw="<a href='/tokyo/tea'>Afternoon Tea</a>"*100+"<a href='/other/tea'>Afternoon tea</a>"
        self.assertEqual(len(links(raw,BASE+'/tokyo/',[HOST],'/tokyo/')[1]),1)

    def test_catalog_all14_and_discovery_not_a_store_master(self):
        from afternoon_tea.master import ROOT
        sources=json.loads((ROOT/'data/official_sources.json').read_text())['sources']
        for purpose in ('existing','discovery'):
            self.assertEqual({a for s in sources if s['purpose']==purpose for a in s['areas']},set(range(1,15)))
        self.assertFalse(any('bing' in s['url'] or 'ikyu' in s['url'] or 'tabelog' in s['url'] for s in sources))

if __name__=='__main__':unittest.main()
