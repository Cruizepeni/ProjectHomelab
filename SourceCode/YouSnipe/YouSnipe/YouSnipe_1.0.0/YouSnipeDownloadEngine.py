import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import re

from YouSnipeSettings import get_effective_settings, get_runtime_config
from YouSnipeProgress import build_ytdlp_progress_args, run_ytdlp_with_progress, send_stage_progress
from YouSnipeCommon import raise_for_ytdlp_error, run_subprocess_capture, sanitize_filename
from YouSnipeSpeedLimiter import build_ytdlp_speed_limit_args

_RUNTIME = get_runtime_config()
YTDLP_BIN = _RUNTIME.get("ytdlpBin", "yt-dlp")
VIDEO_OUTPUT_FORMATS = _RUNTIME.get("videoOutputFormats", ["MP4", "MKV", "WEBM", "MOV", "AVI", "WMV", "FLV"])
AUDIO_OUTPUT_FORMATS = _RUNTIME.get("audioOutputFormats", ["MP3", "M4A", "MP4", "MPA", "WAV", "AAC", "FLAC", "OGG", "ALAC", "WMA"])
VIDEO_QUALITY_ORDER = _RUNTIME.get("videoQualityOrder", [4320, 2160, 1440, 1080, 720, 480, 360, 240, 144])
AUDIO_QUALITY_ORDER = _RUNTIME.get("audioQualityOrder", [512, 320, 256, 192, 160, 128, 96, 64])


def _build_ytdlp_runtime_args() -> list[str]:
    runtime_cfg = get_runtime_config()
    args: list[str] = []

    js_runtime = str(runtime_cfg.get("ytdlpJsRuntime") or "").strip()
    if js_runtime and js_runtime.lower() != "default":
        args.extend(["--js-runtimes", js_runtime])

    cookies_path = str(runtime_cfg.get("ytdlpCookiesPath") or "").strip()
    if cookies_path and cookies_path.lower() != "default" and Path(cookies_path).exists():
        args.extend(["--cookies", cookies_path])

    return args


def _build_ytdlp_download_args() -> list[str]:
    runtime_cfg = get_runtime_config()
    args = [*_build_ytdlp_runtime_args(), *build_ytdlp_speed_limit_args(get_effective_settings())]

    ffmpeg_path = str(runtime_cfg.get("ffmpegPath") or "").strip()
    if ffmpeg_path and Path(ffmpeg_path).exists():
        args.extend(["--ffmpeg-location", str(Path(ffmpeg_path).parent)])

    return args


def pick_best_video_info(formats: list) -> dict | None:
    candidates = [f for f in formats if f.get("vcodec") != "none" and f.get("height")]
    if not candidates:
        return None
    return max(candidates, key=lambda f: int(f.get("height") or 0))


def pick_best_audio_info(formats: list) -> dict | None:
    candidates = [
        f
        for f in formats
        if f.get("acodec") != "none" and f.get("abr") is not None
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda f: float(f.get("abr") or 0))


def build_video_quality_options(max_height: int | None) -> list[str]:
    if not max_height:
        return []
    return [str(q) for q in VIDEO_QUALITY_ORDER if q <= max_height]


def build_audio_quality_options(max_abr: int | None) -> list[str]:
    if not max_abr:
        return []
    return [str(q) for q in AUDIO_QUALITY_ORDER if q <= max_abr]


def _should_treat_as_playlist_url(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    query = parse_qs(parsed.query)

    if "youtube.com" in host or "youtu.be" in host:
        if "/playlist" in path or path.endswith("/playlists"):
            return True

        
        
        
        if path.endswith("/watch") and query.get("v"):
            return False

        if "list" in query and not query.get("v"):
            return True

    return False


def resolve_playlist_entry_url(entry: dict) -> str | None:
    
    if not isinstance(entry, dict):
        return None
    for key in ("webpage_url", "url", "original_url"):
        candidate = str(entry.get(key) or "").strip()
        parsed = urlparse(candidate)
        if parsed.scheme.lower() in {"http", "https"} and parsed.hostname:
            return candidate

    
    key = str(entry.get("ie_key") or entry.get("extractor_key") or "").lower()
    ident = str(entry.get("id") or entry.get("url") or "").strip()
    if key in {"youtube", "youtubeie"} and re.fullmatch(r"[a-zA-Z0-9_-]{11}", ident):
        return f"https://www.youtube.com/watch?v={ident}"
    if key in {"youtubeshorts"} and re.fullmatch(r"[a-zA-Z0-9_-]{11}", ident):
        return f"https://www.youtube.com/shorts/{ident}"
    return None


def build_metadata_response(video_info: dict) -> dict:
    entries = video_info.get("entries")
    if isinstance(entries, list):
        playlist_title = sanitize_filename(video_info.get("title", "Unknown Playlist"))
        playlist_items = []
        highest_quality_options = ["Highest"]

        video_qualities_by_format = {
            fmt: highest_quality_options[:] for fmt in VIDEO_OUTPUT_FORMATS
        }
        audio_qualities_by_format = {
            fmt: highest_quality_options[:] for fmt in AUDIO_OUTPUT_FORMATS
        }

        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue

            item_title = sanitize_filename(entry.get("title", f"Item {index + 1}"))
            item_url = resolve_playlist_entry_url(entry) or ""

            playlist_items.append({
                "id": str(entry.get("id") or item_url or index),
                "name": item_title,
                "title": item_title,
                "url": item_url,
                "available": bool(item_url),
                "unavailableReason": "Playlist entry has no resolvable webpage URL" if not item_url else "",
                "thumbnail": entry.get("thumbnail") or "",
                "duration": entry.get("duration"),
                "index": index + 1,
            })

        return {
            "type": "metadata_response",
            "success": True,
            "data": {
                "originalFileName": playlist_title,
                "thumbnail": playlist_items[0].get("thumbnail", "") if playlist_items else "",
                "mediaType": "playlist",
                "playlist": {
                    "name": playlist_title,
                    "items": playlist_items,
                    "count": len(playlist_items),
                },
                "video": {
                    "nativeFormat": "",
                    "nativeQuality": "Highest",
                    "formats": VIDEO_OUTPUT_FORMATS,
                    "qualitiesByFormat": video_qualities_by_format,
                },
                "audio": {
                    "nativeFormat": "",
                    "nativeQuality": "Highest",
                    "formats": AUDIO_OUTPUT_FORMATS,
                    "qualitiesByFormat": audio_qualities_by_format,
                },
                "defaultFormat": "MP4",
                "defaultQuality": "Highest",
                "nativeFormat": "",
                "nativeQuality": "Highest",
            },
        }

    title = sanitize_filename(video_info.get("title", "Unknown Title"))
    thumbnail = video_info.get("thumbnail", "")
    formats = video_info.get("formats", [])

    best_video = pick_best_video_info(formats)
    best_audio = pick_best_audio_info(formats)

    native_video_format = (best_video.get("ext", "") if best_video else "").upper()
    native_video_quality = (
        str(int(best_video.get("height")))
        if best_video and best_video.get("height")
        else ""
    )

    native_audio_format = (best_audio.get("ext", "") if best_audio else "").upper()
    native_audio_quality = (
        str(int(float(best_audio.get("abr"))))
        if best_audio and best_audio.get("abr") is not None
        else ""
    )

    max_video_height = (
        int(best_video.get("height"))
        if best_video and best_video.get("height")
        else None
    )
    max_audio_abr = (
        int(float(best_audio.get("abr")))
        if best_audio and best_audio.get("abr") is not None
        else None
    )

    video_quality_options = build_video_quality_options(max_video_height)
    audio_quality_options = build_audio_quality_options(max_audio_abr)

    video_qualities_by_format = {
        fmt: video_quality_options[:] for fmt in VIDEO_OUTPUT_FORMATS
    }

    audio_qualities_by_format = {
        "MP3": audio_quality_options[:] or ["320", "256", "192", "128"],
        "AAC": [q for q in (audio_quality_options[:] or ["256", "192", "128"]) if int(q) <= 256],
        "OGG": [q for q in (audio_quality_options[:] or ["256", "192", "128"]) if int(q) <= 256],
        "WMA": [q for q in (audio_quality_options[:] or ["192", "128"]) if int(q) <= 192],
        "WAV": ["LOSSLESS"],
        "FLAC": ["LOSSLESS"],
        "ALAC": ["LOSSLESS"],
        "M4A": audio_quality_options[:] or ["256", "192", "128"],
        "MP4": audio_quality_options[:] or ["256", "192", "128"],
        "MPA": [q for q in (audio_quality_options[:] or ["256", "192", "128"]) if int(q) <= 384],
    }

    default_format = "MP4" if video_quality_options else "MP3"
    default_quality = (
        video_quality_options[0]
        if video_quality_options
        else (audio_quality_options[0] if audio_quality_options else "320")
    )
    media_type = "video" if video_quality_options else "audio"

    return {
        "type": "metadata_response",
        "success": True,
        "data": {
            "originalFileName": title,
            "thumbnail": thumbnail,
            "mediaType": media_type,
            "video": {
                "nativeFormat": native_video_format,
                "nativeQuality": native_video_quality,
                "formats": VIDEO_OUTPUT_FORMATS,
                "qualitiesByFormat": video_qualities_by_format,
            },
            "audio": {
                "nativeFormat": native_audio_format,
                "nativeQuality": native_audio_quality,
                "formats": AUDIO_OUTPUT_FORMATS,
                "qualitiesByFormat": audio_qualities_by_format,
            },
            "defaultFormat": default_format,
            "defaultQuality": default_quality,
            "nativeFormat": native_video_format if media_type == "video" else native_audio_format,
            "nativeQuality": native_video_quality if media_type == "video" else native_audio_quality,
        },
    }


async def fetch_metadata(url: str, force_playlist: bool = False) -> dict:
    cmd = [get_runtime_config().get("ytdlpBin", "yt-dlp"), "--dump-single-json", *_build_ytdlp_runtime_args()]

    if force_playlist or _should_treat_as_playlist_url(url):
        cmd.extend(["--yes-playlist", "--flat-playlist", "--skip-download"])
    else:
        cmd.append("--no-playlist")

    cmd.append(url)
    return_code, stdout, stderr = await run_subprocess_capture(cmd)

    if return_code != 0:
        raise_for_ytdlp_error(stderr, "yt-dlp failed to fetch metadata", url)

    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Failed to decode yt-dlp metadata JSON: {exc}") from exc


async def download_video_with_audio(
    url: str,
    output_template: str,
    websocket,
    start_pct: int = 1,
    end_pct: int = 70,
    allow_playlist: bool = False,
    progress_context: dict | None = None,
    network_progress_callback=None,
    progress_callback=None,
    quality_requested: str = "",
) -> None:
    await send_stage_progress(websocket, "downloading_video", max(0, start_pct - 1), **(progress_context or {}))
    playlist_flag = [] if allow_playlist else ["--no-playlist"]

    
    sort_args = ["-S", f"res:{quality_requested},fps"] if str(quality_requested).isdigit() else []

    
    await run_ytdlp_with_progress(
        [
            get_runtime_config().get("ytdlpBin", "yt-dlp"), *build_ytdlp_progress_args(), *_build_ytdlp_download_args(), *playlist_flag,
            "-f", "bestvideo+bestaudio/best", *sort_args, "--merge-output-format", "mkv",
            "-o", output_template, url,
        ],
        websocket,
        "downloading_video",
        start_pct,
        end_pct,
        progress_context=progress_context,
        network_progress_callback=network_progress_callback,
        progress_callback=progress_callback,
        expected_streams=2,
    )


async def download_best_audio(
    url: str,
    output_template: str,
    websocket,
    start_pct: int = 1,
    end_pct: int = 70,
    allow_playlist: bool = False,
    progress_context: dict | None = None,
    network_progress_callback=None,
    progress_callback=None,
) -> None:
    await send_stage_progress(websocket, "downloading_audio", max(0, start_pct - 1), **(progress_context or {}))
    playlist_flag = [] if allow_playlist else ["--no-playlist"]
    await run_ytdlp_with_progress(
        [get_runtime_config().get("ytdlpBin", "yt-dlp"), *build_ytdlp_progress_args(), *_build_ytdlp_download_args(), *playlist_flag, "-f", "bestaudio", "-o", output_template, url],
        websocket,
        "downloading_audio",
        start_pct,
        end_pct,
        progress_context=progress_context,
        network_progress_callback=network_progress_callback,
        progress_callback=progress_callback,
    )


async def probe_media_file(file_path: str) -> dict:
    runtime_cfg = get_runtime_config()
    ffprobe_path = str(runtime_cfg.get("ffprobePath") or "ffprobe").strip()
    command = [
        ffprobe_path,
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        file_path,
    ]
    return_code, stdout, _ = await run_subprocess_capture(command)
    if return_code != 0:
        return {}

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return {}

    streams = payload.get("streams") or []
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), {})
    container = str((payload.get("format") or {}).get("format_name") or "")

    try:
        duration = float((payload.get("format") or {}).get("duration"))
    except (TypeError, ValueError):
        duration = None

    return {
        "durationSeconds": duration,
        "videoCodec": video_stream.get("codec_name"),
        "audioCodec": audio_stream.get("codec_name"),
        "audioBitrateKbps": round(float(audio_stream["bit_rate"]) / 1000) if str(audio_stream.get("bit_rate") or "").isdigit() else None,
        "height": video_stream.get("height"),
        "width": video_stream.get("width"),
        "container": container,
    }