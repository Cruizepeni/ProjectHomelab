from __future__ import annotations

import asyncio
import hmac
import json
import os
import secrets
import logging
from pathlib import Path

import websockets
from websockets.exceptions import ConnectionClosed, InvalidMessage

from YouSnipeCommands import CommandDispatcher, CommandError, error_response
from YouSnipeCommon import safe_json_dumps
from YouSnipePaths import appdata_subdirectory
from YouSnipeSettings import get_effective_settings


class _AbortedHandshakeFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        exception = record.exc_info[1] if record.exc_info else None
        return not isinstance(exception, (InvalidMessage, EOFError))


logging.getLogger('websockets.server').addFilter(_AbortedHandshakeFilter())


def access_token(origin: str) -> str:
    if origin not in {'frontend', 'aitool'}:
        raise ValueError('Unknown server origin')
    directory = appdata_subdirectory('ServerAccess')
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ('YouSnipeAIToolToken.txt' if origin == 'aitool' else 'YouSnipeFrontendToken.txt')
    if path.exists():
        saved = path.read_text(encoding='utf-8').strip()
        if len(saved) < 40:
            raise RuntimeError('Server access token is invalid; manually remove its file to regenerate credentials')
        return saved
    token = secrets.token_urlsafe(48)
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(token)
    except FileExistsError:
        return path.read_text(encoding='utf-8').strip()
    return token


async def process_messages(websocket, dispatcher: CommandDispatcher) -> None:
    origin = None
    frontend_token = access_token('frontend')
    try:
        async for raw_payload in websocket:
            request_id = ''
            command = ''
            try:
                message = json.loads(raw_payload)
                if not isinstance(message, dict):
                    raise CommandError('INVALID_REQUEST', 'Request must be a JSON object')
                request_id = str(message.get('requestId') or '')
                command = ' '.join(str(message.get('command') or '').casefold().split())
                if origin is None:
                    provided_token = str(message.get('token') or '')
                    if command == 'authenticate' and provided_token and hmac.compare_digest(provided_token, frontend_token):
                        origin = 'frontend'
                    elif command == 'authenticate':
                        from YouSnipeAITool import authenticate_ai_tool
                        if authenticate_ai_tool(provided_token, access_token):
                            origin = 'aitool'
                    if origin is None:
                        await websocket.send(safe_json_dumps({'requestId': request_id, 'command': 'authenticate', 'success': False, 'error': {'code': 'AUTH_REQUIRED', 'message': 'Authenticate with a valid server or enabled Ai Tool access token'}}))
                        await websocket.close(code=1008, reason='Authentication required')
                        return
                    dispatcher.manager.subscribe(websocket)
                    await websocket.send(safe_json_dumps({'requestId': request_id, 'command': 'authenticate', 'success': True, 'data': {'authenticated': True, 'role': origin}}))
                    continue
                if command == 'authenticate':
                    raise CommandError('INVALID_REQUEST', 'Already authenticated')
                result = await dispatcher.execute(command, message.get('args'), origin=origin)
                payload = {'requestId': request_id, 'command': command, 'success': True, 'data': result}
            except Exception as exc:
                error = error_response(exc)
                payload = {'requestId': request_id, 'command': command, 'success': False, 'error': error}
            await websocket.send(safe_json_dumps(payload))
            if dispatcher.shutdown_requested.is_set():
                await websocket.close(code=1001, reason='YouSnipe updating')
                return
    except ConnectionClosed:
        pass
    finally:
        dispatcher.manager.unsubscribe(websocket)


async def start_server(host: str | None = None, port: int | None = None, terminal: bool = False, dispatcher: CommandDispatcher | None = None, on_ready=None) -> None:
    settings = get_effective_settings()
    host = host or settings['server']['host']
    port = port or settings['server']['port']
    if host not in {'127.0.0.1', 'localhost', '::1'}:
        raise ValueError('YouSnipe servers are restricted to loopback interfaces')
    dispatcher = dispatcher or CommandDispatcher()
    if dispatcher.restart_mode == 'gui':
        dispatcher.restart_mode = 'headless-server'
    if not dispatcher.started:
        await dispatcher.manager.start()
        dispatcher.started = True
    access_token('frontend')
    access_token('aitool')
    async with websockets.serve(lambda websocket: process_messages(websocket, dispatcher), host, port, max_size=2**20):
        if on_ready:
            on_ready()
        if terminal:
            print(f'YouSnipe API on ws://{host}:{port} (Ai Tool shares this listener when enabled)', flush=True)
        await dispatcher.shutdown_requested.wait()
