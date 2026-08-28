from datetime import datetime


def iso(ts: datetime) -> str:
    return ts.isoformat()


def business_hours_variant(ts: datetime, rng) -> datetime:
    """Nudge a timestamp's clock time into a plausible waking-hours range,
    keeping the same date. `rng` is a random.Random instance."""
    return ts.replace(
        hour=rng.randint(7, 22),
        minute=rng.randint(0, 59),
        second=rng.randint(0, 59),
    )
