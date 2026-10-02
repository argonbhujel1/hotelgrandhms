from datetime import datetime, timezone, timedelta

# Nepal Standard Time = UTC+5:45
NPT = timezone(timedelta(hours=5, minutes=45))


def now_npt() -> datetime:
    return datetime.now(NPT)


def utc_to_npt(dt: datetime) -> datetime:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(NPT)


def format_npt(dt, fmt="%d %b %Y %H:%M") -> str:
    if dt is None:
        return ""
    return utc_to_npt(dt).strftime(fmt)


def npt_now_naive() -> datetime:
    """Naive datetime showing Nepal wall-clock time (for DB storage)."""
    return now_npt().replace(tzinfo=None)
