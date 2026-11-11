"""Weekly list reading, processing and publication through one entry point."""
import argparse


def parser():
    cli = argparse.ArgumentParser(prog='python3 -m afternoon_tea')
    commands = cli.add_subparsers(dest='operation', required=True)
    commands.add_parser('begin', help='週の開始: 前回データを控え、空の調査ファイルと時間・要求数を初期化する')
    fetch = commands.add_parser('fetch', help='リストNo.Nの予約ページURL（または同じ店舗のプラン詳細ページ）を読む')
    fetch.add_argument('no', type=int, help='リストのNo（1から順に）')
    fetch.add_argument('url', nargs='?', help='同じ店舗のプラン詳細ページ（省略時はリストのURL）')
    fetch.add_argument('--full', action='store_true', help='AT関連語の周辺だけでなく、取得した本文全体を出力する')
    fetch.add_argument('--browser', action='store_true', help='GET本文にプランが見えないときヘッドレスブラウザで読む')
    commands.add_parser('build', help='引き継ぎ・表示データ作成・HTML生成・検証をまとめて行う')
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
    if args.operation == 'build':
        from .build import main
        return main()
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
