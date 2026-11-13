"""One entry for research, build and trusted publication checks."""
import argparse
import json
import sys


def parser():
    cli = argparse.ArgumentParser(prog='python3 -m afternoon_tea')
    commands = cli.add_subparsers(dest='operation', required=True)
    commands.add_parser('begin', help='今回の実行を開始する（保存済みの進捗と掲載は消さない）')
    nxt = commands.add_parser('next', help='次に調べる店舗を優先順に表示する')
    nxt.add_argument('--count', type=int, default=5)
    start = commands.add_parser('start', help='これから調べる店舗を指定する（店舗ごとの時間上限の起点）')
    start.add_argument('key', help='候補なら c番号（例: c12）、リスト外なら next や record が示すキー')
    read = commands.add_parser('read', help='公開ページを匿名GETで読む（JavaScriptなし）')
    read.add_argument('url')
    read.add_argument('--full', action='store_true', help='本文全体を出力する')
    browse = commands.add_parser('browse', help='調査用ブラウザを操作する')
    browse.add_argument('action', choices=('start', 'stop', 'serve', 'open', 'text', 'links', 'controls', 'click',
                                           'fill', 'check', 'select', 'submit', 'scroll', 'back', 'tabs', 'tab',
                                           'close-tab'))
    browse.add_argument('value', nargs='*', help='open: URL / click・check・submit: 番号 / fill: 番号 文字列 / '
                                                 'select: 番号 選択肢 / tab: 番号 / links・controls: 絞り込み語')
    browse.add_argument('--full', action='store_true')
    browse.add_argument('--new-tab', action='store_true')
    record = commands.add_parser('record', help='1店舗の調査結果をwebsite/listings_and_progress.jsonへ保存する')
    record.add_argument('file', help='結果のJSONファイル（- で標準入力）')
    commands.add_parser('build', help='分類・ローカルHTML生成・検証を行う（確認日時は変えない）')
    commands.add_parser('report', help='PR本文用の集計を出力する')
    check = commands.add_parser('check', help='JSON・HTMLと週次PRを信頼済みコードで検査する')
    check.add_argument('action', nargs='?', default='site', choices=('site', 'intake', 'prepare', 'verify'))
    check.add_argument('--expected-sha256', help='公開したHTMLの期待SHA-256（verify用）')
    return cli


def emit(value):
    print(json.dumps(value, ensure_ascii=False, indent=1))


def research_command(args):
    from afternoon_tea import manage_research as research
    from afternoon_tea.read_public_pages import AccessRefused, BudgetExhausted, ForbiddenOperation, Unusable, read
    try:
        if args.operation == 'begin':
            emit(research.begin())
        elif args.operation == 'next':
            emit(research.next_tasks(args.count))
        elif args.operation == 'start':
            emit(research.start_task(args.key))
        elif args.operation == 'read':
            emit(read(args.url, full=args.full))
        elif args.operation == 'record':
            raw = sys.stdin.read() if args.file == '-' else open(args.file, encoding='utf-8').read()
            emit(research.record(json.loads(raw)))
        elif args.operation == 'report':
            print(research.report())
        return 0
    except BudgetExhausted as error:
        emit({'stop_research': True, 'error': str(error)})
        return 3
    except (ForbiddenOperation, AccessRefused, Unusable) as error:
        emit({'source_unusable': True, 'kind': type(error).__name__, 'error': str(error),
              'next': 'この取得先は使わず、別の公開情報源へ進むか、店舗の結果を record する'})
        return 1
    except (RuntimeError, ValueError, OSError) as error:
        emit({'error': str(error)})
        return 2


def browse_command(args):
    from afternoon_tea import research_browser as browser
    value = args.value
    try:
        if args.action == 'serve':
            browser.serve()
            return 0
        if args.action == 'start':
            emit(browser.start())
            return 0
        if args.action == 'stop':
            emit(browser.stop())
            return 0
        names = {'open': ('url',), 'click': ('id',), 'check': ('id',), 'submit': ('id',), 'fill': ('id', 'text'),
                 'select': ('id', 'option'), 'tab': ('index',), 'links': ('match',), 'controls': ('match',)}
        keys = names.get(args.action, ())
        if args.action in ('fill', 'select') and len(value) >= 2:
            value = [value[0], ' '.join(value[1:])]
        if len(value) > len(keys) or (args.action not in ('links', 'controls') and len(value) < len(keys)):
            emit({'error': 'wrong_arguments', 'expected': keys})
            return 2
        call = dict(zip(keys, value))
        if args.action == 'text':
            call['full'] = args.full
        if args.action == 'open':
            call['new_tab'] = args.new_tab
        result = browser.call(args.action.replace('-', '-'), **call)
    except browser.BrowserUnavailable as error:
        emit({'browser_unavailable': True, 'error': str(error), 'next': 'python3 -m afternoon_tea read URL で続ける'})
        return 4
    emit(result)
    if result.get('ok'):
        return 0
    return {'stop_research': 3, 'forbidden': 1, 'access_refused': 1, 'unusable': 1}.get(result.get('kind'), 2)


def main(argv=None):
    args = parser().parse_args(argv)
    if args.operation == 'browse':
        return browse_command(args)
    if args.operation in ('begin', 'next', 'start', 'read', 'record', 'report'):
        return research_command(args)
    if args.operation == 'build':
        from afternoon_tea.prepare_listings import main
        return main()
    from afternoon_tea.publication_checks import main
    return main(args.action, args.expected_sha256)


if __name__ == '__main__':
    raise SystemExit(main())
