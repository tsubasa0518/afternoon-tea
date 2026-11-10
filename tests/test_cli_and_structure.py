"""Offline checks for the package entry point and relocated components."""
import ast
import importlib
import json
from pathlib import Path
import pkgutil
import subprocess
import sys
import unittest
import afternoon_tea
from afternoon_tea.__main__ import parser
from afternoon_tea.common import ROOT
from afternoon_tea.publication.renderer import render

class StructureTests(unittest.TestCase):

    def test_all_modules_import_and_only_one_executable_entry(self):
        for entry in pkgutil.walk_packages(afternoon_tea.__path__, afternoon_tea.__name__ + '.'):
            importlib.import_module(entry.name)
        guards = []
        for path in (ROOT / 'afternoon_tea').rglob('*.py'):
            for node in ast.parse(path.read_text()).body:
                if isinstance(node, ast.If) and '__name__' in ast.unparse(node.test):
                    guards.append(path.name)
        self.assertEqual(guards, ['__main__.py'])

    def test_every_subcommand_help_is_offline_and_successful(self):
        choices = next((a.choices for a in parser()._actions if isinstance(a, __import__('argparse')._SubParsersAction)))
        for command in choices:
            result = subprocess.run([sys.executable, '-m', 'afternoon_tea', command, '--help'], cwd=ROOT, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, (command, result.stderr))
            self.assertIn(command, result.stdout)

    def test_render_does_not_change_any_site_input_and_matches_current_html(self):
        paths = [ROOT / 'site' / name for name in ('research.json', 'index.html')]
        before = [p.read_bytes() for p in paths]
        result = render(json.loads(before[0])).encode()
        self.assertEqual(result, before[1])
        self.assertEqual([p.read_bytes() for p in paths], before)

    def test_workflows_parse_and_call_existing_commands_only(self):
        import re
        choices = next((a.choices for a in parser()._actions if isinstance(a, __import__('argparse')._SubParsersAction)))
        called = set()
        for path in sorted((ROOT / '.github/workflows').glob('*.yml')):
            text = path.read_text()
            self.assertNotIn('\t', text, path.name)
            try:
                import yaml
            except ImportError:
                # Offline CI without PyYAML: keys and lists must still be well formed.
                for line in text.splitlines():
                    if line.strip() and not line.lstrip().startswith('#'):
                        self.assertEqual((len(line) - len(line.lstrip())) % 2, 0, (path.name, line))
            else:
                self.assertIn('jobs', yaml.safe_load(text), path.name)
            called |= set(re.findall(r'python3 -m afternoon_tea ([a-z-]+)', text))
        self.assertTrue(called)
        self.assertLessEqual(called, set(choices))

    def test_browser_is_optional_and_old_research_machinery_is_gone(self):
        import sys
        from unittest.mock import patch
        with patch.dict(sys.modules, {'playwright': None, 'playwright.sync_api': None}):
            importlib.reload(importlib.import_module('afternoon_tea.collection.browser'))
        names = {p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*') if '.git' not in p.parts}
        for gone in ('site/search_failures.json', 'data/official_sources.json', 'data/references/user_candidates_385.csv',
                     'afternoon_tea/collection/campaign.py', 'afternoon_tea/collection/official.py'):
            self.assertNotIn(gone, names)
        source = '\n'.join(p.read_text() for p in (ROOT / 'afternoon_tea').rglob('*.py'))
        for word in ('bing.com', 'research_campaign =', 'collect-official', 'validate-campaign'):
            self.assertNotIn(word, source)
