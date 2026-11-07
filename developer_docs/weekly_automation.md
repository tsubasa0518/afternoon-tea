# 毎週の自動更新

Claude Codeが調査とJSON更新・固定生成器の実行、GitHubが検証・取り込み・公開を担当します。Codexの定期実行やOpenAI APIは使用しません。

```mermaid
flowchart TD
  A[月曜07:17 JST Claudeのクラウドタスク] --> B[調査とJSON更新・固定HTML生成]
  B --> C[claude/weekly-afternoon-tea-で始まるブランチからweekly-site PR]
  C --> D[main側コードで技術検証]
  D -->|合格| E[自動マージ]
  E --> F[公開ワークフローを明示的に起動]
  F --> G[最新mainのHTMLをPagesへ公開]
  D -->|不合格| H[前回サイトを維持しActionsに理由を保存]
```

## 最初の一度だけ行う設定

1. [Claude Codeクラウドタスク](https://claude.ai/code/routines)でGitHubを接続し、`tsubasa0518/afternoon-tea`への取得・ブランチpush・PR作成を許可します。ClaudeのGitHub操作は接続ユーザーの名義です。本人の接続・権限承認は代行できません。追加のAPIキーやPATは不要です。
2. タスクを作成し、このリポジトリ、main、下記プロンプトを指定します。毎週月曜日07:17、タイムゾーンAsia/Tokyoを選びます。UTC指定の5フィールドcronなら `17 22 * * 0` です。不要なコネクターを外してください。
3. GitHubのRepository variables `CLAUDE_ROUTINE_AUTHOR`を実際のPR作成者loginに設定します。未設定ならリポジトリ所有者`tsubasa0518`のみ許可します。bot名を推測して設定しないでください。
4. GitHub Settings → Pages → SourceをGitHub Actionsにします。既存のgithub-pages Environmentに毎回の承認必須設定があると無人公開が止まります。その場合は本人が保護方針を確認してください。
5. Claudeで一度Run nowを実行し、PR作成とActionsログを確認します。成功表示だけでPR作成済みとは判断しません。

Claude公式の現在の名称はCloud Scheduled Tasks（旧Routines）です。毎回クラウドでリポジトリを取得し、通常claude/weekly-afternoon-tea-で始まるブランチを作成します。公式仕様: https://code.claude.com/docs/en/routines 。通常の契約枠を利用し、有料APIや追加の従量課金は設定しません。環境のネットワーク許可が不足する場合は、必要な公開ドメインだけを本人が許可します。サイト側のrobots・403・CAPTCHAは回避しません。

## 3ファイル

- `site/index.html`: インラインCSS・フィルター用JavaScriptを持つ単独HTML。Pagesで公開するのはこのファイルだけです。画像は埋め込み、フォントは任意のGoogle Fontsのみを使用します。外部JavaScript・フォーム・自動通信を含めません。
- `site/research.json`: `schema_version: 1`, `generated_at`（タイムゾーン付きISO日時）, `shops`配列。各店舗に名前・エリア・確認した情報・原文・出典URL・確認日時を保存します。不明値はnullです。
- `site/search_failures.json`: 同様にschema_version・generated_at・`failures`配列。各記録はname, area, checked_at, sources（URL配列）, status, reason, retry（真偽値）を持ちます。statusは`information_insufficient`, `access_denied`, `site_restriction`, `no_results`, `unresearched`, `confirmed`です。必要ならstation（駅）とscope（shop/site/area/station）も記録します。情報取得失敗はAT提供なしの証明ではありません。

例（書式説明用。本番調査結果ではありません）:

```json
{"schema_version":1,"generated_at":"2026-11-09T07:17:00+09:00","failures":[{"name":"書式説明用","area":"対象エリア","checked_at":"2026-11-09T07:17:00+09:00","sources":[],"status":"unresearched","reason":"時間制限に達した","retry":true}]}
```

初期のindex.htmlは旧120店舗HTMLとバイト単位で同一です。初期JSONの`legacy_copy_not_new_research`は、このHTMLが今回の新規調査結果ではないことを示します。最初のClaude実行で当週の情報へ置き換えます。JSONの空shops配列を120店舗の最新確認済み情報と解釈しないでください。

## 自動マージと公開

ブランチは`claude/weekly-afternoon-tea-YYYYMMDD`、PRタイトルは`[weekly-site] YYYY-MM-DD 自動更新`です。Claudeのクラウド実行が別のclaude/名から開始した場合も、push先は指定の接頭辞を持つブランチにします。同じ日の再実行は既存の未マージPRを更新するか、日付の後ろに実行識別子を追加します。

GitHubの権限は、取り込みジョブにcontents: write・pull-requests: write・actions: write、公開ジョブにcontents: read・pages: write・id-token: writeのみを与えます。公開ジョブはmainへpushしません。許可作成者がtsubasa0518であれば追加の変数設定は不要です。

`auto-merge-weekly.yml`は同じリポジトリ、許可作成者、claude/weekly-afternoon-tea-で始まるブランチ、[weekly-site]タイトル、3ファイル限定を確認します。追加・変更だけを許可し、削除・リネーム・シンボリックリンク・ワークフロー変更を拒否します。PRをcheckoutせず、信頼できるmain側コードがGitHub APIでファイルをデータとして読みます。PRのプログラムは実行しません。

技術検証に合格すると、検証したhead SHAを指定してsquash mergeします。ブランチ保護は解除しません。必須CI待ちには短時間再試行します。権限不足・必須の人間レビュー等で止まったら、ActionsのHTTPステータスを確認し、本人がSettings → Rules/Branches/Actionsの必要箇所を一度確認します。自動マージ機能の設定や新しいPATを無条件で要求する構成ではありません。

マージ後、GITHUB_TOKENを使って`deploy.yml`のworkflow_dispatchを明示的に呼びます。GITHUB_TOKENのpushで次のpushワークフローが起動するとは仮定しません。dispatch失敗時は失敗として残り、同じ取り込みジョブの再実行でマージ済みPRから公開だけ再試行できます。GitHub公式: https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow 。

`deploy.yml`だけがPages権限を持ちます。最新mainの3ファイルを再検証し、index.htmlだけをPages Artifactへ入れ、同じURLへ公開します。公開後にHTTP 200とSHA-256一致を確認し、コミット・実行ID・ハッシュ・生成HTMLを30日間Artifactに保存します。調査JSONはGit上に保存され、Pagesのルートには配信しません。

店舗数0・2、未解決76、14エリア未完了、価格null、REVIEW_REQUIRED等は停止条件にしません。0店舗の場合は「今週確認できた情報はありません」と表示します。JSON破損・HTML欠落/空・タグ破損・欠落する外部アセット・秘密情報らしい値・想定外ファイル変更は停止します。静的な秘密情報検査は既知パターンの検査であり、全ての個人情報や悪意あるJavaScriptを完全に判別する保証ではありません。Claudeに認証情報を渡さず、許可作成者を限定することも必要です。

## 競合と復旧

`deploy.yml`を再利用し、公開対象をsite/index.htmlへ切り替えました。旧120店舗を自動配信する経路と、重複した公開ワークフローは残していません。元のワークフローは`backups/legacy-deploy.yml.txt`、元120店舗HTMLは`docs/index.html`と`afternoon_tea_tokyo_2026-11-06.html`に保管し、従来のSHA-256保護を維持します。deploy.ymlの保護値だけを新しい公開処理の値へ更新しました。予約禁止規則は変更していません。

取り込みは直列実行し、merge APIにhead SHAを指定します。公開も`github-pages`グループで直列実行し、最新mainを公開するため、同週の二重実行で古いソースを押し戻しません。research_dataだけのpushは公開対象外です。旧Python週次調査は補助機能として残り、公開しません。Claude運用ではWEEKLY_RESEARCH_ENABLEDを有効にする必要はありません。

HTML生成ができない場合は、Claudeに公開用PRを作らず実行エラーを報告させます。HTMLの欠落・破損や技術検証失敗はデプロイ前に停止し、前回サイトが残ります。公開や公開URL確認に失敗した場合はActionsを失敗として記録し、同じmainから再実行できます。店舗数・調査範囲・旧品質判定を理由とする自動ロールバックはありません。生成HTMLは公開成功後の最新バージョンとして扱います。技術障害時の手動復旧は前回成功コミットのsite/index.htmlを復元してmainへ反映し、Publish siteを実行します。元120店舗版を必要とするときだけdocs/index.htmlをsite/index.htmlへコピーします。旧ワークフローは再有効化しません。

## 手動実行・停止

公開だけ再実行: GitHub Actions → Publish site to GitHub Pages → Run workflow → main。ソースは常に最新mainです。

毎週の調査を止める: ClaudeのクラウドタスクをPause/Disableにします。自動マージも止めたい場合はGitHub ActionsでAuto-merge weekly siteをDisable workflowにします。全公開を止める場合はPublish siteもDisableにします。サイト自体は最後に成功したHTMLを表示し続けます。

## Claudeへ貼り付ける最終プロンプト

[claude_weekly_prompt.md](claude_weekly_prompt.md)の全文を使ってください。

## ローカル検証

```sh
python3 -m afternoon_tea.routine_site validate
python3 -m unittest discover -s tests -v
```

公開正常系はローカルのモックHTMLで検査します。GitHubのE2Eでは旧HTMLのバイトを維持したメタデータ変更PRを使い、架空店舗のページは本番に公開しません。Claude本人のアカウント接続と実際のRoutine実行は、GitHub上の模擬PR試験とは別の確認です。

## 調査範囲・期間・検索操作の改善

毎週の調査は「14エリアの公開一覧 → 70マスターと5候補の情報源 → 前週未調査を優先したエリア巡回 → 予約プラン詳細 → 余裕があれば新規店舗」の順に進めます。最後の完成時間を確保し、確認しやすい2店舗だけで時間を使い切らない指示へ更新しました。実際に探索できたエリア・駅・URLと未調査範囲を既存のsearch_failuresへ記録します。全件完了を公開条件にはしません。

日付は既存Pythonの日付処理を再利用します。

```sh
python3 -m afternoon_tea.weekly_review --period
python3 -m afternoon_tea.routine_site validate
python3 -m afternoon_tea.weekly_review
```

`--period`はJST実行日と40日後を出力します。日付確認は両端を含み、終了日の後に開始するプラン、開始日の前に終了するプランを報告します。両方または片方がnullの場合も推測して補完しません。既知の端点だけで期間外と確定できる場合を除き、期間未確認として保持します。事前確認は読み取り専用で、問題があると終了コード1、問題なしなら0です。確認済み店舗数や調査完了率は判定しません。このCLIを自動マージ・公開の必須処理には追加していません。

今回の修正では、PR #20にあった12月19日〜25日のプランを11月7日〜12月17日の掲載対象から除き、JSON・HTML・件数を9から8プランへ揃えました。店舗数は2のまま、確認日時・価格・出典は変更していません。別のプランの未知の日付を推測したり、新たなWeb調査を行った扱いにはしていません。

HTMLには店舗・ホテル名検索、季節/テーマ（プラン名）検索、料金帯、解除、表示件数、該当なし表示を追加しました。組合せは同じプランで判定し、価格不明を0円扱いしません。既存の色・カードを保ち、スマートフォンでは入力欄を縦に並べ、操作領域を44px以上にしています。エリアを切り替えても調査範囲の説明は隠しません。

### PRとActionsで確認する項目

ClaudeのPR本文に実行日・対象期間・掲載店舗/プラン数・未調査店舗数・取得状況・14エリア別探索を記載します。ActionsのSummaryにも同じデータの集計とPR/実行URLを表示します。取り込みの「自動マージ成功・公開開始要求」と、公開側の「Pages公開確認成功」を分けて表示します。失敗はエラーとして残し、成功表示に置き換えません。HTML、集計レポート、HTTP確認結果は既存Artifactに保存されます。

件数は店舗とレコードを区別します。PR #20のsearch_failuresは76レコードですが、内訳は未調査店舗73、全エリアの新規探索未実施1、確認済み記録2です。「未確認店舗76」とは数えません。拒否・規制・情報不足などもstatus別に集計します。これらは運用情報であり、公開の停止条件にはしません。

### 登録済みRoutineで一度だけ更新する指示

GitHubのファイルを編集しても、Claudeに登録した指示文が自動更新されるとは限りません。**既存Routineを編集し、スケジュール・GitHub接続をそのままにして、指示文を次の起動文へ置き換えてください。新しいRoutineを重複作成する必要はありません。**

```text
tsubasa0518/afternoon-teaの最新mainを取得してください。
毎回、AGENTS.mdとdeveloper_docs/claude_weekly_prompt.mdを全文読み、
その最新版に従って東京14エリアの週次調査、JSON・HTML生成、検証、PR作成まで完了してください。
前週未調査を優先して14エリアに調査機会を配り、JST日付から40日後までと重なるプランだけを掲載してください。
日付未確認は推測せず保持し、0店舗・調査未完了でも説明付きHTMLを完成してください。
変更はsite/index.html、site/research.json、site/search_failures.jsonだけに限定します。
予約・仮予約・フォーム操作・ログイン・決済・アクセス制限の回避は一切禁止です。
PR本文に実行日・期間・店舗/プラン数・未調査/取得状況と14エリアの探索範囲を記載してください。
```

毎週月曜日07:17 JSTの既存スケジュールやGitHubの自動マージ・公開設定を変更する必要はありません。


## 元HTMLの固定デザインを使う

デザインの正本は`afternoon_tea_tokyo_2026-11-06.html`です。添付のHomepage:example.htmlと内容が同一であることも確認しました。過去の120店舗情報は移植していません。

```sh
python3 -m afternoon_tea.weekly_review
python3 -m afternoon_tea.routine_renderer generate
python3 -m afternoon_tea.routine_site validate
```

生成器はネットワーク接続せず、site内のJSONを読み、検証後にindex.htmlだけを一時ファイルから安全に置き換えます。生成に失敗した場合は既存HTMLを維持します。build_html.pyと保護済みの元HTMLは変更していません。

`afternoon_tea/templates/routine.css`と`routine.js`は元HTMLからそのまま分離したCSS・基本JSです。routine.htmlが全体構造、routine_extra.css/jsが未確認値・検索・表示件数等の補助です。色、hero、3カテゴリの集計、14エリア、カテゴリ別見出し、card/plan/when/price/links、季節/スイーツ/曜日/価格確認フィルター、エリアジャンプ、ダークモード、上部へ戻る構造を再利用しています。

JSONの任意項目は後方互換です。categoryはcafe/hotel/luxで、欠落した場合は分類未確認として表示します。現在の2店舗のcategoryは既存store_masterの分類を出典付きで明示しました。価格からカテゴリを推定していません。スイーツ・季節はJSONで指定された分類だけを使います。駅出口・曜日・時間等が不明なら未確認と表示します。店舗共通の時間補足は個別プランの確定時間に流用しません。

今回の掲載は2店舗・8プランです。既知の対象期間外1プランを除いた修正を維持しています。元120店舗の料金・期間・駅出口は流用していません。0店舗でも14エリアと未確認表示が崩れず、店舗数の少なさを公開停止条件にしません。

### Routineに登録する指示の更新

既存RoutineのスケジュールとGitHub接続を維持し、指示文を以下へ置き換えてください。GitHubのドキュメント更新だけで登録済み指示文も変わったとは判断しないでください。

```text
毎回tsubasa0518/afternoon-teaの最新mainを取得し、AGENTS.mdと
 developer_docs/claude_weekly_prompt.mdを全文読み、最新版に従って週次調査を行ってください。
変更はsite/research.json、site/search_failures.json、site/index.htmlだけです。
HTMLのデザインは変更せず、JSON更新後に必ず
python3 -m afternoon_tea.routine_renderer generate
を実行してsite/index.htmlを生成してください。HTML/CSS/JavaScriptを手書きしないでください。
日付確認・技術検証後に指定のclaude/weekly-afternoon-tea-ブランチと
[weekly-site]タイトルでPRを作成してください。予約操作やアクセス制限の回避は禁止です。
```

毎週の作業は「調査→JSON更新→固定生成器→技術検証→PR」です。デザイン変更が必要なときだけ、別の開発PRでテンプレートを修正します。GitHub側の自動マージ・Pages公開ワークフローは従来のままです。
