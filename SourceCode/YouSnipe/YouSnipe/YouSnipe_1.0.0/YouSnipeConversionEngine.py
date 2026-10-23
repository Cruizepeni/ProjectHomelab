from YouSnipeSettings import get_runtime_config
from YouSnipeProgress import run_ffmpeg_with_stage_progress

_RUNTIME = get_runtime_config()
FFMPEG_PATH = _RUNTIME.get("ffmpegPath", "ffmpeg")

_CONTAINER_VIDEO_CODECS = {
    "MP4": {"h264", "hevc", "av1"},
    "MOV": {"h264", "hevc"},
    "MKV": {"h264", "hevc", "av1", "vp9", "vp8"},
    "WEBM": {"vp9", "vp8", "av1"},
}

_CONTAINER_AUDIO_CODECS = {
    "MP4": {"aac", "mp3"},
    "MOV": {"aac", "mp3"},
    "MKV": {"aac", "mp3", "opus", "vorbis", "flac"},
    "WEBM": {"opus", "vorbis"},
}

_HIGHEST_AUDIO_ARGS = {
    "MP3": ["-q:a", "0"],
    "M4A": ["-b:a", "256k"],
    "MP4": ["-b:a", "256k"],
    "MPA": ["-b:a", "256k"],
    "AAC": ["-b:a", "256k"],
    "OGG": ["-q:a", "8"],
    "WMA": ["-b:a", "192k"],
}


def plan_video_output(source_info: dict, format_requested: str, quality_requested: str, source_extension: str = "") -> dict:
    
    source_height = source_info.get("height")
    requested_height = int(quality_requested) if str(quality_requested).isdigit() else None

    
    needs_scaling = bool(requested_height and source_height and source_height > requested_height)

    video_codec = str(source_info.get("videoCodec") or "").lower()
    audio_codec = str(source_info.get("audioCodec") or "").lower()
    compatible = (
        video_codec in _CONTAINER_VIDEO_CODECS.get(format_requested, set())
        and audio_codec in _CONTAINER_AUDIO_CODECS.get(format_requested, set())
    )

    if not needs_scaling and compatible:
        if source_extension.lstrip('.').upper() == format_requested.upper():
            return {"mode": "direct", "needsScaling": False}
        return {"mode": "remux", "needsScaling": False}
    return {"mode": "transcode", "needsScaling": needs_scaling}


def plan_audio_output(source_info: dict, format_requested: str, quality_requested: str, source_extension: str = "") -> dict:
    expected = {
        "MP3": "mp3", "AAC": "aac", "OGG": "vorbis", "WMA": "wmav2",
        "WAV": "pcm_s16le", "FLAC": "flac", "ALAC": "alac",
        "M4A": "aac", "MP4": "aac", "MPA": "mp2",
    }
    source_codec = str(source_info.get('audioCodec') or '').casefold()
    extension = 'M4A' if format_requested.upper() == 'ALAC' else format_requested.upper()
    direct = (source_codec == expected.get(format_requested.upper())
              and source_extension.lstrip('.').upper() == extension
              and not str(quality_requested).isdigit())
    return {'mode': 'direct' if direct else 'convert'}


def build_video_convert_command(
    input_file: str,
    output_path: str,
    format_requested: str,
    quality_requested: str,
    plan: dict | None = None,
) -> list[str]:
    cmd = [
        get_runtime_config().get("ffmpegPath", "ffmpeg"),
        "-y",
        "-i",
        input_file,
    ]

    if plan and plan.get("mode") == "remux":
        cmd.extend(["-c", "copy"])
        if format_requested in {"MP4", "MOV"}:
            cmd.extend(["-movflags", "+faststart"])
        cmd.append(output_path)
        return cmd

    if quality_requested.isdigit() and (plan is None or plan.get("needsScaling", True)):
        cmd.extend(["-vf", f"scale=-2:{quality_requested}"])

    if format_requested == "WEBM":
        cmd.extend(["-c:v", "libvpx-vp9", "-crf", "32", "-b:v", "0", "-row-mt", "1", "-c:a", "libopus", "-b:a", "160k"])
    elif format_requested == "WMV":
        cmd.extend(["-c:v", "wmv2", "-c:a", "wmav2"])
    elif format_requested == "AVI":
        cmd.extend(["-c:v", "mpeg4", "-c:a", "mp3"])
    elif format_requested in {"MP4", "MOV", "FLV", "MKV"}:
        cmd.extend(
            [
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "23",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
            ]
        )
        if format_requested in {"MP4", "MOV"}:
            cmd.extend(["-movflags", "+faststart"])
    else:
        raise ValueError(f"Unsupported video output format: {format_requested}")

    cmd.append(output_path)
    return cmd


def build_audio_convert_command(
    input_audio_file: str,
    output_path: str,
    format_requested: str,
    quality_requested: str,
    source_info: dict | None = None,
) -> list[str]:
    cmd = [
        get_runtime_config().get("ffmpegPath", "ffmpeg"),
        "-y",
        "-i",
        input_audio_file,
    ]

    source_codec = str((source_info or {}).get("audioCodec") or "").lower()
    copy_compatible = {
        "MP3": "mp3", "AAC": "aac", "OGG": "vorbis", "WMA": "wmav2",
        "WAV": "pcm_s16le", "FLAC": "flac", "ALAC": "alac",
        "M4A": "aac", "MP4": "aac", "MPA": "mp2",
    }
    
    if source_codec == copy_compatible.get(format_requested) and not quality_requested.isdigit():
        cmd.extend(["-vn", "-c:a", "copy", output_path])
        return cmd

    lossy_codecs = {"MP3": "libmp3lame", "M4A": "aac", "MP4": "aac", "MPA": "mp2", "AAC": "aac", "OGG": "libvorbis", "WMA": "wmav2"}
    lossless_codecs = {"WAV": "pcm_s16le", "FLAC": "flac", "ALAC": "alac"}

    if format_requested == "MPA" and quality_requested.isdigit() and int(quality_requested) > 384:
        raise ValueError("MPA (MPEG Layer II) bitrate cannot exceed 384 kbps")
    if format_requested in lossy_codecs:
        cmd.extend(["-codec:a", lossy_codecs[format_requested]])
        if quality_requested.isdigit():
            cmd.extend(["-b:a", f"{quality_requested}k"])
        else:
            
            cmd.extend(_HIGHEST_AUDIO_ARGS[format_requested])
    elif format_requested in lossless_codecs:
        cmd.extend(["-codec:a", lossless_codecs[format_requested]])
    else:
        raise ValueError(f"Unsupported audio output format: {format_requested}")

    cmd.extend(["-vn", output_path])
    return cmd


async def convert_video_file(
    websocket,
    input_file: str,
    output_path: str,
    format_requested: str,
    quality_requested: str,
    duration_seconds: float | None = None,
    progress_context: dict | None = None,
    plan: dict | None = None,
    progress_callback=None,
) -> None:
    cmd = build_video_convert_command(
        input_file=input_file,
        output_path=output_path,
        format_requested=format_requested.upper(),
        quality_requested=str(quality_requested).upper(),
        plan=plan,
    )

    await run_ffmpeg_with_stage_progress(
        cmd=cmd,
        websocket=websocket,
        stage="converting_video",
        start_pct=71,
        end_pct=96,
        duration_seconds=duration_seconds,
        progress_context=progress_context,
        progress_callback=progress_callback,
    )


async def convert_audio_file(
    websocket,
    input_audio_file: str,
    output_path: str,
    format_requested: str,
    quality_requested: str,
    duration_seconds: float | None = None,
    progress_context: dict | None = None,
    progress_callback=None,
    source_info: dict | None = None,
) -> None:
    cmd = build_audio_convert_command(
        input_audio_file=input_audio_file,
        output_path=output_path,
        format_requested=format_requested.upper(),
        quality_requested=str(quality_requested).upper(),
        source_info=source_info,
    )

    await run_ffmpeg_with_stage_progress(
        cmd=cmd,
        websocket=websocket,
        stage="converting_audio",
        start_pct=71,
        end_pct=96,
        duration_seconds=duration_seconds,
        progress_context=progress_context,
        progress_callback=progress_callback,
    )