"""Weekly public reading, processing and publication through one entry point."""
import argparse
import json
from pathlib import Path
from .common import ROOT

def parser():
    cli = argparse.ArgumentParser(prog='python3 -m afternoon_tea')
    commands = cli.add_subparsers(dest='operation', required=True)
    commands.add_parser('begin', help='週次の調査時間・要求数だけを初期化する')
    fetch = commands.add_parser('fetch', help='安全な公開ページ1件を読み、本文を標準出力へ返す')
    fetch.add_argument('url')
    enrich = commands.add_parser('enrich')
    enrich.add_argument('--data', type=Path, default=ROOT/'site/research.json')
    enrich.set_defaults(parser=enrich)
    review = commands.add_parser('review')
    review.add_argument('--period', action='store_true')
    review.add_argument('--data', type=Path, default=ROOT/'site/research.json')
    prep = commands.add_parser('themes-prepare')
    prep.add_argument('--previous', type=Path)
    prep.set_defaults(command='prepare', parser=prep)
    end = commands.add_parser('themes-finalize')
    end.set_defaults(command='finalize', previous=None, parser=end)
    refresh = commands.add_parser('refresh', help='14日以内の前回プランを確認日時のまま引き継ぐ')
    refresh.add_argument('--previous', type=Path, required=True)
    for name in ('render','validate-site','check-protected','intake','resume-intake','publish-prepare','publish-verify'):
        commands.add_parser(name)
    return cli

def main(argv=None):
    args = parser().parse_args(argv)
    if args.operation == 'begin':
        from .collection.weekly import begin
        print(json.dumps(begin())); return
    if args.operation == 'fetch':
        from .collection.weekly import fetch
        print(json.dumps(fetch(args.url), ensure_ascii=False)); return
    if args.operation == 'refresh':
        from .processing.weekly import retain
        from .collection.storage import atomic_json
        target = ROOT/'site/research.json'
        if target.is_symlink():
            raise ValueError('symlink data forbidden')
        atomic_json(target, retain(json.loads(target.read_text()), json.loads(args.previous.read_text())))
        return
    if args.operation == 'enrich':
        from .processing.enrichment import main
        return main(args)
    if args.operation == 'review':
        from .processing.period_review import main
        return main(args)
    if args.operation.startswith('themes-'):
        from .processing.themes import main
        return main(args)
    if args.operation == 'render':
        from .publication.renderer import main
        return main()
    if args.operation == 'check-protected':
        from .publication.guards import protected_files
        protected_files(); print('Protected files verified.'); return
    if args.operation == 'resume-intake':
        from .publication.ci import main
        return main()
    from .publication.site import main
    return main({'validate-site':'validate','intake':'intake','publish-prepare':'prepare','publish-verify':'verify'}[args.operation])

if __name__ == '__main__':
    raise SystemExit(main())
