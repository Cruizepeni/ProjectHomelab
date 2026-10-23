from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from YouSnipeDB import ensure_database, get_connection
from YouSnipeSettings import NEVER_SENTINEL


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return "{}"


def _retention_cutoff(retention: Dict[str, Any]) -> Optional[datetime]:
    mode = str(retention.get("mode") or "interval").strip().lower()
    if mode != "interval":
        return None
    try:
        amount = int(retention.get("value"))
    except Exception:
        return None
    unit = str(retention.get("unit") or "year").strip().lower()

    now = datetime.now(timezone.utc)
    if unit == "minute":
        return now - timedelta(minutes=amount)
    if unit == "hour":
        return now - timedelta(hours=amount)
    if unit == "day":
        return now - timedelta(days=amount)
    if unit == "week":
        return now - timedelta(weeks=amount)
    if unit == "month":
        return now - timedelta(days=30 * amount)
    if unit == "year":
        return now - timedelta(days=365 * amount)
    return None


def _normalize_status(raw_status: Any, fallback: str = "queued") -> str:
    status = str(raw_status or "").strip().lower()
    allowed = {
        "queued",
        "running",
        "completed",
        "failed",
        "cancelled",
        "skipped",
        "partial",
    }
    return status if status in allowed else fallback


class YouSnipeDBManager:
    def __init__(self) -> None:
        ensure_database()

    def _fetchone(self, query: str, params: Tuple[Any, ...] = ()) -> Optional[Dict[str, Any]]:
        with get_connection() as conn:
            row = conn.execute(query, params).fetchone()
            return dict(row) if row else None

    def _fetchall(self, query: str, params: Tuple[Any, ...] = ()) -> List[Dict[str, Any]]:
        with get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def create_job(
        self,
        *,
        source_type: str,
        source_url: str,
        target_media_mode: str,
        target_format: str,
        save_path: str,
        metadata: Optional[Dict[str, Any]] = None,
        playlist_id: Optional[str] = None,
        playlist_title: Optional[str] = None,
        custom_name: Optional[str] = None,
        target_quality: Optional[str] = None,
        total_items: int = 1,
        selected_items: int = 1,
        status: str = "queued",
    ) -> Dict[str, Any]:
        now = _now_iso()
        job_uuid = str(uuid.uuid4())
        normalized_status = _normalize_status(status, fallback="queued")

        with get_connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO jobs (
                    job_uuid, source_type, source_url, playlist_id, playlist_title,
                    custom_name, target_media_mode, target_format, target_quality,
                    save_path, status, created_at, total_items, selected_items, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_uuid,
                    source_type,
                    source_url,
                    playlist_id,
                    playlist_title,
                    custom_name,
                    target_media_mode,
                    target_format,
                    target_quality,
                    save_path,
                    normalized_status,
                    now,
                    max(1, int(total_items)),
                    max(1, int(selected_items)),
                    _safe_json(metadata or {}),
                ),
            )
            conn.commit()
            job_id = int(cur.lastrowid)

        return self.get_job_by_id(job_id) or {}

    def create_download_item(
        self,
        *,
        job_id: int,
        title: Optional[str],
        webpage_url: Optional[str],
        extractor_id: Optional[str],
        duration_seconds: Optional[float],
        item_index: Optional[int] = None,
        raw_metadata: Optional[Dict[str, Any]] = None,
        status: str = "queued",
    ) -> Dict[str, Any]:
        now = _now_iso()
        item_uuid = str(uuid.uuid4())
        normalized_status = _normalize_status(status, fallback="queued")

        with get_connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO download_items (
                    item_uuid, job_id, item_index, title, webpage_url, extractor_id,
                    duration_seconds, status, progress_percent, downloaded_bytes,
                    total_bytes, speed_bytes_per_second, eta_seconds, file_path,
                    created_at, raw_metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL, NULL, ?, ?)
                """,
                (
                    item_uuid,
                    job_id,
                    item_index,
                    title,
                    webpage_url,
                    extractor_id,
                    duration_seconds,
                    normalized_status,
                    now,
                    _safe_json(raw_metadata or {}),
                ),
            )
            conn.commit()
            item_id = int(cur.lastrowid)

        row = self._fetchone("SELECT * FROM download_items WHERE id = ?", (item_id,))
        return row or {}

    def get_job_by_id(self, job_id: int) -> Optional[Dict[str, Any]]:
        return self._fetchone("SELECT * FROM jobs WHERE id = ?", (job_id,))

    def get_job_by_uuid(self, job_uuid: str) -> Optional[Dict[str, Any]]:
        return self._fetchone("SELECT * FROM jobs WHERE job_uuid = ?", (job_uuid,))

    def get_item_by_uuid(self, item_uuid: str) -> Optional[Dict[str, Any]]:
        return self.get_download_item_with_job(item_uuid)

    def get_download_item_with_job(self, item_uuid: str) -> Optional[Dict[str, Any]]:
        return self._fetchone(
            """
            SELECT
                di.*,
                j.job_uuid,
                j.source_type,
                j.source_url AS job_source_url,
                j.playlist_id,
                j.playlist_title,
                j.custom_name AS job_custom_name,
                j.target_media_mode,
                j.target_format,
                j.target_quality,
                j.save_path,
                j.metadata_json,
                j.status AS job_status
            FROM download_items di
            JOIN jobs j ON j.id = di.job_id
            WHERE di.item_uuid = ?
            """,
            (item_uuid,),
        )

    def list_jobs(self, limit: int = 100, include_completed: bool = True) -> List[Dict[str, Any]]:
        limit = max(1, min(int(limit), 1000))
        if include_completed:
            return self._fetchall(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        return self._fetchall(
            "SELECT * FROM jobs WHERE status NOT IN ('completed', 'failed', 'cancelled', 'partial') ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )

    def list_terminal_jobs(self, limit: int = 100, include_failed: bool = True) -> List[Dict[str, Any]]:
        statuses = ("completed", "failed", "cancelled", "partial") if include_failed else ("completed", "cancelled", "partial")
        placeholders = ",".join("?" for _ in statuses)
        return self._fetchall(f"SELECT * FROM jobs WHERE status IN ({placeholders}) ORDER BY COALESCE(completed_at, failed_at, cancelled_at, created_at) DESC LIMIT ?", (*statuses, max(1, min(limit, 1000))))

    def list_download_items_for_job(self, job_id: int) -> List[Dict[str, Any]]:
        return self._fetchall(
            "SELECT * FROM download_items WHERE job_id = ? ORDER BY COALESCE(item_index, 999999), id ASC",
            (job_id,),
        )

    def enqueue_single(
        self,
        *,
        source_url: str,
        target_media_mode: str,
        target_format: str,
        target_quality: Optional[str] = None,
        save_path: str,
        title: Optional[str] = None,
        extractor_id: Optional[str] = None,
        duration_seconds: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        job = self.create_job(
            source_type="single",
            source_url=source_url,
            target_media_mode=target_media_mode,
            target_format=target_format,
            target_quality=target_quality,
            save_path=save_path,
            metadata=metadata,
            total_items=1,
            selected_items=1,
            status="queued",
        )
        item = self.create_download_item(
            job_id=int(job["id"]),
            item_index=1,
            title=title,
            webpage_url=source_url,
            extractor_id=extractor_id,
            duration_seconds=duration_seconds,
            raw_metadata=metadata,
            status="queued",
        )
        return {"job": job, "items": [item]}

    def enqueue_playlist(
        self,
        *,
        source_url: str,
        playlist_id: Optional[str],
        playlist_title: Optional[str],
        target_media_mode: str,
        target_format: str,
        save_path: str,
        selected_entries: Iterable[Dict[str, Any]],
        total_entries: int,
        custom_name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        entries = list(selected_entries)
        selected_count = max(1, len(entries))

        job = self.create_job(
            source_type="playlist",
            source_url=source_url,
            playlist_id=playlist_id,
            playlist_title=playlist_title,
            custom_name=custom_name,
            target_media_mode=target_media_mode,
            target_format=target_format,
            save_path=save_path,
            metadata=metadata,
            total_items=max(selected_count, int(total_entries) if total_entries else selected_count),
            selected_items=selected_count,
            status="queued",
        )

        created_items: List[Dict[str, Any]] = []
        for idx, entry in enumerate(entries, start=1):
            created_items.append(
                self.create_download_item(
                    job_id=int(job["id"]),
                    item_index=int(entry.get("playlist_index") or entry.get("index") or idx),
                    title=entry.get("title"),
                    webpage_url=entry.get("url") or entry.get("webpage_url"),
                    extractor_id=entry.get("id"),
                    duration_seconds=entry.get("duration"),
                    raw_metadata=entry,
                    status="queued",
                )
            )

        return {"job": job, "items": created_items}

    def update_job_status(self, job_id: int, status: str, error_message: Optional[str] = None, error_code: Optional[str] = None) -> None:
        now = _now_iso()
        status = _normalize_status(status, fallback="queued")
        current = self.get_job_by_id(job_id) or {}

        started_at = current.get("started_at") or (now if status == "running" else None)
        completed_at = now if status in {"completed", "partial"} else None
        failed_at = now if status == "failed" else None
        cancelled_at = now if status == "cancelled" else None

        with get_connection() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET status = ?,
                    started_at = ?,
                    completed_at = ?,
                    failed_at = ?,
                    cancelled_at = ?,
                    error_message = ?,
                    error_code = ?
                WHERE id = ?
                """,
                (status, started_at, completed_at, failed_at, cancelled_at, error_message, error_code, job_id),
            )
            conn.commit()

    def update_item_progress(
        self,
        *,
        item_id: int,
        status: Optional[str] = None,
        progress_percent: Optional[float] = None,
        downloaded_bytes: Optional[int] = None,
        total_bytes: Optional[int] = None,
        speed_bytes_per_second: Optional[float] = None,
        eta_seconds: Optional[float] = None,
        file_path: Optional[str] = None,
        error_message: Optional[str] = None,
        stage: Optional[str] = None,
        error_code: Optional[str] = None,
        cancelled: bool = False,
    ) -> None:
        current = self._fetchone("SELECT * FROM download_items WHERE id = ?", (item_id,))
        if not current:
            return

        now = _now_iso()
        next_status = _normalize_status(status, fallback=current.get("status") or "queued") if status else current.get("status")

        started_at = current.get("started_at")
        if next_status == "running" and not started_at:
            started_at = now

        completed_at = current.get("completed_at")
        failed_at = current.get("failed_at")
        cancelled_at = current.get("cancelled_at")
        if next_status == "completed":
            completed_at = now
            failed_at = None
        elif next_status == "failed":
            failed_at = now
            completed_at = None
        elif next_status == "cancelled":
            cancelled_at = now
            completed_at = None
            failed_at = None

        values = {
            "status": next_status,
            "progress_percent": progress_percent if progress_percent is not None else current.get("progress_percent"),
            "downloaded_bytes": downloaded_bytes if downloaded_bytes is not None else current.get("downloaded_bytes"),
            "total_bytes": total_bytes if total_bytes is not None else current.get("total_bytes"),
            "speed_bytes_per_second": speed_bytes_per_second if speed_bytes_per_second is not None else current.get("speed_bytes_per_second"),
            "eta_seconds": eta_seconds if eta_seconds is not None else current.get("eta_seconds"),
            "file_path": file_path if file_path is not None else current.get("file_path"),
            "stage": stage if stage is not None else current.get("stage"),
            "error_code": error_code if error_code is not None else current.get("error_code"),
            "error_message": error_message if error_message is not None else current.get("error_message"),
            "started_at": started_at,
            "completed_at": completed_at,
            "failed_at": failed_at,
            "cancelled_at": cancelled_at,
        }

        with get_connection() as conn:
            conn.execute(
                """
                UPDATE download_items
                SET status = ?,
                    progress_percent = ?,
                    downloaded_bytes = ?,
                    total_bytes = ?,
                    speed_bytes_per_second = ?,
                    eta_seconds = ?,
                    file_path = ?,
                    started_at = ?,
                    completed_at = ?,
                    failed_at = ?,
                    error_message = ?, stage = ?, error_code = ?, cancelled_at = ?
                WHERE id = ?
                """,
                (
                    values["status"], values["progress_percent"], values["downloaded_bytes"], values["total_bytes"], values["speed_bytes_per_second"], values["eta_seconds"], values["file_path"], values["started_at"], values["completed_at"], values["failed_at"], values["error_message"], values["stage"], values["error_code"], values["cancelled_at"],
                    item_id,
                ),
            )
            conn.commit()

    def record_usage(self, *, item_id: Optional[int], bytes_transferred: int, source: str = "download") -> None:
        if bytes_transferred <= 0:
            return
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO usage_ledger (event_time, item_id, bytes_transferred, source) VALUES (?, ?, ?, ?)",
                (_now_iso(), item_id, int(bytes_transferred), source),
            )
            conn.commit()

    def get_usage_summary(self) -> Dict[str, Any]:
        with get_connection() as conn:
            total = conn.execute("SELECT COALESCE(SUM(bytes_transferred), 0) AS bytes_total FROM usage_ledger").fetchone()
            today = conn.execute(
                """
                SELECT COALESCE(SUM(bytes_transferred), 0) AS bytes_today
                FROM usage_ledger
                WHERE date(event_time) = date('now')
                """
            ).fetchone()

        return {
            "bytesTotal": int(total["bytes_total"] if total else 0),
            "bytesToday": int(today["bytes_today"] if today else 0),
        }

    def get_usage_for_window(self, start: datetime, end: datetime) -> int:
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT COALESCE(SUM(bytes_transferred), 0) AS bytes_used
                FROM usage_ledger
                WHERE event_time >= ? AND event_time < ?
                """,
                (start.isoformat(), end.isoformat()),
            ).fetchone()
        return int(row["bytes_used"] if row else 0)

    def clear_usage_history(self) -> None:
        with get_connection() as conn:
            conn.execute("DELETE FROM usage_ledger")
            conn.commit()

    def get_usage_total(self, start: Optional[datetime] = None, end: Optional[datetime] = None) -> int:
        clauses, params = [], []
        if start:
            clauses.append("event_time >= ?")
            params.append(start.isoformat())
        if end:
            clauses.append("event_time < ?")
            params.append(end.isoformat())
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        row = self._fetchone(f"SELECT COALESCE(SUM(bytes_transferred), 0) AS bytes_used FROM usage_ledger{where}", tuple(params))
        return int((row or {}).get("bytes_used") or 0)

    def delete_usage_ranges(self, ranges: List[Tuple[datetime, datetime]]) -> Dict[str, int]:
        if not ranges:
            return {"deletedRows": 0, "deletedBytes": 0}
        clauses, params = [], []
        for start, end in ranges:
            clauses.append("(event_time >= ? AND event_time < ?)")
            params.extend([start.isoformat(), end.isoformat()])
        with get_connection() as conn:
            row = conn.execute(f"SELECT COUNT(*) AS cnt, COALESCE(SUM(bytes_transferred), 0) AS bytes FROM usage_ledger WHERE {' OR '.join(clauses)}", tuple(params)).fetchone()
            conn.execute(f"DELETE FROM usage_ledger WHERE {' OR '.join(clauses)}", tuple(params))
            conn.commit()
        return {"deletedRows": int(row["cnt"]), "deletedBytes": int(row["bytes"])}

    def clear_usage_history_with_summary(self) -> Dict[str, int]:
        with get_connection() as conn:
            row = conn.execute("SELECT COUNT(*) AS cnt, COALESCE(SUM(bytes_transferred), 0) AS bytes FROM usage_ledger").fetchone()
            conn.execute("DELETE FROM usage_ledger")
            conn.commit()
        return {"deletedRows": int(row["cnt"]), "deletedBytes": int(row["bytes"])}

    def get_data_cap_state(self) -> Dict[str, Any]:
        return self._fetchone("SELECT * FROM data_cap_state WHERE id = 1") or {"id": 1, "enabled_last_seen": 0, "bytes_used": 0}

    def reset_data_cap_cycle(self, enabled: bool, cycle_started_at: datetime) -> None:
        with get_connection() as conn:
            conn.execute("UPDATE data_cap_state SET enabled_last_seen = ?, cycle_started_at = ?, bytes_used = 0, updated_at = ? WHERE id = 1", (int(enabled), cycle_started_at.isoformat(), _now_iso()))
            conn.commit()

    def increment_data_cap_usage(self, delta: int) -> int:
        with get_connection() as conn:
            conn.execute("UPDATE data_cap_state SET bytes_used = bytes_used + ?, updated_at = ? WHERE id = 1", (max(0, int(delta)), _now_iso()))
            row = conn.execute("SELECT bytes_used FROM data_cap_state WHERE id = 1").fetchone()
            conn.commit()
        return int(row["bytes_used"])

    def enforce_history_retention(self, retention_rule: Any) -> Dict[str, int]:
        if retention_rule == NEVER_SENTINEL:
            return {"deletedJobs": 0, "deletedItems": 0}
        if not isinstance(retention_rule, dict):
            return {"deletedJobs": 0, "deletedItems": 0}

        cutoff = _retention_cutoff(retention_rule)
        if cutoff is None:
            return {"deletedJobs": 0, "deletedItems": 0}

        cutoff_iso = cutoff.isoformat()
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT id FROM jobs WHERE status IN ('completed', 'failed', 'cancelled', 'partial') AND COALESCE(completed_at, failed_at, created_at) < ?",
                (cutoff_iso,),
            ).fetchall()
            job_ids = [int(r[0]) for r in rows]
            if not job_ids:
                return {"deletedJobs": 0, "deletedItems": 0}

            placeholders = ",".join("?" for _ in job_ids)
            items_before = conn.execute(
                f"SELECT COUNT(*) FROM download_items WHERE job_id IN ({placeholders})",
                tuple(job_ids),
            ).fetchone()[0]
            conn.execute(
                f"DELETE FROM jobs WHERE id IN ({placeholders})",
                tuple(job_ids),
            )
            conn.commit()

        return {"deletedJobs": len(job_ids), "deletedItems": int(items_before)}

    def reserve_next_queued_item(self) -> Optional[Dict[str, Any]]:
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT di.*, j.job_uuid, j.target_media_mode, j.target_format, j.save_path, j.source_url, j.source_type
                FROM download_items di
                JOIN jobs j ON j.id = di.job_id
                WHERE di.status = 'queued' AND j.status IN ('queued', 'running')
                ORDER BY j.created_at ASC, COALESCE(di.item_index, 999999) ASC, di.id ASC
                LIMIT 1
                """
            ).fetchone()
            if not row:
                return None

            item_id = int(row["id"])
            now = _now_iso()
            conn.execute(
                "UPDATE download_items SET status = 'running', started_at = COALESCE(started_at, ?) WHERE id = ?",
                (now, item_id),
            )
            conn.execute(
                "UPDATE jobs SET status = 'running', started_at = COALESCE(started_at, ?) WHERE id = ?",
                (now, int(row["job_id"])),
            )
            conn.commit()

        return self._fetchone("SELECT * FROM download_items WHERE id = ?", (item_id,))

    def finalize_job_if_complete(self, job_id: int) -> Optional[str]:
        items = self.list_download_items_for_job(job_id)
        if not items:
            return None

        statuses = {str(item.get("status") or "").lower() for item in items}
        if "running" in statuses:
            self.update_job_status(job_id, "running")
            return "running"
        if "queued" in statuses:
            self.update_job_status(job_id, "running")
            return "running"
        if "completed" in statuses and ("failed" in statuses or "cancelled" in statuses):
            self.update_job_status(job_id, "partial")
            return "partial"
        if "failed" in statuses:
            self.update_job_status(job_id, "failed")
            return "failed"
        if "cancelled" in statuses:
            self.update_job_status(job_id, "cancelled")
            return "cancelled"

        self.update_job_status(job_id, "completed")
        return "completed"

    def reset_item_for_auto_retry(self, item_id: int) -> None:
        
        with get_connection() as conn:
            conn.execute("""
                UPDATE download_items SET status='running', stage='retrying',
                    progress_percent=0, downloaded_bytes=NULL, total_bytes=NULL,
                    speed_bytes_per_second=NULL, eta_seconds=NULL,
                    error_code=NULL, error_message=NULL, started_at=NULL,
                    completed_at=NULL, failed_at=NULL, cancelled_at=NULL,
                    retry_count=retry_count+1 WHERE id=?
            """, (item_id,))
            row = conn.execute("SELECT job_id FROM download_items WHERE id=?", (item_id,)).fetchone()
            if row:
                conn.execute("""UPDATE jobs SET status='running', completed_at=NULL,
                    failed_at=NULL, cancelled_at=NULL, error_code=NULL, error_message=NULL
                    WHERE id=?""", (int(row["job_id"]),))
            conn.commit()

    def requeue_item(self, item_id: int) -> None:
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE download_items
                SET status = 'queued',
                    stage = 'queued',
                    progress_percent = NULL,
                    downloaded_bytes = NULL,
                    total_bytes = NULL,
                    speed_bytes_per_second = NULL,
                    eta_seconds = NULL,
                    error_code = NULL,
                    error_message = NULL,
                    started_at = NULL,
                    completed_at = NULL,
                    failed_at = NULL,
                    cancelled_at = NULL,
                    retry_count = retry_count + 1
                WHERE id = ?
                """,
                (item_id,),
            )
            row = conn.execute("SELECT job_id FROM download_items WHERE id = ?", (item_id,)).fetchone()
            if row:
                conn.execute(
                    "UPDATE jobs SET status = 'queued', completed_at = NULL, failed_at = NULL, cancelled_at = NULL, error_code = NULL, error_message = NULL WHERE id = ?",
                    (int(row["job_id"]),),
                )
            conn.commit()

    def remove_job_by_uuid(self, job_uuid: str) -> bool:
        with get_connection() as conn:
            cursor = conn.execute("DELETE FROM jobs WHERE job_uuid = ?", (job_uuid,))
            conn.commit()
        return cursor.rowcount > 0

    def clear_terminal_history(self) -> Dict[str, int]:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM jobs WHERE status IN ('completed', 'failed', 'cancelled', 'partial')"
            ).fetchone()
            conn.execute("DELETE FROM jobs WHERE status IN ('completed', 'failed', 'cancelled', 'partial')")
            conn.commit()
        return {"deletedJobs": int(row["cnt"] if row else 0)}

    def get_usage_buckets(self, start: datetime, end: datetime) -> List[Dict[str, Any]]:
        return self._fetchall(
            "SELECT event_time, bytes_transferred FROM usage_ledger WHERE event_time >= ? AND event_time < ? ORDER BY event_time ASC",
            (start.isoformat(), end.isoformat()),
        )

    def remove_download_item_by_uuid(self, item_uuid: str) -> bool:
        item = self._fetchone("SELECT id, job_id FROM download_items WHERE item_uuid = ?", (item_uuid,))
        if not item:
            return False

        job_id = int(item["job_id"])
        item_id = int(item["id"])

        with get_connection() as conn:
            conn.execute("DELETE FROM download_items WHERE id = ?", (item_id,))
            remaining = conn.execute(
                "SELECT COUNT(*) AS cnt FROM download_items WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            remaining_count = int(remaining["cnt"] if remaining else 0)
            if remaining_count <= 0:
                conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            conn.commit()

        if remaining_count:
            
            with get_connection() as conn:
                conn.execute("UPDATE jobs SET selected_items = ? WHERE id = ?", (remaining_count, job_id))
            self.finalize_job_if_complete(job_id)

        return True
