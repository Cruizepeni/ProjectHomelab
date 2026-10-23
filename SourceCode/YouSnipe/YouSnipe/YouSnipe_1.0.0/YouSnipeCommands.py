from __future__ import annotations

import asyncio
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any

from YouSnipeCommon import AUDIO_OUTPUT_FORMATS, VIDEO_OUTPUT_FORMATS
from YouSnipeDataCap import get_data_cap_status, reset_data_cap
from YouSnipeDataUsage import get_usage_history, get_usage_overview, parse_ranges
from YouSnipeDBManager import YouSnipeDBManager
from YouSnipeDownloadEngine import build_metadata_response, fetch_metadata
from YouSnipeDependencies import dependency_report, install_missing_dependencies
from YouSnipePaths import appdata_subdirectory
from YouSnipeSettings import get_effective_settings, update_settings
from YouSnipeShowFile import reveal_file_in_folder
from YouSnipeUpdater import CURRENT_VERSION, check_update, start_external_update

TERMINAL_STATUSES = frozenset({'completed', 'failed', 'cancelled', 'partial'})
DESTRUCTIVE = frozenset({'remove download history item', 'remove all download history', 'remove data usage history item', 'remove all data usage history', 'reset data cap'})
CONFIRMATION_ACTIONS = DESTRUCTIVE | {'start update'}
DOWNLOAD_ACTIONS = frozenset({'download', 'download playlist', 'confirm playlist download', 'cancel download', 'cancel download job', 'retry download', 'retry download job', 'remove download queue item', 'remove download queue job'})
CACHE = appdata_subdirectory('Cache') / 'CommandRequests'
EXPIRY_SECONDS = 30 * 60


class CommandError(ValueError):
    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


def error_response(exc: Exception) -> dict:
    code = getattr(exc, 'code', None)
    if not code and isinstance(exc, LookupError):
        code = str(exc) or 'NOT_FOUND'
    return {'code': code or 'INVALID_REQUEST', 'message': str(exc), **getattr(exc, 'details', {})}


def _entry_path(prefix: str, reference: str) -> Path:
    if not isinstance(reference, str) or len(reference) != 32 or any(c not in '0123456789abcdef' for c in reference):
        raise CommandError('INVALID_REQUEST', 'Invalid selection or approval identifier')
    return CACHE / f'{prefix}-{reference}.json'


def _save_request(prefix: str, data: dict) -> str:
    CACHE.mkdir(parents=True, exist_ok=True)
    reference = secrets.token_hex(16)
    target = _entry_path(prefix, reference)
    record = {'expires': time.time() + EXPIRY_SECONDS, **data}
    with target.open('x', encoding='utf-8') as stream:
        os.chmod(target, 0o600)
        json.dump(record, stream, ensure_ascii=False)
    return reference


def _load_request(prefix: str, reference: str, consume: bool = False) -> dict:
    target = _entry_path(prefix, reference)
    if consume:
        try:
            target.rename(target.with_suffix('.claimed'))
        except FileNotFoundError as exc:
            raise CommandError('REQUEST_EXPIRED', 'Request is no longer available') from exc
        target = target.with_suffix('.claimed')
    try:
        record = json.loads(target.read_text(encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise CommandError('REQUEST_EXPIRED', 'Request is no longer available') from exc
    finally:
        if consume:
            target.unlink(missing_ok=True)
    if time.time() > record.get('expires', 0):
        raise CommandError('REQUEST_EXPIRED', 'Request expired. Submit the operation again.')
    return record


def _positive_list(raw: Any) -> list[str]:
    if isinstance(raw, (list, tuple)):
        return [str(item).strip() for item in raw if str(item).strip()]
    return [segment.strip() for segment in str(raw or '').split(',') if segment.strip()]


def _permission(command: str, data: dict, origin: str) -> None:
    if origin != 'aitool':
        return
    cfg = get_effective_settings()['aiTool']
    if not cfg['enabled']:
        raise CommandError('ACCESS_DENIED', 'AITool is disabled')
    if command == 'update setting':
        changes = data.get('changes')
        target_name = str(data.get('name') or '').split('.')[0]
        if (changes is not None and not isinstance(changes, dict)) or (isinstance(changes, dict) and any(str(section).casefold() == 'aitool' for section in changes)) or target_name.casefold() == 'aitool':
            raise CommandError('ACCESS_DENIED', 'AITool settings cannot be changed through the AITool entry point')
        if not cfg['enableSettingsUpdates']:
            raise CommandError('ACCESS_DENIED', 'AITool settings updates are disabled')
    if command in DOWNLOAD_ACTIONS and not cfg['enableDownloads']:
        raise CommandError('ACCESS_DENIED', 'AITool downloads and download management are disabled')
    if command in DESTRUCTIVE and not cfg['enableHistoryRemoval']:
        raise CommandError('ACCESS_DENIED', 'AITool history removal is disabled')
    if command == 'start update':
        raise CommandError('ACCESS_DENIED', 'Application updates require frontend or local user authorisation')
    if command == 'confirm operation':
        raise CommandError('ACCESS_DENIED', 'AITool cannot approve its own operations')
    if command in {'remove download queue item', 'remove download queue job'}:
        db = YouSnipeDBManager()
        ident = str(data.get('id') or '')
        record = db.get_item_by_uuid(ident) if command.endswith('item') else db.get_job_by_uuid(ident)
        if record and (record.get('job_status') in TERMINAL_STATUSES or record.get('status') in TERMINAL_STATUSES) and not cfg['enableHistoryRemoval']:
            raise CommandError('ACCESS_DENIED', 'Removing completed download records is restricted')


def _default_download_arguments(data: dict) -> dict:
    settings = get_effective_settings()['downloadDefaults']
    mode = str(data.get('mediaMode', data.get('mode') or settings['defaultMediaMode'])).casefold()
    if mode not in {'audio', 'video'}:
        raise CommandError('INVALID_REQUEST', 'Mode must be audio or video')
    fmt = str(data.get('format') or (settings['defaultAudioFormat'] if mode == 'audio' else settings['defaultVideoFormat'])).upper()
    if fmt not in (AUDIO_OUTPUT_FORMATS if mode == 'audio' else VIDEO_OUTPUT_FORMATS):
        raise CommandError('UNSUPPORTED_FORMAT', f'Format {fmt} is not valid for {mode}')
    return {**data, 'mediaMode': mode, 'format': fmt, 'quality': str(data.get('quality') or 'Highest')}


def _playlist_exclusions(items: list[dict], excludes: Any) -> tuple[list[dict], list[dict]]:
    values = _positive_list(excludes)
    positions = {int(value) for value in values if value.isdigit()}
    ids = {value[3:] if value.startswith('id:') else value for value in values if not value.isdigit()}
    valid_positions = {int(item['index']) for item in items}
    valid_ids = {str(item['id']) for item in items}
    invalid = (positions - valid_positions) | (ids - valid_ids)
    if invalid:
        raise CommandError('INVALID_EXCLUSION', 'Unknown playlist positions or IDs: ' + ', '.join(sorted(map(str, invalid))))
    selected = [item for item in items if int(item['index']) not in positions and str(item['id']) not in ids and item.get('available')]
    excluded = [item for item in items if int(item['index']) in positions or str(item['id']) in ids]
    if not selected:
        raise CommandError('NO_PLAYABLE_ENTRIES', 'No playable playlist entries remain after exclusions')
    return selected, excluded


class CommandDispatcher:
    def __init__(self, manager=None):
        if manager is None:
            from YouSnipeJobManager import YouSnipeJobManager
            manager = YouSnipeJobManager()
        self.manager = manager
        self.db = manager.db
        self.started = False
        self.shutdown_requested = asyncio.Event()
        self.restart_mode = 'gui'

    def prepare_playlist(self, request: dict, playlist: dict) -> dict:
        if not isinstance(playlist, dict) or not isinstance(playlist.get('items'), list):
            raise CommandError('INVALID_PLAYLIST', 'Playlist items are missing')
        if not any(item.get('available') for item in playlist['items']):
            raise CommandError('NO_PLAYABLE_ENTRIES', 'Playlist contains no playable items')
        selection_id = _save_request('playlist', {'request': _default_download_arguments(request), 'playlist': playlist})
        return {'confirmationRequired': True, 'selectionId': selection_id, 'playlist': playlist, 'expiresInSeconds': EXPIRY_SECONDS}

    async def execute(self, command: str, args: dict | None = None, origin: str = 'cli', approved: bool = False) -> dict:
        command = ' '.join(str(command or '').casefold().split())
        data = args if isinstance(args, dict) else {}
        _permission(command, data, origin)
        if command == 'confirm operation':
            if origin == 'aitool':
                raise CommandError('ACCESS_DENIED', 'AITool cannot approve operations')
            request = _load_request('approval', str(data.get('approvalId') or ''), consume=True)
            return await self.execute(request['command'], request['args'], origin='trusted', approved=True)
        active_remove = command in {'remove download queue item', 'remove download queue job'}
        record = None
        if active_remove:
            ident = str(data.get('id') or '')
            record = self.db.get_item_by_uuid(ident) if command.endswith('item') else self.db.get_job_by_uuid(ident)
        needs_confirmation = command in CONFIRMATION_ACTIONS or (active_remove and record and (record.get('status') in TERMINAL_STATUSES or record.get('job_status') in TERMINAL_STATUSES))
        if needs_confirmation and not approved:
            approval_id = _save_request('approval', {'command': command, 'args': data})
            raise CommandError('CONFIRMATION_REQUIRED', f'Confirm destructive operation: {command}', approvalId=approval_id, command=command)
        if command in {'system ping', 'ping'}:
            return {'service': 'YouSnipe'}
        if command == 'get system info':
            return {'service': 'YouSnipe', 'version': CURRENT_VERSION, 'schemaVersion': 3}
        if command == 'get capabilities':
            return {'audioFormats': sorted(AUDIO_OUTPUT_FORMATS), 'videoFormats': sorted(VIDEO_OUTPUT_FORMATS), 'supportsPlaylists': True, 'commands': list(COMMANDS)}
        if command == 'get dependencies':
            return dependency_report(get_effective_settings()['runtime'])
        if command == 'install dependencies':
            from YouSnipeCommon import safe_json_dumps
            loop = asyncio.get_running_loop()
            def report(event):
                message = safe_json_dumps({'event': 'dependency installation progress', 'data': event})
                if origin in {'cli', 'trusted'}:
                    print(message, flush=True)
                loop.call_soon_threadsafe(lambda raw=message: asyncio.create_task(self.manager.broadcast_raw(raw)))
            return {'installed': await asyncio.to_thread(install_missing_dependencies, get_effective_settings()['runtime'], progress=report)}
        if command == 'get settings':
            return get_effective_settings()
        if command == 'get setting':
            path = str(data.get('name') or '').split('.')
            value = get_effective_settings()
            for part in path:
                if not isinstance(value, dict) or part not in value:
                    raise CommandError('UNKNOWN_SETTING', 'Unknown setting name')
                value = value[part]
            return {'name': '.'.join(path), 'value': value}
        if command == 'update setting':
            changes = data.get('changes')
            if changes is None:
                path = str(data.get('name') or '')
                if not path or '.' not in path:
                    raise CommandError('INVALID_REQUEST', 'Use section.settingName for setting names')
                keys = path.split('.')
                changes = {}
                node = changes
                for key in keys[:-1]:
                    node[key] = {}
                    node = node[key]
                node[keys[-1]] = data.get('value')
            if not isinstance(changes, dict):
                raise CommandError('INVALID_REQUEST', 'Changes must be a JSON object')
            if origin == 'aitool' and any(str(section).casefold() == 'aitool' for section in changes):
                raise CommandError('ACCESS_DENIED', 'AITool settings are immutable through AITool')
            return update_settings(changes)
        if command == 'check updates':
            return await asyncio.to_thread(check_update)
        if command == 'start update':
            if self.shutdown_requested.is_set():
                raise CommandError('UPDATE_ALREADY_STARTED', 'YouSnipe is already preparing to exit for an update')
            active_jobs = [job for job in self.db.list_jobs(include_completed=False) if job.get('status') not in TERMINAL_STATUSES]
            if active_jobs:
                raise CommandError('DOWNLOADS_ACTIVE', 'Wait for current downloads to finish before updating')
            result = await asyncio.to_thread(start_external_update, self.restart_mode)
            self.shutdown_requested.set()
            return result
        if command == 'get metadata':
            url = str(data.get('url') or '').strip()
            if not url:
                raise CommandError('INVALID_URL', 'Metadata requires a URL')
            return build_metadata_response(await fetch_metadata(url, force_playlist=bool(data.get('playlist', False))))['data']
        if command == 'download':
            return await self.manager.create_download(_default_download_arguments(data))
        if command == 'download playlist':
            request = _default_download_arguments(data)
            url = str(request.get('url') or '').strip()
            if not url:
                raise CommandError('INVALID_URL', 'Playlist URL is required')
            metadata = build_metadata_response(await fetch_metadata(url, force_playlist=True))['data']
            playlist = metadata.get('playlist')
            if not playlist:
                raise CommandError('INVALID_PLAYLIST', 'URL did not return a playlist')
            return self.prepare_playlist(request, playlist)
        if command == 'confirm playlist download':
            selection = _load_request('playlist', str(data.get('selectionId') or ''), consume=False)
            entries, excluded = _playlist_exclusions(selection['playlist']['items'], data.get('excludeItems', []))
            request = selection['request']
            payload = {**request, 'playlistName': request.get('playlistName') or selection['playlist']['name'], 'items': entries}
            _load_request('playlist', str(data['selectionId']), consume=True)
            result = await self.manager.create_playlist(payload)
            return {**result, 'excludedItems': excluded, 'playlistTotalItems': len(selection['playlist']['items'])}
        if command == 'get download queue':
            return {'jobs': self.db.list_jobs(include_completed=False)}
        if command == 'get download jobs':
            return {'jobs': self.db.list_jobs(include_completed=bool(data.get('includeCompleted', True)))}
        if command == 'get download status':
            ident = str(data.get('id') or '')
            return self.manager.get_item(ident) if self.db.get_item_by_uuid(ident) else self.manager.get_job(ident)
        if command == 'cancel download':
            ident = str(data.get('id') or '')
            if not await self.manager.cancel_item(ident):
                raise LookupError('ITEM_NOT_FOUND')
            return {'itemId': ident, 'status': 'cancelled'}
        if command == 'cancel download job':
            ident = str(data.get('id') or '')
            if not await self.manager.cancel_job(ident):
                raise LookupError('JOB_NOT_FOUND')
            return {'jobId': ident, 'status': 'cancelled'}
        if command == 'retry download':
            return await self.manager.retry_item(str(data.get('id') or ''))
        if command == 'retry download job':
            return await self.manager.retry_job(str(data.get('id') or ''))
        if command == 'remove download queue item':
            return self.manager.remove_item(str(data.get('id') or ''))
        if command == 'remove download queue job':
            return self.manager.remove_job(str(data.get('id') or ''))
        if command == 'get download history':
            return {'jobs': self.db.list_terminal_jobs(include_failed=get_effective_settings()['history']['keepFailedDownloadsInHistory'])}
        if command == 'get download history item':
            ident = str(data.get('id') or '')
            record = self.db.get_job_by_uuid(ident)
            if record and record['status'] in TERMINAL_STATUSES:
                return self.manager.get_job(ident)
            record = self.db.get_item_by_uuid(ident)
            if record and record['status'] in TERMINAL_STATUSES:
                return self.manager.get_item(ident)
            raise LookupError('HISTORY_ITEM_NOT_FOUND')
        if command == 'remove download history item':
            results = []
            identities = _positive_list(data.get('ids', data.get('id')))
            if not identities:
                raise CommandError('INVALID_REQUEST', 'At least one history item identifier is required')
            for ident in identities:
                job = self.db.get_job_by_uuid(ident)
                item = self.db.get_item_by_uuid(ident)
                if job and job['status'] in TERMINAL_STATUSES:
                    results.append({'id': ident, 'removed': self.db.remove_job_by_uuid(ident)})
                elif item and item['status'] in TERMINAL_STATUSES:
                    results.append({'id': ident, **self.manager.remove_item(ident)})
                else:
                    results.append({'id': ident, 'removed': False, 'error': 'HISTORY_ITEM_NOT_FOUND'})
            return {'results': results}
        if command == 'remove all download history':
            return self.db.clear_terminal_history()
        if command == 'get data usage':
            return {**get_usage_overview(self.db, data.get('value'), data.get('unit')), 'dataCap': get_data_cap_status(self.db)}
        if command == 'get data usage history':
            return {'buckets': get_usage_history(self.db, data.get('groupBy') or 'day', data.get('start'), data.get('end'))}
        if command == 'remove data usage history item':
            return self.db.delete_usage_ranges(parse_ranges(data.get('ranges')))
        if command == 'remove all data usage history':
            return self.db.clear_usage_history_with_summary()
        if command == 'get data cap':
            return get_data_cap_status(self.db)
        if command == 'reset data cap':
            return reset_data_cap(self.db)
        if command == 'reveal file':
            result = reveal_file_in_folder(str(data.get('filePath') or ''))
            if not result.get('ok'):
                raise CommandError('FILE_NOT_FOUND', str(result.get('message') or 'Unable to reveal file'))
            return result
        raise CommandError('UNKNOWN_COMMAND', f'Unknown YouSnipe command: {command}')


COMMANDS = (
    'download', 'download playlist', 'confirm playlist download', 'get metadata',
    'get download queue', 'get download jobs', 'get download status',
    'cancel download', 'cancel download job', 'retry download', 'retry download job',
    'remove download queue item', 'remove download queue job',
    'get download history', 'get download history item', 'remove download history item',
    'remove all download history', 'get settings', 'get setting', 'update setting',
    'get dependencies', 'install dependencies', 'check updates', 'start update',
    'get data usage', 'get data usage history', 'remove data usage history item',
    'remove all data usage history', 'get data cap', 'reset data cap',
    'get system info', 'get capabilities', 'system ping', 'reveal file', 'confirm operation',
)
