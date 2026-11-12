"""One entry for weekly research, build and trusted publication checks."""
import argparse


def parser():
    cli = argparse.ArgumentParser(prog='python3 -m afternoon_tea')
    commands = cli.add_subparsers(dest='operation', required=True)
    commands.add_parser('begin', help='前回を控え、今週の空データと上限を初期化する')
    fetch = commands.add_parser('fetch', help='候補のNo順に店舗ページを読む')
    fetch.add_argument('no', type=int)
    fetch.add_argument('url', nargs='?', help='同じ店舗のプラン詳細URL')
    fetch.add_argument('--full', action='store_true', help='取得本文全体を出力する')
    fetch.add_argument('--browser', action='store_true', help='同じ公開ページを任意のブラウザで読む')
    commands.add_parser('build', help='引き継ぎ・分類・ローカルHTML生成・検証を行う')
    commands.add_parser('report', help='週次PR本文用の集計を出力する')
    check = commands.add_parser('check', help='JSON・HTMLと週次PRを信頼済みコードで検査する')
    check.add_argument('action', nargs='?', default='site', choices=('site', 'intake', 'prepare', 'verify'))
    check.add_argument('--expected-sha256', help='公開したHTMLの期待SHA-256（verify用）')
    return cli


def main(argv=None):
    args = parser().parse_args(argv)
    if args.operation in ('begin', 'fetch', 'report'):
        from .fetch import main
        return main(args)
    if args.operation == 'build':
        from .build import main
        return main()
    from .check import main
    return main(args.action, args.expected_sha256)


if __name__ == '__main__':
    raise SystemExit(main())
