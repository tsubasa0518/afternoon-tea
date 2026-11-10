"""One command entry point for collection, processing and publication."""
import argparse
import json
from pathlib import Path
from .common import ROOT


def parser():
    cli=argparse.ArgumentParser(prog='python3 -m afternoon_tea',description=__doc__)
    commands=cli.add_subparsers(dest='operation',required=True)
    collect=commands.add_parser('collect',help='385行の優先調査を再開する')
    collect.add_argument('--output',type=Path,default=ROOT/'.staging/list-research')
    collect.add_argument('--limit',type=int,default=385)
    collect.add_argument('--seconds',type=float,default=600)
    official=commands.add_parser('collect-official',help='承認済みの公式公開情報を収集する')
    official.add_argument('--sources',type=Path,default=ROOT/'data/official_sources.json')
    official.add_argument('--output',type=Path,default=ROOT/'.staging/official-research')
    official.add_argument('--seconds',type=float,default=1200)
    official.add_argument('--max-requests',type=int,default=280)
    enrich=commands.add_parser('enrich',help='保存済み根拠から分類・タグを補完する')
    enrich.add_argument('--data',type=Path,default=ROOT/'site/research.json')
    enrich.set_defaults(parser=enrich)
    review=commands.add_parser('review',help='期間・日付と未確認項目を検査する')
    review.add_argument('--period',action='store_true')
    review.add_argument('--data',type=Path,default=Path('site/research.json'))
    prepare=commands.add_parser('themes-prepare',help='テーマ国の新規・変更分を準備する')
    prepare.add_argument('--previous',type=Path)
    prepare.set_defaults(command='prepare',parser=prepare)
    finalize=commands.add_parser('themes-finalize',help='人が判断したテーマ国の根拠を確定する')
    finalize.set_defaults(command='finalize',previous=None,parser=finalize)
    for name,help_text in {
        'render':'固定テンプレートからHTMLを生成する',
        'validate-site':'siteの3ファイルを技術検証する',
        'validate-campaign':'調査完了・証拠・監査の公開条件を検証する',
        'validate-catalog':'保護された店舗マスターを検証する',
        'check-protected':'保護対象のハッシュを検証する',
        'intake':'信頼するmainのコードで週次PRを審査する',
        'resume-intake':'最新headのCI完了を受けてPR審査を再開する',
        'publish-prepare':'公開用HTMLを検証・準備する',
        'publish-verify':'公開URLのHTTPとHTML一致を確認する',
    }.items():commands.add_parser(name,help=help_text)
    return cli


def main(argv=None):
    args=parser().parse_args(argv)
    operation=args.operation
    if operation=='collect':
        from .collection.campaign import main as collect
        return collect(args)
    if operation=='collect-official':
        from .collection.official import main as collect_official
        return collect_official(args)
    if operation=='enrich':
        from .processing.enrichment import main as enrich
        return enrich(args)
    if operation=='review':
        from .processing.period_review import main as review
        return review(args)
    if operation in ('themes-prepare','themes-finalize'):
        from .processing.themes import main as themes
        return themes(args)
    if operation=='render':
        from .publication.renderer import main as render
        return render()
    if operation=='check-protected':
        from .publication.guards import protected_files
        protected_files();print('Protected file hashes match.');return 0
    if operation=='validate-catalog':
        from .collection.catalog import load_master
        print(json.dumps(load_master()['counts'],ensure_ascii=False));return 0
    if operation=='validate-campaign':
        from .publication.gate import publication_gate
        publication_gate(json.loads((ROOT/'site/research.json').read_text()),
                         json.loads((ROOT/'site/search_failures.json').read_text()))
        print('Campaign publication requirements satisfied.');return 0
    if operation=='resume-intake':
        from .publication.ci import main as resume_intake
        return resume_intake()
    from .publication.site import main as publication
    return publication({'validate-site':'validate','intake':'intake',
                        'publish-prepare':'prepare','publish-verify':'verify'}[operation])


if __name__=='__main__':
    raise SystemExit(main())
