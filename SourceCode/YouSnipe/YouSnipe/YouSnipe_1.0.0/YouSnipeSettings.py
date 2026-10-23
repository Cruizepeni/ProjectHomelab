from __future__ import annotations

import copy
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict

SCHEMA_VERSION = 2
DEFAULT_SENTINEL = "default"
UNLIMITED_SENTINEL = "unlimited"
NEVER_SENTINEL = "never"

VIDEO_OUTPUT_FORMATS = ["MP4", "MKV", "WEBM", "MOV", "AVI", "WMV", "FLV"]
AUDIO_OUTPUT_FORMATS = ["MP3", "M4A", "MP4", "MPA", "WAV", "AAC", "FLAC", "OGG", "ALAC", "WMA"]
VIDEO_QUALITY_ORDER = [4320, 2160, 1440, 1080, 720, 480, 360, 240, 144]
AUDIO_QUALITY_ORDER = [512, 320, 256, 192, 160, 128, 96, 64]

from YouSnipePaths import APP_ROOT, appdata_subdirectory
from YouSnipeDependencies import resolve_program, default_js_runtime

SETTINGS_DIR = appdata_subdirectory("Settings")
SETTINGS_PATH = SETTINGS_DIR / "YouSnipeSettingsConfig.json"
ACCENT_PRESETS = {
    "Electric Purple": "#A855F7",
    "Violet": "#8B5CF6",
    "Neon Pink": "#FF4DA6",
    "Magenta": "#E879F9",
    "Cyan": "#32D7FF",
    "Coral": "#FF5555",
}
DEFAULT_ACCENT = ACCENT_PRESETS["Electric Purple"]


def normalize_accent(value):
    if not isinstance(value, str):
        return DEFAULT_ACCENT
    value = value.strip().upper()
    if len(value) == 7 and value.startswith("#") and all(char in "0123456789ABCDEF" for char in value[1:]):
        return value
    return DEFAULT_ACCENT


def get_accent_color():
    return normalize_accent(get_effective_settings()["application"]["accentColor"])



def _deep_copy(value: Any) -> Any:
    return copy.deepcopy(value)


def _ffmpeg_default_path() -> str:
    return resolve_program('ffmpeg')


def _ffprobe_default_path() -> str:
    return resolve_program('ffprobe')


def _build_download_root() -> Path:
    return APP_ROOT / "Downloads" / "YouSnipe"


def _ytdlp_default_path() -> str:
    return resolve_program('yt-dlp')


def _ytdlp_js_runtime_default() -> str:
    return default_js_runtime()


def get_save_path(media_mode: str, settings: Dict[str, Any] | None = None) -> str:
    cfg = settings if settings is not None else get_effective_settings()
    storage = cfg['storage']
    key = 'audioSavePath' if media_mode.lower() == 'audio' else 'videoSavePath'
    return str(storage.get(key) or storage['defaultSavePath'])


def build_builtin_settings() -> Dict[str, Any]:
    root = _build_download_root()
    ytdlp_bin = _ytdlp_default_path()
    return {
        "schemaVersion": SCHEMA_VERSION,
        "server": {
            "host": "127.0.0.1",
            "port": 5030,
        },
        "aiTool": {
            "enabled": False,
            "enableDownloads": True,
            "enableHistoryRemoval": False,
            "enableSettingsUpdates": False,
        },
        "application": {
            "rememberRecentPaths": True,
            "accentColor": DEFAULT_ACCENT,
            "framelessGUI": False,  
            "legacyDownloadsMigrated": False,
        },
        "downloadDefaults": {
            "defaultMediaMode": "video",
            "defaultVideoFormat": "MP4",
            "defaultAudioFormat": "MP3",
            "overwriteExisting": False,
            "includeVideoQualityInFileName": True,
            "includeAudioQualityInFileName": False,
        },
        "storage": {
            "defaultSavePath": str(root),
            "videoSavePath": "",
            "audioSavePath": "",
        },
        "queue": {
            
            "maxConcurrentDownloads": 2,
        },
        "playlist": {
            "createPlaylistFolder": True,
            "addPlaylistIndexToMetadata": False,
            "addPlaylistIndexToFileName": False,
        },
        "history": {
            "keepFailedDownloadsInHistory": True,
            "historyRetention": {
                "mode": "interval",
                "value": 1,
                "unit": "year",
            },
        },
        "limits": {
            "dataUsageCap": {
                "enabled": False,
                "amount": 20,
                "unit": "GB",
                "period": {"value": 1, "unit": "month"},
            },
            "maxDownloadSpeedMBPerSecond": UNLIMITED_SENTINEL,
        },
        "runtime": {
            "ffmpegPath": _ffmpeg_default_path(),
            "ffprobePath": _ffprobe_default_path(),
            "ytdlpBin": ytdlp_bin,
            "ytdlpJsRuntime": _ytdlp_js_runtime_default(),
            "ytdlpCookiesPath": "",
            "videoOutputFormats": _deep_copy(VIDEO_OUTPUT_FORMATS),
            "audioOutputFormats": _deep_copy(AUDIO_OUTPUT_FORMATS),
            "videoQualityOrder": _deep_copy(VIDEO_QUALITY_ORDER),
            "audioQualityOrder": _deep_copy(AUDIO_QUALITY_ORDER),
        },
    }


RAW_DEFAULT_CONFIG: Dict[str, Any] = {
    "schemaVersion": SCHEMA_VERSION,
    "server": {"host": DEFAULT_SENTINEL, "port": DEFAULT_SENTINEL},
    "aiTool": {
        "enabled": DEFAULT_SENTINEL,
        "enableDownloads": DEFAULT_SENTINEL,
        "enableHistoryRemoval": DEFAULT_SENTINEL,
        "enableSettingsUpdates": DEFAULT_SENTINEL,
    },
    "application": {
        "rememberRecentPaths": DEFAULT_SENTINEL,
        "accentColor": DEFAULT_SENTINEL,
        "framelessGUI": DEFAULT_SENTINEL,
        "legacyDownloadsMigrated": DEFAULT_SENTINEL,
    },
    "downloadDefaults": {
        "defaultMediaMode": DEFAULT_SENTINEL,
        "defaultVideoFormat": DEFAULT_SENTINEL,
        "defaultAudioFormat": DEFAULT_SENTINEL,
        "overwriteExisting": DEFAULT_SENTINEL,
        "includeVideoQualityInFileName": DEFAULT_SENTINEL,
        "includeAudioQualityInFileName": DEFAULT_SENTINEL,
    },
    "storage": {
        "defaultSavePath": DEFAULT_SENTINEL,
        "videoSavePath": DEFAULT_SENTINEL,
        "audioSavePath": DEFAULT_SENTINEL,
    },
    "queue": {
        "maxConcurrentDownloads": DEFAULT_SENTINEL,
    },
    "playlist": {
        "createPlaylistFolder": DEFAULT_SENTINEL,
        "addPlaylistIndexToMetadata": DEFAULT_SENTINEL,
        "addPlaylistIndexToFileName": DEFAULT_SENTINEL,
    },
    "history": {
        "keepFailedDownloadsInHistory": DEFAULT_SENTINEL,
        "historyRetention": DEFAULT_SENTINEL,
    },
    "limits": {
        "dataUsageCap": {
            "enabled": DEFAULT_SENTINEL,
            "amount": DEFAULT_SENTINEL,
            "unit": DEFAULT_SENTINEL,
            "period": {"value": DEFAULT_SENTINEL, "unit": DEFAULT_SENTINEL},
        },
        "maxDownloadSpeedMBPerSecond": DEFAULT_SENTINEL,
    },
    "runtime": {
        "ytdlpCookiesPath": DEFAULT_SENTINEL,
        "ytdlpBin": DEFAULT_SENTINEL,
        "ffmpegPath": DEFAULT_SENTINEL,
        "ffprobePath": DEFAULT_SENTINEL,
        "ytdlpJsRuntime": DEFAULT_SENTINEL,
    },
}


def _ensure_settings_dir() -> None:
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)


def _load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    return data if isinstance(data, dict) else {}


def _save_json(path: Path, payload: Dict[str, Any]) -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as fh:
        json.dump(payload, fh, indent=2)
        temp_path = Path(fh.name)
    os.replace(temp_path, path)


def _shape_user_config(raw_shape: Dict[str, Any], user_payload: Dict[str, Any]) -> Dict[str, Any]:
    shaped: Dict[str, Any] = {}
    for key, raw_value in raw_shape.items():
        if key == "schemaVersion":
            shaped[key] = SCHEMA_VERSION
            continue

        user_value = user_payload.get(key, _deep_copy(raw_value))
        if isinstance(raw_value, dict):
            if isinstance(user_value, dict):
                shaped[key] = _shape_user_config(raw_value, user_value)
            else:
                shaped[key] = _deep_copy(raw_value)
        else:
            shaped[key] = user_value
    return shaped


def _resolve_config_value(user_value: Any, builtin_value: Any) -> Any:
    if isinstance(builtin_value, dict):
        if not isinstance(user_value, dict):
            return _deep_copy(builtin_value)
        resolved: Dict[str, Any] = {}
        for key, sub_builtin in builtin_value.items():
            resolved[key] = _resolve_config_value(user_value.get(key, DEFAULT_SENTINEL), sub_builtin)
        return resolved

    if user_value in (None, DEFAULT_SENTINEL):
        return _deep_copy(builtin_value)

    return _deep_copy(user_value)


def _normalize_unlimited_or_int(value: Any, builtin: Any) -> Any:
    if value == UNLIMITED_SENTINEL:
        return UNLIMITED_SENTINEL
    try:
        parsed = int(value)
        if parsed < 1:
            return _deep_copy(builtin)
        return parsed
    except Exception:
        return _deep_copy(builtin)


def _normalize_retention(value: Any, builtin: Any) -> Any:
    if value == NEVER_SENTINEL:
        return NEVER_SENTINEL
    if value == DEFAULT_SENTINEL:
        return _deep_copy(builtin)
    if isinstance(value, dict):
        mode = str(value.get("mode") or "interval").strip().lower()
        if mode != "interval":
            return _deep_copy(builtin)
        try:
            amount = int(value.get("value"))
            if amount < 1:
                raise ValueError
        except Exception:
            return _deep_copy(builtin)
        unit = str(value.get("unit") or "year").strip().lower()
        if unit not in {"minute", "hour", "day", "week", "month", "year"}:
            return _deep_copy(builtin)
        return {"mode": "interval", "value": amount, "unit": unit}
    return _deep_copy(builtin)


def _normalize_data_cap(value: Any, builtin: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        return _deep_copy(builtin)
    try:
        amount = float(value.get("amount"))
        if amount <= 0:
            raise ValueError
    except (TypeError, ValueError):
        amount = builtin["amount"]
    unit = str(value.get("unit") or builtin["unit"]).strip().upper()
    if unit not in {"MB", "GB"}:
        unit = builtin["unit"]
    period = value.get("period") if isinstance(value.get("period"), dict) else {}
    try:
        period_value = int(period.get("value"))
        if period_value < 1:
            raise ValueError
    except (TypeError, ValueError):
        period_value = builtin["period"]["value"]
    period_unit = str(period.get("unit") or builtin["period"]["unit"]).strip().lower()
    if period_unit not in {"hour", "day", "week", "month", "year"}:
        period_unit = builtin["period"]["unit"]
    return {"enabled": bool(value.get("enabled")), "amount": amount, "unit": unit, "period": {"value": period_value, "unit": period_unit}}


def _normalize_speed_limit(value: Any, builtin: Any) -> Any:
    if value == UNLIMITED_SENTINEL:
        return UNLIMITED_SENTINEL
    text = str(value or "").strip().lower().replace("/s", "").replace("mbs", "").replace("mb", "").strip()
    try:
        parsed = float(text)
        return parsed if parsed > 0 else _deep_copy(builtin)
    except (TypeError, ValueError):
        return _deep_copy(builtin)


def _normalize_effective_settings(settings: Dict[str, Any], builtin: Dict[str, Any]) -> Dict[str, Any]:
    normalized = _deep_copy(settings)

    dl = normalized["downloadDefaults"]
    dl["defaultMediaMode"] = str(dl.get("defaultMediaMode") or builtin["downloadDefaults"]["defaultMediaMode"]).strip().lower()
    if dl["defaultMediaMode"] not in {"video", "audio"}:
        dl["defaultMediaMode"] = builtin["downloadDefaults"]["defaultMediaMode"]

    dl["defaultVideoFormat"] = str(dl.get("defaultVideoFormat") or builtin["downloadDefaults"]["defaultVideoFormat"]).strip().upper()
    if dl["defaultVideoFormat"] not in VIDEO_OUTPUT_FORMATS:
        dl["defaultVideoFormat"] = builtin["downloadDefaults"]["defaultVideoFormat"]

    dl["defaultAudioFormat"] = str(dl.get("defaultAudioFormat") or builtin["downloadDefaults"]["defaultAudioFormat"]).strip().upper()
    if dl["defaultAudioFormat"] not in AUDIO_OUTPUT_FORMATS:
        dl["defaultAudioFormat"] = builtin["downloadDefaults"]["defaultAudioFormat"]

    normalized["application"]["accentColor"] = normalize_accent(normalized["application"].get("accentColor"))

    for key in ["rememberRecentPaths", "framelessGUI", "legacyDownloadsMigrated"]:
        normalized["application"][key] = bool(normalized["application"].get(key))

    for key in [
        "overwriteExisting",
        "includeVideoQualityInFileName",
        "includeAudioQualityInFileName",
    ]:
        dl[key] = bool(dl.get(key))

    for key in [
        "createPlaylistFolder",
        "addPlaylistIndexToMetadata",
        "addPlaylistIndexToFileName",
    ]:
        normalized["playlist"][key] = bool(normalized["playlist"].get(key))

    normalized["history"]["keepFailedDownloadsInHistory"] = bool(normalized["history"].get("keepFailedDownloadsInHistory"))

    queue_builtin = builtin["queue"]
    normalized["queue"]["maxConcurrentDownloads"] = _normalize_unlimited_or_int(
        normalized["queue"].get("maxConcurrentDownloads"),
        queue_builtin["maxConcurrentDownloads"],
    )

    history_builtin = builtin["history"]
    normalized["history"]["historyRetention"] = _normalize_retention(
        normalized["history"].get("historyRetention"),
        history_builtin["historyRetention"],
    )

    limits_builtin = builtin["limits"]
    normalized["limits"]["dataUsageCap"] = _normalize_data_cap(normalized["limits"].get("dataUsageCap"), limits_builtin["dataUsageCap"])
    normalized["limits"]["maxDownloadSpeedMBPerSecond"] = _normalize_speed_limit(normalized["limits"].get("maxDownloadSpeedMBPerSecond"), limits_builtin["maxDownloadSpeedMBPerSecond"])

    storage = normalized.get("storage", {})
    default_save_path = str(storage.get("defaultSavePath") or "").strip()

    if not default_save_path:
        default_save_path = str(builtin["storage"]["defaultSavePath"])

    normalized["storage"] = {"defaultSavePath": os.path.normpath(os.path.expanduser(default_save_path))}
    for name in ('videoSavePath', 'audioSavePath'):
        custom = str(storage.get(name) or '').strip()
        normalized['storage'][name] = os.path.normpath(os.path.expanduser(custom)) if custom else '' 

    normalized["server"]["host"] = str(normalized["server"].get("host") or builtin["server"]["host"]).strip() or builtin["server"]["host"]
    if normalized["server"]["host"] not in ("127.0.0.1", "localhost", "::1"):
        normalized["server"]["host"] = "127.0.0.1"
    try:
        port = int(normalized["server"].get("port", builtin["server"]["port"]))
        if port < 1 or port > 65535:
            raise ValueError
        normalized["server"]["port"] = port
    except Exception:
        normalized["server"]["port"] = builtin["server"]["port"]

    ai = normalized["aiTool"]
    for key in ("enabled", "enableDownloads", "enableHistoryRemoval", "enableSettingsUpdates"):
        ai[key] = ai[key] if isinstance(ai.get(key), bool) else builtin["aiTool"][key]
    normalized["schemaVersion"] = SCHEMA_VERSION

    runtime_builtin = builtin["runtime"]
    runtime_user = normalized.get("runtime", {}) if isinstance(normalized.get("runtime"), dict) else {}
    runtime_effective = _deep_copy(runtime_builtin)
    for key in ("ytdlpBin", "ffmpegPath", "ffprobePath", "ytdlpJsRuntime", "ytdlpCookiesPath"):
        override = runtime_user.get(key)
        if override not in (None, DEFAULT_SENTINEL, ''):
            runtime_effective[key] = str(override).strip()
    cookies_path = str(runtime_effective.get('ytdlpCookiesPath') or '').strip()
    runtime_effective['ytdlpCookiesPath'] = os.path.normpath(os.path.expanduser(cookies_path)) if cookies_path else ''

    normalized["runtime"] = runtime_effective
    return normalized


def load_user_settings_config() -> Dict[str, Any]:
    _ensure_settings_dir()

    if not SETTINGS_PATH.exists() or SETTINGS_PATH.stat().st_size == 0:
        initial = _deep_copy(RAW_DEFAULT_CONFIG)
        _save_json(SETTINGS_PATH, initial)
        return initial

    try:
        payload = _load_json(SETTINGS_PATH)
    except Exception:
        payload = {}

    limits = payload.get("limits") if isinstance(payload.get("limits"), dict) else {}
    if "maxDownloadSpeedBytesPerSecond" in limits and "maxDownloadSpeedMBPerSecond" not in limits:
        legacy_speed = limits.pop("maxDownloadSpeedBytesPerSecond")
        limits["maxDownloadSpeedMBPerSecond"] = DEFAULT_SENTINEL if legacy_speed == DEFAULT_SENTINEL else (UNLIMITED_SENTINEL if legacy_speed == UNLIMITED_SENTINEL else round(float(legacy_speed) / 1_000_000, 6))
    legacy_cap = limits.get("dataUsageCap")
    if legacy_cap == UNLIMITED_SENTINEL:
        limits["dataUsageCap"] = {"enabled": False, "amount": DEFAULT_SENTINEL, "unit": DEFAULT_SENTINEL, "period": {"value": DEFAULT_SENTINEL, "unit": DEFAULT_SENTINEL}}
    elif isinstance(legacy_cap, dict) and "mode" in legacy_cap:
        amount_bytes = float(legacy_cap.get("amountBytes") or 20_000_000_000)
        reset = legacy_cap.get("resetInterval") if isinstance(legacy_cap.get("resetInterval"), dict) else {}
        limits["dataUsageCap"] = {"enabled": str(legacy_cap.get("mode")).lower() == "capped", "amount": amount_bytes / 1_000_000_000, "unit": "GB", "period": {"value": reset.get("value", 1), "unit": reset.get("unit", "month")}}
    payload["limits"] = limits
    shaped = _shape_user_config(RAW_DEFAULT_CONFIG, payload)
    
    
    
    app = shaped['application']
    if app.get('legacyDownloadsMigrated') is not True:
        saved_root = str(shaped['storage'].get('defaultSavePath') or '')
        old_root = str(Path.home() / 'Downloads' / 'YouSnipe')
        if os.path.normcase(os.path.normpath(os.path.expanduser(saved_root))) == os.path.normcase(os.path.normpath(old_root)):
            shaped['storage']['defaultSavePath'] = DEFAULT_SENTINEL
        app['legacyDownloadsMigrated'] = True
    if shaped != payload:
        _save_json(SETTINGS_PATH, shaped)
    return shaped


def get_effective_settings() -> Dict[str, Any]:
    builtin = build_builtin_settings()
    user_config = load_user_settings_config()

    effective = {
        "schemaVersion": SCHEMA_VERSION,
        "server": _resolve_config_value(user_config.get("server", {}), builtin["server"]),
        "aiTool": _resolve_config_value(user_config.get("aiTool", {}), builtin["aiTool"]),
        "application": _resolve_config_value(user_config.get("application", {}), builtin["application"]),
        "downloadDefaults": _resolve_config_value(user_config.get("downloadDefaults", {}), builtin["downloadDefaults"]),
        "storage": _resolve_config_value(user_config.get("storage", {}), builtin["storage"]),
        "queue": _resolve_config_value(user_config.get("queue", {}), builtin["queue"]),
        "playlist": _resolve_config_value(user_config.get("playlist", {}), builtin["playlist"]),
        "history": _resolve_config_value(user_config.get("history", {}), builtin["history"]),
        "limits": _resolve_config_value(user_config.get("limits", {}), builtin["limits"]),
        "runtime": _resolve_config_value(user_config.get("runtime", {}), {
            key: builtin["runtime"].get(key, "") for key in RAW_DEFAULT_CONFIG["runtime"]
        }),
    }
    raw_history = user_config.get('history', {})
    if isinstance(raw_history, dict) and raw_history.get('historyRetention') == NEVER_SENTINEL:
        effective['history']['historyRetention'] = NEVER_SENTINEL
    return _normalize_effective_settings(effective, builtin)


def get_runtime_config() -> Dict[str, Any]:
    settings = get_effective_settings()
    return settings.get("runtime", {})


def update_settings(changes: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(changes, dict):
        raise ValueError("Settings update must be an object")
    current = load_user_settings_config()
    for section, values in changes.items():
        if section not in RAW_DEFAULT_CONFIG or section == "schemaVersion" or not isinstance(values, dict):
            raise ValueError(f"Unknown settings section: {section}")
        allowed = RAW_DEFAULT_CONFIG[section]
        for key, value in values.items():
            if key not in allowed:
                raise ValueError(f"Unknown setting: {section}.{key}")
            if isinstance(allowed[key], dict):
                if not isinstance(value, dict):
                    raise ValueError(f"Invalid setting value: {section}.{key}")
                current[section][key].update(value)
            else:
                current[section][key] = value
    if current.get("aiTool"):
        for key in ("enabled", "enableDownloads", "enableHistoryRemoval", "enableSettingsUpdates"):
            val = current["aiTool"][key]
            if val != DEFAULT_SENTINEL and not isinstance(val, bool):
                raise ValueError(f"{key} must be a boolean")
    accent = current["application"]["accentColor"]
    if accent != DEFAULT_SENTINEL and (not isinstance(accent, str) or normalize_accent(accent) != accent.strip().upper()):
        raise ValueError("Accent colour must be a six-digit HEX colour such as #A855F7")
    if accent != DEFAULT_SENTINEL:
        current["application"]["accentColor"] = accent.strip().upper()
    server_port = current['server']['port']
    server_port = build_builtin_settings()['server']['port'] if server_port == DEFAULT_SENTINEL else int(server_port)
    if not 1 <= server_port <= 65535:
        raise ValueError('Server port must be between 1 and 65535')
    _save_json(SETTINGS_PATH, current)
    return get_effective_settings()
