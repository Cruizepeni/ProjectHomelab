import os
import shutil
import tempfile
import asyncio
import traceback
import json
import time
import uuid

from YouSnipeDBManager import YouSnipeDBManager
from YouSnipeConversionEngine import convert_audio_file, convert_video_file, plan_video_output, plan_audio_output
from YouSnipeDownloadEngine import (
    build_metadata_response,
    download_best_audio,
    download_video_with_audio,
    fetch_metadata,
    probe_media_file,
)
from YouSnipeDataCap import TransferUsageTracker, assert_transfer_allowed, YouSnipeDataCapReachedError
from YouSnipeOverwritePolicy import overwrite_enabled, replace_completed_output
from YouSnipeShowFile import reveal_file_in_folder
from YouSnipeProgress import send_stage_progress
from YouSnipeSettings import get_effective_settings, get_save_path
from YouSnipeCommon import (
    ensure_directory,
    file_exists_and_nonzero,
    find_first_matching_file,
    get_final_filename,
    is_audio_format,
    is_video_format,
    send_error,
    send_ws,
)

DB_MANAGER = YouSnipeDBManager()


def _resolve_save_path(data: dict, media_mode: str, settings: dict) -> str:
    requested = (data.get("savePath") or "").strip()
    if requested:
        return requested

    storage = settings.get("storage", {})
    return get_save_path(media_mode, settings)


def validate_download_request(data: dict) -> str | None:
    if not (data.get("url") or "").strip():
        return "Download request missing URL"
    if not (data.get("originalFileName") or "").strip():
        return "Download request missing original file name"
    if not (data.get("format") or "").strip():
        return "Download request missing format"
    if not (str(data.get("quality") or "")).strip():
        return "Download request missing quality"
    return None


def _build_progress_context(request_data: dict, item_public_id: str, job_public_id: str) -> dict:
    return {
        "itemId": item_public_id,
        "jobId": job_public_id,
        "clientRequestId": request_data.get("_clientRequestId") or "",
        "sourceUrl": request_data.get("url") or "",
        "format": request_data.get("format") or "",
        "title": request_data.get("customFileName") or request_data.get("originalFileName") or "",
    }


def _format_extension(format_requested: str) -> str:
    
    return "m4a" if format_requested.upper() == "ALAC" else format_requested.lower()


def _build_output_filename(base_name: str, format_requested: str, quality_requested: str, include_quality: bool, video: bool) -> str:
    ext = _format_extension(format_requested)
    if not include_quality or not quality_requested:
        return f"{base_name}.{ext}"

    if video and quality_requested.isdigit():
        quality_suffix = f"{quality_requested}p"
    elif video:
        return f"{base_name}.{ext}"
    elif not video and quality_requested.isdigit():
        quality_suffix = f"{quality_requested}kbps"
    elif not video:
        quality_suffix = quality_requested.title()
    else:
        return f"{base_name}.{ext}"

    return f"{base_name} [{quality_suffix}].{ext}"


def _staged_output_path(save_path: str, format_requested: str) -> str:
    
    return os.path.join(save_path, f".yousnipe-{uuid.uuid4().hex}.{_format_extension(format_requested)}")


def _build_progress_persister(item_id):
    
    state = {"percent": -1, "stage": "", "time": 0.0}

    async def persist(update: dict) -> None:
        if not item_id:
            return

        percent = int(update.get("progressPercent") or 0)
        stage = str(update.get("stage") or "")
        now = time.monotonic()
        if stage == state["stage"] and percent - state["percent"] < 1 and now - state["time"] < 1.0:
            return

        state.update({"percent": percent, "stage": stage, "time": now})
        DB_MANAGER.update_item_progress(
            item_id=int(item_id),
            status="running",
            stage=stage,
            progress_percent=float(percent),
            downloaded_bytes=update.get("downloadedBytes"),
            total_bytes=update.get("totalBytes"),
            speed_bytes_per_second=update.get("speedBytesPerSecond"),
            eta_seconds=update.get("etaSeconds"),
        )

    return persist


async def handle_video_download_request(websocket, request_data: dict, allow_playlist: bool = False) -> None:
    url = request_data["url"]
    save_path = request_data["savePath"]
    original_file_name = request_data["originalFileName"]
    custom_file_name = request_data.get("customFileName", "")
    format_requested = request_data["format"].upper()
    quality_requested = str(request_data["quality"]).upper()
    item_id = request_data.get("_itemId")
    job_id = request_data.get("_jobId")
    item_public_id = str(request_data.get("_itemPublicId") or "")
    job_public_id = str(request_data.get("_jobPublicId") or "")
    progress_context = _build_progress_context(request_data, item_public_id, job_public_id)
    settings = get_effective_settings()

    ensure_directory(save_path)

    final_base_name = f"{request_data.get('filenamePrefix') or ''}{get_final_filename(original_file_name, custom_file_name)}"
    include_quality = bool(settings.get("downloadDefaults", {}).get("includeVideoQualityInFileName", True))
    final_file_name = _build_output_filename(
        final_base_name,
        format_requested,
        quality_requested,
        include_quality,
        video=True,
    )

    final_output_path = os.path.join(save_path, final_file_name)
    overwrite = overwrite_enabled(settings)

    usage_tracker = TransferUsageTracker(DB_MANAGER, int(item_id) if item_id else None)
    persist_progress = _build_progress_persister(item_id)

    async def account_video_progress(downloaded_bytes: int | None, stream_id: str = "") -> None:
        usage_tracker.record_progress(f"video:{stream_id}", downloaded_bytes)

    with tempfile.TemporaryDirectory(prefix="yousnipe_", dir=save_path) as temp_dir:
        source_template = os.path.join(temp_dir, "source.%(ext)s")
        converted_output_path = _staged_output_path(save_path, format_requested)

        try:
            assert_transfer_allowed(DB_MANAGER, settings)
            await download_video_with_audio(
                url=url,
                output_template=source_template,
                websocket=websocket,
                start_pct=1,
                end_pct=70,
                allow_playlist=allow_playlist,
                progress_context=progress_context,
                network_progress_callback=account_video_progress,
                progress_callback=persist_progress,
                quality_requested=quality_requested,
            )

            source_file = find_first_matching_file(temp_dir, "source.*")
            if not source_file:
                raise RuntimeError("Downloaded video file not found")

            source_info = await probe_media_file(source_file)
            plan = plan_video_output(source_info, format_requested, quality_requested,
                                     os.path.splitext(source_file)[1])

            if plan['mode'] == 'direct':
                await send_stage_progress(websocket, 'finalizing', 96,
                                          'Using already compatible video without FFmpeg', **progress_context)
                shutil.move(source_file, converted_output_path)
            else:
                await convert_video_file(
                    websocket=websocket,
                    input_file=source_file,
                    output_path=converted_output_path,
                    format_requested=format_requested,
                    quality_requested=quality_requested,
                    duration_seconds=source_info.get("durationSeconds"),
                    progress_context=progress_context,
                    plan=plan,
                    progress_callback=persist_progress,
                )

            if not file_exists_and_nonzero(converted_output_path):
                raise RuntimeError("Final output file was not created or is empty")

            if include_quality and not quality_requested.isdigit():
                output_info = await probe_media_file(converted_output_path)
                actual_height = output_info.get("height")
                if actual_height:
                    final_output_path = os.path.join(
                        save_path,
                        _build_output_filename(
                            final_base_name,
                            format_requested,
                            str(actual_height),
                            include_quality,
                            video=True,
                        ),
                    )

            final_output_path = replace_completed_output(converted_output_path, final_output_path, overwrite)
        finally:
            if os.path.exists(converted_output_path):
                os.remove(converted_output_path)

    await send_stage_progress(websocket, "finalizing", 100, "Download completed", **progress_context)
    if item_id:
        DB_MANAGER.update_item_progress(
            item_id=int(item_id),
            status="completed",
            stage="completed",
            progress_percent=100.0,
            file_path=final_output_path,
        )
    if job_id:
        DB_MANAGER.finalize_job_if_complete(int(job_id))
    await send_ws(
        websocket,
        {
            "type": "download_complete",
            "data": {
                **progress_context,
                "filePath": final_output_path,
            },
        },
    )


async def handle_audio_download_request(websocket, request_data: dict, allow_playlist: bool = False) -> None:
    url = request_data["url"]
    save_path = request_data["savePath"]
    original_file_name = request_data["originalFileName"]
    custom_file_name = request_data.get("customFileName", "")
    format_requested = request_data["format"].upper()
    quality_requested = str(request_data["quality"]).upper()
    item_id = request_data.get("_itemId")
    job_id = request_data.get("_jobId")
    item_public_id = str(request_data.get("_itemPublicId") or "")
    job_public_id = str(request_data.get("_jobPublicId") or "")
    progress_context = _build_progress_context(request_data, item_public_id, job_public_id)
    settings = get_effective_settings()

    ensure_directory(save_path)

    final_base_name = f"{request_data.get('filenamePrefix') or ''}{get_final_filename(original_file_name, custom_file_name)}"
    include_quality = bool(settings.get("downloadDefaults", {}).get("includeAudioQualityInFileName", False))
    final_file_name = _build_output_filename(
        final_base_name,
        format_requested,
        quality_requested,
        include_quality,
        video=False,
    )
    final_output_path = os.path.join(save_path, final_file_name)
    overwrite = overwrite_enabled(settings)

    usage_tracker = TransferUsageTracker(DB_MANAGER, int(item_id) if item_id else None)
    persist_progress = _build_progress_persister(item_id)

    async def account_audio_progress(downloaded_bytes: int | None, stream_id: str = "") -> None:
        usage_tracker.record_progress(f"audio:{stream_id}", downloaded_bytes)

    with tempfile.TemporaryDirectory(prefix="yousnipe_", dir=save_path) as temp_dir:
        audio_temp_template = os.path.join(temp_dir, "audio_temp.%(ext)s")
        converted_output_path = _staged_output_path(save_path, format_requested)

        try:
            assert_transfer_allowed(DB_MANAGER, settings)
            await download_best_audio(
                url=url,
                output_template=audio_temp_template,
                websocket=websocket,
                start_pct=1,
                end_pct=70,
                allow_playlist=allow_playlist,
                progress_context=progress_context,
                network_progress_callback=account_audio_progress,
                progress_callback=persist_progress,
            )

            audio_file = find_first_matching_file(temp_dir, "audio_temp.*")
            if not audio_file:
                raise RuntimeError("Audio temp file not found after download")

            source_info = await probe_media_file(audio_file)

            audio_plan = plan_audio_output(source_info, format_requested, quality_requested,
                                           os.path.splitext(audio_file)[1])
            if audio_plan['mode'] == 'direct':
                await send_stage_progress(websocket, 'finalizing', 96,
                                          'Using already compatible audio without FFmpeg', **progress_context)
                shutil.move(audio_file, converted_output_path)
            else:
                await convert_audio_file(
                    websocket=websocket,
                    input_audio_file=audio_file,
                    output_path=converted_output_path,
                    format_requested=format_requested,
                    quality_requested=quality_requested,
                    duration_seconds=source_info.get("durationSeconds"),
                    progress_context=progress_context,
                    progress_callback=persist_progress,
                    source_info=source_info,
                )

            if not file_exists_and_nonzero(converted_output_path):
                raise RuntimeError("Final audio file was not created or is empty")

            if include_quality and not quality_requested.isdigit():
                final_probe = await probe_media_file(converted_output_path)
                bitrate = final_probe.get("audioBitrateKbps")
                
                tag = f"{bitrate}" if bitrate else ("Lossless" if format_requested in ("ALAC", "FLAC", "WAV") else "")
                final_output_path = os.path.join(save_path, _build_output_filename(
                    final_base_name, format_requested, tag, bool(tag), video=False))
            final_output_path = replace_completed_output(converted_output_path, final_output_path, overwrite)
        finally:
            if os.path.exists(converted_output_path):
                os.remove(converted_output_path)

    await send_stage_progress(websocket, "finalizing", 100, "Download completed", **progress_context)
    if item_id:
        DB_MANAGER.update_item_progress(
            item_id=int(item_id),
            status="completed",
            stage="completed",
            progress_percent=100.0,
            file_path=final_output_path,
        )
    if job_id:
        DB_MANAGER.finalize_job_if_complete(int(job_id))
    await send_ws(
        websocket,
        {
            "type": "download_complete",
            "data": {
                **progress_context,
                "filePath": final_output_path,
            },
        },
    )


async def execute_download_item(websocket, data: dict, client_request_id: str) -> None:
    settings = get_effective_settings()

    
    
    if isinstance(data, dict) and not str(data.get("originalFileName") or "").strip():
        data = {**data, "originalFileName": "Download"}
    validation_error = validate_download_request(data)
    if validation_error:
        raise ValueError(validation_error)

    target_format = (data.get("format") or "").strip().upper()
    media_mode = "audio" if str(data.get("mediaMode") or "").lower() == "audio" or (is_audio_format(target_format) and target_format != "MP4") else "video"
    save_path = _resolve_save_path(data, media_mode, settings)
    if not save_path:
        raise ValueError("Download request missing save path")

    try:
        assert_transfer_allowed(DB_MANAGER, settings)
    except YouSnipeDataCapReachedError as exc:
        
        raise exc

    playlist_folder_name = str(data.get("playlistFolderName") or "").strip()
    if settings.get("playlist", {}).get("createPlaylistFolder", True) and playlist_folder_name:
        save_path = os.path.join(save_path, get_final_filename(playlist_folder_name, ""))

    try:
        playlist_index = int(data.get("playlistIndex"))
    except (TypeError, ValueError):
        playlist_index = None

    playlist_settings = settings.get("playlist", {})
    filename_prefix = ""
    if playlist_index and playlist_settings.get("addPlaylistIndexToFileName", False):
        filename_prefix = f"{playlist_index:02d} - "

    request_data = {
        "url": (data.get("url") or "").strip(),
        "savePath": save_path,
        "originalFileName": (data.get("originalFileName") or "").strip(),
        "customFileName": (data.get("customFileName") or "").strip(),
        "format": (data.get("format") or "").strip(),
        "mediaMode": media_mode,
        "quality": str(data.get("quality") or "").strip(),
        "playlistFolderName": playlist_folder_name,
        "playlistIndex": playlist_index,
        "filenamePrefix": filename_prefix,
        "_clientRequestId": client_request_id,
    }
    
    
    allow_playlist = False

    item_metadata = {
        "request": {
            "customFileName": request_data["customFileName"],
            "format": request_data["format"],
            "quality": request_data["quality"],
            "savePath": request_data["savePath"],
        }
    }
    if playlist_index and playlist_settings.get("addPlaylistIndexToMetadata", False):
        item_metadata["playlist"] = {"index": playlist_index}

    persisted = data.get("_persisted") if isinstance(data.get("_persisted"), dict) else None
    if persisted:
        job = DB_MANAGER.get_job_by_uuid(str(persisted.get("jobId") or "")) or {}
        item = DB_MANAGER.get_download_item_with_job(str(persisted.get("itemId") or "")) or {}
    else:
        queue_record = DB_MANAGER.enqueue_single(
            source_url=request_data["url"], target_media_mode=media_mode, target_format=target_format,
            target_quality=request_data["quality"], save_path=save_path, title=request_data["originalFileName"], metadata=item_metadata,
        )
        job = queue_record.get("job") or {}
        item = (queue_record.get("items") or [{}])[0]
    job_id = int(job.get("id")) if job.get("id") is not None else None
    item_id = int(item.get("id")) if item.get("id") is not None else None
    item_public_id = str(item.get("item_uuid") or "")
    job_public_id = str(job.get("job_uuid") or "")

    if item_id:
        DB_MANAGER.update_item_progress(item_id=item_id, status="running", progress_percent=0.0)
    if job_id:
        DB_MANAGER.update_job_status(job_id, "running")

    request_data["_jobId"] = job_id
    request_data["_itemId"] = item_id
    request_data["_jobPublicId"] = job_public_id
    request_data["_itemPublicId"] = item_public_id

    await send_ws(
        websocket,
        {
            "type": "download_enqueued",
            "success": True,
            "data": {
                "jobId": job_public_id,
                "itemId": item_public_id,
                "clientRequestId": client_request_id,
                "status": "running",
                "title": request_data["customFileName"] or request_data["originalFileName"],
                "sourceUrl": request_data["url"],
                "format": request_data["format"],
                "quality": request_data["quality"],
                "savePath": request_data["savePath"],
            },
        },
    )

    try:
        if request_data.get("mediaMode") == "video" or (is_video_format(request_data["format"]) and request_data.get("mediaMode") != "audio"):
            await handle_video_download_request(websocket, request_data, allow_playlist=allow_playlist)
        elif is_audio_format(request_data["format"]):
            await handle_audio_download_request(websocket, request_data, allow_playlist=allow_playlist)
        else:
            if item_id:
                DB_MANAGER.update_item_progress(
                    item_id=item_id,
                    status="failed",
                    error_message=f"Unsupported format requested: {request_data['format']}",
                )
            if job_id:
                DB_MANAGER.update_job_status(
                    job_id,
                    "failed",
                    f"Unsupported format requested: {request_data['format']}",
                )
            await send_error(
                websocket,
                f"Unsupported format requested: {request_data['format']}",
                "UNSUPPORTED_FORMAT",
            )
    except asyncio.CancelledError:
        if item_id:
            DB_MANAGER.update_item_progress(
                item_id=item_id,
                status="cancelled",
                stage="cancelled",
                error_message="Cancelled by user",
            )
        if job_id:
            DB_MANAGER.finalize_job_if_complete(job_id)

        await send_ws(
            websocket,
            {
                "type": "download_canceled",
                "success": True,
                "data": {
                    **_build_progress_context(request_data, item_public_id, job_public_id),
                    "message": "Download cancelled by user",
                },
            },
        )
        raise
    except Exception as exc:
        print(f"Download failed: {exc}")
        try:
            from YouSnipePaths import appdata_subdirectory
            log_dir = appdata_subdirectory("Logs")
            log_dir.mkdir(parents=True, exist_ok=True)
            with (log_dir / "YouSnipeDownloads.log").open("a", encoding="utf-8") as handle:
                handle.write(f"\nURL: {request_data['url']}\n")
                handle.write(traceback.format_exc() + "\n")
        except OSError:
            pass
        error_code = getattr(exc, "code", "DOWNLOAD_FAILED")
        if item_id:
            DB_MANAGER.update_item_progress(
                item_id=item_id,
                status="failed",
                stage="failed",
                error_code=error_code,
                error_message=str(exc),
            )
        if job_id:
            DB_MANAGER.finalize_job_if_complete(job_id)
        await send_ws(
            websocket,
            {
                "type": "download_failed",
                "success": False,
                "data": {
                    **_build_progress_context(request_data, item_public_id, job_public_id),
                    "message": str(exc),
                    "code": error_code,
                },
            },
        )