"""Weekly list reading, processing and publication through one entry point."""
import argparse
import json
from pathlib import Path
from .common import ROOT

PREVIOUS = ROOT / '.staging/weekly/previous.json'


def parser():
    cli = argparse.ArgumentParser(prog='python3 -m afternoon_tea')
    commands = cli.add_subparsers(dest='operation', required=True)
    commands.add_parser('begin', help='週の開始: 前回データを控え、空の調査ファイルと時間・要求数を初期化する')
    fetch = commands.add_parser('fetch', help='リストNo.Nの予約ページURL（または同じ店舗のプラン詳細ページ）を読む')
    fetch.add_argument('no', type=int, help='リストのNo（1から順に）')
    fetch.add_argument('url', nargs='?', help='同じ店舗のプラン詳細ページ（省略時はリストのURL）')
    fetch.add_argument('--browser', action='store_true', help='GET本文にプランが見えないときヘッドレスブラウザで読む')
    refresh = commands.add_parser('refresh', help='14日以内の前回プランを確認日時のまま引き継ぐ')
    refresh.add_argument('--previous', type=Path, default=PREVIOUS)
    enrich = commands.add_parser('enrich', help='料金区分・スイーツ・期間・曜日を付ける')
    enrich.add_argument('--data', type=Path, default=ROOT / 'site/research.json')
    enrich.set_defaults(parser=enrich)
    prep = commands.add_parser('themes-prepare', help='テーマ国の未判定プランを用意する')
    prep.add_argument('--previous', type=Path, default=PREVIOUS)
    prep.set_defaults(command='prepare', parser=prep)
    end = commands.add_parser('themes-finalize', help='テーマ国の判定を確定する')
    end.set_defaults(command='finalize', previous=None, parser=end)
    helps = {'render': '固定HTMLを生成する', 'validate-site': 'JSON・HTMLを技術検証する',
             'report': 'PR本文用の今週の集計を出力する', 'check-protected': '保護ファイルのハッシュを確認する',
             'intake': '週次PRを信頼済みmainで審査する（Actions用）', 'resume-intake': 'CI完了後に審査を再開する（Actions用）',
             'publish-prepare': '公開前検証（Actions用）', 'publish-verify': '公開後のHTTP 200・HTML一致確認（Actions用）'}
    for (name, text) in helps.items():
        commands.add_parser(name, help=text)
    return cli


def main(argv=None):
    args = parser().parse_args(argv)
    if args.operation in ('begin', 'fetch', 'report'):
        from .collection.weekly import main
        return main(args)
    if args.operation == 'refresh':
        from .processing.weekly import retain
        from .collection.storage import atomic_json
        target = ROOT / 'site/research.json'
        if target.is_symlink():
            raise ValueError('symlink data forbidden')
        previous = json.loads(args.previous.read_text()) if args.previous.exists() else {'shops': []}
        atomic_json(target, retain(json.loads(target.read_text()), previous))
        return 0
    if args.operation == 'enrich':
        from .processing.enrichment import main
        return main(args)
    if args.operation.startswith('themes-'):
        from .processing.themes import main
        return main(args)
    if args.operation == 'render':
        from .publication.renderer import main
        return main()
    if args.operation == 'check-protected':
        from .publication.guards import protected_files
        protected_files()
        print('Protected files verified.')
        return 0
    if args.operation == 'resume-intake':
        from .publication.ci import main
        return main()
    from .publication.site import main
    return main({'validate-site': 'validate', 'intake': 'intake', 'publish-prepare': 'prepare',
                 'publish-verify': 'verify'}[args.operation])


if __name__ == '__main__':
    raise SystemExit(main())
