# Step 12 公開品質ゲート

`python3 -m afternoon_tea.publication_quality --data <data.json> --audit <audit.json> --html <generated.html> --report <quality_report.json>` を実行します。終了コード0は承認済み、2は公開不可です。処理はオフラインで、レポート以外のファイルを書き換えず、公開機能も持ちません。

状態は次の通りです。

- `STAGING_VALID`: JSON/HTMLの構造は検証済み。公開品質未達、公開不可。
- `REVIEW_REQUIRED`: 構造は有効で店舗候補もありますが、品質ゲート未達または初回移行の人間確認が必要。
- `APPROVED_FOR_PUBLICATION`: 全ての確認と明示的な初回移行承認を満たした場合に限ります。

設定は `data/publication_quality.json` にあります。最低確認店舗数、マスター確認率、エリア調査率、未解決率、旧サイトとの差、鮮度を個別に設定します。設定値を変えても、店舗0、マスター70件の未完了、未解決/取得失敗/未着手、14エリアの完了未確認、50%超の店舗減少、初回移行承認なし等の必須条件は解除できません。

JSON検証は既存validator、HTMLは既存HTML検査器を使います。出典、確認日、予約URL、監査状態、調査中断、テストデータ、旧公開HTMLのカード差を別々に記録します。レポートは各条件のpass/fail/evidence、指標、失敗理由を持つJSONです。予約URLへのネットワークアクセスは行いません。

## Step 11実データでの判定

2026-11-07調査JSONは14エリア・2店舗・3プラン、HTMLも2カードで構造検証を通過しました。旧サイト120カードからの減少率は98.3%、未解決76、14エリアの完全探索なし、初回移行承認なしのため`REVIEW_REQUIRED`, `publishable=false`です。レポートは `.staging/step12-quality-report.json` に生成されました。旧公開HTMLは変更していません。

テストでは架空データのみを使用し、正常な構造検証、120→2減少、ゼロ店舗、エリア欠落、古い日付、テスト目的、途中中断を検査しました。架空店舗を公開HTMLへ生成していません。
