"""Generate into private staging only. There is deliberately no publish function."""
import hashlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .html_validation import validate_html
from .master import ROOT, dumps, load_master
from .validation import load_json, require, validate_data

STAGING = ROOT / ".staging"


def staging_directory(path=STAGING):
    require(not STAGING.is_symlink(), ".stagingをシンボリックリンクにしないでください")
    destination = Path(path).resolve()
    require(destination == STAGING.resolve() or STAGING.resolve() in destination.parents,
            "生成先はリポジトリの.staging配下だけです（公開先への書き込み禁止）")
    destination.mkdir(parents=True, exist_ok=True)
    return destination


def protected_files():
    manifest = load_json(ROOT / "data/protected_hashes.json")
    for name, expected in manifest.items():
        require(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected,
                "保護対象ファイルが変更されています: " + name)


def build(data, staging_root=STAGING):
    protected_files()
    master = load_master()
    summary = validate_data(data, master)
    destination = staging_directory(staging_root)
    temporary = Path(tempfile.mkdtemp(prefix=".pending-", dir=destination))
    try:
        start = data["period"]["start"]
        json_path = temporary / f"data_{start}.json"
        json_path.write_text(dumps(data), encoding="utf-8")
        snapshot = json_path.read_bytes()
        # The original script writes to cwd; never run it with docs/ as cwd.
        result = subprocess.run([sys.executable, str(ROOT / "build_html.py"), json_path.name],
                                cwd=temporary, capture_output=True, text=True, timeout=60)
        require(result.returncode == 0 and not result.stderr,
                "HTML生成失敗: " + result.stdout + result.stderr)
        output = temporary / f"afternoon_tea_tokyo_{start}.html"
        require(output.is_file(), "生成HTMLがありません")
        html_summary = validate_html(output.read_text(encoding="utf-8"), data)
        require(json_path.read_bytes() == snapshot and load_json(json_path) == data,
                "生成時にJSON・未確認情報が変更されました")
        protected_files()
        report = {"validation": "passed", "publishable": False,
                  "warning": "公開しないでください。未調査・テスト用の生成物を含む一時成果物です。",
                  "data": summary, "html": html_summary, "generator_stdout": result.stdout,
                  "sha256": {output.name: hashlib.sha256(output.read_bytes()).hexdigest(),
                             json_path.name: hashlib.sha256(snapshot).hexdigest()}}
        (temporary / "validation.json").write_text(dumps(report), encoding="utf-8")
        final = destination / temporary.name.replace(".pending-", "validated-", 1)
        temporary.rename(final)
        return final
    except BaseException:
        shutil.rmtree(temporary)
        raise


def build_file(path, staging_root=STAGING):
    return build(load_json(path), staging_root)
