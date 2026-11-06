# Step 9 confirmed=0 診断（修正前）

既存19ページ訪問（重複URLを含む）の監査を対象とする。分類は重複計上。

| 原因 | ページ数 |
|---|---:|
| A | 0 |
| B | 15 |
| C | 19 |
| D | 0 |
| E | 15 |
| F | 19 |
| G | 19 |
| H | 18 |
| I | 15 |
| J | 18 |

| URL | 診断分類 | 実際の昇格拒否理由 |
|---|---|---|
| https://restaurant.ikyu.com/112520/ | B,C,E,F,G,H,I | supported_plan_structure_not_found;identity_not_uniquely_matched |
| https://tabelog.com/tokyo/A1302/A130202/13226051/party/232732756/ | C,F,G | identity_not_uniquely_matched |
| https://www.tablecheck.com/en/shops/hotel-chinzanso-tokyo-jardin/reserve | C,F,G,H | identity_not_uniquely_matched |
| https://www.tablecheck.com/ja/capitolhoteltokyu-lounge | B,C,E,F,G,H,I | supported_plan_structure_not_found;identity_not_uniquely_matched |
| https://www.tablecheck.com/en/shops/palacehoteltokyo-the-palace-lounge/reserve | C,F,G,H | identity_not_uniquely_matched |
| https://restaurant.ikyu.com/101719/ | B,C,E,F,G,H,I | supported_plan_structure_not_found;identity_not_uniquely_matched |
| https://restaurant.ikyu.com/120875/ | B,C,E,F,G,H,I | supported_plan_structure_not_found;identity_not_uniquely_matched |
| https://restaurant.ikyu.com/151824/ | B,C,E,F,G,H,I | supported_plan_structure_not_found;identity_not_uniquely_matched |
| https://restaurant.ikyu.com/151564/ | B,C,E,F,G,H,I | supported_plan_structure_not_found;identity_not_uniquely_matched |
| https://restaurant.ikyu.com/102168/ | B,C,E,F,G,H,I | supported_plan_structure_not_found;identity_not_uniquely_matched |
| https://restaurant.ikyu.com/109753/ | B,C,E,F,G,H,I | supported_plan_structure_not_found;identity_not_uniquely_matched |
| https://restaurant.ikyu.com/106388/ | B,C,E,F,G,H,I | supported_plan_structure_not_found;identity_not_uniquely_matched |
| https://restaurant.ikyu.com/113312/ | B,C,E,F,G,H,I | supported_plan_structure_not_found;identity_not_uniquely_matched |
| https://restaurant.ikyu.com/108615/ | B,C,E,F,G,H,I | supported_plan_structure_not_found;identity_not_uniquely_matched |
| https://restaurant.ikyu.com/106767/ | B,C,E,F,G,H,I | supported_plan_structure_not_found;identity_not_uniquely_matched |
| https://restaurant.ikyu.com/108054/ | B,C,E,F,G,H,I | supported_plan_structure_not_found;identity_not_uniquely_matched |
| https://restaurant.ikyu.com/120847/ | B,C,E,F,G,H,I | supported_plan_structure_not_found;identity_not_uniquely_matched |
| https://www.tablecheck.com/en/hotel-edmont-beltempo | B,C,E,F,G,H,I | supported_plan_structure_not_found;identity_not_uniquely_matched |
| https://www.tablecheck.com/en/shops/hotel-chinzanso-tokyo-jardin/reserve | C,F,G,H | identity_not_uniquely_matched |

## 根本原因と仕様との照合

全19訪問が最初の店舗同一性ゲートで停止していた。TableCheckではtitle以外の施設・住所・店舗案内を読まず、テーブルの「交通手段」に駅があることを全サイトに要求していた。この駅必須条件は仕様の掲載条件にない。ホテルの同一性はホテル＋ラウンジ＋施設根拠でも検証できる。

一休は店舗概要だけを取得しており、静的本文にプランがない。TableCheckの英語メニュー、店舗情報に未対応。ジャンルが不明でも仕様「検索対象」は対象として扱い予約ページとメニューで確認するが、現行コードは明示的な日本語ジャンル完全一致を必須にしていた。これはJ（コード独自ゲート）。既存監査のidentityを再点検すると交通手段が抽出されていない18訪問に独自の駅必須条件が追加されていたため、J=18と計上した。他の同一性根拠まで十分だったという意味ではない。

research_spec.md「各店で記録する項目」「新規候補の扱い」では価格・提供期間・曜日・評価の不明を許容する。現行コードも価格/期間nullでは拒否しておらず、F/G/Hは欠測の報告であって主因ではない。validatorもnullを許容する。VAVAのイタリアン併記は真の対象外条件であり緩和しない。

初回診断のB/E/Iは構造上未検出という意味であり、実際にATがないと断定するものではない。後段の条件は先行ゲートで未評価の場合がある。改善後の実店舗・プラン別結果は別途追記する。

## 改善後の実地検証（2026-11-06 JST）

2公開ページを匿名GETで取得。予約操作0回。Jardinは施設根拠とホテル・ラウンジを照合してconfirmed=1。Palaceは説明ブロックと選択ブロックが分離し、同一プラン内のメニュー/導線を照合しきれないため未解決。価格・期間のnullは昇格を妨げなかった。

| 店舗/プラン | A〜J | 判定 |
|---|---|---|
| master-070 / クリスマスアフタヌーンティー | F,G,H | 公開文書条件適合 |
| master-010 / アフタヌーンティー "Stones" クリスマスエディション | B,E,F,G,H | 未確認 |
| master-010 / アフタヌーンティー "Stones"クリスマスエディション | B,F,G,H | 未確認 |
| master-010 / アフタヌーンティー "Stones"クリスマスエディション（グラスシャンパーニュ付き） | B,F,G,H | 未確認 |
| master-010 / 春のアフタヌーンティー "Stones" | B,E,F,G,H | 未確認 |
| master-010 / 夏のアフタヌーンティー "Stones" | E,F,G,H | 未確認 |
| master-010 / 秋のアフタヌーンティー "Stones" | E,F,G,H | 未確認 |
| master-010 / アフタヌーンティー "Stones" | B,F,G,H | 未確認 |
| master-010 / アフタヌーンティー "Stones"（グラスシャンパーニュ付き） | B,F,G,H | 未確認 |
| master-010 / 【メッセージプレート】アフタヌーンティーをご注文のお客様 | B,E,F,G,H | 未確認 |

改善後のコード別件数はページ/プランを重複計上（各行はプラン単位、ページコードはページ単位で一度だけ集計）。F/G/Hは任意項目の欠測であり掲載拒否理由ではない。

A=0, B=7, C=0, D=0, E=5, F=10, G=10, H=10, I=0, J=0

### 最小限の変更と仕様の根拠

- research_spec.md「各店で記録する項目」では価格・期間・曜日の不明を許容。既存validatorは対応済みで変更しなかった。nullでconfirmed→実HTMLを生成する回帰テストを追加。
- 同仕様「検索対象」ではジャンル不明は対象として予約ページ・メニューで確認する。未知ジャンルそのものを独自に必須化するゲートを修正。明示的な対象外ジャンルは引き続き拒否する。
- 交通手段テーブルの駅名を唯一の同一性証拠にせず、TableCheckのページタイトルと施設情報ブロックに同じホテル名・ラウンジ名があり、東京都の郵便住所も明示される場合の厳密照合を追加。階数/「ロビーラウンジ」の役割語だけを正規化。似た名前や別ラウンジは不可。
- 食べログの専用点数要素を抽出できた場合は3未満を拒否。不明はnullで保持。
- 日本語・英語の具体的メニュー表現を認識するが、英語施設名の別名対応・JSON-LD照合はまだ未実装。

### 成果物

ホテル椿山荘東京「ロビーラウンジ ル・ジャルダン」1店舗、クリスマスアフタヌーンティー1プラン。
URL: https://www.tablecheck.com/ja/shops/hotel-chinzanso-tokyo-jardin/reserve

価格は公開表示「税込サ別」のため最終税サ込価格はnull、提供期間も明示的な提供期間として確定できずstart/end=null、曜日はoff、時間はnull、評価はnull。推測計算や予約操作で補っていない。スコーンは本文メニューで確認。

JSON: .staging/step9-20261106T235406948114/data_2026-11-06.json
HTML: .staging/validated-g3bxsc4n/afternoon_tea_tokyo_2026-11-06.html
14エリア・1カード、JSONに70店を保持（confirmed1/未調査69）。候補5店は監査に未調査として保持。公開不可、公開HTML/デプロイは未変更。

86テスト中85成功・1スキップ（ローカルにnode CLIがないため）。同じJSフィルター検査を別のローカルNode実行環境で実行し、スコーン1件→ホテル解除0件→復帰1件を確認。ブラウザー/実予約サイトでの操作は行っていない。CIはNodeのある環境でこの回帰テストも実行する。

### 調査範囲の限界

今回の新規店舗確定は0。確認1店舗はエリア14（池袋・目白）で、その他13エリアは追加確認0。全エリアとも調査未完了。69マスター店と候補5店が未確認のまま残る。
優先サイトのIkyu/Tabelogは、この2ラウンジに対応する許可された探索経路が未確定で監査にunresolvedと明記した。ATが存在しないと判定しておらず、サイト優先順位を含む全店探索が完了したとは扱わない。既知のTableCheck公開文書の掲載条件確認と、先行サイトの探索完了は別の記録である。

Palaceの分離説明/選択ブロック対応、一休のランチ/朝食一覧からの正規詳細探索、多言語/構造化データからの施設照合、新店・ホテル一覧・候補調査が残る。

実HTMLの最小抜粋フィクスチャを3サイト分保存。TableCheckは実店舗昇格、食べログはVAVAの対象外ジャンル、一休は店舗概要をプランと誤認しない回帰を確認。一休の実プラン詳細フィクスチャは未整備。
