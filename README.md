# 東京アフタヌーンティー

東京14エリアのホテル・カフェを毎週調べ、集められた公開情報を固定HTMLで掲載します。未完了でも公開し、確認後14日以内の前回プランを実際の確認日時のまま引き継ぎます。0件も正常な公開です。予約操作は行いません。

## 構成

```text
.github/workflows/     CI・信頼済みmainでのPR審査・Pages公開
afternoon_tea/
  __main__.py         python3 -m afternoon_tea の入口
  common.py           共通パス・検証
  collection/         匿名GET、安全検査、候補リスト、実行中だけの上限
  processing/         14日引継ぎ、料金・期間・曜日・スイーツ・テーマ国
  publication/        固定HTML生成、技術検証、PR審査、公開前後の確認
  templates/          既存デザイン・検索・絞り込み
data/                 14エリアの店舗マスター、保護ハッシュ、国レジストリ
  references/user_candidates.csv  優先候補（エリア番号付き）
docs/weekly_procedure.md         毎回読む短い週次手順
site/research.json     掲載する店舗・プラン
site/index.html        生成した公開HTML
tests/                外部接続なしのテスト・fixtures
```

## 流れ

既存Claude Routine（月曜07:17 JST）だけが調査を起動します。毎回最新mainの指示を読み、候補リストNo.1から予約ページURL→一休→食べログ→TableCheckの順に未試行サービスを調べます。時間が残ればリスト外の14エリアを探します。使える時間・トークンの7割（調査420秒、通信150要求まで）で調査を終え、前回の14日以内のプランを引き継ぎ、補完・国判定・固定HTML生成・検証・PRへ進みます。未完了店舗を今週確認済みにはしません。

週次が変更できるのは `site/research.json` と `site/index.html` だけです。Actionsは調査を起動せず、PR審査・テスト・自動マージ・Pages公開を担当します。詳細は [週次手順](docs/weekly_procedure.md)、安全規則は [AGENTS.md](AGENTS.md) を参照してください。

## 公開条件

同一リポジトリ・許可作成者・main宛て・指定ブランチ/タイトル・2ファイル制限、検証したhead SHAのCI成功、JSON/HTML安全検査、各プランのタイムゾーン付き確認日時（直近14日以内・未来でない）、14エリア、秘密情報なしを確認します。調査の完了度や件数を条件にしません。Pages権限は公開ジョブに限定し、公開後にHTTP 200とHTMLの一致を検証します。

## コマンド

`python3 -m afternoon_tea --help` が一覧です。`begin`（時間・要求数を初期化）、`fetch URL`（安全な取得）、`refresh --previous PATH`（引継ぎ）、`enrich`、`themes-prepare`、`themes-finalize`、`review`（期間診断）、`render`、`validate-site`、`check-protected`、`intake`、`resume-intake`（CI完了後の審査）、`publish-prepare`、`publish-verify` を使います。本文や店舗別の調査進捗を翌週へ保存する仕組みはありません。

ローカル検証は `python3 -m unittest discover -s tests -v`。Python標準ライブラリのみで実行できます。絞り込みの実行テストにはNode.jsも必要です（CIのUbuntuには付属）。

## うまくいかないとき

転送・危険な要求は送信せず、その店舗を諦めて次へ進みます。403・429・CAPTCHA・robots拒否ではホストの再試行を止め、回避しません。サイズ超過・秘密情報のあるページは使いません。時間・通信上限でも集めた分で公開手順へ進みます。JSON破損、生成失敗、危険なHTML、秘密情報、PR審査不合格の場合は公開せず前回のサイトを残します。保護や必須レビューは解除しません。
