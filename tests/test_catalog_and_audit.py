"""Current protection and audit invariants; all transport is mocked."""
import ast
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from afternoon_tea.collection import catalog as master
from afternoon_tea.publication.guards import protected_files
from afternoon_tea.collection.audit import CommunicationAudit
from afternoon_tea.collection.transport import ReadOnlyTransport, ForbiddenOperation, NoRedirect
from afternoon_tea.collection.evidence import validate_audit

URL='https://restaurant.ikyu.com/107408/'

class CatalogProtectionTests(unittest.TestCase):
    def test_protected_files_and_canonical_schema(self):
        protected_files();catalog=master.load_master()
        self.assertEqual([a['no'] for a in catalog['areas']],list(range(1,15)))
        self.assertEqual(sum(len(g['shops']) for a in catalog['areas'] for g in a['cats'].values()),catalog['counts']['shops'])

    def test_catalog_edit_requires_hash_and_valid_schema(self):
        original=master.load_master()
        mutations=[lambda d:d['areas'].pop(),lambda d:d['areas'][0]['cats'].pop('cafe'),
                   lambda d:d['areas'][0]['cats']['cafe']['shops'][0].update(id='master-999'),
                   lambda d:d['counts'].update(shops=0)]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'data').mkdir();path=root/'data/store_master.json'
            path.write_text(json.dumps(original));manifest=root/'data/protected_hashes.json'
            manifest.write_text(json.dumps({'data/store_master.json':'0'*64}))
            with patch.object(master,'ROOT',root),self.assertRaisesRegex(ValueError,'untrusted'):master.load_master()
            for mutate in mutations:
                data=copy.deepcopy(original);mutate(data);path.write_text(json.dumps(data))
                manifest.write_text(json.dumps({'data/store_master.json':hashlib.sha256(path.read_bytes()).hexdigest()}))
                with patch.object(master,'ROOT',root),self.assertRaises(ValueError):master.load_master()

    def test_manifest_tamper_is_rejected(self):
        from afternoon_tea.publication import guards as guards
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'data').mkdir();(root/'protected.txt').write_text('changed')
            (root/'data/protected_hashes.json').write_text(json.dumps({'protected.txt':'0'*64}))
            with patch.object(guards,'ROOT',root),self.assertRaises(ValueError):guards.protected_files()

class AuditBoundaryTests(unittest.TestCase):
    def test_disk_tamper_pending_request_and_replay_tamper_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'audit.jsonl';journal=CommunicationAudit('offline',path)
            request=journal.begin(URL,'GET')
            self.assertFalse(journal.snapshot()['complete'])
            journal.finish(request,'http_success',http_status=200)
            snapshot=journal.snapshot();validate_audit(snapshot)
            altered=copy.deepcopy(snapshot);altered['events'][1]['method']='POST'
            with self.assertRaises(ValueError):validate_audit(altered)
            (Path(tmp)/'audit.jsonl').write_text('corrupted')
            self.assertFalse(journal.snapshot()['complete'])

    def test_forbidden_method_is_audited_without_network(self):
        journal=CommunicationAudit('offline');transport=ReadOnlyTransport(journal);transport.opener=Mock()
        with self.assertRaises(ForbiddenOperation):transport.open(URL,method='POST')
        transport.opener.open.assert_not_called()
        self.assertTrue(journal.snapshot()['violations'])
        with self.assertRaises(ValueError):validate_audit(journal.snapshot())

    def test_rejected_query_is_redacted_and_redirect_never_followed(self):
        journal=CommunicationAudit('offline');transport=ReadOnlyTransport(journal);transport.opener=Mock()
        with self.assertRaises(ForbiddenOperation):transport.open(URL+'?secret=TEST_PRIVATE')
        self.assertNotIn('TEST_PRIVATE',json.dumps(journal.snapshot()))
        transport.opener.open.side_effect=lambda *a,**k:NoRedirect().redirect_request(None,None,302,'',{},'https://example.invalid/confirm?token=TEST_PRIVATE')
        with self.assertRaises(ForbiddenOperation):transport.open(URL)
        self.assertEqual(transport.opener.open.call_count,1)
        self.assertNotIn('TEST_PRIVATE',json.dumps(journal.snapshot()))

    def test_no_uninstrumented_document_http_imports(self):
        root=Path(__file__).parents[1]/'afternoon_tea'
        for path in root.rglob('*.py'):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node,ast.ImportFrom) and node.module=='urllib.request':
                    allowed={'Request'} if path.name=='documents.py' else {'Request','HTTPRedirectHandler','build_opener'} if path.name=='transport.py' else set()
                    self.assertTrue({n.name for n in node.names}<=allowed,path.name)
                if isinstance(node,ast.Import):
                    self.assertFalse(any(n.name.split('.')[0] in ('requests','httpx','http','socket') for n in node.names),path.name)
