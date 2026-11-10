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
        for entry in pkgutil.walk_packages(afternoon_tea.__path__,afternoon_tea.__name__+'.'):
            importlib.import_module(entry.name)
        guards=[]
        for path in (ROOT/'afternoon_tea').rglob('*.py'):
            for node in ast.parse(path.read_text()).body:
                if isinstance(node,ast.If) and '__name__' in ast.unparse(node.test):guards.append(path.name)
        self.assertEqual(guards,['__main__.py'])

    def test_every_subcommand_help_is_offline_and_successful(self):
        choices=next(a.choices for a in parser()._actions if isinstance(a,__import__('argparse')._SubParsersAction))
        for command in choices:
            result=subprocess.run([sys.executable,'-m','afternoon_tea',command,'--help'],cwd=ROOT,capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,(command,result.stderr))
            self.assertIn(command,result.stdout)

    def test_render_does_not_change_any_site_input_and_matches_current_html(self):
        paths=[ROOT/'site'/name for name in ('research.json','search_failures.json','index.html')]
        before=[p.read_bytes() for p in paths]
        result=render(json.loads(before[0]),json.loads(before[1])).encode()
        self.assertEqual(result,before[2]);self.assertEqual([p.read_bytes() for p in paths],before)
