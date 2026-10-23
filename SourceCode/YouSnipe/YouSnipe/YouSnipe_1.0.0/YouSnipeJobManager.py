from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.parse import urlparse
import re

from YouSnipeDownloadEngine import resolve_playlist_entry_url

from YouSnipeCommon import is_audio_format, is_video_format
from YouSnipeDataCap import assert_transfer_allowed
from YouSnipeDBManager import YouSnipeDBManager
from YouSnipeHandlers import execute_download_item
from YouSnipeSettings import UNLIMITED_SENTINEL, get_effective_settings, get_save_path


class YouSnipeRequestError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class _EventSocket:
    

    def __init__(self, manager: "YouSnipeJobManager") -> None:
        self._manager = manager

    async def send(self, raw_payload: str) -> None:
        await self._manager.broadcast_raw(raw_payload)


class YouSnipeJobManager:
    def __init__(self) -> None:
        self.db = YouSnipeDBManager()
        self._tasks: dict[str, asyncio.Task] = {}
        self._subscribers = set()
        self._lock = asyncio.Lock()
        self._socket = _EventSocket(self)

    async def start(self) -> None:
        for job in self.db.list_jobs(include_completed=False, limit=1000):
            for item in self.db.list_download_items_for_job(int(job["id"])):
                if item["status"] == "running":
                    self.db.update_item_progress(
                        item_id=int(item["id"]),
                        status="failed",
                        stage="failed",
                        error_code="INTERRUPTED_BY_RESTART",
                        error_message="Interrupted by service restart",
                    )
            self.db.finalize_job_if_complete(int(job["id"]))
        await self.pump()

    def subscribe(self, websocket) -> None:
        self._subscribers.add(websocket)

    def unsubscribe(self, websocket) -> None:
        self._subscribers.discard(websocket)

    async def broadcast_raw(self, raw_payload: str) -> None:
        for websocket in list(self._subscribers):
            try:
                await websocket.send(raw_payload)
            except Exception:
                self.unsubscribe(websocket)

    def _limit(self) -> int | None:
        value = get_effective_settings()["queue"]["maxConcurrentDownloads"]
        if value == UNLIMITED_SENTINEL:
            return None
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    def _running_count(self) -> int:
        return len([task for task in self._tasks.values() if not task.done()])

    def _validate(self, data: dict, settings: dict) -> tuple[str, str, str, str]:
        url = str(data.get("url") or "").strip()
        parsed = urlparse(url)
        if not url or parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise YouSnipeRequestError("INVALID_URL", "A valid http(s) URL is required")

        target_format = str(data.get("format") or "").strip().upper()
        if not (is_audio_format(target_format) or is_video_format(target_format)):
            raise YouSnipeRequestError("UNSUPPORTED_FORMAT", f"Unsupported output format: {target_format or 'missing'}")

        quality = str(data.get("quality") or "").strip()
        if not quality:
            raise YouSnipeRequestError("INVALID_REQUEST", "Quality is required")

        save_path = str(data.get("savePath") or get_save_path("audio" if str(data.get("mediaMode") or "").lower() == "audio" or (is_audio_format(target_format) and target_format not in ("MP4",)) else "video", settings)).strip()
        if not save_path:
            raise YouSnipeRequestError("INVALID_REQUEST", "A save path is required")

        return url, target_format, quality, save_path

    async def create_download(self, data: dict, request_id: str = "") -> dict[str, Any]:
        settings = get_effective_settings()
        assert_transfer_allowed(self.db, settings)
        url, target_format, quality, save_path = self._validate(data, settings)

        record = self.db.enqueue_single(
            source_url=url,
            target_media_mode="audio" if str(data.get("mediaMode") or "").lower() == "audio" or (is_audio_format(target_format) and target_format not in ("MP4",)) else "video",
            target_format=target_format,
            target_quality=quality,
            save_path=save_path,
            title=str(data.get("originalFileName") or ""),
            metadata={"request": {**data, "savePath": save_path}},
        )
        job, item = record["job"], record["items"][0]
        await self.pump()

        current = self.db.get_download_item_with_job(str(item["item_uuid"])) or {}
        return {
            "jobId": job["job_uuid"],
            "itemId": item["item_uuid"],
            "status": current.get("status", "queued"),
            "requestId": request_id,
        }

    async def create_playlist(self, data: dict, request_id: str = "") -> dict[str, Any]:
        settings = get_effective_settings()
        assert_transfer_allowed(self.db, settings)

        entries = data.get("items")
        if not isinstance(entries, list) or not entries:
            raise YouSnipeRequestError("INVALID_REQUEST", "Playlist requires an items list")

        target_format = str(data.get("format") or "").strip().upper()
        if not (is_audio_format(target_format) or is_video_format(target_format)):
            raise YouSnipeRequestError("UNSUPPORTED_FORMAT", f"Unsupported output format: {target_format or 'missing'}")

        quality = str(data.get("quality") or "Highest").strip()
        save_path = str(data.get("savePath") or get_save_path("audio" if str(data.get("mediaMode") or "").lower() == "audio" or (is_audio_format(target_format) and target_format not in ("MP4",)) else "video", settings)).strip()
        playlist_title = str(data.get("playlistName") or "Playlist").strip()

        selected = []
        skipped = []
        for index, entry in enumerate(entries, start=1):
            if not isinstance(entry, dict):
                skipped.append({"index": index, "reason": "Invalid playlist entry"})
                continue
            entry_url = resolve_playlist_entry_url(entry)
            if not entry_url:
                skipped.append({"index": index, "reason": "Entry URL could not be resolved", "title": str(entry.get("title") or "")})
                continue
            selected.append({
                "url": entry_url,
                "title": str(entry.get("title") or f"Item {index}"),
                "playlist_index": int(entry.get("index") or index),
                "request": {
                    "url": entry_url,
                    "savePath": save_path,
                    "originalFileName": str(entry.get("title") or f"Item {index}"),
                    "customFileName": str(entry.get("title") or f"Item {index}"),
                    "format": target_format,
                    "quality": quality,
                    "playlistFolderName": playlist_title,
                    "playlistIndex": int(entry.get("index") or index),
                    "thumbnail": str(entry.get("thumbnail") or ""),
                    "mediaMode": str(data.get("mediaMode") or "").lower(),
                },
            })

        if not selected:
            raise YouSnipeRequestError("NO_PLAYABLE_ENTRIES", "No selected playlist entries contain usable URLs")

        record = self.db.enqueue_playlist(
            source_url=str(data.get("url") or "").strip(),
            playlist_id=str(data.get("playlistId") or ""),
            playlist_title=playlist_title,
            target_media_mode="audio" if str(data.get("mediaMode") or "").lower() == "audio" or (is_audio_format(target_format) and target_format not in ("MP4",)) else "video",
            target_format=target_format,
            save_path=save_path,
            selected_entries=selected,
            total_entries=len(selected),
            custom_name=playlist_title,
            metadata={"request": {"format": target_format, "quality": quality, "savePath": save_path}},
        )
        await self.pump()

        return {
            "jobId": record["job"]["job_uuid"],
            "itemIds": [item["item_uuid"] for item in record["items"]],
            "status": "queued",
            "requestId": request_id,
            "skippedEntries": skipped,
            "selectedCount": len(selected),
        }

    def get_job(self, job_id: str) -> dict[str, Any]:
        job = self.db.get_job_by_uuid(job_id)
        if not job:
            raise LookupError("JOB_NOT_FOUND")
        job["jobId"] = job["job_uuid"]
        job["items"] = self.db.list_download_items_for_job(int(job["id"]))
        return job

    def get_item(self, item_id: str) -> dict[str, Any]:
        item = self.db.get_download_item_with_job(item_id)
        if not item:
            raise LookupError("ITEM_NOT_FOUND")
        item["itemId"] = item["item_uuid"]
        item["jobId"] = item["job_uuid"]
        return item

    async def pump(self) -> None:
        async with self._lock:
            while True:
                limit = self._limit()
                if limit is not None and self._running_count() >= limit:
                    return

                next_item = self.db.reserve_next_queued_item()
                if not next_item:
                    return

                item_id = str(next_item["item_uuid"])
                task = asyncio.create_task(self._run_item(next_item))
                self._tasks[item_id] = task
                task.add_done_callback(
                    lambda completed, identifier=item_id: asyncio.create_task(self._finish(identifier, completed))
                )

    async def _run_item(self, item: dict) -> None:
        record = self.db.get_download_item_with_job(str(item["item_uuid"])) or {}

        try:
            stored = json.loads(record.get("raw_metadata_json") or "{}")
        except json.JSONDecodeError:
            stored = {}

        request = stored.get("request") or {}
        request = {
            **request,
            "url": record.get("webpage_url") or request.get("url"),
            "originalFileName": record.get("title") or request.get("originalFileName"),
            "format": request.get("format") or record.get("target_format"),
            "quality": request.get("quality") or record.get("target_quality"),
            "savePath": request.get("savePath") or record.get("save_path"),
            "_persisted": {"jobId": record.get("job_uuid"), "itemId": record.get("item_uuid")},
        }
        
        
        for attempt in range(3):
            await execute_download_item(self._socket, request, "")
            latest = self.db.get_download_item_with_job(str(item["item_uuid"])) or {}
            if latest.get("status") != "failed" or attempt == 2:
                return
            if str(latest.get('error_code') or '').upper() in ('RATE_LIMITED', 'YOUTUBE_ACCESS_RESTRICTED'):
                return
            message = str(latest.get("error_message") or "").lower()
            temporary = (
                re.search(r"\b(?:500|502|503|504)\b", message)
                or any(phrase in message for phrase in (
                    "timed out", "timeout", "connection reset", "connection aborted",
                    "connection refused", "temporary failure", "temporarily unavailable",
                    "network is unreachable", "remote end closed", "broken pipe",
                ))
            )
            if not temporary:
                return
            delay = 2 ** attempt
            await self.broadcast_raw(json.dumps({"type": "download_retrying", "data": {
                "itemId": item["item_uuid"], "attempt": attempt + 2,
                "maxAttempts": 3, "delaySeconds": delay, "reason": latest.get("error_message")}}))
            await asyncio.sleep(delay)
            self.db.reset_item_for_auto_retry(int(latest["id"]))

    async def _finish(self, item_id: str, task: asyncio.Task) -> None:
        self._tasks.pop(item_id, None)
        try:
            task.result()
        except asyncio.CancelledError:
            record = self.db.get_download_item_with_job(item_id)
            if record and record["status"] not in {"cancelled", "completed"}:
                self.db.update_item_progress(item_id=int(record["id"]), status="cancelled", stage="cancelled")
                self.db.finalize_job_if_complete(int(record["job_id"]))
        except Exception as exc:
            
            record = self.db.get_download_item_with_job(item_id)
            if record and record["status"] not in {"failed", "cancelled", "completed"}:
                self.db.update_item_progress(
                    item_id=int(record["id"]),
                    status="failed",
                    stage="failed",
                    error_code="INTERNAL_EXECUTION_ERROR",
                    error_message=str(exc),
                )
                self.db.finalize_job_if_complete(int(record["job_id"]))
        await self.pump()

    async def cancel_item(self, item_id: str) -> bool:
        record = self.db.get_download_item_with_job(item_id)
        if not record:
            return False

        task = self._tasks.get(item_id)
        if task and not task.done():
            task.cancel()
            return True

        if record["status"] == "queued":
            self.db.update_item_progress(item_id=int(record["id"]), status="cancelled", stage="cancelled")
            self.db.finalize_job_if_complete(int(record["job_id"]))
            return True
        return False

    async def cancel_job(self, job_id: str) -> bool:
        job = self.db.get_job_by_uuid(job_id)
        if not job:
            return False
        results = [await self.cancel_item(str(item["item_uuid"])) for item in self.db.list_download_items_for_job(int(job["id"]))]
        return any(results)

    async def retry_item(self, item_id: str) -> dict[str, Any]:
        record = self.db.get_download_item_with_job(item_id)
        if not record:
            raise LookupError("ITEM_NOT_FOUND")
        if record["status"] not in {"failed", "cancelled"}:
            raise YouSnipeRequestError("ITEM_ACTIVE", "Only failed or cancelled items can be retried")

        self.db.requeue_item(int(record["id"]))
        await self.pump()
        return {"itemId": item_id, "status": "queued"}

    async def retry_job(self, job_id: str) -> dict[str, Any]:
        job = self.db.get_job_by_uuid(job_id)
        if not job:
            raise LookupError("JOB_NOT_FOUND")

        retried = []
        for item in self.db.list_download_items_for_job(int(job["id"])):
            if item["status"] in {"failed", "cancelled"}:
                self.db.requeue_item(int(item["id"]))
                retried.append(item["item_uuid"])

        await self.pump()
        return {"jobId": job_id, "retriedItemIds": retried}

    def remove_item(self, item_id: str) -> dict[str, Any]:
        record = self.db.get_download_item_with_job(item_id)
        if not record:
            raise LookupError("ITEM_NOT_FOUND")
        if record["status"] in {"queued", "running"}:
            raise YouSnipeRequestError("ITEM_ACTIVE", "Cancel the item before removing it")

        self.db.remove_download_item_by_uuid(item_id)
        return {"itemId": item_id, "removed": True}

    def remove_job(self, job_id: str) -> dict[str, Any]:
        job = self.db.get_job_by_uuid(job_id)
        if not job:
            raise LookupError("JOB_NOT_FOUND")
        if job["status"] in {"queued", "running"}:
            raise YouSnipeRequestError("JOB_ACTIVE", "Cancel the job before removing it")

        self.db.remove_job_by_uuid(job_id)
        return {"jobId": job_id, "removed": True}
