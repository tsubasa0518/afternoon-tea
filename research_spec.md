# 目的
東京都心14エリアで、調査期間（下記）に提供されるアフタヌーンティー（AT）を調べ、この会話の中でHTMLファイルを1つ作成して提示する。
HTMLは手書きしない。調査結果を店ごとのデータ（data_開始日.json）にまとめ、最後に下の「HTML生成スクリプト」で作る。

# 進行状況の表示（毎回行う）
作業の最初にタスクリスト（TaskCreate）で次の10個を作り、各段階の開始時に in_progress、終了時に completed にする（TaskUpdate）。HTMLの中には進行状況を表示しない。
1. 複数エージェントで調査開始 ／ 2. 調査中 ／ 3. HTML作成 ／ 4. HTML公開 ／ 5. 検証 ／ 6. 提示 ／ 7. 未検証の候補を複数エージェントで調査 ／ 8. HTMLへデータを追記し、HTMLを再生成 ／ 9. 検証 ／ 10. 提示
- 1：サブエージェントを起動したら完了にし、2を進行中にする。2は全担当の結果がそろったら完了にする。
- 3：frag_N.json を統合して data_開始日.json を作り、スクリプトでHTMLを生成する。
- 5・9「検証」では最低限、次を確認する：①HTMLのカード数と開閉タグの一致 ②リンク先が一休.com・食べログ・TableCheckだけであること ③同じ店の重複がないこと ④スクリプトのエラーが出ていないこと。リンク先が今も開けるかは確認していない場合、その旨を報告に書く。
- 6：HTMLを会話内にファイルとして提示する（途中版）。ユーザーの返信を待たずに、そのまま7へ進む。
- 7〜10：下の「未検証の候補の調査（自動で続ける）」に従う。未検証の候補が0件なら、7〜10は「候補0件のためスキップ」と書いて完了にし、6のHTMLを最終版とする。
- 10：最終版のHTMLを会話内にファイルとして提示し、変更点レポートを出す。

# 未検証の候補の調査（自動で続ける）
- 6の後、data の candidates を candidates.json に書き出し、確認専用のサブエージェント（候補5〜6件ずつ）に分担させる。各担当は1店ずつ順番に確認する（同時アクセスを避ける。429が出たら少し待って再試行する）。
- 候補ごとに「調べる順番」どおりにページを開いて確認する。価格・期間・曜日・時間などの重要な値は、WebFetchで「該当部分を原文のまま引用して」と指示して確認する。
- 判定：promote＝予約ページを開き、調査期間内のATのプランを確認できた／drop＝ATがない・期間外のみ・席のみまたは電話予約のみ・予約ページが見つからない・デート向けでない・検索対象外のジャンル／unresolved＝接続できない等で確認を尽くしても判定できなかった（何をどこまで試したかを記録する）。
- promote の店は「店データの形式」どおりに作り（"new": true。店舗マスターの店は false）、エリア番号と分類を付けて data に追記し、candidates から外す。drop の店は candidates から外し、excluded に理由を書く。unresolved の店は candidates に残す。追記後にスクリプトを再実行して8〜10に進む。

# 調査期間
- 開始日：この調査を始めた日（日本時間）。手動でもスケジュールでも同じ。
- 終了日：開始日の40日後。終了日は暗算せず、最初にコードで計算する（例：TZ=Asia/Tokyo python3 -c "import datetime as d;s=d.datetime.now(d.timezone(d.timedelta(hours=9))).date();print(s, s+d.timedelta(days=40))"）。
- 調べる対象は、開始日から終了日までの間に1日でも提供されるATのプラン。期間の外でしか提供しないプランは記録しない。
- 期間中にテーマが替わる店は、期間内に提供されるプランをすべて、提供期間つきで記録する。
- 次のプランの内容が未発表の場合は、分かっている範囲（提供期間やテーマ名だけでも）を記録し、残りは「要確認」にする。
- 検索語の「実行した年」は開始日の年とする。期間が年をまたぐ場合は、終了日の年でも検索する。

# 入力（外部ファイルは探さない）
このプロンプト内の「店舗マスター」「未検証の候補・調査対象外」「HTML生成スクリプト」だけを使う。
Google Drive、Notion、プロジェクトのファイル、パソコン上のフォルダは検索しない。
調査対象は、店舗マスターの全店舗、「未検証の候補」、および調査中に見つけた新規候補。ただし「検索対象」の節で対象外になる店は除く。

# 予約サイト（この3つだけを扱う）
一休.com（restaurant.ikyu.com）／食べログ（tabelog.com）／TableCheck（tablecheck.com）
調べる順番（1店ずつ）：一休.com → 食べログ → TableCheck。各サイトで、ATの予約ページとメニュー（プラン内容）の両方を確認できた時点でその店の調査は終了し、後のサイトは調べない。見つからなければ次のサイトへ進み、TableCheckでも見つからなければ諦める（それ以上調査せず、記録もしない）。予約ページはあってもメニューが分からない場合は「見つからない」として次のサイトへ進む。links には、調査を終了したサイトのURLを1つだけ記録する（終了後にほかのサイトを開いて追加しない）。
一休.comでATを探すときは、ページ上部の食事帯の切り替え（ディナー／ランチ／朝食）のうち、「ランチ」と「朝食」のプランだけを対象にする。「ディナー」のプランは検索せず、開かず、記録しない。ディナーの枠でしか見つからなかったATは、一休.comでは見つからなかったものとして、次のサイト（食べログ）へ進む。この決まりは、未検証の候補の確認にも同じように使う。

# 検索対象（カフェ・ラウンジのアフタヌーンティーだけ）
検索対象は、アフタヌーンティー、カフェ、ラウンジ（カフェ、およびホテルのラウンジが提供するアフタヌーンティー）だけ。一休.com・食べログ・TableCheckのすべてで、次の料理ジャンルは検索せず、絞り込みや一覧ページにも使わない。
- 洋食系：洋食／フレンチ／イタリアン／スペイン料理／ステーキ／シュラスコ／イノベーティブ
- 和食系：和食／懐石料理／割烹／京料理／海鮮／鉄板焼き／寿司／天ぷら／すき焼き／しゃぶしゃぶ／焼き鳥／鍋／うなぎ／そば／串カツ／お好み焼き
- 中華系：中華／北京料理／上海料理／四川料理／広東料理／香港料理／飲茶
- アジア・エスニック系：焼肉／韓国料理／台湾料理／タイ料理／ベトナム料理／インド料理／地中海料理／メキシコ料理／ブラジル料理／ハワイアン／エスニック／多国籍料理
- その他：バーベキュー／居酒屋／ブッフェ／ワインバー
- 店が3サイトのいずれかで表示しているジャンルが上の一覧に当てはまる店は、店舗マスターの店も含めて対象外とし、調べない。本表にも未検証の候補にも excluded にも書かない（一切残さず、次の店へ進む）。「カフェ」「ラウンジ」「喫茶」「スイーツ」「アフタヌーンティー」と表示される店は対象。ジャンルが分からない店は対象として扱い、予約ページとメニューで確認する。

# 調査の分担（サブエージェントを使う場合）
次の単位で9つのサブエージェントに分担させ、3体ずつ3回の波で起動する（前の波の全員が終わってから次を起動）：①エリア1 ②エリア2 ③エリア3・4（第1波）／④エリア5・6 ⑤エリア7 ⑥エリア8（第2波）／⑦エリア9・10 ⑧エリア11・12 ⑨エリア13・14（第3波）。
各サブエージェントには、調査仕様（このプロンプトの該当部分）と店舗マスターを、作業フォルダのファイルに書き出して渡し、結果を担当別のJSON（frag_N.json）に保存させる。保存は最後に1回ではなく、エリアが終わるたびに追記する。各担当は最後に「確認した店数／担当の店数」を返し、親は最終報告に載せる。検索上限に近づいたら、未実施の作業の一覧を先に返すよう指示する。
親は、frag_N.json を統合して data_開始日.json を作る。統合後、各サブエージェントが報告した「未実施・未確認」を、最終報告にそのまま載せる。

# 調査の進め方（必ずこの順で行う）
ステップ1 エリア一覧でまとめて集める
エリアごとに、まず一休の「エリア名＋アフタヌーンティー」一覧ページを開き、載っている全店の店名・URL・料金・提供日を記録する。次に食べログの同じ一覧を開き、一休で確認できなかった店だけを記録する（一休で確認できた店には食べログのURLを追加しない）。店舗マスターの店にはURLを付け、店舗マスターにない店は新規候補にする。

ステップ2 足りない分だけ個別検索（上の「調べる順番」を守る）
- 一覧で見つからなかった店は、「店名＋アフタヌーンティー＋一休」→「同＋食べログ」→「同＋TableCheck」の順に各1回検索し、見つかった時点でその店の検索は終了する。
- 取得エラーのページは1回だけ再試行し、だめなら「駅名＋アフタヌーンティー」の検索に切り替える。
- 予約ページとメニューが見つからない店：TableCheckまで調べて見つからなければあきらめて次へ。店舗マスターの店なら excluded に「予約ページが見つからず」と確認日だけ書く。新規候補は何も記録しない。
- ATがない店は打ち切る：開いたページで調査期間内のATのプランがないと分かったら、次の店へ進む。店舗マスターの店なら excluded に「期間内のATなし」と確認日を書く。新規候補は何も記録しない。

ステップ3 評価
食べログの点数は、ステップ1・2で開いたページに出ていれば記録する。点数のためだけに追加の検索はしない。確認できなければ tabelog を null にする。Googleマップの評価は検索しない。
（2026-11-06 追加）食べログの点数は、データ（tabelog）には記録してよいが、HTMLのカードには表示しない。掲載条件の「食べログ3未満の除外」は、点数が確認できた店にだけ従来どおり適用する。

ステップ4 新規店の探索の残り
全エリアで「エリア名＋アフタヌーンティー＋新登場（または オープン）＋実行した年」を検索し、直近3か月のニュースやプレスリリース、調査期間中に始まる新しいプラン・新店の告知を確認する。
店舗マスターで（該当なし）になっている分類があるエリアでは、「該当なしの厳格チェック」も行う。

# 各店で記録する項目
- 営業状況：閉店・移転・掲載保留・予約停止なら本表から外し、excluded に理由と確認日を書く。期間の一部だけ休業する店は、休業期間を days_text に書く。
- 予約ページ：予約ボタン、ネット予約、予約プランがあるページを記録する。食べログは、ネット予約やコース予約のボタンがあるページだけを予約ページとする。同じサイトで店舗ページとAT専用ページの両方があれば、AT専用ページを記録する。
- ATを予約できない店（席だけ予約できる店、ATは当日のみ・予約不可の店）は記録しない（本表・未検証の候補・excluded のどれにも残さない）。
- 「予約可能日なし」「予約枠なし」などの表示は、データにもHTMLにも書かない。
- ATのプラン（調査期間内に提供されるものすべて）：プランごとに、テーマ、提供期間（開始日・終了日）、一人当たりの値段（一休の割引後ではなく通常価格・税サ込）、提供日、提供時間、時間制。確認できない項目は「要確認」。提供期間が分からないプランも記録し、start・end を null にする。
- メニュー内容（マカロン・パフェ・スコーンなど）：プラン説明や予約ページに書かれていれば、プランごとの sw に付ける。ただし、基本のセットに含まれるのか、追加料金のオプション（「〜付き」プラン）なのかを price_text か days_text に書き分ける。確認できなければ付けない（推測で付けない）。
- 駅の出口：店舗マスターの「出口」を出発点にする。［要検証］や「要確認」が付いている店は、開いたページに出口番号や徒歩分数が書かれていれば更新する。待ち合わせスポットは調べない・記録しない。
- 掲載条件（評価3以上・事前予約可・賑やかでないこと）を満たさなくなった店は除外し、理由を書く。
  - 評価：食べログの点数が確認できて3未満の店だけを除外する。確認できない店は条件を満たすものとして扱う。
  - デートに向かない店は完全に排除する：騒がしい・賑やかな店、居酒屋・バル・ビアホール・ダイニングバー・カラオケなど宴会向けの店、パーティー・推し活・誕生日向けのコンセプト店、混み合うブランチ店。これらは本表にも未検証の候補にも excluded にも書かない（一切残さない）。
- 調べるのはATのプランだけ：ランチ・ディナー・コース料理など、AT以外のメニューは調べない。目的は、アフタヌーンティーというスイーツのメニューを調べることである。
- 最寄り駅が一覧にない店も、いちばん近いエリアのカードとして載せる。station には実際の最寄り駅を書く。

# 新規候補の扱い
- ATを予約制で提供している店が店舗マスターにない場合は新規候補とし、既存店と同じ項目を記録する。
- 予約ページを開いてATの提供を確認できた店だけを本表に追加し、"new" を true にする（検索結果の抜粋だけで本表に追加しない）。
- 本表に載せてよい店：提供期間・曜日・静かさ・食べログの点数が分からない店、コースとしてだけ提供される店。分からない点は notes.status にだけ書く。
- 「未検証の候補」（candidates）にするのは、ATの提供を検索結果の抜粋でしか確認できない店だけ。確認できた点とできなかった点を note に書く。url には見つかったAT専用ページ（なければ店舗ページ）を1つ入れる。
- 分類：ホテル（高級）＝ホテル内の店で、ATの一人当たりの値段（一番安いプラン）が9,000円以上。ホテル＝ホテル内の店で、9,000円未満または不明。カフェ＝ホテル内にない店。ホテル内の店は hotel・lux のどちらに入れてもよく、スクリプトが自動で振り分ける。

# 該当なしの厳格チェック
店舗マスターで（該当なし）になっているエリアと分類は、毎回本当に店がないかを厳しく確認する。
- 一覧（一休・食べログ）と、食べログの「駅名＋アフタヌーンティー」検索を行う。
- ホテルの分類では、「エリア名＋ホテル 一覧」と「エリア名＋ホテル＋開業＋実行した年」でホテルを洗い出し、1軒ずつ「調べる順番」（一休.com → 食べログ → TableCheck。見つかった時点で終了）でATの有無を確認する。
- すべて行っても条件を満たす店がない場合にだけ status を "none" にする。途中までなら "unchecked" にし、確認できなかった探し方を確認状況に書く。

# テーマ国（プランごとの country・cc）
プランごとに country に国名、cc に国旗コード（jp／gb／fr／it／ma／cn。ほかの国は cc を null にして国名のみ）を入れる。
- プラン名・説明に国が明記されていれば、それに従う。
- 直接の記載がない場合は、テーマ名・メニュー内容・店のコンセプトなどから推測して入れてよい。
- 推測で入れたプランは、notes.status に「店名・プラン名・推測した国・根拠」を書く（HTMLには表示されない）。
- 根拠がまったく見当たらない場合は、無理に入れず両方 null にする（何も表示しない）。

# スイーツ・イベントの分類（プランごとの sw に英字で入れる。複数可）
【スイーツの行】テーマ名・メニュー説明に含まれる言葉で付ける。
ichigo＝いちご／melon＝メロン／peach＝桃／mango＝マンゴー／grape＝ぶどう・マスカット／kuri＝栗・マロン／imo＝芋・かぼちゃ／kaki＝柿・洋梨・いちじく／citrus＝柑橘／choco＝チョコレート／wa＝抹茶・和／macaron＝マカロン／parfait＝パフェ／scone＝スコーン／other＝その他・テーマ未確認
【イベント／季節の行】
halloween＝ハロウィン／xmas＝クリスマス／valentine＝バレンタイン／whiteday＝ホワイトデー／collab＝コラボ企画（「コラボ」「コラボレーション」と明記されたものだけ。ブランド名だけでは付けない）／season＝季節の味覚（果実名のない季節テーマ。果実名の分類が付く場合は付けない）
- 重なる分類は、根拠があれば両方付けてよい。

# データファイル data_開始日.json の形式
{
  "generated": "YYYY-MM-DD（調査した日）",
  "period": {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD（開始日の40日後）"},
  "areas": [
    {"no": 1, "name": "丸の内・日本橋", "cats": {
      "cafe":  {"status": "ok", "shops": [ 店データ, ... ]},
      "hotel": {"status": "ok", "shops": [ ... ]},
      "lux":   {"status": "ok", "shops": [ ... ]}
    }}
    （14エリアすべて。店がない分類は shops を [] にし、status を "none" か "unchecked" にする）
  ],
  "candidates": [{"area": "中目黒", "name": "店名", "url": "https://...（なければ省略）", "note": "確認できた点・できなかった点"}],
  "excluded":   [{"name": "店名", "reason": "理由と確認日"}],
  "notes": {"status": "確認状況：未確認事項、資料間の食い違い、検索結果の抜粋だけで確認した情報、推測で入れたテーマ国、調査できなかった店"}
}
店データの形式：
{
  "name": "h4に出す名前（ホテル内の店はホテル名だけ）",
  "shop": "ホテル内の店舗名。カフェは null",
  "station": "最寄り駅", "exit": "駅の出口（［要検証］はそのまま）",
  "links": [{"site": "ik", "url": "https://..."}],   ← site は ik／tb／tc だけ
  "links_note": "予約ページが1つも見つからないときの説明（任意）",
  "plans": [
    {
      "theme": "ATのテーマ（不明なら null）",
      "start": "2026-10-01", "end": "2026-10-31",   ← 不明なら null（期間外のプランを入れるとスクリプトがエラー）
      "period_text": null,
      "sw": ["halloween", "kuri"],
      "country": null, "cc": null,
      "price_min": 7900,
      "price_text": "7,900円（平日）／8,400円（土日祝）",
      "wd": "on", "we": "on",   ← on／no／off（要確認）
      "days_text": "毎日", "time_text": "2時間制。入店13:00〜18:00"
    }
  ],
  "tabelog": 3.58,
  "new": false
}

# 出力
1. 調査がすべて終わったら、下の「HTML生成スクリプト」を作業フォルダに build_html.py として保存し、一字も変えずに「python3 build_html.py data_開始日.json」で実行する。「データに誤りがあります」と表示されたらデータを直して再実行する。（このスクリプトは、カードに食べログ点数を表示しない版である。）
2. できた afternoon_tea_tokyo_開始日.html を、この会話の中でファイルとして提示する。
3. 変更点レポート（10の最終版の提示時に会話に出力）：新規に追加した店と見つけた経路／未検証の候補に加えた店と確認できなかった条件／「該当なし」の各分類の確認と結果／店ごとの予約サイト数／調査期間／期間中にテーマが替わる店と切り替え日／値段・テーマ・提供日の変更／閉店・掲載保留・AT提供なしで外した店と理由（賑やかな店は載せない）／確認できなかった店と項目／駅の出口の変更。データの notes と除外店の一覧は、HTMLには表示せず、このレポートで出す。

# 厳守事項
- 出典・URL・値段・評価を捏造しない。URLは検索結果に出たか、開いて確認できたものだけを記録する。確認できないものは「要確認」または［要検証］とする。
- 最後まで全店・全エリアの調査をやり切る。作業量が多いことを理由に、店やエリアを省略しない。1つの店の予約ページを、決められた順番を超えて探し続けることはしない。
- 外的な理由で続けられなくなった場合に限り、そこまでのデータでHTMLを生成して提示する。未調査の店は店舗マスターの内容だけを入れ、links は空、links_note を「未調査」、price_min は null、wd・we は off とし、未調査の店名と未確認のエリア・分類を確認状況に列挙する。
- 出力は日本語。

# 店舗マスター（2026年10月2日時点）
# 対象エリアと駅
1 丸の内・日本橋：東京、大手町、二重橋前、日本橋、三越前、京橋
2 銀座・有楽町・日比谷：銀座、銀座一丁目、有楽町、日比谷、東銀座
3 新橋・汐留・浜松町：新橋、汐留、浜松町、大門、御成門、竹芝、芝公園
4 赤坂・永田町・虎ノ門：赤坂、赤坂見附、永田町、虎ノ門、虎ノ門ヒルズ、溜池山王、国会議事堂前
5 六本木・麻布・広尾：六本木、六本木一丁目、神谷町、麻布十番、広尾
6 新宿・代々木：新宿、新宿三丁目、西新宿、都庁前、南新宿、代々木、西武新宿
7 渋谷・代々木公園：渋谷、神泉、代々木公園、代々木八幡
8 青山・表参道・原宿：表参道、外苑前、青山一丁目、明治神宮前、原宿
9 恵比寿・代官山・中目黒：恵比寿、代官山、中目黒
10 品川・田町・五反田：品川、高輪ゲートウェイ、田町、三田、五反田、大崎、白金台
11 上野・浅草・押上：上野、御徒町、浅草、田原町、押上、とうきょうスカイツリー
12 水道橋・御茶ノ水・神田：水道橋、後楽園、御茶ノ水、神田、淡路町
13 飯田橋・神楽坂・四ツ谷：飯田橋、神楽坂、牛込神楽坂、四ツ谷、市ケ谷、早稲田
14 池袋・目白：池袋、目白、東池袋、江戸川橋

# 店舗マスター（店名｜駅｜出口）
【1 丸の内・日本橋｜カフェ】
- cafe VAVA（日本橋髙島屋S.C. 新館3F）｜日本橋駅｜日本橋駅 B4出口（日本橋髙島屋S.C.に直結）／東京駅 八重洲北口（徒歩5分）
- ROSSINI TERRACE（東京會舘）｜二重橋前駅｜二重橋前駅 B5出口（地下通路でビル直結）／東京駅（徒歩3分）
- レゾナンス（東京ビルTOKIA 2F）｜東京駅｜東京駅 丸の内南口（徒歩2分）
【1｜ホテル】
- 丸ノ内ホテル 8F（ポム・ダダン）｜東京駅｜東京駅 丸の内北口（徒歩1分。OAZO側の丸ノ内ホテル専用入口から7Fフロント経由で8F）
【1｜ホテル（高級）】
- フォーシーズンズホテル東京大手町（THE LOUNGE）｜大手町駅｜大手町駅 C4出口（直結）
- 東京ステーションホテル（ロビーラウンジ）｜東京駅｜東京駅 丸の内南口（ホテル直結）
- 東京ステーションホテル 2F（カメリア）｜東京駅｜東京駅 丸の内南口（徒歩1分）
- マンダリン オリエンタル 東京（オリエンタルラウンジ）｜三越前駅｜三越前駅 A7出口（直結）
- シャングリ・ラ 東京（ザ・ロビーラウンジ）｜東京駅｜東京駅 八重洲北口（徒歩2分）
- パレスホテル東京 1F（ザ パレス ラウンジ）｜大手町駅・二重橋前駅｜大手町駅 C13b出口（地下通路で直結）／東京駅 丸の内北口（徒歩8分）
- アマン東京 33F（ザ・ラウンジ by アマン）｜大手町駅｜大手町駅（東西線 西口改札前から地下通路で直結）
- パレスホテル東京 6F（ラウンジバー プリヴェ）｜大手町駅・二重橋前駅｜大手町駅 C13b出口（地下通路で直結）／東京駅 丸の内北口（徒歩8分）

【2 銀座・有楽町・日比谷｜カフェ】
- ロイヤルクリスタルカフェ 銀座店（B1F）｜銀座駅｜銀座駅（徒歩1〜3分。並木通り沿い）
- GINZA TENSHODO CAFE（天賞堂カフェ）｜銀座一丁目駅｜銀座一丁目駅（徒歩1分）／有楽町駅（徒歩3分）
- REIKASAI GINZA（ポーラ銀座ビル 9F）｜銀座一丁目駅｜銀座一丁目駅 7番出口（すぐ）
- ボン ボヌール（銀座三越 4F）｜銀座駅｜銀座駅 A7出口すぐ（銀座三越4F）
- ザ・グラン ラウンジ（GINZA SIX 13F）｜銀座駅｜銀座駅 A2・B2出口付近の直通通路からGINZA SIXへ（13F）
- HIGASHIYA GINZA（ポーラ銀座ビル 2F）｜銀座一丁目駅｜銀座一丁目駅 7番出口（地上すぐ）
- アルマーニ リストランテ（アルマーニ銀座タワー 10F）｜銀座駅｜銀座駅 B3出口（直結）
- LOUANGE TOKYO Le Musée｜銀座一丁目駅｜銀座一丁目駅（徒歩1分）
【2｜ホテル】
- ミレニアム 三井ガーデンホテル 東京 B1F（現代里山料理 ZEN HOUSE）｜東銀座駅｜東銀座駅（徒歩約2分。出口番号は要確認）
- ハイアット セントリック 銀座 東京 3F（NAMIKI667）｜銀座駅｜銀座駅 B5出口（徒歩約3分）
- 三井ガーデンホテル銀座プレミア 16F（RISTORANTE E'VOLTA il cielo）｜東銀座駅｜銀座駅 A3出口（徒歩約7分）
【2｜ホテル（高級）】
- ザ・ペニンシュラ東京（ザ・ロビー）｜日比谷駅・有楽町駅｜日比谷駅・有楽町駅 地下通路 A6・A7出口（徒歩0分）
- 帝国ホテル 東京（インペリアルラウンジ アクア）｜日比谷駅｜日比谷駅（出口番号は要確認）

【3 新橋・汐留・浜松町｜カフェ】（該当なし）
【3｜ホテル】
- ザ ロイヤルパーク キャンバス 銀座8 14F（Opuses）｜新橋駅｜銀座駅 A4出口（徒歩約5分）／新橋駅（徒歩5分）
- ザ・プリンス パークタワー東京（ロビーラウンジ）｜大門駅・御成門駅｜芝公園駅／赤羽橋駅［要検証］
- ホテル インターコンチネンタル 東京ベイ（ニューヨーク ラウンジ）｜竹芝駅｜竹芝駅［要検証］
【3｜ホテル（高級）】
- コンラッド東京（トゥエンティエイト）｜汐留駅｜汐留駅（直結。出口番号は要確認）／新橋駅
- フェアモント東京（Vue Mer）｜竹芝駅｜竹芝駅／浜松町駅［要検証］

【4 赤坂・永田町・虎ノ門｜カフェ】（該当なし）
【4｜ホテル】（該当なし）
【4｜ホテル（高級）】
- ザ・プリンスギャラリー 東京紀尾井町（レヴィータ）｜赤坂見附駅・永田町駅｜赤坂見附駅／永田町駅［要検証］
- アンダーズ 東京（ザ タヴァン グリル＆ラウンジ）｜虎ノ門ヒルズ駅｜虎ノ門ヒルズ駅［要検証］

【5 六本木・麻布・広尾｜カフェ】
- Restaurant THE MOON｜六本木駅｜六本木駅 1C出口（日比谷線、コンコース直結）
【5｜ホテル】（該当なし）
【5｜ホテル（高級）】
- ジャヌ東京（ジャヌ ラウンジ＆ガーデンテラス）｜六本木一丁目駅・神谷町駅｜神谷町駅（麻布台ヒルズ方面の出口）［要検証］
- ザ・リッツ・カールトン東京 45F（ザ・ロビーラウンジ）｜六本木駅｜六本木駅（東京ミッドタウン直結）［要検証］

【6 新宿・代々木｜カフェ】（該当なし）
【6｜ホテル】
- 小田急ホテルセンチュリーサザンタワー（ラウンジ サウスコート）｜新宿駅・南新宿駅｜新宿駅 南口（南改札から徒歩3分）
- 新宿プリンスホテル 25F（和風ダイニング＆バー FUGA）｜新宿駅｜西武新宿駅（直結）［要検証］
【6｜ホテル（高級）】
- パーク ハイアット 東京（ピーク ラウンジ）｜西新宿駅｜都庁前駅（徒歩約7分）

【7 渋谷・代々木公園｜カフェ】
- Legato（E・スペースタワー 15F）｜神泉駅｜渋谷駅（徒歩5分）／神泉駅
- ザ・レギャン・トーキョー（cocotiビル 12F）｜渋谷駅｜渋谷駅（すぐ）
【7｜ホテル】
- セルリアンタワー東急ホテル（ガーデンラウンジ 坐忘）｜渋谷駅・神泉駅｜渋谷駅（出口は要確認）／神泉駅
- セルリアンタワー東急ホテル 40F（タワーズバー ベロビスト）｜渋谷駅｜渋谷駅（出口は要確認）／神泉駅
- 渋谷エクセルホテル東急 5F（エスタシオン カフェ）｜渋谷駅｜渋谷駅直結（渋谷マークシティ イースト内）
【7｜ホテル（高級）】（該当なし）

【8 青山・表参道・原宿｜カフェ】
- サロン ド テ ジャンナッツ｜表参道駅｜表参道駅（徒歩7分）
- A to Z cafe（equboビル 5F）｜表参道駅｜表参道駅（徒歩5分。骨董通り方面）
- カフェ＆ダイニング ゼルコヴァ（ザ ストリングス 表参道）｜表参道駅｜表参道駅（直結）
- IL LUPINO PRIME（ののあおやま 2F）｜表参道駅｜表参道駅（出口は要確認）
- ブルー・ブリック・ラウンジ（ヨックモック青山本店）｜表参道駅｜表参道駅（出口は要確認）
- TAVERN by the green（ザ ストリングス 表参道 2F）｜表参道駅｜表参道駅（直結）
- HAUTE COUTURE CAFE OMOTESANDO｜表参道駅｜表参道駅（徒歩2分）
【8｜ホテル】
- THE AOYAMA GRAND HOTEL（TOKYO AFTERNOON TEA）｜外苑前駅｜外苑前駅 3番出口（徒歩3分）
【8｜ホテル（高級）】（該当なし）

【9 恵比寿・代官山・中目黒｜カフェ】
- PAYSAGE 代官山本店｜代官山駅｜代官山駅（約100m）
- カフェ アクイーユ 恵比寿店｜恵比寿駅｜恵比寿駅 西口（徒歩4分）
- ROTISSERIE★BLUE（恵比寿ガーデンプレイスタワー 39F）｜恵比寿駅｜恵比寿駅 東口（恵比寿スカイウォーク経由）［要検証］
- マディソン ニューヨーク キッチン｜恵比寿駅｜恵比寿駅 西口（徒歩2分）
- 336 ébisu（クーカイ・テラス 1F）｜恵比寿駅｜恵比寿駅（恵比寿スカイウォーク出口から徒歩10分）
【9｜ホテル】
- ウェスティンホテル東京（ザ・ラウンジ）｜恵比寿駅｜恵比寿駅 東口（恵比寿スカイウォーク経由）［要検証］
【9｜ホテル（高級）】（該当なし）

【10 品川・田町・五反田｜カフェ】（該当なし）
【10｜ホテル】
- グランドプリンスホテル新高輪（Lounge Momiji）｜品川駅｜品川駅 高輪口［要検証］
- 東京マリオットホテル（Lounge & Dining G）｜品川駅｜品川駅 高輪口［要検証］
- シェラトン都ホテル東京（バンブー）｜白金台駅｜白金台駅［要検証］
- THE Tender HOUSE DINING｜白金台駅｜白金台駅［要検証］（ホテル内かカフェかは調査時に確認して分類）
- ALL DAY DINING FUDO｜白金台駅｜白金台駅［要検証］（ホテル内かカフェかは調査時に確認して分類）
【10｜ホテル（高級）】（該当なし）

【11 上野・浅草・押上｜カフェ】
- ラ・ラナリータ 吾妻橋店（アサヒビル 22F）｜浅草駅｜浅草駅（吾妻橋方面の出口）［要検証］
【11｜ホテル】
- 浅草ビューホテル 28F（THE TOP BAR Hanabi）｜浅草駅・田原町駅｜浅草駅（つくばエクスプレス）［要検証］
【11｜ホテル（高級）】（該当なし）

【12 水道橋・御茶ノ水・神田｜カフェ】（該当なし）
【12｜ホテル】
- 東京ドームホテル 43F（アーティスト カフェ）｜水道橋駅・後楽園駅｜水道橋駅［要検証］／後楽園駅
【12｜ホテル（高級）】（該当なし）

【13 飯田橋・神楽坂・四ツ谷｜カフェ】
- SOMBREUIL TOKYO｜飯田橋駅｜飯田橋駅［要検証］
【13｜ホテル】
- ホテルメトロポリタン エドモント（ベルテンポ）｜飯田橋駅｜飯田橋駅［要検証］
- リーガロイヤルホテル東京（ガーデンラウンジ）｜早稲田駅｜早稲田駅［要検証］
【13｜ホテル（高級）】（該当なし）

【14 池袋・目白｜カフェ】（該当なし）
【14｜ホテル】
- ホテルメトロポリタン 25F（ダイニング＆バー オーヴェスト）｜池袋駅｜池袋駅［要検証］
【14｜ホテル（高級）】
- ホテル椿山荘東京（ロビーラウンジ ル・ジャルダン）｜江戸川橋駅｜江戸川橋駅 1a出口（徒歩約10分）／目白駅から都営バス約10分

# 未検証の候補（前回条件未確認。今回ATの予約ページがあれば本表へ）
- 中目黒：HAUTE COUTURE CAFE（中目黒・目黒川沿い）
- 上野：Bistro NOHGA（NOHGA HOTEL）／ラ ココリコ 上野本店
- 新宿：ZATTA（ヒルトン東京）／District（キンプトン新宿東京）

# 調査対象外（調べない。HTML・データに一切出さない）
bills 銀座／NEWLIGHT（渋谷）／マーサーブランチ全店／CE LA VI TOKYO／Serafina NEW YORK／古城の国のアリス／SPANISH LOUNGE PARADOR／latte All day diner／Gallery11（ホテルインディゴ東京渋谷）／boB the garden Ginza／THE GREY ROOM／Banksia／Wattle Tokyo／mood board／168点心飲茶／HARNEY&SONS OMOTESANDO

# HTML生成スクリプト（build_html.py として保存し、一字も変えずに使う。カードに食べログ点数を表示しない版）

```python
import json, sys, re, html, datetime

# ===== 使い方 =====
# python3 build_html.py data_開始日.json
# → afternoon_tea_tokyo_開始日.html を同じフォルダに作る。このスクリプトは変更しない。

CSS = r""":root{--bg:#EEF1F4;--paper:#FFFFFF;--ink:#1C2733;--sub:#5E6B78;--mute:#98A3AE;--line:#DCE2E8;
--hotel:#2F5D86;--hotel-t:#E4EDF5;--lux:#8F6C22;--lux-t:#F4EDDC;--cafe:#4F6F55;--cafe-t:#E3EDE4;--ok:#2E6B4F;--ok-t:#DCEFE4;--no:#9AA3AC;
box-sizing:border-box;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#12181E;--paper:#1A222B;--ink:#E6EBF0;--sub:#A4AFBA;--mute:#6D7985;--line:#2B3540;
--hotel:#8DB4D8;--hotel-t:#1F2E3C;--lux:#D9B770;--lux-t:#35301F;--cafe:#9EC3A3;--cafe-t:#1F3024;--ok:#8FD1AE;--ok-t:#1E3629;--no:#5F6B76}}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:calc(env(safe-area-inset-top,0px) + 16px)}
body{margin:0;background:var(--bg);color:var(--ink);font-family:"Noto Sans JP","Hiragino Sans","Yu Gothic",sans-serif;font-size:15px;line-height:1.7}
.hero{background:var(--paper);border-bottom:1px solid var(--line)}
.hero-in{max-width:1120px;margin:0 auto;padding:44px 24px 28px;display:grid;grid-template-columns:1.5fr 1fr;gap:32px;align-items:end}
h1{font-family:"Zen Old Mincho","Hiragino Mincho ProN",serif;font-size:clamp(26px,3.4vw,40px);word-break:keep-all;line-height:1.25;margin:0 0 10px;letter-spacing:.03em}
.lead{color:var(--sub);margin:0;max-width:62ch}
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}
.stat{border-radius:12px;padding:12px 14px}.stat b{display:block;font-size:26px;font-family:"Zen Old Mincho",serif;line-height:1.2}.stat span{font-size:13px}
.s-hotel{background:var(--hotel-t);color:var(--hotel)}.s-lux{background:var(--lux-t);color:var(--lux)}.s-cafe{background:var(--cafe-t);color:var(--cafe)}
.fpanel{background:var(--paper);border-bottom:1px solid var(--line)}.fpanel-in{max-width:1120px;margin:0 auto;padding:14px 24px 16px;display:flex;flex-direction:column;gap:10px}
.frow{display:grid;grid-template-columns:5.5em 1fr;gap:8px 10px;align-items:start}.frow .lb{font-size:12.5px;color:var(--sub);padding-top:6px;white-space:nowrap}
.btns{display:grid;grid-template-columns:repeat(auto-fill,minmax(max(128px,calc((100% - 32px) / 5)),1fr));gap:8px}
.frow .hint{grid-column:2;color:var(--mute);font-size:11.5px;margin:-2px 0 0}
.totop{position:fixed;right:16px;bottom:calc(env(safe-area-inset-bottom,0px) + 16px);z-index:10;font-size:12.5px;font-weight:700;text-decoration:none;color:var(--ink);background:var(--paper);border:1.5px solid var(--line);border-radius:999px;padding:7px 14px;box-shadow:0 2px 8px rgba(0,0,0,.18);display:none}.totop.show{display:block}
.fb{font:inherit;font-size:13px;line-height:1.4;border:1.5px solid var(--line);background:var(--paper);color:var(--ink);border-radius:999px;padding:5px 8px;cursor:pointer;text-align:center;min-width:0;white-space:nowrap}
.fb[aria-pressed="true"]{border-color:currentColor;font-weight:700}
.fb.f-hotel[aria-pressed="true"]{color:var(--hotel);background:var(--hotel-t)}.fb.f-lux[aria-pressed="true"]{color:var(--lux);background:var(--lux-t)}.fb.f-cafe[aria-pressed="true"]{color:var(--cafe);background:var(--cafe-t)}
.fb.f-x[aria-pressed="true"]{color:var(--ok);background:var(--ok-t)}
.legendline{margin-top:12px;font-size:12.5px;display:flex;flex-wrap:wrap;gap:6px 16px;align-items:center}.lg{white-space:nowrap;display:inline-flex;gap:6px;align-items:center}
.area-btn{color:var(--ink);text-decoration:none;font-size:13px;line-height:1.4;border:1.5px solid var(--line);background:var(--paper);border-radius:10px;padding:5px 8px;display:flex;gap:6px;align-items:center;justify-content:center;text-align:center;min-width:0;word-break:keep-all}
.area-btn:hover{border-color:var(--ink);background:var(--bg)}
button:focus-visible,a:focus-visible{outline:2px solid var(--hotel);outline-offset:2px}
main{max-width:1120px;margin:0 auto;padding:12px 24px 72px}
.area{margin-top:40px}
h2{font-family:"Zen Old Mincho",serif;font-size:26px;margin:0 0 6px;display:flex;align-items:baseline;gap:14px}
h2 .no{font-family:"Noto Sans JP",sans-serif;font-size:14px;color:var(--mute);font-weight:500}h2 .acnt{font-size:13px;color:var(--sub);font-family:"Noto Sans JP",sans-serif;font-weight:400}
.cat{margin:14px 0 8px}.cat.hide{display:none}
h3{margin:0 0 10px;display:flex;align-items:center;gap:10px;font-size:14px}
.tag{padding:2px 12px;border-radius:999px;font-weight:700}
.c-hotel .tag{background:var(--hotel-t);color:var(--hotel)}.c-lux .tag{background:var(--lux-t);color:var(--lux)}.c-cafe .tag{background:var(--cafe-t);color:var(--cafe)}
.cnt{color:var(--sub);font-weight:400;font-size:13px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:14px}
.card{background:var(--paper);border:1px solid var(--line);border-radius:14px;padding:18px 18px 14px;display:flex;flex-direction:column;gap:8px;position:relative;overflow:hidden}.top{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}
.card::before{content:"";position:absolute;inset:0 0 auto 0;height:4px}
.c-hotel .card::before,.card.c-hotel::before{background:var(--hotel)}.card.c-lux::before{background:var(--lux)}.card.c-cafe::before{background:var(--cafe)}
.card.hide{display:none}
.card header{min-width:0}
h4{margin:0;font-size:16.5px;line-height:1.45;font-family:"Zen Old Mincho",serif}

.shop{margin:1px 0 0;font-size:13px;color:var(--sub)}
.rnote{margin:-2px 0 0;font-size:11.5px;color:var(--mute)}
.loc,.theme,.time{margin:0;display:flex;gap:6px;align-items:flex-start;font-size:13.5px}
.loc{color:var(--sub)}
svg{width:15px;height:15px;flex:none;margin-top:3px;color:var(--mute)}.theme svg{width:17px;height:17px;margin-top:2px}
.price{border-top:1px dashed var(--line);padding-top:10px;display:flex;flex-direction:column}
.pbig{font-size:24px;font-weight:700;font-variant-numeric:tabular-nums;line-height:1.2}.pbig small{font-size:13px;font-weight:500;margin-left:2px}
.pdet{font-size:12.5px;color:var(--sub)}
.plans{display:flex;flex-direction:column;gap:10px;margin-top:auto}
.plan{--pc:var(--hotel);--pt:var(--hotel-t);display:flex;flex-direction:column;gap:6px;background:var(--pt);border:1px solid var(--line);border-left:5px solid var(--pc);border-radius:12px;padding:10px 12px 12px}
.card.c-lux .plan{--pc:var(--lux);--pt:var(--lux-t)}.card.c-cafe .plan{--pc:var(--cafe);--pt:var(--cafe-t)}
.plan .price{border-top:0;padding-top:0}.plan .when{margin-top:0;background:var(--paper)}.plan .theme{font-weight:700}.plan .theme svg{color:var(--pc)}
.plan-hd{display:flex;flex-wrap:wrap;align-items:center;gap:6px}
.pno{font-size:11.5px;font-weight:700;color:var(--paper);background:var(--pc);border-radius:999px;padding:1px 9px;white-space:nowrap}
.pper{margin:0;font-size:12.5px;font-weight:700;color:var(--pc);font-variant-numeric:tabular-nums}.pper.na{color:var(--sub);font-weight:500}
.pst{font-size:11px;font-weight:700;border-radius:999px;padding:0 8px;white-space:nowrap}.pst.now{background:var(--ok-t);color:var(--ok)}.pst.soon{color:var(--sub);border:1px dashed var(--mute)}
.period{margin:0 0 8px;font-size:clamp(17px,2vw,21px);font-weight:700;font-variant-numeric:tabular-nums}.period small{font-size:13px;font-weight:500;color:var(--sub);margin-left:4px}
.when{margin-top:auto;background:var(--bg);border-radius:10px;padding:9px 11px}
.chips{display:flex;gap:6px}
.chip{font-size:12px;font-weight:700;padding:1px 10px;border-radius:999px}
.chip.on{background:var(--ok-t);color:var(--ok)}.chip.no{color:var(--no);text-decoration:line-through;background:transparent;border:1px solid var(--line)}.chip.off{color:var(--mute);border:1px dashed var(--mute)}
.dtxt{margin:5px 0 3px;font-size:12.5px;color:var(--sub)}
.time{font-size:13px}
.meet{border:1px solid var(--line);border-radius:10px;padding:8px 11px;font-size:13px}.meet p{margin:0;display:flex;gap:8px;align-items:baseline}.meet p+p{margin-top:3px}
.mk{flex:none;font-size:11px;font-weight:700;color:var(--paper);background:var(--sub);border-radius:5px;padding:0 6px;line-height:1.7}
.vf{font-size:10.5px;color:#B5542B;border:1px solid #B5542B;border-radius:4px;padding:0 4px;margin:0 3px;white-space:nowrap}
.fb .bc{font-size:11px;color:var(--mute);margin-left:5px;font-weight:400}
.swt{margin:-2px 0 0;padding-left:23px;display:flex;flex-wrap:wrap;gap:4px}.swt span{font-size:11.5px;line-height:1.6;padding:0 8px;border-radius:999px;background:var(--bg);color:var(--sub);border:1px solid var(--line)}
.links{display:flex;flex-wrap:wrap;gap:6px;padding-left:23px}
.lk{display:inline-flex;align-items:center;gap:4px;font-size:12.5px;font-weight:500;text-decoration:none;color:var(--ink);border:1px solid var(--line);background:var(--paper);border-radius:8px;padding:3px 9px;transition:border-color .15s,background .15s}
.lk svg{width:11px;height:11px;margin:0;color:var(--mute)}.lk:hover{border-color:var(--ink);background:var(--bg)}
.lk-ik{border-left:3px solid #C9A33A}.lk-tb{border-left:3px solid #D0643A}.lk-tc{border-left:3px solid #2B8A8A}
.none{margin:0;padding:14px 16px;border:1px dashed var(--line);border-radius:12px;color:var(--sub);font-size:14px}
.aside{margin-top:64px;display:grid;grid-template-columns:1fr;gap:24px}
.box{min-width:0;overflow-wrap:anywhere;background:var(--paper);border:1px solid var(--line);border-radius:14px;padding:18px 20px}
.clink{color:var(--hotel);text-decoration:underline;text-underline-offset:2px;display:inline-flex;align-items:center;gap:3px}.clink svg{width:11px;height:11px;margin:0;color:currentColor}.clink:hover{text-decoration-thickness:2px}
.box h2{font-size:19px}.box ul{list-style:none;margin:0;padding:0}.box li{padding:8px 0;border-top:1px solid var(--line);font-size:14px}.box li:first-child{border-top:0}
@media (max-width:820px){.hero-in{grid-template-columns:1fr}.aside{grid-template-columns:1fr}}
@media (max-width:420px){.grid{grid-template-columns:1fr}.hero-in,.fpanel-in,main{padding-left:16px;padding-right:16px}.frow{grid-template-columns:4em 1fr}.fb{white-space:normal}.btns{grid-template-columns:repeat(auto-fill,minmax(max(118px,calc((100% - 32px) / 5)),1fr))}}
@media (prefers-reduced-motion:reduce){html{scroll-behavior:auto}.lk{transition:none}}
.ctry{margin:0;padding-left:23px;display:flex;align-items:center;gap:6px;font-size:13px;font-weight:700;color:var(--ink)}.ctry svg{width:24px;height:16px;margin:0;border-radius:2px;box-shadow:0 0 0 1px var(--line)}
@media print{.totop{display:none}}"""
JS = r"""const st={cat:{hotel:true,lux:true,cafe:true},x:{wd:false,we:false,pk:false},sw:new Set()};
function apply(){
 document.querySelectorAll('.card').forEach(c=>{let ok=st.cat[c.dataset.cat];
  if(st.x.wd&&c.dataset.wd!=="1")ok=false; if(st.x.we&&c.dataset.we!=="1")ok=false; if(st.x.pk&&c.dataset.pk!=="1")ok=false;
  if(st.sw.size&&!(c.dataset.sw||"").split(" ").some(t=>st.sw.has(t)))ok=false;
  c.classList.toggle('hide',!ok);});
 document.querySelectorAll('.cat').forEach(b=>{const on=st.cat[b.dataset.cat];b.classList.toggle('hide',!on);
  const vis=b.querySelectorAll('.card:not(.hide)').length;const cn=b.querySelector('.cnt');if(cn)cn.textContent=vis+'件';});
}
document.querySelectorAll('.fb').forEach(b=>b.addEventListener('click',()=>{const on=b.getAttribute('aria-pressed')!=='true';b.setAttribute('aria-pressed',on);
 if(b.dataset.cat)st.cat[b.dataset.cat]=on; else if(b.dataset.sw){on?st.sw.add(b.dataset.sw):st.sw.delete(b.dataset.sw);} else st.x[b.dataset.x]=on; apply();}));
const tp=document.getElementById('top'),tt=document.querySelector('.totop');
if(tp&&tt&&'IntersectionObserver'in window){new IntersectionObserver(e=>tt.classList.toggle('show',!e[0].isIntersecting)).observe(tp);}else if(tt){tt.classList.add('show');}"""

SITES = [("ik", "一休.com"), ("tb", "食べログ"), ("tc", "TableCheck")]
SWEETS = [("ichigo", "いちご"), ("melon", "メロン"), ("peach", "桃"), ("mango", "マンゴー"), ("grape", "ぶどう・マスカット"),
          ("kuri", "栗・マロン"), ("imo", "芋・かぼちゃ"), ("kaki", "柿・洋梨・いちじく"), ("citrus", "柑橘"), ("choco", "チョコレート"),
          ("wa", "抹茶・和"), ("macaron", "マカロン"), ("parfait", "パフェ"), ("scone", "スコーン"), ("halloween", "ハロウィン"), ("xmas", "クリスマス"), ("valentine", "バレンタイン"), ("whiteday", "ホワイトデー"), ("collab", "コラボ企画"), ("season", "季節の味覚"), ("other", "その他")]
CATS = [("cafe", "カフェ", "c-cafe"), ("hotel", "ホテル", "c-hotel"), ("lux", "ホテル（高級）", "c-lux")]
SVG_LOC = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 1.5a4.5 4.5 0 0 0-4.5 4.5c0 3.4 4.5 8.5 4.5 8.5s4.5-5.1 4.5-8.5A4.5 4.5 0 0 0 8 1.5zm0 6.2a1.7 1.7 0 1 1 0-3.4 1.7 1.7 0 0 1 0 3.4z" fill="currentColor"/></svg>'
SVG_TEA = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 9h13v4a6 6 0 0 1-6 6H10a6 6 0 0 1-6-6V9zm13 1h1.5a2.5 2.5 0 0 1 0 5H17" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/><path d="M8 3.5c0 1.5 1.2 1.5 1.2 3M11.5 3.5c0 1.5 1.2 1.5 1.2 3" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>'
SVG_EXT = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M6 3h7v7M13 3 6.5 9.5M11 9.5V13H3V5h3.5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>'
def _star(cx, cy, r, fill="none", stroke="none", sw=0):
    import math
    pts = [(cx + r * math.sin(math.radians(144 * i)), cy - r * math.cos(math.radians(144 * i))) for i in range(5)]
    d = "M" + " L".join(f"{x:.2f},{y:.2f}" for x, y in pts) + " Z"
    return f'<path d="{d}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}" stroke-linejoin="miter"/>'
FLAGS = {
    "jp": '<rect width="90" height="60" fill="#fff"/><circle cx="45" cy="30" r="18" fill="#BC002D"/>',
    "gb": '<rect width="60" height="30" fill="#012169"/><path d="M0,0 L60,30 M60,0 L0,30" stroke="#fff" stroke-width="6"/><path d="M0,0 L60,30 M60,0 L0,30" stroke="#C8102E" stroke-width="2"/><path d="M30,0 v30 M0,15 h60" stroke="#fff" stroke-width="10"/><path d="M30,0 v30 M0,15 h60" stroke="#C8102E" stroke-width="6"/>',
    "fr": '<rect width="90" height="60" fill="#CE1126"/><rect width="60" height="60" fill="#fff"/><rect width="30" height="60" fill="#002654"/>',
    "it": '<rect width="90" height="60" fill="#CE2B37"/><rect width="60" height="60" fill="#fff"/><rect width="30" height="60" fill="#009246"/>',
    "ma": '<rect width="90" height="60" fill="#C1272D"/>' + _star(45, 31, 13, stroke="#006233", sw=2.6),
    "cn": '<rect width="90" height="60" fill="#DE2910"/>' + _star(15, 15, 9, fill="#FFDE00") + _star(30, 6, 3, fill="#FFDE00") + _star(36, 12, 3, fill="#FFDE00") + _star(36, 21, 3, fill="#FFDE00") + _star(30, 27, 3, fill="#FFDE00"),
}
FLAG_VB = {"gb": "0 0 60 30"}

def flag_svg(cc):
    if cc not in FLAGS: return ""
    return f'<svg viewBox="{FLAG_VB.get(cc, "0 0 90 60")}" preserveAspectRatio="none" role="img" aria-label="国旗">{FLAGS[cc]}</svg>'

SVG_CLK = '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6.2" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M8 4.6V8l2.4 1.6" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>'

def esc(t):
    return html.escape(str(t or ""), quote=False)

def vf(t):
    return re.sub(r"［要検証(?:：([^］]*))?］",
                  lambda m: '<span class="vf">要検証</span>' + (f"［{m.group(1)}］" if m.group(1) else ""), esc(t))

def chip(state, name):
    return {"on": f'<span class="chip on">{name}</span>', "no": f'<span class="chip no">{name} ✕</span>'}.get(
        state, f'<span class="chip off">{name} ?</span>')

def ymd(t):
    try:
        return datetime.date.fromisoformat(t) if t else None
    except ValueError:
        return None

def md(x):
    return f"{x.month}/{x.day}"

def plans_of(s):
    if s.get("plans"):
        return s["plans"]
    return [{k: s.get(k) for k in ("theme", "sw", "price_min", "price_text", "wd", "we", "days_text", "time_text")}]

def agg(s):
    ps = plans_of(s)
    prices = [p["price_min"] for p in ps if p.get("price_min") is not None]
    sw = []
    for p in ps:
        for k in (p.get("sw") or ["other"]):
            if k not in sw: sw.append(k)
    if len(sw) > 1 and "other" in sw: sw.remove("other")
    return {"price_min": min(prices) if prices else None, "sw": sw,
            "wd": "on" if any(p.get("wd") == "on" for p in ps) else "off",
            "we": "on" if any(p.get("we") == "on" for p in ps) else "off"}

def ref_price(s):
    p = agg(s)["price_min"]
    if p is not None: return p
    nums = []
    for q in plans_of(s):
        m = re.search(r"([0-9][0-9,]{2,})\s*円", str(q.get("price_text") or ""))
        if m: nums.append(int(m.group(1).replace(",", "")))
    return min(nums) if nums else None

def regroup(a):
    hs = a["cats"]["hotel"]["shops"] + a["cats"]["lux"]["shops"]
    for ck in ("hotel", "lux"):
        c = a["cats"][ck]
        c["shops"] = [s for s in hs if (ck == "lux") == ((ref_price(s) or 0) >= 9000)]
        if c["shops"]: c["status"] = "ok"
        elif c["status"] == "ok": c["status"] = "none"

def check(d):
    errs = []
    sw_ok = {k for k, _ in SWEETS}; site_ok = {k for k, _ in SITES}
    per = d.get("period") or {}
    ps, pe = ymd(per.get("start")), ymd(per.get("end"))
    if not ps or not pe:
        errs.append("period の start / end がない（YYYY-MM-DD）")
    elif pe != ps + datetime.timedelta(days=40):
        errs.append(f"period の end は start の40日後（{ps + datetime.timedelta(days=40)}）にする")
    for a in d["areas"]:
        for ck, _, _ in CATS:
            c = a["cats"].get(ck)
            if c is None: errs.append(f'エリア{a["no"]} に {ck} がない'); continue
            if c["status"] not in ("ok", "none", "unchecked"): errs.append(f'エリア{a["no"]} {ck} の status が不正')
            for s in c["shops"]:
                for l in s.get("links", []):
                    if l["site"] not in site_ok: errs.append(f'{s["name"]}: site「{l["site"]}」が不正')
                for p in plans_of(s):
                    for k in (p.get("sw") or []):
                        if k not in sw_ok: errs.append(f'{s["name"]}: sw「{k}」が不正')
                    for k in ("wd", "we"):
                        if p.get(k) not in ("on", "no", "off"): errs.append(f'{s["name"]}: {k} が不正')
                    st, en = ymd(p.get("start")), ymd(p.get("end"))
                    if ps and pe and ((en and en < ps) or (st and st > pe)):
                        errs.append(f'{s["name"]}: 調査期間の外のプラン「{p.get("theme")}」が入っている')
    if errs:
        print("データに誤りがあります:\n" + "\n".join(errs)); sys.exit(1)

TODAY = None

def clean(t):
    t = str(t or "").strip()
    if re.match(r"(要確認|未確認|不明|未調査)", t): return ""
    t = re.sub(r"[（(][^（）()]*(要確認|未確認|不明)[^（）()]*[）)]", "", t)
    t = re.sub(r"[・、]\s*(要確認|未確認)", "", t)
    t = re.sub(r"[。、／・]?[^。、／（）()]*(は要確認|は未確認|は不明)", "", t)
    t = re.sub(r"[。、／・]?[^。、／（）()]*(要確認|未確認)[。]?$", "", t)
    return t.strip(" 　。、／")

def known(t):
    t = clean(t)
    return bool(t) and not re.fullmatch(r"[\s（(]*(要確認|不明|未調査|未確認|期間要確認|記載なし|曜日の記載なし|—|-)[\s）)。．]*", t)

def plan_html(p, names, i=0, n=1):
    st, en = ymd(p.get("start")), ymd(p.get("end"))
    per = p.get("period_text") or ((md(st) if st else "") + "〜" + (md(en) if en else "") if (st or en) else "")
    sw = [k for k in (p.get("sw") or []) if k != "other"]
    stat = ""
    if TODAY and (st or en):
        if st and st > TODAY: stat = '<span class="pst soon">これから</span>'
        elif not en or en >= TODAY: stat = '<span class="pst now">提供中</span>'
    no = f'<span class="pno">プラン{i + 1}／{n}</span>' if n > 1 else ""
    body = []
    if known(p.get("theme")): body.append(f'<p class="theme">{SVG_TEA}<span>{esc(clean(p["theme"]))}</span></p>')
    if known(p.get("country")): body.append(f'<p class="ctry">{esc(clean(p["country"]))}：{flag_svg(p.get("cc"))}</p>')
    if sw: body.append('<p class="swt" aria-label="スイーツの分類">' + "".join(f"<span>{names[k]}</span>" for k in sw) + "</p>")
    pt = clean(p.get("price_text")) if known(p.get("price_text")) else ""
    if p.get("price_min") is not None:
        body.append(f'<div class="price"><span class="pbig">{p["price_min"]:,}<small>円〜</small></span>' + (f'<span class="pdet">{esc(pt)}</span>' if pt else "") + "</div>")
    elif pt:
        body.append(f'<div class="price"><span class="pdet">{esc(pt)}</span></div>')
    chips = "".join(chip(p.get(k), nm) for k, nm in (("wd", "平日"), ("we", "土日祝")) if p.get(k) in ("on", "no")) or '<span class="chip off">曜日未確認</span>'
    w = []
    if chips: w.append(f'<div class="chips" aria-label="提供日">{chips}</div>')
    if known(p.get("days_text")): w.append(f'<p class="dtxt">{esc(clean(p["days_text"]))}</p>')
    if known(p.get("time_text")): w.append(f'<p class="time">{SVG_CLK}<span>{esc(clean(p["time_text"]))}</span></p>')
    if w: body.append('<div class="when">' + "".join(w) + "</div>")
    if not body and not known(per): return ""
    hd = no + (f'<p class="pper">{esc(clean(per))}</p>' if known(per) else '<p class="pper na">期間不明</p>') + stat
    return '<div class="plan">' + (f'<div class="plan-hd">{hd}</div>' if hd else "") + "".join(body) + "</div>"

def card(s, ck, cls, ym):
    g_ = agg(s)
    sw = g_["sw"]
    pk = 1 if g_["price_min"] is not None else 0
    wd = 1 if g_["wd"] == "on" else 0
    we = 1 if g_["we"] == "on" else 0
    h = [f'<article data-sw="{" ".join(sw)}" class="card {cls}" data-cat="{ck}" data-wd="{wd}" data-we="{we}" data-pk="{pk}">']
    head = f'<h4>{esc(s["name"])}</h4>' + (f'<p class="shop">{esc(s["shop"])}</p>' if s.get("shop") else "")
    h.append(f'<div class="top"><header>{head}</header></div>')  # 食べログ点数はカードに表示しない（データには残す）
    if s.get("new"): h.append(f'<p class="rnote">{ym}の調査で新規掲載</p>')
    h.append(f'<p class="loc">{SVG_LOC}{esc(s.get("station"))}</p>')
    if known(s.get("exit")): h.append(f'<div class="meet"><p><span class="mk">駅の出口</span>{vf(clean(s.get("exit")))}</p></div>')
    links = {l["site"]: l["url"] for l in s.get("links", [])}
    lk = "".join(f'<a class="lk lk-{k}" href="{html.escape(links[k])}" target="_blank" rel="noopener">{n}{SVG_EXT}</a>' for k, n in SITES if k in links)
    if lk: h.append(f'<div class="links" aria-label="予約・情報サイト">{lk}</div>')
    names = dict(SWEETS)
    ps = sorted(plans_of(s), key=lambda p: (ymd(p.get("start")) or datetime.date.min))
    ph = "".join(plan_html(p, names, i, len(ps)) for i, p in enumerate(ps))
    if ph: h.append('<div class="plans">' + ph + "</div>")
    h.append("</article>")
    return "\n".join(h)

def main():
    path = sys.argv[1]
    d = json.load(open(path, encoding="utf-8"))
    check(d)
    global TODAY
    dt = datetime.date.fromisoformat(d["generated"])
    TODAY = dt
    ps_, pe_ = ymd(d["period"]["start"]), ymd(d["period"]["end"])
    ym = f"{dt.month}月{dt.day}日"
    tot = {ck: 0 for ck, _, _ in CATS}; swc = {k: 0 for k, _ in SWEETS}; nlinks = 0
    for a in d["areas"]:
        regroup(a)
        for ck, _, _ in CATS:
            c = a["cats"][ck]
            if c["shops"] and not any(s.get("links") for s in c["shops"]): c["status"] = "unchecked"
            c["shops"] = [s for s in c["shops"] if s.get("links")]
            shops = c["shops"]
            shops.sort(key=lambda s: (agg(s)["price_min"] is None, agg(s)["price_min"] or 0))
            tot[ck] += len(shops)
            for s in shops:
                for k in agg(s)["sw"]: swc[k] += 1
                nlinks += len(s.get("links", []))
    out = ['<!doctype html><html lang="ja"><head><meta charset="utf-8">',
           '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">',
           '<title>東京 アフタヌーンティー</title>',
           '<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>',
           '<link href="https://fonts.googleapis.com/css2?family=Zen+Old+Mincho:wght@500;700&family=Noto+Sans+JP:wght@400;500;700&display=swap" rel="stylesheet">',
           "<style>" + CSS + "</style></head><body>"]
    out.append('<div class="hero"><div class="hero-in"><div>\n<h1>東京 アフタヌーンティー</h1>\n'
               f'<p class="period">{ps_.year}年{ps_.month}月{ps_.day}日〜{pe_.year}年{pe_.month}月{pe_.day}日<small>（40日間）</small></p>'
               '<p class="lead legendline"><span class="lg"><span class="chip on">平日</span> 提供あり</span><span class="lg"><span class="chip no">土日祝 ✕</span> そのプランでは提供なし</span></p></div>\n'
               f'<div class="stats"><div class="stat s-cafe"><b>{tot["cafe"]}</b><span>カフェ</span></div><div class="stat s-hotel"><b>{tot["hotel"]}</b><span>ホテル</span></div><div class="stat s-lux"><b>{tot["lux"]}</b><span>ホテル（高級）</span></div></div>\n</div></div>')
    EV = ("halloween", "xmas", "valentine", "whiteday", "collab", "season")
    def mk(keys):
        return "".join(f'<button class="fb f-x" data-sw="{k}" aria-pressed="false">{n}<span class="bc">{swc[k]}</span></button>' for k, n in SWEETS if k in keys and (swc[k] or k in ("macaron", "parfait", "scone", "valentine", "whiteday", "collab")))
    btn = mk([k for k, _ in SWEETS if k not in EV])
    btn_ev = mk(EV)
    nav = "".join(f'<a class="area-btn" href="#a{a["no"]}">{esc(a["name"]).replace("・", "・<wbr>")}</a>' for a in d["areas"])
    out.append('<div class="fpanel" id="top"><div class="fpanel-in">\n'
               '<div class="frow" role="group" aria-label="分類で絞り込み"><span class="lb">分類</span><div class="btns">'
               '<button class="fb f-cafe" data-cat="cafe" aria-pressed="true">カフェ</button><button class="fb f-hotel" data-cat="hotel" aria-pressed="true">ホテル</button><button class="fb f-lux" data-cat="lux" aria-pressed="true">ホテル（高級）</button></div></div>\n'
               '<div class="frow" role="group" aria-label="条件で絞り込み"><span class="lb">条件</span><div class="btns">'
               '<button class="fb f-x" data-x="wd" aria-pressed="false">平日に行ける</button><button class="fb f-x" data-x="we" aria-pressed="false">土日祝に行ける</button><button class="fb f-x" data-x="pk" aria-pressed="false">値段確認済</button></div></div>\n'
               f'<div class="frow" role="group" aria-label="スイーツで絞り込み"><span class="lb">スイーツ</span><div class="btns">{btn}</div><p class="hint">複数選択可（どれかに当てはまる店を表示）</p></div>\n'
               f'<div class="frow" role="group" aria-label="イベント・季節で絞り込み"><span class="lb">イベント<br>季節</span><div class="btns">{btn_ev}</div></div>\n'
               f'<nav class="frow" aria-label="エリア"><span class="lb">場所</span><div class="btns">{nav}</div></nav>\n'
               '</div></div>\n<a class="totop" href="#top">▲ 絞り込み・場所へ</a>\n<main>')
    for a in d["areas"]:
        n = sum(len(a["cats"][ck]["shops"]) for ck, _, _ in CATS)
        sec = [f'<section id="a{a["no"]}" class="area"><h2><span class="no">{a["no"]:02d}</span>{esc(a["name"])}<span class="acnt">{n}件</span></h2>']
        for ck, label, cls in CATS:
            c = a["cats"][ck]
            sec.append(f'<div class="cat {cls}" data-cat="{ck}"><h3><span class="tag">{label}</span><span class="cnt">{len(c["shops"])}件</span></h3>')
            if c["shops"]:
                sec.append('<div class="grid">' + "".join(card(s, ck, cls, ym) for s in c["shops"]) + "</div>")
            elif c["status"] == "unchecked":
                sec.append('<p class="none">未確認（確認できた範囲では該当なし）</p>')
            else:
                sec.append('<p class="none">該当なし（今回の調査で条件を満たす店を確認できず）</p>')
            sec.append("</div>")
        sec.append("</section>")
        out.append("".join(sec))
    cand = "".join(f'<li><b>{esc(c["area"])}</b>　' + (f'<a class="clink" href="{html.escape(c["url"])}" target="_blank" rel="noopener">{esc(c["name"])}{SVG_EXT}</a>' if c.get("url") else esc(c["name"])) + f'<br><small>{esc(c.get("note"))}</small></li>' for c in d.get("candidates", [])) or "<li>なし</li>"
    out.append(f'<div class="aside"><div class="box"><h2>未検証の候補</h2><ul>{cand}</ul></div></div>')
    out.append('</main>')
    out.append("<script>" + JS + "</script></body></html>")
    name = f"afternoon_tea_tokyo_{ps_.isoformat()}.html"
    open(name, "w", encoding="utf-8").write("\n".join(out))
    print(f"作成: {name}  店数 カフェ{tot['cafe']}・ホテル{tot['hotel']}・高級{tot['lux']}、リンク{nlinks}件")

main()
```
