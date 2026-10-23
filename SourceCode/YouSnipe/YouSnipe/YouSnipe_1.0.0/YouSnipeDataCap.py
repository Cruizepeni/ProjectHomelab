from __future__ import annotations

import calendar
from datetime import datetime, timedelta, timezone
from typing import Any

from YouSnipeSettings import get_effective_settings

MEGABYTE = 1_000_000
GIGABYTE = 1_000_000_000


class YouSnipeDataCapReachedError(RuntimeError):
    code = "DATA_CAP_REACHED"


def _cycle_end(start: datetime, period: dict[str, Any]) -> datetime:
    value = max(1, int(period.get("value") or 1))
    unit = str(period.get("unit") or "month").lower()

    if unit == "hour":
        return start + timedelta(hours=value)
    if unit == "day":
        return start + timedelta(days=value)
    if unit == "week":
        return start + timedelta(weeks=value)

    months_offset = value if unit == "month" else value * 12
    month_index = start.month - 1 + months_offset
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return start.replace(year=year, month=month, day=day)


def _cap_bytes(config: dict[str, Any]) -> int:
    amount = float(config.get("amount") or 0)
    multiplier = MEGABYTE if str(config.get("unit")).upper() == "MB" else GIGABYTE
    return int(amount * multiplier)


def get_data_cap_status(db_manager, settings: dict | None = None, now: datetime | None = None) -> dict[str, Any]:
    settings = settings or get_effective_settings()
    config = settings["limits"]["dataUsageCap"]
    current = now or datetime.now(timezone.utc)
    state = db_manager.get_data_cap_state()

    if not config.get("enabled"):
        
        if state.get("enabled_last_seen"):
            db_manager.reset_data_cap_cycle(False, current)
        return {
            "enabled": False,
            "amount": config["amount"],
            "unit": config["unit"],
            "capBytes": _cap_bytes(config),
            "period": config["period"],
            "cycleStart": None,
            "cycleEnd": None,
            "usedBytes": 0,
            "remainingBytes": None,
            "percentUsed": 0,
            "capReached": False,
        }

    if not state.get("enabled_last_seen") or not state.get("cycle_started_at"):
        db_manager.reset_data_cap_cycle(True, current)
        state = db_manager.get_data_cap_state()

    cycle_start = datetime.fromisoformat(state["cycle_started_at"])
    cycle_end = _cycle_end(cycle_start, config["period"])

    if current >= cycle_end:
        db_manager.reset_data_cap_cycle(True, current)
        state = db_manager.get_data_cap_state()
        cycle_start = datetime.fromisoformat(state["cycle_started_at"])
        cycle_end = _cycle_end(cycle_start, config["period"])

    cap = _cap_bytes(config)
    used = int(state.get("bytes_used") or 0)

    return {
        "enabled": True,
        "amount": config["amount"],
        "unit": config["unit"],
        "capBytes": cap,
        "period": config["period"],
        "cycleStart": cycle_start.isoformat(),
        "cycleEnd": cycle_end.isoformat(),
        "usedBytes": used,
        "remainingBytes": max(0, cap - used),
        "percentUsed": min(100, used / cap * 100 if cap else 100),
        "capReached": used >= cap,
    }


def assert_transfer_allowed(db_manager, settings: dict | None = None) -> None:
    if get_data_cap_status(db_manager, settings)["capReached"]:
        raise YouSnipeDataCapReachedError("Configured data cap has been reached")


def reset_data_cap(db_manager, settings: dict | None = None) -> dict[str, Any]:
    config = (settings or get_effective_settings())["limits"]["dataUsageCap"]
    now = datetime.now(timezone.utc)
    db_manager.reset_data_cap_cycle(bool(config.get("enabled")), now)
    return get_data_cap_status(db_manager, settings, now)


class TransferUsageTracker:
    def __init__(self, db_manager, item_id: int | None) -> None:
        self._db_manager = db_manager
        self._item_id = item_id
        self._last_downloaded_bytes: dict[str, int] = {}

    def record_progress(self, transfer_key: str, downloaded_bytes: int | None) -> None:
        if downloaded_bytes is None:
            return

        current = max(0, int(downloaded_bytes))
        previous = self._last_downloaded_bytes.get(transfer_key, 0)
        
        delta = current if current < previous else current - previous
        self._last_downloaded_bytes[transfer_key] = current

        if not delta:
            return

        self._db_manager.record_usage(item_id=self._item_id, bytes_transferred=delta, source=transfer_key)

        settings = get_effective_settings()
        if get_data_cap_status(self._db_manager, settings)["enabled"]:
            self._db_manager.increment_data_cap_usage(delta)

        assert_transfer_allowed(self._db_manager, settings)
