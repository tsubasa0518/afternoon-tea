"""Only mocked openers. No request is sent to a reservation service."""
import copy
import datetime as dt
import hashlib
import io
import json
from email.message import Message
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock
from urllib.error import HTTPError
from afternoon_tea.communication_audit import CommunicationAudit
from afternoon_tea.run_context import RunContext
from afternoon_tea.read_only import ReadOnlyTransport,ForbiddenOperation,NoRedirect
from afternoon_tea.research import Browser
from afternoon_tea.research_queue import process
from afternoon_tea.research_store import new_state
from afternoon_tea.master import load_master
from afternoon_tea.data import JST
from afternoon_tea.publication_safety import current_evidence,valid_communication
from tests.test_step9 import RAW,URL

class Response(io.BytesIO):
 def __init__(self,url,raw,content_type='text/html; charset=utf-8'):
  super().__init__(raw.encode());self.url=url;self.status=200;self.headers=Message();self.headers['Content-Type']=content_type
 def geturl(self):return self.url

class CurrentRunTests(unittest.TestCase):
 def pilot(self,raw=RAW):
  tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);directory=Path(tmp.name)
  ctx=RunContext(directory);b=Browser(delay=0,audit=ctx.journal)
  b.transport.opener=Mock()
  b.transport.opener.open.side_effect=lambda req,timeout:Response(req.full_url,'User-agent: *\nAllow: /' if req.full_url.endswith('/robots.txt') else raw)
  master=load_master();state=new_state(master,str(dt.datetime.now(JST).date()));state['data']['metadata']['run_id']=ctx.id
  item=next(x for x in state['items'] if x['id']=='master-070');item['sources']['tc']=[URL]
  process(item,state,master,b,directory,time.monotonic()+20,ctx)
  state['current_run']=ctx.snapshot(b);state['data']['metadata']['generated_at']=state['current_run']['generated_at']
  return state,ctx,b,directory
 def test_real_extraction_from_mock_get_issues_receipt(self):
  state,ctx,b,_=self.pilot();self.assertEqual(len(ctx.receipts),1);self.assertTrue(current_evidence(state['data'],state));self.assertEqual(b.count,2)
 def test_missing_menu_never_issues_receipt(self):
  state,ctx,_,_=self.pilot(RAW.replace('menu-item-description','missing'));self.assertEqual(ctx.receipts,{});self.assertFalse(current_evidence(state['data'],state))
 def test_loading_same_day_does_not_generate_receipts(self):
  state,_,_,_=self.pilot();ctx=RunContext();b=Browser(delay=0,audit=ctx.journal);state['current_run']=ctx.snapshot(b);state['data']['metadata'].update(run_id=ctx.id,generated_at=state['current_run']['generated_at']);self.assertFalse(current_evidence(state['data'],state));self.assertFalse(ctx.receipts)
 def test_mutated_final_shop_is_rejected(self):
  state,_,_,_=self.pilot();next(s for a in state['data']['areas'] for g in a['cats'].values() for s in g['shops'] if s['master_id']=='master-070')['plans'][0]['theme']='TEST_ONLY changed';self.assertFalse(current_evidence(state['data'],state))
 def test_wrong_evidence_shop_rejected(self):
  state,_,_,_=self.pilot();next(iter(state['current_run']['evidence'].values()))['item_id']='master-001';self.assertFalse(current_evidence(state['data'],state))
 def test_wrong_run_rejected(self):
  state,_,_,_=self.pilot();state['current_run']['receipts']['master-070']['run_id']='old';self.assertFalse(current_evidence(state['data'],state))
 def test_receipt_missing_rejected(self):
  state,_,_,_=self.pilot();state['current_run']['receipts'].clear();self.assertFalse(current_evidence(state['data'],state))
 def test_log_tamper_makes_incomplete(self):
  state,ctx,b,d=self.pilot();(d/'communication.jsonl').write_text('corrupt');self.assertFalse(ctx.snapshot(b)['reservation_audit']['complete'])
 def test_log_event_removal_rejected_offline(self):
  state,_,_,_=self.pilot();state['current_run']['reservation_audit']['events'].pop();self.assertFalse(current_evidence(state['data'],state))
 def test_pending_request_is_incomplete(self):
  ctx=RunContext();ctx.journal.begin(URL,'GET');self.assertFalse(ctx.journal.snapshot()['complete'])
 def test_forbidden_method_is_logged_without_sending(self):
  ctx=RunContext();t=ReadOnlyTransport(ctx.journal);t.opener=Mock()
  with self.assertRaises(ForbiddenOperation):t.open(URL,method='POST')
  t.opener.open.assert_not_called();s=ctx.journal.snapshot();self.assertTrue(s['complete']);self.assertTrue(s['violations']);self.assertFalse(valid_communication(s,ctx.id))
 def test_query_and_credentials_are_not_logged(self):
  ctx=RunContext();t=ReadOnlyTransport(ctx.journal)
  with self.assertRaises(ForbiddenOperation):t.open(URL+'?secret=TEST_PRIVATE')
  self.assertNotIn('TEST_PRIVATE',json.dumps(ctx.journal.snapshot()))
 def test_redirect_is_logged_and_not_followed(self):
  ctx=RunContext();t=ReadOnlyTransport(ctx.journal);t.opener=Mock();t.opener.open.side_effect=lambda *args,**kw:NoRedirect().redirect_request(None,None,302,'',{},'https://secret.example/confirm?token=TEST_PRIVATE')
  with self.assertRaises(ForbiddenOperation):t.open(URL)
  s=ctx.journal.snapshot();self.assertTrue(s['violations']);self.assertNotIn('TEST_PRIVATE',json.dumps(s))
 def test_403_is_http_failure_not_safety_bypass(self):
  ctx=RunContext();t=ReadOnlyTransport(ctx.journal);t.opener=Mock();t.opener.open.side_effect=HTTPError(URL,403,'denied',{},None)
  with self.assertRaises(HTTPError):t.open(URL)
  s=ctx.journal.snapshot();self.assertTrue(s['complete']);self.assertEqual(s['events'][-1]['http_status'],403)
 def test_robots_denial_has_no_store_request(self):
  ctx=RunContext();b=Browser(delay=0,audit=ctx.journal);b.transport.opener=Mock();b.transport.opener.open.return_value=Response('https://www.tablecheck.com/robots.txt','User-agent: *\nDisallow: /')
  with self.assertRaisesRegex(RuntimeError,'robots_unknown'):b.fetch(URL)
  self.assertEqual(b.transport.opener.open.call_count,1);self.assertTrue(any(e.get('reason')=='robots_unknown_or_disallowed' for e in ctx.journal.events))
 def test_duplicate_receipt_rejected(self):
  state,ctx,b,d=self.pilot();e=next(iter(ctx.evidence.values()));shop=next(s for a in state['data']['areas'] for g in a['cats'].values() for s in g['shops'] if s['master_id']=='master-070')
  with self.assertRaisesRegex(ValueError,'duplicate'):ctx.confirm(shop,e,'ref',b.last_document,dt.datetime.now(JST).isoformat())
 def test_get_failure_does_not_create_receipt(self):
  tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);ctx=RunContext(Path(tmp.name));b=Browser(delay=0,audit=ctx.journal);b.transport.opener=Mock();b.transport.opener.open.side_effect=HTTPError(URL,403,'denied',{},None)
  master=load_master();state=new_state(master,str(dt.datetime.now(JST).date()));item=next(x for x in state['items'] if x['id']=='master-070');item['sources']['tc']=[URL]
  process(item,state,master,b,Path(tmp.name),time.monotonic()+10,ctx);self.assertFalse(ctx.receipts);self.assertNotEqual(item['status'],'confirmed')
 def test_missing_transport_witness_is_not_complete(self):
  ctx=RunContext();b=Mock();b.count=0;b.communication_audit=None;self.assertFalse(ctx.snapshot(b)['reservation_audit']['complete'])
 def test_uninstrumented_http_import_is_absent(self):
  import ast
  root=Path(__file__).parents[1]/'afternoon_tea'
  for path in root.glob('*.py'):
   tree=ast.parse(path.read_text())
   for node in ast.walk(tree):
    if isinstance(node,ast.ImportFrom) and node.module=='urllib.request':
     allowed={'Request'} if path.name in {'research.py','browser.py'} else {'Request','HTTPRedirectHandler','build_opener'} if path.name=='read_only.py' else set()
     self.assertTrue({n.name for n in node.names}<=allowed,path.name)
    if isinstance(node,ast.Import):self.assertFalse(any(n.name.split('.')[0] in ('requests','httpx','http','socket') for n in node.names),path.name)
 def test_final_bundle_bindings(self):
  from afternoon_tea.pipeline import build
  from afternoon_tea.publication_bundle import prepare,sha
  state,ctx,b,d=self.pilot();data=state['data'];out=build(data);self.addCleanup(__import__('shutil').rmtree,out)
  from afternoon_tea.research_store import atomic_json
  atomic_json(d/'data.json',data);atomic_json(d/'audit.json',{'current_run':state['current_run']})
  # Bundle output uses repository staging only. Temp directory must be under staging.
  root=Path(__file__).parents[1]/'.staging'
  with tempfile.TemporaryDirectory(dir=root) as t:
   html=out/('afternoon_tea_tokyo_'+data['generated']+'.html');m=prepare(d/'data.json',d/'audit.json',html,root.parent/'docs/index.html',Path(t)/'bundle',ctx.id,'TEST_COMMIT')
   self.assertEqual(m['run_id'],ctx.id);self.assertEqual(m['files']['index.html'],sha(html.read_bytes()))
   q=json.loads((Path(t)/'bundle/quality_report.json').read_text());self.assertFalse(q['publishable']);self.assertTrue(q['checks']['current_run_evidence']['status']=='pass')
 def test_standalone_transport_also_audits_success(self):
  t=ReadOnlyTransport();t.opener=Mock();t.opener.open.return_value=Response(URL,'TEST_ONLY')
  with t.open(URL) as response:response.read()
  s=t.communication_audit.snapshot();self.assertTrue(s['complete']);self.assertEqual(s['requests'],1)
 def test_fresh_reset_preserves_prior_day_comparison(self):
  from afternoon_tea.research_store import save_state
  from afternoon_tea.research_queue import run
  from afternoon_tea.extraction import apply_page
  from unittest.mock import Mock
  import shutil
  master=load_master();today=dt.datetime.now(JST).date();previous=new_state(master,str(today-dt.timedelta(days=1)))
  previous['data']['metadata']['purpose']='research';apply_page(previous['data'],master,RAW,URL)
  state=new_state(master,str(today),previous)
  self.assertIn('master-070',state['previous_confirmed'])
  with tempfile.TemporaryDirectory() as tmp:
   save_state(tmp,state,master);browser=Mock();browser.count=0;browser.fetch.side_effect=RuntimeError('HTTP_403')
   out,result=run(limit=1,seconds=10,directory=tmp,browser=browser,fresh=True)
   try:self.assertIn({'id':'master-070','change':'no_current_confirmation'},result['diff'])
   finally:shutil.rmtree(out)
