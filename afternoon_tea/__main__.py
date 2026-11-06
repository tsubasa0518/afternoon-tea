"""python3 -m afternoon_tea {extract,init,validate,build}. No network access."""
import argparse
import subprocess
import sys
from pathlib import Path

from .data import create_data
from .master import ROOT, dumps, extract_master, load_master
from .pipeline import STAGING, build_file, protected_files, staging_directory
from .validation import load_json, validate_data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("extract", help="仕様からdata/store_master.jsonを抽出")
    init = commands.add_parser("init", help="全店未調査のJSONを.stagingに生成")
    init.add_argument("--start", help="YYYY-MM-DD（省略時は日本時間の今日）")
    for name in ("validate", "build"):
        command = commands.add_parser(name)
        command.add_argument("json_file", type=Path)
    args = parser.parse_args()
    try:
        protected_files()
        if args.command == "extract":
            master = extract_master()
            (ROOT / "data/store_master.json").write_text(dumps(master), encoding="utf-8")
            print(dumps(master["counts"]), end="")
        elif args.command == "init":
            data = create_data(load_master(), start=args.start)
            validate_data(data, load_master())
            staging_directory()
            path = STAGING / ("data_" + data["period"]["start"] + ".json")
            # Never overwrite an existing research input, even in staging.
            with path.open("x", encoding="utf-8") as stream:
                stream.write(dumps(data))
            print(path)
        elif args.command == "validate":
            print(dumps(validate_data(load_json(args.json_file), load_master())), end="")
        else:
            print(build_file(args.json_file))
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print("失敗（公開は行いません）: " + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
