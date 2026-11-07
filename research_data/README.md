# 永続調査データ（公開サイトへは直接使用しない）

- `state.json`：全70マスター、既存候補5店、発見したURL候補の再開可能なキュー。状態、理由、サイト順の試行、今回の検証済みJSONを保持。
- `runs/YYYY-MM-DD/snapshot.json`：その調査日のチェックポイント。翌日の調査で過去日のファイルを上書きしない。
- `evidence/SHA256.json`：公開ページのURL、確認日時、抽出した原文根拠、ページのハッシュ。ファイル名は証拠JSON自体のSHA-256。原HTMLは保存・公開しない。

同日の実行は未処理項目から再開する。翌日は前回のconfirmedもunresearchedに戻し、価格・テーマ・期間等を新しいデータへコピーしない。旧状態と失敗理由・URLは履歴に保存する。明示的な `--retry-unresolved` は同日未解決項目の再試行用。

```sh
python3 -m afternoon_tea.research_queue --limit 8 --seconds 180 --max-requests 40
python3 -m afternoon_tea.research_queue --limit 75 --seconds 600 --max-requests 180
python3 -m afternoon_tea.discovery
```

ここに含まれるデータをGitへコミットすることで次のチェックアウトに引き継ぐ。自動コミットやスケジュール実行はまだ実装していない。`.staging/` のHTML、検証レポート、一時ファイルはGitへ登録しない。保存済み確認結果を別の日の「最新確認」として流用しない。

`unresearched/confirmed/excluded/unresolved/failed` は調査キューの状態。既存HTML用JSONは旧スキーマを維持し、未確認マスターを未知値のレコードとして保持する。confirmed以外はカードに表示しない。対象外ジャンルの詳細は監査にのみ保持する。

新たに見つかった名前とURLは未照合の候補であり、新店・掲載可能店・対象エリアへの該当を確定したものではない。全14エリアの駅・ホテル・新規開業情報を網羅したデータではない。

実行入口はローカルファイルロックを取得し、同じ作業ディレクトリへの二重書き込みを拒否する。`*-audit.json` は実行別の履歴で、snapshot/stateと区別する。複数のGitHub実行間のコミット競合制御は次工程で必要。
