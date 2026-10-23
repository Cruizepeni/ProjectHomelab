import asyncio
import subprocess
import json
import os
import re
import sys
from pathlib import Path

from YouSnipeSettings import get_runtime_config

_RUNTIME = get_runtime_config()
AUDIO_OUTPUT_FORMATS = _RUNTIME.get("audioOutputFormats", ["MP3", "M4A", "MP4", "MPA", "WAV", "AAC", "FLAC", "OGG", "ALAC", "WMA"])
VIDEO_OUTPUT_FORMATS = _RUNTIME.get("videoOutputFormats", ["MP4", "MKV", "WEBM", "MOV", "AVI", "WMV", "FLV"])


def sanitize_filename(filename: str) -> str:
    if not filename:
        return "Unknown Title"
    sanitized = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "", filename)
    sanitized = re.sub(r"\s+", " ", sanitized).strip()
    return sanitized or "Unknown Title"


def ensure_directory(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def get_final_filename(original_name: str, custom_name: str | None) -> str:
    if custom_name and custom_name.strip():
        return sanitize_filename(custom_name)
    return sanitize_filename(original_name)


def is_video_format(fmt: str) -> bool:
    return fmt.upper() in VIDEO_OUTPUT_FORMATS


def is_audio_format(fmt: str) -> bool:
    return fmt.upper() in AUDIO_OUTPUT_FORMATS


_AUTH_CHALLENGE_MARKERS = (
    "confirm your age",
    "this video is private",
    "members-only content",
    "login required",
    "account cookies are no longer valid",
    "use --cookies-from-browser or --cookies",
)


class YouSnipeAuthRequiredError(RuntimeError):
    code = "AUTH_REQUIRED"


class YouSnipeYouTubeAccessError(RuntimeError):
    code = "YOUTUBE_ACCESS_RESTRICTED"


class YouSnipeRateLimitedError(RuntimeError):
    code = "RATE_LIMITED"


_YOUTUBE_RESTRICTION_MARKERS = (
    "sign in to confirm you're not a bot",
    "sign in to confirm you’re not a bot",
    "unusual traffic from your computer network",
    "this ip address has been blocked",
    "youtube has restricted",
)




def is_auth_challenge(stderr: str) -> bool:
    lowered = stderr.lower()
    return any(marker in lowered for marker in _AUTH_CHALLENGE_MARKERS)


def concise_ytdlp_error(stderr: str) -> str:
    lines = [line.strip() for line in stderr.splitlines() if line.strip().startswith("ERROR:")]
    return (lines[-1] if lines else stderr.strip()).split("See  https://")[0].strip()


def raise_for_ytdlp_error(stderr: str, fallback: str, url: str = "") -> None:
    message = concise_ytdlp_error(stderr) or fallback
    lowered = stderr.casefold()
    youtube = any(host in url.casefold() for host in ('youtube.com', 'youtu.be', 'youtube-nocookie.com')) or '[youtube]' in lowered
    restricted = any(marker in lowered for marker in _YOUTUBE_RESTRICTION_MARKERS)
    rate_limited = 'http error 429' in lowered or '429: too many requests' in lowered or 'http error 402' in lowered
    if youtube and (restricted or rate_limited):
        raise YouSnipeYouTubeAccessError(
            'YouTube may be temporarily restricting downloads from your public IP address or network. '
            'Pause further downloads and try again later. Check the video in your browser; '
            'you can also try another Wi-Fi network or a VPN to change your IP address if appropriate. '
            'Changing IP addresses will not resolve every YouTube challenge. Details: ' + message
        )
    if rate_limited:
        raise YouSnipeRateLimitedError('The website is rate limiting downloads. Wait before retrying. Details: ' + message)
    if is_auth_challenge(stderr):
        raise YouSnipeAuthRequiredError(message)
    raise RuntimeError(stderr.strip() or fallback)


def safe_json_dumps(data) -> str:
    return json.dumps(data, ensure_ascii=False)


async def send_ws(websocket, payload: dict) -> None:
    try:
        await websocket.send(safe_json_dumps(payload))
    except Exception as exc:
        print(f"Failed to send websocket message: {exc}")


async def send_error(websocket, message: str, code: str = "GENERAL_ERROR") -> None:
    await send_ws(
        websocket,
        {
            "type": "error",
            "code": code,
            "message": message,
        },
    )


async def run_subprocess_capture(
    cmd: list[str], cwd: str | None = None
) -> tuple[int, str, str]:
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=creationflags,
        )
    except (OSError, NotImplementedError) as exc:
        
        
        
        
        if sys.platform != "win32" or (
            isinstance(exc, OSError) and getattr(exc, "winerror", None) != 50
        ):
            raise

        def capture_without_asyncio_transport():
            completed = subprocess.run(
                cmd,
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                creationflags=creationflags,
            )
            return completed.returncode, completed.stdout, completed.stderr

        returncode, stdout, stderr = await asyncio.to_thread(capture_without_asyncio_transport)
    else:
        stdout, stderr = await process.communicate()
        returncode = process.returncode
    return (
        returncode,
        stdout.decode("utf-8", errors="replace"),
        stderr.decode("utf-8", errors="replace"),
    )


class _ThreadedStream:
    def __init__(self, stream):
        self._stream = stream

    async def readline(self):
        return await asyncio.to_thread(self._stream.readline)


class _ThreadedProcess:
    def __init__(self, process):
        self._process = process
        self.stdout = _ThreadedStream(process.stdout) if process.stdout else None
        self.stderr = _ThreadedStream(process.stderr) if process.stderr else None

    @property
    def returncode(self):
        return self._process.poll()

    async def wait(self):
        return await asyncio.to_thread(self._process.wait)

    def terminate(self):
        self._process.terminate()

    def kill(self):
        self._process.kill()


async def start_streaming_process(command: list[str], merge_stderr: bool = False):
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    stderr = asyncio.subprocess.STDOUT if merge_stderr else asyncio.subprocess.PIPE
    try:
        return await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=stderr,
            creationflags=creationflags,
        )
    except (OSError, NotImplementedError) as exc:
        if sys.platform != "win32" or (isinstance(exc, OSError) and getattr(exc, "winerror", None) != 50):
            raise
        process = await asyncio.to_thread(
            subprocess.Popen,
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT if merge_stderr else subprocess.PIPE,
            creationflags=creationflags,
        )
        return _ThreadedProcess(process)


def find_first_matching_file(directory: str, pattern: str) -> str | None:
    matches = list(Path(directory).glob(pattern))
    if not matches:
        return None
    return str(matches[0])


def file_exists_and_nonzero(path: str) -> bool:
    return os.path.exists(path) and os.path.getsize(path) > 0