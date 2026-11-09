# 毎週の自動更新

毎週月曜日07:17 JSTに、既存のClaude Code Routineがクラウド環境 `afternoon-tea-weekly` で `tsubasa0518/afternoon-tea` の最新mainを取得します。起動指示は毎回 `AGENTS.md` と `developer_docs/claude_weekly_prompt.md` の最新版を読みます。既存Routineを使い、Codexの定期実行や追加のAPIキーは作りません。

2026-11-07にRoutine画面で、有効・対象リポジトリ・実行環境・毎週月曜日07:17 JST・次回11月9日07:17・最新版指示書優先を確認しました。既存の登録指示やスケジュールの変更は不要でした。

## 毎週の流れ

1. 14エリア・対象駅を読み、JST実行日から40日後までを対象に公開情報を調査します。既存リストは参考で、店舗数の上限はありません。既存店の確認と新店舗の探索を行い、同一店舗の複数プランを保存します。
2. `site/research.json` に店舗・各プランの情報、通常価格、出典、確認日時、短い根拠抜粋を保存します。未知はnullです。AT提供を確認できれば期間未確認でも掲載できます。
3. `site/search_failures.json` に未確認・制限・未調査と、全14エリアの実際の探索範囲を保存します。取得失敗をAT提供なしと扱いません。
4. 次を順に実行します。

```sh
python3 -m afternoon_tea.routine_enrichment
python3 -m afternoon_tea.weekly_review
python3 -m afternoon_tea.routine_renderer generate
python3 -m afternoon_tea.routine_site validate
```

5. `site/` 内の上記JSON2ファイルと `index.html` だけを `claude/weekly-afternoon-tea-YYYYMMDD` へコミット・pushし、mainへ `[weekly-site] YYYY-MM-DD 自動更新` の非ドラフトPRを作成します。
6. GitHub Actionsが技術CI成功後に自動マージし、既存の `deploy.yml` を明示起動します。
7. Pages公開後、HTTP 200とHTMLのSHA-256一致を検証します。公開記録はActionsのSummaryとArtifactに残ります。

## 分類とデザイン

通常価格が確認できる場合は施設の種類に関係なく価格で分類します。対象期間内の確認済みプランの最安通常価格で、cafe（6,000円以下）/ hotel（6,001〜9,999円）/ lux（10,000円以上）、通常価格不明の場合のみ、確認済み施設情報からホテル内はhotel、それ以外はcafeとし、施設情報も不明ならunknownです。料金は未確認のまま保持します。割引価格は別フィールドにし、割引率から通常価格を逆算しません。

JSON補完とHTML生成で同じ価格分類処理を使います。生成器は対象期間外のプランを除き、残ったプランから分類を計算するため、古いcategoryが残っても画面へ流用しません。価格不明を0円と扱いません。確認日時は補完・再分類では更新しません。

固定テンプレートを使い、毎週デザインを書き直しません。14エリア、3価格分類と分類未確認、スイーツ15項目・イベント季節5項目、曜日、店舗名・テーマ・料金の検索、複数プラン、出典と確認日時、スマートフォン対応を維持します。プランごとに情報URLを保存すれば、個別リンクも出力します。公式サイトを含むHTTPS公開情報URLに対応します。

## 公開条件と権限

`auto-merge-weekly.yml` は、同一リポジトリ・許可作成者・ブランチ接頭辞・タイトル接頭辞・3ファイル限定を検証します。PRをcheckoutせず、信頼するmainのプログラムでデータを読みます。技術CIの成功を確認し、検証したhead SHAを指定してsquash mergeします。GITHUB_TOKENによるマージ後も公開が起動するよう、workflow_dispatchを明示的に呼びます。

許可作成者はRepository variable `CLAUDE_ROUTINE_AUTHOR`、未設定なら `tsubasa0518` です。取り込みジョブだけがcontents/pull-requests/actionsの書き込み権限、公開ジョブだけがPages公開権限を持ちます。週次実行でワークフロー・認証・Python・保護ファイルを変更しません。

店舗数・未調査数・調査完了率は公開停止条件にしません。0店舗でも説明付きの正常HTMLを公開します。JSON破損・不正HTML・秘密情報・想定外ファイル変更は停止し、前回サイトを維持します。生成器は検証後にHTMLを一時ファイルから置き換え、失敗時には既存HTMLを維持します。

匿名の安全な公開GETのみを利用します。予約・仮予約・日時人数選択・フォーム送信・問い合わせ・ログイン・決済・アクセス制限の回避は禁止です。Pythonの既存HTTP層はrobots・要求間隔・サイズ上限・認証禁止・リダイレクト禁止を適用します。公式の公開情報源は `Browser(public_hosts=["正確なホスト名"])` で実行ごとに明示できます。既知サービスのURL規則は緩和せず、拒否されたサイトの別名を使いません。

## 最初の設定と復旧

既存設定が維持されていれば毎週の追加操作は不要です。接続が失効した場合だけClaudeのGitHub接続・ブランチpush・PR作成権限を確認します。GitHub PagesのSourceはGitHub Actions、公開Environmentに必須の手動承認がない構成を使用します。権限不足や必須レビューで停止したら、Actionsの具体的エラーに基づいて確認し、保護を自動解除しません。

公開だけ再実行する場合はGitHub Actionsの「Publish site to GitHub Pages」からmainを指定します。自動取り込みのdispatch失敗時は同じ取り込みジョブを再実行できます。Routineを停止する場合はClaude側で一時停止します。旧Python週次調査は補助であり、`WEEKLY_RESEARCH_ENABLED` の有効化は不要です。

元HTML・build_html.py・research_spec.mdと既存の公開ワークフローは保護したままです。今回の86店舗の再分類は保存済み根拠の処理で、最新の再調査ではありません。新規探索やプラン追加の実施結果は、次のRoutineのJSON・PR・Actionsから確認します。

## 店舗の最寄駅

店舗カードには公開情報で確認した最寄駅名のみを表示します。複数駅は「／」で区切り、不明は未確認とします。出口・改札・徒歩分数・直結・道順は追加調査や専用項目への抽出をしません。エリアの対象駅を店舗の最寄駅に流用せず、14エリア・対象駅の探索範囲を維持します。既存の出典・根拠・確認日時は整形だけでは変更しません。
