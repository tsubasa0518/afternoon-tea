"""Offline, pre-PR date review for Claude. Not an automatic publication gate."""
import argparse
import datetime as dt
import json
from pathlib import Path
from .data import JST, period


def day(value):
    if value is None:
        return None
    parsed = dt.date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError('use YYYY-MM-DD or null')
    return parsed


def review(data):
    errors, outside = [], []
    try:
        window = data['period']
        start, end = day(window['start']), day(window['end'])
        if start is None or end is None or end != start + dt.timedelta(days=40):
            raise ValueError('period.end must be 40 days after period.start')
        generated = data.get('generated_at')
        if generated is not None:
            stamp = dt.datetime.fromisoformat(generated)
            if stamp.tzinfo is None or stamp.astimezone(JST).date() != start:
                raise ValueError('period.start must match generated_at in JST')
    except (KeyError, TypeError, ValueError) as exc:
        return {'errors': [{'reason': 'invalid_research_period', 'detail': str(exc)}],
                'outside_plans': [], 'unknown_periods': 0}
    unknown = total = 0
    for si, shop in enumerate(data.get('shops', [])):
        for pi, plan in enumerate(shop.get('plans', [])):
            total += 1
            location = {'shop_index': si, 'plan_index': pi}
            try:
                first, last = day(plan.get('start')), day(plan.get('end'))
                if first and last and first > last:
                    raise ValueError('plan.start is after plan.end')
            except (TypeError, ValueError) as exc:
                errors.append({**location, 'reason': 'invalid_plan_period', 'detail': str(exc)})
                continue
            # Inclusive intersection; an unknown endpoint is never invented.
            if (first and first > end) or (last and last < start):
                item = {**location, 'reason': 'outside_research_period'}
                outside.append(item)
                errors.append(item)
            elif first is None or last is None:
                unknown += 1
    return {'period': window, 'shops': len(data.get('shops', [])), 'plans': total,
            'errors': errors, 'outside_plans': outside, 'unknown_periods': unknown}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--period', action='store_true', help='Print today in JST and its 40-day window')
    parser.add_argument('--data', type=Path, default=Path('site/research.json'))
    args = parser.parse_args()
    if args.period:
        print(json.dumps(period(), ensure_ascii=False))
        return 0
    result = review(json.loads(args.data.read_text(encoding='utf-8')))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result['errors'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
