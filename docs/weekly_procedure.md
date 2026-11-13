# 調査と公開の操作手順

既存Claude Routineは毎週月曜07:17 Asia/Tokyoに実行する。守る内容は `AGENTS.md` の7項目だけで、本書はその操作手順を示す。上限・間隔・再試行と再確認の日数は `data/research_settings.json`（環境変数 `AFTERNOON_TEA_<キー名>` で一時変更可）が正で、本書には書かない。

## 1. 開始

1. 最新mainの `AGENTS.md`・`CLAUDE.md`・本書を読む。
2. 未マージの `[weekly-site]` PRがあれば（0件で公開を見送った回など）、そのブランチから続けて同じPRを更新する。なければ最新mainから `claude/weekly-afternoon-tea-YYYYMMDD` を作る。別名PRや並行実行を増やさない。
3. 準備と開始:

```sh
pip install -r requirements-browser.txt
python3 -m afternoon_tea begin
python3 -m afternoon_tea browse start
```

`begin` は保存済みの掲載と進捗を消さず、今回の対象期間と上限を設定して、次に調べる店舗を示す。ブラウザが起動しない場合は `python3 -m playwright install chromium` を一度試し、それでも使えなければ `read` で続ける。

## 2. 1店舗ずつ調べる

```sh
python3 -m afternoon_tea next            # 優先順: 未調査 → 再試行 → 再確認（一部）→ リスト外の探索 → 残りの再確認
python3 -m afternoon_tea start c12       # 調べる店舗のキー
```

1. **公開検索**：`next` が示す検索語（店舗名・ホテル名＋「アフタヌーンティー」、優先サイト名付き）で、Routineの検索機能（WebSearch）を使って検索する。検索結果の要約は確認済みの根拠にしない。
2. **ページを開いて読む**：検索結果の公式ページ・予約サイトの公開ページを開く。

```sh
python3 -m afternoon_tea browse open 'https://...'      # --new-tab で別タブ
python3 -m afternoon_tea browse text --full             # 本文（既定はアフタヌーンティー周辺の抜粋）
python3 -m afternoon_tea browse links アフタヌーン        # 開けるリンク（番号つき）
python3 -m afternoon_tea browse click 12                # リンク・展開・ページ送り
python3 -m afternoon_tea browse scroll | back | tabs | tab 1 | close-tab
python3 -m afternoon_tea read 'https://...'             # ブラウザなしで読む場合
```

3. **サイト内検索**（一休.comなど）：`browse controls` で番号と可否を見て、キーワード欄に店舗名・ホテル名を `fill`、アフタヌーンティーの項目だけを `check`（選択欄なら `select`）、`submit` する。ほかの条件を足さない。
4. 結果を1店舗ごとにすぐ保存する（次回はここから再開できる）。

```sh
python3 -m afternoon_tea record result.json
```

```json
{"key": "c12", "status": "plan_confirmed", "urls": ["https://..."], "note": "公式ページで確認",
 "shop": {"address": "東京都…", "station": "銀座駅／有楽町駅", "source_site": "公式サイト", "info_url": "https://...",
          "plans": [{"plan_name": "…アフタヌーンティー", "price_yen": 7500, "price_note": "税・サ込", "start": "2026-12-01",
                     "end": "2027-01-31", "weekday_available": true, "weekend_available": true, "time_note": "12:00〜",
                     "menu": "…", "source_url": "https://...", "cc": null}]}}
```

- `status`：`plan_confirmed`（具体的なプランを読んだ）、`general_only`（紹介だけ）、`no_at_found`（読めたページに記載なし。提供なしではない）、`failed`（取得不能。`reason` に `HTTP_403` などを書く）、`excluded_genre`、`out_of_area`。
- `source_url`・`info_url` は今回の実行で実際に開いたページだけ。`checked_at` は書かない（読んだ時刻が自動で入る）。不明な値は `null`。料金は読んだ通常料金を整数で、割引は `discount_price_yen` に。年を含む日付だけを `YYYY-MM-DD` で。駅名は「○○駅」だけ。
- スイーツの種類の分類・タグ付け用項目は作らない。プラン名・メニュー本文にある食品名はそのまま記録する。
- リスト外の店舗は `key` を省き、`shop` に `name`・`hotel_name`・`area_no`（1〜14）・`genre`（会場の主ジャンル）を書く。名称が候補リストと一致すれば、その行として保存される。
- 終了コード：1＝その取得先は使えない（理由を見て別の公開情報源へ）、3＝上限到達（調査をやめて3へ）、4＝ブラウザ利用不可（`read` で続ける）。

## 3. 掲載データ作成と提出

```sh
python3 -m afternoon_tea browse stop
python3 -m afternoon_tea build
python3 -m afternoon_tea report
```

- `build` は確認日時を変えずに、終了日が過ぎたプラン・除外ジャンル・14エリア外・壊れたデータを掲載から外し、分類と表示値を作り、ローカル確認用HTMLを生成・検証する。古い確認情報は残し、サイトでは「過去の確認情報」と表示する。
- `site/research.json` だけをコミットし、`[weekly-site]` タイトル・main宛ての非draft PRを作成・更新する。PR本文は `report` の出力を使い、調査途中を完了と書かない。
- `build` の `publication` が `refused_zero_listing` の回も、進捗を残すためにPRは出す。publish.ymlは0件をマージ・公開しない（前回のサイトを維持）。

| 通常料金 | 店舗の分類・プランの料金帯 |
|---|---|
| 5,000円以下 | カフェ・低料金帯 |
| 5,001〜8,000円 | ホテル・中料金帯 |
| 8,001円以上 | ホテル（高級）・高料金帯 |
| 未確認 | 分類未確認・料金未確認 |

## 4. 公開

- publish.ymlが信頼済みmainのコードでPRを審査し（作成者・同一リポジトリ・main宛て・指定ブランチとタイトル・変更ファイルが `site/research.json` だけ・期待head・JSONと生成HTMLの安全性・掲載件数が非ゼロ）、期待headを指定してマージし、最新mainからHTMLを生成してPagesへ公開し、HTTP 200・HTML一致・掲載カード数が非ゼロであることを確認する。週次PRはCI完了を待たない。通常PRとmainへのpushはtest.ymlで試験する。
- 公開だけを再実行する場合は、mainを対象にpublish.ymlのworkflow_dispatchを使う。保存JSONと確認日時は変えない。
- 結果の報告では、Routineの実行、0件による公開見送り、プログラムの異常終了、本番公開の成否を区別する。
