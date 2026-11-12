"""Owner-editable settings, the candidate list, genre exclusion and venue identity."""
import csv
import json
import os
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = ROOT / 'data/candidates.csv'
GENRES = ROOT / 'data/excluded_genres.json'
SETTINGS = ROOT / 'data/research_settings.json'
AREAS = range(1, 15)
CANDIDATE_HEADERS = ['No', '店舗名', 'ホテル名', 'エリア番号', 'ジャンル', '優先して調べるサイト', '参考URL', '備考']
NUMBER_SETTINGS = {
    'total_seconds', 'max_navigations', 'shop_seconds', 'min_interval_seconds', 'page_timeout_seconds',
    'max_page_bytes', 'max_redirects', 'browser_idle_seconds', 'excerpt_chars', 'max_excerpt_chars',
    'retry_after_days', 'recheck_after_days', 'stale_after_days', 'recheck_per_run', 'period_days'}


def settings(path=None, environ=None):
    """Limits are never unbounded: every value must be a positive finite number."""
    raw = json.loads(Path(path or SETTINGS).read_text(encoding='utf-8'))
    environ = os.environ if environ is None else environ
    result = {}
    for key in NUMBER_SETTINGS:
        value = environ.get('AFTERNOON_TEA_' + key.upper(), raw.get(key))
        try:
            value = float(value)
        except (TypeError, ValueError):
            raise ValueError('invalid_setting:' + key)
        if not (0 < value < 10 ** 9):
            raise ValueError('invalid_setting:' + key)
        result[key] = int(value) if value == int(value) else value
    return result


def norm(text):
    """Comparable form of a venue name: width, case, spaces and punctuation removed."""
    text = unicodedata.normalize('NFKC', str(text or '')).lower()
    text = re.sub(r'[(（\[【].*?[)）\]】]', '', text)  # floor numbers and notes
    text = re.sub(r'[「」『』"“”]', '', text)
    text = text.replace('&', 'and').replace('＆', 'and')
    return re.sub(r'[\s・･\-‐‑–—_.,，、。:：;；\'’"“”!！?？/／|]+', '', text)


def name_parts(name, hotel_name=None):
    """Split 'store／hotel' or 'hotel / store' into normalized non-empty parts."""
    parts = []
    for value in (name, hotel_name):
        for piece in re.split(r'\s+/\s+|／', unicodedata.normalize('NFKC', str(value or ''))):
            piece = norm(piece)
            if piece and piece not in parts:
                parts.append(piece)
    return parts


def _close(a, b):
    if a == b:
        return True
    short, long = sorted((a, b), key=len)
    return len(short) >= 4 and short in long


def same_venue(a, b):
    """Name/facility evidence, never URL equality. a and b are (name, hotel_name) pairs."""
    pa, pb = name_parts(*a), name_parts(*b)
    if not pa or not pb:
        return False
    if len(pa) == 1 or len(pb) == 1:
        # One side gives only a store name: it must match a part of the other side closely.
        single, other = (pa, pb) if len(pa) == 1 else (pb, pa)
        if len(single[0]) < 4 and len(other) > 1:
            return False
        return any(_close(single[0], part) for part in other) and (len(other) == 1 or len(single[0]) >= 6)
    matched = sum(any(_close(x, y) for y in pb) for x in pa)
    return matched >= 2


def main_genre(genre):
    parts = [p.strip() for p in re.split(r'[／/、,，・]', unicodedata.normalize('NFKC', str(genre or ''))) if p.strip()]
    return parts[0] if parts else None


@lru_cache(maxsize=4)
def _genres(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    entries = data.get('genres')
    if not isinstance(entries, list) or not entries:
        raise ValueError('excluded_genres_invalid')
    result = []
    for entry in entries:
        terms = entry.get('terms') if isinstance(entry, dict) else None
        if not isinstance(entry.get('label'), str) or not isinstance(terms, list) or not all(
                isinstance(t, str) and t.strip() for t in terms):
            raise ValueError('excluded_genres_invalid')
        result.append((entry['label'], tuple(unicodedata.normalize('NFKC', t).lower() for t in terms)))
    return tuple(result)


def excluded_genre(genre, path=None):
    """Return the excluded label for the venue's main genre, or None (unknown is not excluded)."""
    main = main_genre(genre)
    if main is None:
        return None
    main = main.lower()
    for label, terms in _genres(str(path or GENRES)):
        if any(term in main for term in terms):
            return label
    return None


def candidates(path=None):
    """The owner's list of shops to look up. A reference URL is optional and never required."""
    with Path(path or CANDIDATES).open(encoding='utf-8', newline='') as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != CANDIDATE_HEADERS:
            raise ValueError('candidate_columns_invalid')
        rows = list(reader)
    seen = set()
    for row in rows:
        if not row['No'].isdigit() or row['No'] in seen or not row['店舗名'].strip():
            raise ValueError('candidate_number_or_name_invalid')
        if row['エリア番号'] not in {str(n) for n in AREAS}:
            raise ValueError('candidate_area_outside_fourteen')
        seen.add(row['No'])
    return rows


def search_queries(name, hotel_name=None, site=None):
    """Public search starts from names, never from a stored URL."""
    base = ' '.join(x for x in (name, hotel_name) if x)
    queries = [base + ' アフタヌーンティー']
    if site:
        queries.append(base + ' ' + site + ' アフタヌーンティー')
    return queries
