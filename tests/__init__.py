
"""Synthetic privacy samples created only while the tests execute."""
import secrets


EMAIL = chr(64).join(('privacy-' + secrets.token_hex(6), 'example.invalid'))
PHONE = '-'.join(('0' + '9' + '0', ''.join(str(secrets.randbelow(10)) for _ in range(4)),
                  ''.join(str(secrets.randbelow(10)) for _ in range(4))))
KEY_HEADER = ('-' * 5) + ' '.join(('BEGIN', 'PRIVATE', 'KEY')) + ('-' * 5)


def _card_sample():
    digits = [4] + [secrets.randbelow(10) for _ in range(14)]
    doubled = [n * 2 if i % 2 == 0 else n for i, n in enumerate(digits)]
    check = (-sum(n - 9 if n > 9 else n for n in doubled)) % 10
    value = ''.join(map(str, digits + [check]))
    return ' '.join(value[i:i + 4] for i in range(0, len(value), 4))


CARD = _card_sample()
