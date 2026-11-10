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
from afternoon_tea.collection.transport import ReadOnlyTransport, ForbiddenOperation, NoRedirect
URL = 'https://restaurant.ikyu.com/107408/'

class CatalogProtectionTests(unittest.TestCase):

    def test_protected_files_and_canonical_schema(self):
        protected_files()
        catalog = master.load_master()
        self.assertEqual([a['no'] for a in catalog['areas']], list(range(1, 15)))
        self.assertEqual(sum((len(g['shops']) for a in catalog['areas'] for g in a['cats'].values())), catalog['counts']['shops'])

    def test_catalog_edit_requires_hash_and_valid_schema(self):
        original = master.load_master()
        mutations = [lambda d: d['areas'].pop(),
             lambda d: d['areas'][0]['cats'].pop('cafe'),
             lambda d: d['areas'][0]['cats']['cafe']['shops'][0].update(id='master-999'),
             lambda d: d['counts'].update(shops=0)]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'data').mkdir()
            path = root / 'data/store_master.json'
            path.write_text(json.dumps(original))
            manifest = root / 'data/protected_hashes.json'
            manifest.write_text(json.dumps({'data/store_master.json': '0' * 64}))
            with patch.object(master, 'ROOT', root), self.assertRaisesRegex(ValueError, 'untrusted'):
                master.load_master()
            for mutate in mutations:
                data = copy.deepcopy(original)
                mutate(data)
                path.write_text(json.dumps(data))
                manifest.write_text(json.dumps({'data/store_master.json': hashlib.sha256(path.read_bytes()).hexdigest()}))
                with patch.object(master, 'ROOT', root), self.assertRaises(ValueError):
                    master.load_master()

    def test_manifest_tamper_is_rejected(self):
        from afternoon_tea.publication import guards as guards
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'data').mkdir()
            (root / 'protected.txt').write_text('changed')
            (root / 'data/protected_hashes.json').write_text(json.dumps({'protected.txt': '0' * 64}))
            with patch.object(guards, 'ROOT', root), self.assertRaises(ValueError):
                guards.protected_files()
