from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


def _rolling_start(value: int, unit: str, now: datetime) -> datetime:
    multipliers = {"hour": timedelta(hours=value), "day": timedelta(days=value), "week": timedelta(weeks=value), "month": timedelta(days=30 * value), "year": timedelta(days=365 * value)}
    return now - multipliers[unit]


def get_usage_overview(db_manager, value: int | None = None, unit: str | None = None) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    totals = {"lastHourBytes": db_manager.get_usage_total(_rolling_start(1, "hour", now), now), "lastDayBytes": db_manager.get_usage_total(_rolling_start(1, "day", now), now), "lastWeekBytes": db_manager.get_usage_total(_rolling_start(1, "week", now), now), "lastMonthBytes": db_manager.get_usage_total(_rolling_start(1, "month", now), now), "lastYearBytes": db_manager.get_usage_total(_rolling_start(1, "year", now), now), "allTimeBytes": db_manager.get_usage_total()}
    if value and unit in {"hour", "day", "week", "month", "year"}:
        totals["customBytes"] = db_manager.get_usage_total(_rolling_start(int(value), unit, now), now)
    return totals


def parse_ranges(raw_ranges: Any) -> list[tuple[datetime, datetime]]:
    if not isinstance(raw_ranges, list):
        raise ValueError("ranges must be a list")
    ranges = []
    for entry in raw_ranges:
        try:
            start, end = datetime.fromisoformat(entry["start"]), datetime.fromisoformat(entry["end"])
        except Exception as exc:
            raise ValueError("Invalid usage range") from exc
        if start >= end:
            raise ValueError("Usage range end must be after start")
        ranges.append((start, end))
    return ranges


def _bucket_start(moment: datetime, group_by: str) -> datetime:
    moment = moment.astimezone(timezone.utc)
    if group_by == "hour":
        return moment.replace(minute=0, second=0, microsecond=0)
    if group_by == "day":
        return moment.replace(hour=0, minute=0, second=0, microsecond=0)
    if group_by == "week":
        day_start = moment.replace(hour=0, minute=0, second=0, microsecond=0)
        return day_start - timedelta(days=day_start.weekday())
    if group_by == "month":
        return moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return moment.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)


def _bucket_end(start: datetime, group_by: str) -> datetime:
    if group_by == "hour":
        return start + timedelta(hours=1)
    if group_by == "day":
        return start + timedelta(days=1)
    if group_by == "week":
        return start + timedelta(weeks=1)
    if group_by == "month":
        year, month = (start.year + 1, 1) if start.month == 12 else (start.year, start.month + 1)
        return start.replace(year=year, month=month)
    return start.replace(year=start.year + 1)


def get_usage_history(db_manager, group_by: str, start: str | None = None, end: str | None = None) -> list[dict[str, Any]]:
    group_by = str(group_by or "").strip().lower()
    if group_by not in {"hour", "day", "week", "month", "year"}:
        raise ValueError("groupBy must be one of hour, day, week, month, year")

    now = datetime.now(timezone.utc)
    window_end = datetime.fromisoformat(end).astimezone(timezone.utc) if end else now
    window_start = datetime.fromisoformat(start).astimezone(timezone.utc) if start else _rolling_start(30, "day", window_end)
    if window_start >= window_end:
        raise ValueError("Usage range end must be after start")

    buckets: dict[datetime, int] = {}
    for row in db_manager.get_usage_buckets(window_start, window_end):
        try:
            moment = datetime.fromisoformat(row["event_time"])
        except (TypeError, ValueError):
            continue
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        bucket = _bucket_start(moment, group_by)
        buckets[bucket] = buckets.get(bucket, 0) + int(row["bytes_transferred"] or 0)

    return [
        {
            "rangeStart": bucket.isoformat(),
            "rangeEnd": _bucket_end(bucket, group_by).isoformat(),
            "bytesUsed": total,
        }
        for bucket, total in sorted(buckets.items())
    ]
