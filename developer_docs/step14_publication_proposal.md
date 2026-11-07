# Step 14 公開保護変更の提案・実装境界

現時点では本番公開の実装・有効化をしない。既存のAGENTS.md、保護ハッシュ、deploy.yml、docs/index.htmlは変更しない。ユーザーのStep 14指示に従い、以下の保護変更は承認待ちとして分離する。

## 今回の実装

- 公開品質に調査着手率と調査完了率を別々に記録。completeのみ完了に算入、欠落・重複・不明エリアは拒否。
- 当回のrun_id、started_at、generated_at、fetched_at、verified_at、restored_from_previous、店舗データのSHA-256を照合。generatedの日付更新だけでは鮮度を満たさない。通信監査の完了・違反なしが不明なら拒否。
- レポート出力先を.staging内に制限し、原子的JSON置換。保護対象やシンボリックリンク経由の書込みを拒否。
- publication_bundle.prepareはJSON/HTMLを再検証し、4成果物のSHA-256とrun_id・commit_sha・旧HTMLハッシュを同一manifestに束ねる。
- verifyはファイルを再ハッシュし、出典・HTML構造・当回根拠・公開品質を再検証する。
- rehearseは.staging以外を拒否する隔離公開試験専用。両フラグ、CI、実行IDとHTML/JSONハッシュに対応する承認コンテキストを要求し、原子的置換後の失敗時は旧バイト列へ復旧する。

この実装は本番Pagesクライアントを含まない。rehearseの承認コンテキストはモック試験用であり、JSONを用意しただけで信頼できる人間承認にはならない。prepareは検証済みの品質レポートを束ねるが、公開承認を発行しない。

## 方式選定と承認待ちの変更

方式A（検証済みPages Artifactの直接デプロイ）を推奨する。docsへの無条件な書込み権限を調査処理に与えずに済む。Git管理のdocsは移行前の保護された基準として保存する。

旧deploy.ymlはmain pushで常に旧120店舗Artifactをデプロイする。そのまま新経路を追加すると、research_dataだけのpushでも旧サイトへの巻き戻し競合が生じる。新経路有効化前に、旧deployをmigration ledgerの状態により停止する変更が必須。新旧は同一github-pages concurrency群を使い、旧デプロイを無効化した記録を初回承認に含める。既存固定ハッシュは単純削除せず、旧経路では維持し、新経路ではmanifestに束ねたHTML SHA-256との照合に置換する。この変更は本PRに含めない。

## 初回移行の信頼境界

初回用GitHub Environment（Required Reviewers、自己承認禁止、main制限）を別途設定する。reviewerは120→移行後店舗数・減少率、店舗/プラン一覧、未解決/failed、14エリア/駅の探索状況、プレビュー、run_id、JSON/HTMLハッシュを確認する。単なるworkflow_dispatchやCLIフラグは承認にならない。

承認待ちジョブは事前に凍結したmanifestだけを受け取り、承認後に同じrun_id、commit_sha、4ハッシュを再照合する。Environmentによる承認の確認はGitHubの保護ジョブが担う。Artifact内の自己申告approvalやquality JSONだけを信用しない。

初回成功後のみ、実際のdeployment ID・run_id・HTML/JSONハッシュ・確認済み公開URLを信頼できるledgerへ記録する。以後の週次はこの成功ledgerを検証し、当週の別manifestに対して品質・鮮度を再検証する。初回のハッシュ承認を別HTMLへ流用しない。

## 本番ジョブ設計（未接続）

1. research: contents:read。匿名GET、安全機構、当回の取得/検証receiptと通信監査、JSON・HTML・監査Artifactを保存。
2. quality: contents:read。既存validator、現行公開成果物との差、精度と網羅性を別判定、hash manifestを確定。
3. initial_publish: 必須reviewer Environment。承認対象のmanifestを再検証してからPages権限を付与。
4. weekly_publish: WEEKLY_RESEARCH_ENABLED=true、WEEKLY_PUBLICATION_ENABLED=true、成功済みmigration ledger、当週品質承認、CI、安全性、同一実行・ハッシュを全て要求。research_dataだけのpushはトリガーにしない。
5. verify: HTTP応答と公開HTMLハッシュを検証、成功時のみledger更新。失敗時は保持した直前の成功Artifactで復旧し、復旧結果もHTTP/hash照合する。

publish以外にはpages:write/id-token:writeを与えない。調査状態commitとの排他も同じ公開ledgerの基準SHA照合で検出し、force pushしない。両本番フラグはOFFのまま。

## 未完了事項

現研究エンジンはまだ当回receipt・完全な通信監査を生成していない。そのため既存2店舗はcurrent_run_evidence不合格になる。これは根拠なしに最新扱いしないための閉じたゲートであり、収集側の接続は追加実装が必要。

現品質の未解決0・全エリア完了の固定必須条件も維持している。精度の必須条件を維持しつつ、不完全網羅性の公開を認める運用基準（対象駅ごとの最低探索、重大障害率、前週差の許容と明示表示）は提案/レビューが必要。単なるしきい値緩和で今回は通さない。

本番ワークフロー、Required Reviewers設定、成功ledger、HTTP検証とPages復旧の実接続、通常週次の自動承認は未実装。今回の正常系は架空データ・隔離ディレクトリとモックだけで検証する。現在の2店舗HTMLは公開しない。
