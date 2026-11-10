"""Canonical metadata digest shared by acquisition and evidence verification."""
import hashlib
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

class ValidationError(ValueError):
    pass

def require(condition, message):
    if not condition:
        raise ValidationError(message)

def load_json(path):

    def pairs(items):
        result = {}
        for (key, value) in items:
            require(key not in result, 'JSONキーの重複: ' + key)
            result[key] = value
        return result

    def constant(value):
        raise ValidationError('JSONに非有限数: ' + value)
    try:
        with open(path, encoding='utf-8') as stream:
            return json.load(stream, object_pairs_hook=pairs, parse_constant=constant)
    except json.JSONDecodeError as exc:
        raise ValidationError('JSON構文エラー: ' + str(exc)) from exc

def dumps(data):
    return json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
