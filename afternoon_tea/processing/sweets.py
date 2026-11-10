"""One offline plan-level keyword classifier for saved tags, counts and filtering."""
import re
import unicodedata

PATTERNS = {
    'ichigo': r'いちご|イチゴ|苺|ストロベリー|\bstrawberr(?:y|ies)\b',
    'melon': r'メロン|\bmelons?\b',
    'peach': r'桃|ピーチ|\bpeach(?:es)?\b',
    'mango': r'マンゴー|\bmango(?:es|s)?\b',
    'grape': r'ぶどう|ブドウ|葡萄|グレープ(?!フルーツ)|マスカット|\bgrapes?\b|\bmuscat\b',
    'kuri': r'栗|マロン|モンブラン|\bmarrons?\b|\bchestnuts?\b|\bmont blanc\b',
    'imo': r'芋|さつまいも|かぼちゃ|カボチャ|南瓜|パンプキン|スイートポテト|\bsweet potato(?:es)?\b|\bpumpkins?\b',
    'kaki': r'柿|洋梨|洋ナシ|梨|いちじく|イチジク|無花果|\bpersimmons?\b|\bpears?\b|\bfigs?\b|ペア(?=の?(?:ムース|タルト|ジュレ|コンポート|ケーキ|ゼリー|パフェ))',
    'citrus': r'柑橘|オレンジ|みかん|ミカン|レモン|ゆず|ユズ|柚子|グレープフルーツ|\bcitrus\b|\boranges?\b|\blemons?\b|\bgrapefruits?\b|\byuzu\b',
    'choco': r'チョコ|ショコラ|\bchocolat(?:e|es)?\b|\bcacao\b|\bcocoa\b',
    'wa': r'抹茶|ほうじ茶|玄米茶|あずき|小豆|あんこ|きなこ|和風|和菓子|和スイーツ|和の心|和洋中|ジャパニーズスタイル|\bmatcha\b|\bhojicha\b|\bgenmaicha\b|\bazuki\b|\bkinako\b',
    'macaron': r'マカロン|\bmacarons?\b',
    'parfait': r'パフェ|\bparfaits?\b',
    'scone': r'スコーン|\bscones?\b',
}
COMPILED = {key: re.compile(pattern, re.I) for key, pattern in PATTERNS.items()}
FIELDS = ('plan_name', 'theme', 'theme_name', 'menu', 'description', 'explanation', 'evidence_quote', 'note')
EXTRA = re.compile(r'追加料金|別料金|オプション|別売|追加注文|単品|アラカルト|通常(?:の)?ランチ|ランチメニュー|他(?:の)?プラン|別プラン|他店|別店舗|他店舗|\boptional\b|\badd[- ]on\b|\ba la carte\b|\blunch menu\b', re.I)
NEGATIVE = re.compile(r'含まれません|含まれない|含まれていません|含まない|ありません|ございません|付いていません|提供(?:しません|されません|しない|されない|終了)|販売終了|不使用|未提供|対象外|\bnot (?:included|available|served)\b|\bunavailable\b|\bwithout\b', re.I)
OTHER = re.compile(r'チーズケーキ|ティラミス|プリン|カヌレ|フィナンシェ|マドレーヌ|バクラヴァ|バクラバ|杏仁豆腐|エッグタルト|\bcheesecake\b|\btiramisu\b|\bpudding\b|\bcanele\b|\bbaklava\b', re.I)
POSITIVE_HEADING = re.compile(r'アフタヌーン|AT本体|プラン本体|対象プラン|メニュー|スイーツ|デザート|セイボリー|\bmenu\b|\bsweets?\b|\bdesserts?\b|\bafternoon tea\b', re.I)


def text_values(value):
    if isinstance(value, str):yield value
    elif isinstance(value, list):
        for item in value:yield from text_values(item)
    elif isinstance(value, dict):
        for item in value.values():yield from text_values(item)


def option_scope(text):
    # These phrases explicitly say the item is included, not an extra-cost option.
    return re.sub(r'(?:追加料金|別料金)(?:は)?(?:なし|不要|かかりません|発生しません)|(?:オプション|別売)(?:ではありません|ではない)', '', text)


def menu_scope(text):
    text = option_scope(text)
    # Non-menu restrictions must not negate an actual dessert in the same clause.
    return re.sub(r'(?:アルコール|予約|提供期間|提供時間|料金|人数|時間制限|砂糖|生クリーム|乳製品|小麦|グルテン)(?:は|を|が)?\s*(?:含まれません|含まれていません|ありません|ございません|不使用|なし|未確認|未定|提供しません)', '', text)


def eligible_clauses(plan):
    for field in FIELDS:
        for text in text_values(plan.get(field)):
            blocked = False
            normalized = unicodedata.normalize('NFKC', text)
            for line in normalized.splitlines():
                line = line.strip()
                heading = bool(re.fullmatch(r'[【\[].*?[】\]]\s*[:：]?', line) or line.endswith((':','：')) or line in ('オプション','別売','通常ランチ','スイーツ','デザート','AT本体'))
                if heading:
                    if EXTRA.search(option_scope(line)) or NEGATIVE.search(line) or re.search(r'未確認|未定',line):blocked = True
                    elif POSITIVE_HEADING.search(line):blocked = False
                    continue
                if blocked:continue
                if re.match(r'^(?:(?:メニュー|内容)?(?:未確認|未定))',line):continue
                if re.match(r'^(?:[【\[])?(?:オプション|別料金|追加料金|単品|通常ランチ|他のプラン|optional|add-on)',option_scope(line),re.I):
                    parts = line.split('。', 1)
                    if len(parts) == 1:continue
                    line = parts[1]
                for clause in re.split(r'[、,。;；]|ただし|一方|代わりに|ですが|(?<=ません)が', line):
                    clause = clause.strip()
                    if not clause or EXTRA.search(option_scope(clause)) or NEGATIVE.search(menu_scope(clause)):continue
                    if re.search(r'(?:なし|無し|抜き)(?:です)?[。)）]*$',option_scope(clause)) and not re.search(r'予約|制限|人数|個数|アルコール|変更|キャンセル',clause):continue
                    yield field, clause


def extract(plan):
    """Deduplicate within a plan; never merge old tags or shop-wide tags."""
    hits, other = {}, []
    for field, clause in eligible_clauses(plan):
        for key, pattern in COMPILED.items():
            for match in pattern.finditer(clause):
                # Local negation such as 'スコーンなしでも苺付き' affects only scone.
                if re.match(r'\s*(?:は|が|を)?\s*(?:なし|無し|抜き|未確認|未定)',clause[match.end():]):continue
                if re.search(r'(?:no|without)\s*$',clause[:match.start()],re.I):continue
                hits.setdefault(key, (field, clause))
        if OTHER.search(clause):other.append((field, clause))
    if not hits and other:hits['other'] = other[0]
    return hits


def tags(plan):
    return sorted(extract(plan))
