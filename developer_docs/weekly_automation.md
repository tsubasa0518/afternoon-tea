# 唯一の週次起動と公開条件（2026-11-09改訂）

定期の調査・JSON更新・固定HTML生成・週次PR作成は、既存Claude Routine
`trig_01GKrMV2hRzd756Pu3sPnjVf`（東京アフタヌーンティー毎週更新）だけです。
環境は`afternoon-tea-weekly`、repoは`tsubasa0518/afternoon-tea`、
毎週月曜日07:17 Asia/Tokyo。登録指示は最新mainのAGENTS.md、CLAUDE.md、
週次指示書を読むよう更新済みです。保守PRがmain未反映なら起動を中断します。
Codexは依頼された保守を担当します。新しい定期タスクは作成しません。

## 起動経路の監査

PR #45の署名だけで実行元を判断していません。2026-11-09にRoutine画面と
セッション履歴を照合し、上記Routine IDの11月9日07:17「予定済み」実行が
`session_01C7FU3d6mig3GSxABe3yJnn`を起動し、PR #45を作ったことを確認しました。
PR作成は2026-11-09 07:20:17 JST、マージは07:21:09 JSTです。
従って「PR #45を作成したCodex側の週次処理」という呼称が指すこの実行はClaudeです。
独立したCodex定期タスクが存在しないことまでは証明していません。

Codexの設定確認用`/Users/tsubasa/.codex/automations`は存在せず、Codexアプリ画面の
操作は利用制限により拒否されました。独立したCodex設定のID・名前・実行履歴は未確認、
停止実績もありません。利用者がCodexのAutomations/定期実行一覧で対象repoまたは
Claude Routineを起動する設定を探し、該当設定をPauseし、ID・指示・時刻・履歴を記録する
必要があります。確認できたIDはautomation_updateでPAUSEDへ変更できます。
未確認を「存在しない」「停止済み」と報告しません。

旧Actionsのweekly-research.ymlにはscheduleを置きません。手動診断しか持たず、
書き込み権限・状態commit・PR・公開はありません。WEEKLY_RESEARCH_ENABLEDを
変更しても復活しません。11月9日の旧schedule run 42547140145はskippedでした。

## 同じ週の一つの実行・一つのPR

`python3 -m afternoon_tea.weekly_run start`を調査前に実行します。
week_keyはJSTの月曜日YYYY-MM-DD。新規branchは
`claude/weekly-afternoon-tea-YYYYMMDD`（月曜日の日付）です。
全状態の同週PR・既存branch・稼働lease・旧診断稼働を照合します。
旧-r2 PRも実データのperiodから対象週を照合し、同名問題で追加PRを作りません。

GitHubの`routine-lock/<week_key>`制御refが外部Routine間の排他とcheckpointです。
最初のref作成は原子的、更新は現在lock commitを親にしたfast-forwardのみです。
並行ownerの兄弟commitは失敗します。leaseは2時間、owner/run_id/開始時刻/branch/
PR/head/3ファイルSHA/状態をcommit messageに記録します。秘密情報は保存しません。
Actions concurrencyだけに依存せず、更新直前にownerとleaseを再確認します。
失敗・競合時はforce pushせず停止します。

pauseや期限切れは`start --week YYYY-MM-DD --resume`で同じrunのdraftを復元します。
作業は2時間以内にcheckpoint保存し、長い調査はpauseして同じ週で再開します。
submitは既存PRを更新、未完了はdraft、完成時もdraft作成→checkpoint保存→readyの順です。
同head/baseのPRに対するGitHubの一意性と422後の既存PR再確認も利用します。
公開済みは変更なしで終了。マージ済みで公開失敗なら既存PR・コミットに対して
recover-publicationを使います。公開後の追加訂正は明示依頼の保守PRです。
GitHubへの変更は既存GH_TOKENか認証済みghを使用し、利用不能なら停止します。
この認証の次回Claude実環境での利用可能性は本保守のオフライン検証では未確認です。

## 技術検証と調査完了

JSON/HTMLの構造・個人情報・予約禁止・保護対象・固定デザインの技術検証を維持します。
別のresearch_completion検証は、信頼するmainのマスターと前週掲載店から作業を展開します。
14エリアの各対象駅にexistingとdiscovery、前週掲載店ごとのexistingが必要です。
今回runと週に属するURL・取得日時・文書SHA・実抜粋・対象駅/店舗との対応・確認結果を
要求し、共通一覧や前週実績、complete=trueだけでは通りません。

必須未着手・安全に確認不能・中断・禁止操作の記録があれば公開不可です。
一つの情報源の403を別の独立した許可情報源で補えた場合は、失敗記録を残したうえで
必要範囲の読取証拠を紐付けます。禁止操作による即時停止を解除して続行しません。
新規発見0や、調査した結果の料金/期間nullは許可します。
今週の実績はverified_plans参照から再計算し、前週総掲載数と分けます。

routine_site intakeはPR codeをcheckoutせず、main側コードでPRの3ファイルと
GitHub checkpointを検証します。同一repo・許可作成者・branch/title・draft除外・
最新headの技術CI・head再確認・期待SHA指定mergeを維持し、完了条件を追加します。
merged後の明示dispatchと既存要求の重複防止も維持します。

## 公開と保守

deployはpush/dispatch/再実行とも実際のgithub.shaをcheckoutし、公開前に同じgateを
適用します。JSON/HTML/checkpointのSHAと固定生成器の出力が一致しなければartifactを
アップロードしません。失敗時は現在の公開サイトを維持し、過去へ巻き戻しません。
保守でHTMLを再生成する場合は、必須調査完了と公開成功の両方が確認できるmain祖先とJSON2ファイルが
完全一致する場合のみ過去の検証済み掲載を再利用できます。調査JSONを書き換える
保守は新しい完了証拠が必要です。completeフラグや手動dispatchによる迂回はありません。PR #45以前の未完了公開は再公開の例外許可にしません。

Pages権限は公開jobのみ。HTTP200とHTML SHA一致、Summary/Artifactの公開記録を維持。
週次変更先はsite/index.html、site/research.json、site/search_failures.jsonだけです。
制御refのメッセージ以外に認証・workflow・Python・保護対象を週次から変更しません。
公開失敗の復旧は既存記録を参照し、取得失敗を公開成功として報告しません。

この保守PRはレビュー用でマージ・公開していません。ローカルモック、GitHub CI、
実際の次回Routine、Pages公開は別々に報告します。次回予定は11月16日07:17 JSTです。
