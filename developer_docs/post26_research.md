# PR #26監査後の調査改善

毎週の担当は引き続きClaude Code Cloud Routineです。時刻は月曜07:17 JST、環境はafternoon-tea-weeklyです。登録済みRoutineが毎回最新mainのclaude_weekly_prompt.mdを読むため、Routineの追加・再登録・スケジュール変更は不要です。この実装作業からRun nowは起動しません。

## 実行する流れ

1. 最新mainのAGENTS.md、CLAUDE.md、claude_weekly_prompt.mdを読む。
2. `python3 -m afternoon_tea.priority_research prepare` で指定134件＋未重複22件を準備する。
3. 残り時間から完成用の時間を除き、`python3 -m afternoon_tea.routine_collection --seconds 600 --max-requests 240` 等で収集する。
4. 保存HTMLを9担当・3波で解析する。サブエージェントが使えなければ同じ分担で逐次解析する。中央収集器以外から重複HTTPを送らない。
5. 確認できた内容のみをsite/research.json、未確認や制限をsite/search_failures.jsonへ記録する。
6. `python3 -m afternoon_tea.routine_enrichment` → `python3 -m afternoon_tea.weekly_review` → `python3 -m afternoon_tea.routine_renderer generate` → `python3 -m afternoon_tea.routine_site validate` を実行する。
7. site内3ファイルだけの通常PRを作成する。従来のActionsが自動マージ・Pages公開を担当する。

収集器はHTTP取得・原文保存までです。取得成功やキーワード一致でconfirmedへ昇格しません。人に毎週の承認を求めたり、店舗数・未解決数で公開を停止したりしません。

## 複数巡回と新規探索

rounds()は各エリアから未処理店舗を1件ずつ選び、2巡目・3巡目以降も時間・要求数が残る間続けます。14件という打ち切りはありません。156件の順序には前週未調査の優先順が反映されます。取得経路のない店舗はsource_neededとして保持し、アクセス済み・ATなしとは数えません。過去のresearch_dataはURLヒントだけに利用します。

収集予算の20%を最初から新規探索に割り当て、既存の公開AT一覧と、そこから発見した正規エリア一覧を実際に取得します。新しいURLは候補であって確認済み店舗ではありません。エリアはページの見出しから照合し、不明ならnullです。全14エリアの対象駅と新規ホテル・カフェ・ATの検索語をエリア別ファイルへ出力します。一覧に経路がないエリアは、Claudeが許可された公開検索で補います。取得不能なら試した方法と理由を残し、完了と偽りません。

.staging/priority-researchにcollection.json、collected-area-NN.json、pages/*.html、communication-*.jsonlを保存します。同じ実行の再開ではcollection.jsonを読み、処理済みページを再取得しません。別run_idの混在は拒否します。HTTP・時間予算の終了、例外時にも途中状態を保存します。時間上限は処理中のHTTPタイムアウト・レート制限待ちの分だけ超過し得るため、PR完成時間を別に確保します。

通信監査は各再開セグメントの要求数・違反・チェーンを保持します。operations_executed=0と評価できるのは、完全な監査がある収集器のGET通信に限ります。他ツール・手作業・Claude側の全通信まで保証しません。生HTMLや完全通信ログを週次PRへコミットせず、要約はsite/search_failures.jsonの任意フィールドへ保存できます。

## 構造化データ

routine_enrichmentはオフライン処理です。元の出典URL・確認日時・原文を残し、確認済み状態や確認日時を変更しません。

- category：IDと正式名称が一致したマスターのホテル内外を使い、category_sourceに出典とマスターの基準日を残します。ホテルの区分は今回の通常価格の最小値で9000円以上ならlux、それ以外・不明ならhotelです。同名に見える別ラウンジは推測で照合しません。
- sweets / season：プラン名・メニュー原文・根拠原文に明記された語だけを構造化します。未知を「その他」などに補いません。否定・未確認の記述からタグを追加しません。
- 曜日：平日限定・土日祝限定など、そのプランの明示条件をtrue/falseへ変換します。条件不明は未知のままです。
- price_yen：通常価格を保存し、割引価格はdiscount_price_yenへ分離します。割引率から通常価格を逆算しません。通常価格が分からない割引はprice_yen:nullです。税・サービス料条件は原文のまま残します。
- structured_evidence：各補完値にURL・元の確認日時・原文と参照フィールドを残します。抽出対象を絞っているので、取りこぼしは保存原文からClaudeが根拠付きで補います。

今回のsiteデータはPR #26の6店舗・6プランを維持し、同一実行ログに保存された原文とマスターから補完しました。新規調査や確認日の更新はしていません。レヴィータは通常9,200円（割引7,200円〜）、Momijiは通常7,345円（割引6,000円）へ訂正しています。季節・曜日フィルターの修正もデータ変更で対応し、固定CSS・JavaScript・テンプレートは変更していません。

## ティー区分の仕様改訂

ユーザーの今回の明示的な依頼によりresearch_spec.mdの一休の対象へティーを追加しました。ATのプラン名・具体的メニュー・公開ネット予約導線を同じプランで確認できることが条件です。ディナー、汎用ティー、メニュー未確認、予約ページだけの採用は引き続き不可です。extraction.py、validation.py、公開プランリンク探索、Claude指示書を同じ条件に揃えました。

AGENTS.mdには今回の人間依頼によるティー区分の改訂だけを承認済み例外として明記し、定期タスクが仕様や安全規則を変更できないことを維持しています。保護ハッシュはresearch_spec.mdの改訂値へ更新しました。店舗マスターの内容は変えず、出典SHAだけ更新しています。過去research_dataの証拠・確認日は書き換えず、当時のマスタースナップショットをdata/master_historyへ固定ハッシュ付きで保存し、履歴の検証に使用します。旧Python調査器が異なる仕様の状態を読み込む場合は、従来どおり安全に拒否します。Cloud Routineの今回のキューは新規準備されるため影響しません。

## 同じPRの重複公開

取り込みジョブの既存concurrencyに加え、PRのhead SHAをキーにしたgithub-actions[bot]の公開要求済み記録を照合します。openedの処理後にeditedが来ても、同じheadへ再dispatchしません。公開要求の直後に記録保存が失敗した場合は、同じmerge SHAのworkflow_dispatch実行履歴から復旧確認します。公開要求自体の失敗は成功記録を作らず、再試行できます。権限保護を解除しません。

GitHubのdispatchと記録保存は単一トランザクションではありません。両者の間でプロセスが停止し、Actions履歴の反映もまだない場合、厳密なexactly-onceまでは保証できません。通常のopened/edited重複はテストで1回に制限しています。公開失敗の再実行はdeploy.ymlの正規の手動再実行を使用します。

既存deploy.yml、週次スケジュール、PRの3ファイル許可リスト、予約禁止・robots・403/429・CAPTCHA・匿名GET規則は変更していません。
