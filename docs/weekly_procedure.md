# 週次手順と数値の正本

既存Claude Routineは毎週月曜07:17 Asia/Tokyoに実行する。安全規則は `AGENTS.md`、ブラウザの判定は `afternoon_tea/browser.py` に従う。毎回最新mainから本書と `CLAUDE.md` を読む。

## 開始

同じ週のPR・ブランチ・公開記録を確認し、既存PRがあれば更新する。別名PRや並行実行を増やさない。翌週は候補CSVの先頭から始め、調査進捗は復元しない。

ブラウザの導入は開始時に一度だけ試す。失敗してもGETだけで続ける。

```sh
pip install -r requirements-browser.txt && python3 -m playwright install chromium
python3 -m afternoon_tea begin
```

`begin` は前回の `site/research.json` を `.staging/weekly/previous.json` に控え、今週の空データと一時状態を作る。途中で再実行しない。

## 調査

`data/references/user_candidates.csv` をNo順に読み、エリア番号列をそのまま使う。エリアや駅自体の調査はしない。

```sh
python3 -m afternoon_tea fetch 1
python3 -m afternoon_tea fetch 1 '同じ店舗のdetail_linksにあるURL'
python3 -m afternoon_tea fetch 2
```

出力の `text` を読み、必要なプランページを読み終えた店舗だけ採用する。取得成功や一般的な紹介だけを具体的なプラン確認と扱わない。通常ランチ・単品・追加オプション・別店舗の情報を混ぜない。標準出力はAT関連語の周辺だけで最大12,000文字。必要なときだけ `--full` で全文を読む（再実行すれば同じURLを再取得する）。本文は保存しない。

GETでプランが見えない場合だけ、同じURLを任意のヘッドレスブラウザで読む。`--browser` で指定できる。許可・禁止の詳細は安全規則と判定コードを参照する。ブラウザが利用できなければGETで続行する。

終了コードの意味は、`abandon_shop` がその店舗を諦めて次へ、`stop_research` が調査終了後にbuildへ、順番違い・begin未実行が使い方の誤り。AT未確認・情報不足も次へ進み、店名を失敗記録へ残さない。

### 上限

| 対象 | 値 |
|---|---|
| 調査全体 | 1,500秒・200要求（robots.txtを含む） |
| 店舗ごと | 最初の取得から60秒 |
| 要求間隔 | 3秒以上。robotsの指定が長ければ優先 |

コードの定義元は `afternoon_tea/fetch.py`。robotsのルール・拒否・不明は週の状態に保存し、サイトごとに週一度だけ取得する。新週のbeginで切り替える。

トークンが足りなくなりそうなら調査をやめ、buildへ進む。

### 掲載データへの記入

取得出力の `shop` をもとに `site/research.json` の `shops` へ追加する。`list_url` はCSVの予約ページURL文字列をそのまま使う。未完了の店舗は追加しない。

- 店舗：`name`、`area_no`、`list_url`、`source_site`、`station`、`address`、任意の `hotel_name`、`plans`。
- プラン：`plan_name`、`price_yen`、任意の `discount_price_yen`、`price_note`、`start`、`end`、`weekday_available`、`weekend_available`、`time_note`、`menu`、`source_url`、`checked_at`、`cc`。

`price_yen`にはページで読んだ通常料金を、割引料金は別の任意項目へ直接記入する。割引率から逆算したり、抜粋・注記からPythonで料金を推定したりしない。未確認値はnull。

期間は年を含む日付が確認できた範囲だけ記入し、年を推定しない。曜日・時間・メニューも読めた範囲だけ記入する。`checked_at` は実際の閲覧日時（タイムゾーン付き）を使う。

最寄駅はページで読んだ駅名だけ、重複を除いて「／」で区切る。出口・改札・徒歩・直結・道順は収集しない。ホテル名も書かれたものだけを使う。

国は読めたプランのテーマから判断できる場合だけISOの `cc` を記入し、不明はnull。根拠文・国名・判定区分・ハッシュ・推測メモは保存しない。国旗はカード表示だけで、国別絞り込みは作らない。

## 掲載データ作成

```sh
python3 -m afternoon_tea build
python3 -m afternoon_tea report
```

buildは前回確認から14日以内のプランを、確認日時のまま引き継ぐ。古い・未来・日時不明、候補CSVのURLと一致しない店舗、対象外エリアを除く。店舗は `list_url`、同一店舗内のプランは `plan_name` で照合し、今週の結果で上書きする。提供期間が対象期間と重ならないプランも除く。対象は東京14エリアで、調査日から40日後までを扱う。

buildで料金区分・スイーツ・季節・曜日を作り、保存する。レンダラーは保存値を表示する。国コードはレジストリにあれば正規化し、なければnullにして続ける。HTML生成と技術検証までまとめて行い、空の掲載データでも正常終了する。再生成・分類だけで確認日時を更新しない。

取得ページ全体には掲載用の秘密情報検査をかけない。掲載候補のプランに秘密情報・個人情報が含まれる場合は、そのプランだけをbuildで除く。除外した内容・店名は記録せず、件数だけを `excluded_sensitive_plans` の `current`・`previous` に分けて保存し、reportには合計を出す。再buildで前回スナップショットを二重に数えない。全プランが除外された店舗は掲載しない。店舗情報や文書全体の破損・秘密情報は、公開前の検査で引き続き拒否する。

| 通常料金 | 店舗の分類・プランの料金帯 |
|---|---|
| 5,000円以下 | カフェ・低料金帯 |
| 5,001〜8,000円 | ホテル・中料金帯 |
| 8,001円以上 | ホテル（高級）・高料金帯 |
| 未確認 | 分類未確認・料金未確認 |

店舗分類には対象期間内のプランの最安通常料金を使い、料金帯の絞り込みはプランごとに行う。店名・施設種別で分類しない。

## PRと公開

週次が変更できる追跡ファイルは `site/research.json` だけ。`site/index.html` は追跡せず、buildでローカル確認用に生成する。公開用HTMLはpublish.ymlが最新mainのJSONから生成する。`claude/weekly-afternoon-tea-YYYYMMDD` ブランチ、`[weekly-site]` タイトル、main宛てでPRを作成・更新し、非draftにする。PR本文にはreport出力を使い、調査途中を完了と書かない。

publish.ymlは信頼済みmainのコードでJSONだけを審査し、期待headを指定してマージした後、最新mainからHTMLを生成してPagesへ公開する。週次PRはCI完了を待たない。作成者・同一リポジトリ・main宛て・指定ブランチ・タイトル・変更ファイル・JSONと生成HTMLの安全性を検査し、ブランチ保護・必須レビューを回避しない。公開後はHTTP 200・HTML一致を確認する。通常PRとmainへのpushはtest.ymlでオフラインテストする。Routineの実行と本番公開の成否を区別して日本語で報告する。

公開時には保存データの経過日数で再判定せず、JSON・確認日時の形式、HTMLの安全性、秘密情報、PRの条件を技術検証する。古い掲載内容の再公開だけを理由に確認日時を更新しない。

JSON破損、HTML生成・安全検査の失敗、除外後に残る秘密情報、PR審査不合格時は公開せず前回のサイトを残す。原因を直してbuildから再確認する。調査上限・情報不足・取得失敗だけで公開を止めない。

公開だけを再実行する場合は、mainを対象にpublish.ymlのworkflow_dispatchを使う。Routineや調査を起動せず、保存JSONと確認日時を変えない。既にマージされた週次PRの重複イベントは公開を再起動しない。公開失敗時も同じ手動公開経路で再試行できる。
