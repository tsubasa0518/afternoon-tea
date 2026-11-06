# Step 5: オフラインのデータ・HTML生成基盤

Python 3.9以降、標準ライブラリのみ。インストールやAPIキーは不要です。
`research_spec.md`が基準です。今回のコードは仕様に記載されたWeb調査を実施せず、
既存HTMLから現在の調査結果を逆生成することもしません。

## 実行

リポジトリのルートで実行します。

```sh
python3 -m afternoon_tea extract
python3 -m afternoon_tea init
python3 -m afternoon_tea validate .staging/data_YYYY-MM-DD.json
python3 -m afternoon_tea build .staging/data_YYYY-MM-DD.json
python3 -m unittest discover -s tests -v
```

`init`は日本時間の今日と40日後を計算します。再現用に`--start YYYY-MM-DD`も指定できます。
同じ日の既存JSONは上書きしません。調査入力を更新する場合は内容を明示的に編集してください。
`extract`は仕様から追跡対象の`data/store_master.json`を再生成します。
通常は抽出済みJSONと仕様の完全一致を毎回確認します。

`build`はJSON検証後、`.staging/.pending-.../`を作り、次を**元のスクリプトのまま**実行します。

```sh
python3 /path/to/repository/build_html.py data_YYYY-MM-DD.json
```

スクリプトの作業ディレクトリを一時ディレクトリにするため、生成先は公開サイトと分離されます。
正常終了・HTML検証後だけ`.staging/validated-.../`へ改名し、次を保存します。

- 入力JSONの完全なコピー
- `afternoon_tea_tokyo_YYYY-MM-DD.html`
- `validation.json`（データとHTMLの検証結果・ハッシュ・生成ログ）

失敗・タイムアウト時はその実行の一時ディレクトリを削除します。既存の成功結果は残ります。
すべてのレポートは`publishable: false`です。`validated`はオフラインの検査通過だけを意味します。
公開・docsへのコピー機能はありません。一時生成先の公開ディレクトリ指定と、シンボリックリンク経由の指定も拒否します。

## 店舗マスター

`data/store_master.json`に、14エリアの対象駅、全42分類の見出し、店舗名・駅・出口、
候補5店、対象外16項目を保存します。元の店舗行・見出し・候補行・対象外行を`raw`等に保持し、
抽出した店舗行の配列が仕様の全店舗行と順序も含めて一致することを検証します。
仕様の出典SHA-256も記録します。

マスターは70店（カフェ28・ホテル24・高級ホテル18）です。
現在のサイトに表示される120店とは別の入力です。マスターの対象外ジャンルに該当し得る店も、
抽出段階では原文どおり保持します。次工程の調査時にジャンル等を判断し、仕様に従って掲載対象から外します。
対象外16項目は検索抑止用マスターにのみ保存され、調査結果の`excluded`への転記はしません。

## 調査JSON

仕様の`generated`、`period`、`areas[].cats.{cafe,hotel,lux}.shops`、
`candidates`、`excluded`、`notes.status`をそのまま使用します。
店舗には`name/shop/station/exit/links/plans/tabelog/new`、プランには仕様の全項目を保持します。
欠落したプラン項目、JSONキー重複、NaN/Infinityは拒否します。

追加メタデータは既存スクリプトには表示されません。

| 項目 | 用途 |
| --- | --- |
| `metadata` | `schema_version: 1`、`purpose: unresearched/research/test`、マスター出典ハッシュ |
| 店舗の`master_id/master_name/master_category` | マスターとの対応、元の店舗名・分類（原文はマスターに保持） |
| 店舗の`research` | `status`、`checked_on`、`in_hotel`、`evidence`、`error` |
| 分類の`research` | `status`、厳格チェックの`checks`、取得失敗時の`error` |
| `notes.pending_candidates` | マスター由来の未調査候補。現在の検索抜粋を確認した候補とは区別 |

`init`は70店すべてを`unresearched`、42分類すべてを`unchecked`にします。
`links: []`、`links_note: 未調査`、価格・期間・テーマ・評価は`null`、曜日は`off`、スイーツは空配列です。
全未調査店名を`notes.status`に列挙します。元の「該当なし」を現在の確認済み結果にはしません。
初期`candidates/excluded`は空です。過去の候補は`notes.pending_candidates`とマスターに残し、
現在の検索結果で確認するまでは仕様の`candidates`へ昇格させません。

ホテルは現在価格が未確認なので`hotel`へ配置し、過去の高級分類は`master_category: lux`として保存します。
これは仕様の「価格不明はホテル」と生成スクリプトの自動振り分けに従います。
表示用のホテル名と店舗名は末尾の括弧から分けますが、元の完全な名前は`master_name`に残ります。
マスター内のホテル内外が未確定の2店も、調査確認までは歴史的分類の暫定配置です。

`failed`は未調査と別の状態です。取得失敗の店は未知値のまま残し、`attempted_on`、
`error`、`links_note: 取得失敗`を記録します。失敗したことを「ATなし」に変換しません。

## 確認済みデータの入力契約（Step 6向け）

`research.status: confirmed`には採用サイトの予約URL1件、確認日、ホテル内外のboolean、
予約ページとメニューの確認根拠が必須です。

```json
{
  "status": "confirmed",
  "checked_on": "YYYY-MM-DD",
  "in_hotel": false,
  "error": null,
  "evidence": {
    "reservation": {
      "url": "採用したHTTPSの予約ページURL",
      "checked_on": "YYYY-MM-DD",
      "quote": "確認した原文",
      "booking": true,
      "menu": true,
      "meal": "lunch"
    },
    "classification": {
      "url": "許可サイトで確認したページURL",
      "checked_on": "YYYY-MM-DD",
      "quote": "ホテル内外を確認した原文"
    }
  }
}
```

上の例は契約説明であり、有効な実店舗データではありません。
既知のプラン値は`/plans/0/theme`、`/plans/0/price_min`、`/plans/0/wd`等のキーごとに、
`url/checked_on/quote`の根拠を要求します。マスターから変更した駅・出口・名称・評価にも
`/exit`等のキーで根拠が必要です。新規店の名称・駅等も同様です。
未確認の`null/off/[]/要確認`はそのまま保持し、生成前後のJSONも完全一致を検査します。
推測の根拠は`kind: inferred`を付けられますが、許可されるのはテーマ国のみです。
推測国の店名と根拠原文を`notes.status`にも記録してください。

予約URLはHTTPSの`restaurant.ikyu.com`、`tabelog.com`、`tablecheck.com`のみ
（`www.`別名も可）。類似ドメイン、任意サブドメイン、認証情報、非標準ポートを拒否します。
一休の根拠`meal`は`lunch/breakfast`のみです。ホテル内外、最安プランの9,000円基準を検証します。
同じホテルの別ラウンジは`name + shop`で区別し、`master_id`と予約URLの重複も検知します。

分類に確認済み店舗がある場合は`ok`を使います。確認済み店と未確認店が混在するときは
分類調査を`partial`にし、HTMLカードには確認済み店舗だけを出します。未確認店はJSONと
`notes.status`に残します。確認済み店がない分類は`unchecked`です。`none`は店舗がないことを
全件調査で確認できた場合に限り、空の店舗配列と次の根拠キーを要求します。

- 全分類：`ikyu_area_list`、`tabelog_area_list`、`tabelog_station_search`
- ホテル分類：加えて`hotel_list`、`hotel_openings`、`hotel_at_checks`

これらも`url/checked_on/quote`を持ちます。`checks`のキーは検査実施記録であり、
全ホテル・全駅を実際に調べたかは次工程の調査担当が保証する必要があります。

## 検証の範囲と限界

JSONの型・構造・日付・重複・許可ドメイン・1店1リンク・分類・出典欠落・未調査状態の
確定情報化を検知します。HTMLは全開閉タグ、14エリア、3分類、カード・プラン数、
予約リンク、料金・曜日属性、期間不明表示、テーマ・日程文言、CSS/JS一致を検査します。
仕様の対象外名称と既知の対象外ジャンルも拒否します。

オフラインコードだけで引用の真偽・値段の通常価格/税サ込・実際の予約可否・ジャンル/静かさ・
URL疎通・全プランの探索完了を保証することはできません。次工程で予約ページとメニューを実際に開き、
証拠を入力する必要があります。根拠があるように偽装されたデータの真偽は判定できません。
証拠URLも現段階では上記3予約サイトに限定しています。ニュース等の探索記録は次工程で別途設計します。

生成スクリプト自身は、リンクのない店や「要確認」の文字列をHTMLから省く仕様です。
それを変更せず、正本JSON・確認状況・検証レポートで未知値を保持します。
全店未調査のHTMLは14エリア・0カードになります。調査成功や完成したレポートを意味しません。

## 公開保護と次工程

`data/protected_hashes.json`は既存の仕様・原文・生成スクリプト・元HTML・公開HTML・
deploy.ymlのSHA-256を固定し、実行前後とテストで未変更を確認します。
`.staging/`はGit管理対象外です。新規CIは読み取り権限だけでオフラインテストを実行し、
Pagesへのアップロードや公開権限を持ちません。既存のdeploy.ymlは変更していません。

Step 6では調査順序・検索上限・429再試行・エリア別担当結果の統合、
通常価格・期間・曜日・メニューの証拠保存、候補の再調査、禁止ジャンル/対象外店の
記録除去、確認状況と変更点レポートの出力を実装します。
その後、レビュー済みのデータだけを公開する条件と新しい公開前検証を設計し、
初回HTML固定比較の置換および日本時間月曜のスケジュール設定を別途行います。
今回はこれらのWeb調査・公開・定期実行を一切行いません。
