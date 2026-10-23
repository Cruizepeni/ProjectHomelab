from typing import Any

from YouSnipeSettings import UNLIMITED_SENTINEL


def get_effective_speed_limit(settings: dict[str, Any]) -> int | None:
    raw_value = (settings or {}).get("limits", {}).get("maxDownloadSpeedMBPerSecond", UNLIMITED_SENTINEL)
    if raw_value == UNLIMITED_SENTINEL:
        return None

    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return None

    return int(value * 1_000_000) if value > 0 else None


def build_ytdlp_speed_limit_args(settings: dict[str, Any]) -> list[str]:
    speed_limit = get_effective_speed_limit(settings)
    if speed_limit is None:
        return []
    return ["--limit-rate", str(speed_limit)]
