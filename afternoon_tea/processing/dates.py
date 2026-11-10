"""JST dates and the forty-day research window."""
import datetime as dt
JST = dt.timezone(dt.timedelta(hours=9))

def period(start=None, now=None):
    if start is None:
        now = now or dt.datetime.now(JST)
        if now.tzinfo is None:
            raise ValueError('now にはタイムゾーンが必要です')
        start = now.astimezone(JST).date()
    elif isinstance(start, str):
        start = dt.date.fromisoformat(start)
    return {'start': start.isoformat(), 'end': (start + dt.timedelta(days=40)).isoformat()}
