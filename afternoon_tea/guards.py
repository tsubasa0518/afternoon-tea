"""Verify protected current configuration before processing and deployment."""
import hashlib
from .master import ROOT
from .common import load_json, require


def protected_files():
    manifest=load_json(ROOT/'data/protected_hashes.json')
    for name,expected in manifest.items():
        require(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==expected,
                '保護対象ファイルが変更されています: '+name)
