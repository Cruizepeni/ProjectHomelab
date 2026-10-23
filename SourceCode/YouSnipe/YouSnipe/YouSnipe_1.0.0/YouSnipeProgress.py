import asyncio
import subprocess
import re
import time
from collections import deque

from YouSnipeCommon import raise_for_ytdlp_error, send_ws, start_streaming_process

PROGRESS_PREFIX = "YOUSNIPE_PROGRESS"

YTDLP_PROGRESS_TEMPLATE = (
    f"download:{PROGRESS_PREFIX}"
    "|%(progress.status)s"
    "|%(progress.downloaded_bytes)s"
    "|%(progress.total_bytes)s"
    "|%(progress.total_bytes_estimate)s"
    "|%(progress.speed)s"
    "|%(progress.eta)s"
    "|%(info.format_id)s"
)

_UNKNOWN_VALUES = {"", "na", "none", "unknown", "-"}


def build_ytdlp_progress_args(interval_seconds: float = 0.5) -> list[str]:
    return [
        "--newline",
        "--progress",
        "--progress-template",
        YTDLP_PROGRESS_TEMPLATE,
        "--progress-delta",
        str(interval_seconds),
    ]


def _numeric(raw_value: str) -> float | None:
    text = str(raw_value or "").strip()
    if text.lower() in _UNKNOWN_VALUES:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_ytdlp_progress_line(line: str) -> dict | None:
    if not line.startswith(PROGRESS_PREFIX):
        return None

    fields = line.split("|")
    if len(fields) < 7:
        return None

    status = fields[1].strip().lower()
    downloaded = _numeric(fields[2])
    total = _numeric(fields[3]) or _numeric(fields[4])
    speed = _numeric(fields[5])
    eta = _numeric(fields[6])
    stream_id = fields[7].strip() if len(fields) > 7 else ""

    transfer_percent = None
    if downloaded is not None and total:
        transfer_percent = max(0.0, min(100.0, (downloaded / total) * 100.0))

    return {
        "status": status or "downloading",
        "streamId": stream_id,
        "downloadedBytes": int(downloaded) if downloaded is not None else None,
        "totalBytes": int(total) if total else None,
        "speedBytesPerSecond": speed,
        "etaSeconds": eta,
        "transferPercent": transfer_percent,
    }


class EtaSmoother:
    

    def __init__(self, weight: float = 0.7) -> None:
        self._weight = weight
        self._value: float | None = None

    def update(self, sample: float | None) -> float | None:
        if sample is None:
            return self._value
        if self._value is None:
            self._value = sample
        else:
            self._value = (self._value * self._weight) + (sample * (1 - self._weight))
        return max(0.0, self._value)

    def reset(self) -> None:
        self._value = None


class DownloadProgressAggregator:
    

    def __init__(self, expected_streams: int = 1) -> None:
        self.expected_streams = max(1, expected_streams)
        self._streams: dict[str, dict] = {}
        self._order: list[str] = []
        self._last_percent = 0.0

    def update(self, metrics: dict) -> dict:
        stream_id = str(metrics.get("streamId") or "default")
        if stream_id not in self._streams:
            self._order.append(stream_id)
        self._streams[stream_id] = metrics
        downloaded = sum(max(0, stream.get("downloadedBytes") or 0) for stream in self._streams.values())
        totals = [stream.get("totalBytes") for stream in self._streams.values()]

        if self.expected_streams > 1:
            
            
            if len(self._order) == 1:
                percent = (metrics.get("transferPercent") or 0.0) * 0.85
            elif len(self._order) == 2 and all(totals):
                percent = 100.0 * downloaded / sum(totals)
            else:
                step = min(self._order.index(stream_id), self.expected_streams - 1)
                percent = ((step + (metrics.get("transferPercent") or 0.0) / 100.0)
                           / max(len(self._order), self.expected_streams)) * 100.0
        elif all(totals) and totals:
            percent = 100.0 * downloaded / sum(totals)
        else:
            percent = metrics.get("transferPercent") or 0.0

        
        percent = min(99.0, max(self._last_percent, percent))
        self._last_percent = percent
        return {
            **metrics,
            "downloadedBytes": downloaded,
            "totalBytes": sum(total for total in totals if total) or None,
            "overallPercent": percent,
        }


async def _terminate_subprocess(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return

    try:
        process.terminate()
    except ProcessLookupError:
        return

    try:
        await asyncio.wait_for(process.wait(), timeout=2.0)
        return
    except Exception:
        pass

    try:
        process.kill()
    except ProcessLookupError:
        return

    try:
        await asyncio.wait_for(process.wait(), timeout=2.0)
    except Exception:
        pass


async def send_stage_progress(
    websocket,
    stage: str,
    percent: int,
    detail: str | None = None,
    **extra_data,
) -> None:
    payload = {
        "type": "download_progress",
        "data": {
            "stage": stage,
            "percent": percent,
        },
    }
    if detail:
        payload["data"]["detail"] = detail
    for key, value in extra_data.items():
        if value is not None:
            payload["data"][key] = value
    await send_ws(websocket, payload)


def clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(max_value, value))


def map_progress_range(raw_percent: float, start: float, end: float) -> int:
    scaled = start + ((raw_percent / 100.0) * (end - start))
    return int(clamp(scaled, start, end))


def _parse_ffmpeg_clock_to_seconds(clock_value: str) -> float | None:
    match = re.match(r"(\d+):(\d+):(\d+(?:\.\d+)?)", clock_value.strip())
    if not match:
        return None

    hours = int(match.group(1))
    minutes = int(match.group(2))
    seconds = float(match.group(3))
    return (hours * 3600) + (minutes * 60) + seconds


def parse_ffmpeg_out_time_seconds(key: str, value: str) -> float | None:
    try:
        if key in {"out_time_us", "out_time_ms"}:
            
            return int(float(value)) / 1_000_000.0
        if key == "out_time":
            return _parse_ffmpeg_clock_to_seconds(value)
    except Exception:
        return None
    return None


async def run_ytdlp_with_progress(
    cmd: list[str],
    websocket,
    stage: str,
    start_pct: int,
    end_pct: int,
    progress_context: dict | None = None,
    network_progress_callback=None,
    progress_callback=None,
    expected_streams: int = 1,
) -> None:
    process = await start_streaming_process(cmd, merge_stderr=True)

    aggregator = DownloadProgressAggregator(expected_streams=expected_streams)
    eta = EtaSmoother()
    recent_output: deque[str] = deque(maxlen=15)
    active_stream = None

    try:
        while True:
            line = await process.stdout.readline()
            if not line:
                break

            text = line.decode("utf-8", errors="replace").strip()
            if not text:
                continue

            metrics = parse_ytdlp_progress_line(text)
            if metrics is None:
                recent_output.append(text)
                continue

            if metrics["streamId"] != active_stream:
                active_stream = metrics["streamId"]
                eta.reset()

            combined = aggregator.update(metrics)
            mapped = map_progress_range(combined["overallPercent"], start_pct, end_pct)
            smoothed_eta = eta.update(metrics.get("etaSeconds"))

            if network_progress_callback:
                await network_progress_callback(metrics.get("downloadedBytes"), metrics["streamId"])

            update = {
                "stage": stage,
                "progressPercent": mapped,
                "transferPercent": metrics.get("transferPercent"),
                "downloadedBytes": combined.get("downloadedBytes"),
                "totalBytes": combined.get("totalBytes"),
                "speedBytesPerSecond": metrics.get("speedBytesPerSecond"),
                "etaSeconds": smoothed_eta,
            }

            if progress_callback:
                await progress_callback(update)

            await send_stage_progress(
                websocket,
                stage,
                mapped,
                **(progress_context or {}),
                downloaded_bytes=update["downloadedBytes"],
                total_bytes=update["totalBytes"],
                speed_bytes_per_second=update["speedBytesPerSecond"],
                eta_seconds=update["etaSeconds"],
                transfer_percent=update["transferPercent"],
            )

        return_code = await process.wait()
        if return_code != 0:
            errors = [entry for entry in recent_output if entry.startswith("ERROR")] or list(recent_output)
            combined = " | ".join(errors)
            raise_for_ytdlp_error(combined, f"yt-dlp failed during stage '{stage}'", cmd[-1])
        
        if progress_callback:
            await progress_callback({"stage": stage, "progressPercent": end_pct})
        await send_stage_progress(websocket, stage, end_pct, **(progress_context or {}))
    except asyncio.CancelledError:
        await _terminate_subprocess(process)
        raise
    except Exception:
        await _terminate_subprocess(process)
        raise


async def run_ffmpeg_with_stage_progress(
    cmd: list[str],
    websocket,
    stage: str,
    start_pct: int,
    end_pct: int,
    duration_seconds: float | None = None,
    progress_context: dict | None = None,
    progress_callback=None,
) -> None:
    await send_stage_progress(websocket, stage, start_pct, **(progress_context or {}))

    ffmpeg_cmd = cmd[:1] + ["-nostdin", "-progress", "pipe:1", "-nostats"] + cmd[1:]

    process = await start_streaming_process(ffmpeg_cmd)

    stderr_chunks: list[str] = []
    last_sent = start_pct
    started_monotonic = time.monotonic()
    eta = EtaSmoother()

    async def read_stdout():
        nonlocal last_sent

        while True:
            line = await process.stdout.readline()
            if not line:
                break

            text = line.decode("utf-8", errors="replace").strip()
            if not text or "=" not in text:
                continue

            key, value = text.split("=", 1)
            key = key.strip()
            value = value.strip()

            out_seconds = parse_ffmpeg_out_time_seconds(key, value)
            if out_seconds is not None and duration_seconds and duration_seconds > 0:
                fraction = min(1.0, out_seconds / duration_seconds)
                mapped = map_progress_range(fraction * 100.0, start_pct, end_pct)
                elapsed_wall = time.monotonic() - started_monotonic

                
                eta_wall = None
                if fraction >= 0.02 and elapsed_wall >= 1.0:
                    eta_wall = eta.update(max(0.0, elapsed_wall * (1 - fraction) / fraction))

                if mapped > last_sent:
                    last_sent = mapped
                    if progress_callback:
                        await progress_callback({
                            "stage": stage,
                            "progressPercent": mapped,
                            "etaSeconds": eta_wall,
                        })
                    await send_stage_progress(
                        websocket,
                        stage,
                        mapped,
                        **(progress_context or {}),
                        eta_seconds=eta_wall,
                    )
                continue

            if key == "progress" and value == "end":
                last_sent = max(last_sent, end_pct)
                await send_stage_progress(websocket, stage, end_pct, **(progress_context or {}))

    async def read_stderr():
        while True:
            line = await process.stderr.readline()
            if not line:
                break
            stderr_chunks.append(line.decode("utf-8", errors="replace"))

    stdout_task = asyncio.create_task(read_stdout())
    stderr_task = asyncio.create_task(read_stderr())

    try:
        return_code = await process.wait()
        await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)

        if return_code != 0:
            stderr_lines = "".join(stderr_chunks).strip().splitlines()
            tail = " | ".join(stderr_lines[-6:]) if stderr_lines else ""
            raise RuntimeError(tail or f"ffmpeg failed during stage '{stage}' with exit code {return_code}")

        if last_sent < end_pct:
            await send_stage_progress(websocket, stage, end_pct, **(progress_context or {}))
    except asyncio.CancelledError:
        stdout_task.cancel()
        stderr_task.cancel()
        await _terminate_subprocess(process)
        await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
        raise
