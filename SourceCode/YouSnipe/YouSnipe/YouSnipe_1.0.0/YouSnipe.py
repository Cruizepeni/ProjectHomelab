
from __future__ import annotations

import argparse
import asyncio
import gc
import json
import queue
import threading
import os
import sys
import time
import traceback
from pathlib import Path

from YouSnipeDependencies import dependency_report, installation_plan, install_missing_dependencies
from YouSnipePythonDependencies import missing_python_packages, install_python_packages
from YouSnipeSettings import get_effective_settings, get_accent_color
from YouSnipeUpdater import check_update, CURRENT_VERSION


def prepare_windows_gui() -> None:
    
    if sys.platform != 'win32':
        return
    import ctypes
    kernel32 = ctypes.windll.kernel32
    
    if not kernel32.GetConsoleWindow():
        return
    try:
        from YouSnipePaths import appdata_subdirectory
        log_dir = appdata_subdirectory('Logs')
        log_dir.mkdir(parents=True, exist_ok=True)
        log_stream = open(log_dir / 'YouSnipeGUI.log', 'a', encoding='utf-8', buffering=1)
        sys.stdout = log_stream
        sys.stderr = log_stream
    except OSError:
        
        sys.stdout = sys.stderr = open(os.devnull, 'w')
    kernel32.FreeConsole()


def cli_parser() -> argparse.ArgumentParser:
    from YouSnipeCommands import COMMANDS
    parser = argparse.ArgumentParser(
        description='YouSnipe 1.0.0 CLI-first downloader',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='Commands (also used by WebSocket):\n  ' + '\n  '.join(COMMANDS) +
               '\n\nExamples:\n  YouSnipe.py get download history\n  YouSnipe.py download playlist https://example.com/playlist --format mp4\n  YouSnipe.py confirm playlist download <selectionId> --exclude 2,4\n  YouSnipe.py update setting server.port 5032')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--headless', action='store_const', dest='mode', const='headless')
    modes.add_argument('--headless-server', action='store_const', dest='mode', const='headless-server')
    modes.add_argument('--diagnostics', action='store_const', dest='mode', const='diagnostics')
    modes.add_argument('--check-image-support', action='store_const', dest='mode', const='check-image-support', help=argparse.SUPPRESS)
    modes.add_argument('--install-desktop', action='store_const', dest='mode', const='install-desktop', help='Add YouSnipe to your Linux application menu')
    modes.add_argument('--remove-desktop', action='store_const', dest='mode', const='remove-desktop', help='Remove YouSnipe from your Linux application menu')
    modes.add_argument('--install-dependencies', action='store_const', dest='mode', const='install-dependencies')
    modes.add_argument('--check-update', action='store_const', dest='mode', const='check-update')
    parser.add_argument('--updated', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--updater-pid', type=int, help=argparse.SUPPRESS)
    parser.add_argument('--updater-path', help=argparse.SUPPRESS)
    parser.add_argument('--previous-version', help=argparse.SUPPRESS)
    parser.add_argument('--update-health-token', help=argparse.SUPPRESS)
    return parser


def parse_command_tokens(tokens: list[str]) -> tuple[str, dict]:
    import shlex
    from YouSnipeCommands import COMMANDS, CommandError
    if isinstance(tokens, str):
        tokens = shlex.split(tokens)
    normalized = [str(t).casefold() for t in tokens]
    command = next((candidate for candidate in sorted(COMMANDS, key=lambda name: -len(name.split()))
                    if normalized[:len(candidate.split())] == candidate.split()), None)
    if command is None:
        raise CommandError('UNKNOWN_COMMAND', 'Unknown YouSnipe command. Run --help for available commands.')
    arguments = tokens[len(command.split()):]
    fields = {'--mode':'mode','--format':'format','--quality':'quality',
              '--save-path':'savePath','--exclude':'excludeItems',
              '--group-by':'groupBy','--start':'start','--end':'end',
              '--value':'value','--unit':'unit','--ranges':'ranges',
              '--file-path':'filePath'}
    positional = []
    data = {}
    pos = 0
    while pos < len(arguments):
        value = arguments[pos]
        if value in fields:
            if pos + 1 >= len(arguments):
                raise CommandError('INVALID_REQUEST', f'{value} requires a value')
            data[fields[value]] = arguments[pos + 1]
            pos += 2
        elif value == '--playlist':
            data['playlist'] = True
            pos += 1
        elif value == '--include-completed':
            data['includeCompleted'] = True
            pos += 1
        elif value.startswith('--'):
            raise CommandError('INVALID_REQUEST', f'Unknown option: {value}')
        else:
            positional.append(value)
            pos += 1
    first_arg = {
        'download':'url', 'download playlist':'url', 'get metadata':'url',
        'confirm playlist download':'selectionId', 'confirm operation':'approvalId',
        'get setting':'name', 'update setting':'name',
        'get download status':'id', 'get download history item':'id',
        'cancel download':'id', 'cancel download job':'id',
        'retry download':'id', 'retry download job':'id',
        'remove download queue item':'id', 'remove download queue job':'id',
        'remove download history item':'ids',
    }.get(command)
    if command == 'remove download history item' and positional:
        data['ids'] = ','.join(segment.strip(' ,') for segment in positional)
        positional.clear()
    elif first_arg and positional:
        data[first_arg] = positional.pop(0)
    if command == 'update setting' and positional:
        import json
        raw = ' '.join(positional)
        try:
            data['value'] = json.loads(raw)
        except json.JSONDecodeError:
            data['value'] = raw
        positional = []
    if 'ranges' in data:
        try:
            data['ranges'] = json.loads(data['ranges'])
        except (NameError, ValueError) as exc:
            raise CommandError('INVALID_REQUEST', '--ranges requires a JSON array') from exc
    if positional:
        raise CommandError('INVALID_REQUEST', 'Unexpected arguments: ' + ' '.join(positional))
    if not first_arg and command not in ('get data usage','get data usage history') and arguments and not data:
        raise CommandError('INVALID_REQUEST', 'Unexpected arguments')
    return command, data


async def run_one_shot(command: str, args: dict, dispatcher=None, origin: str = 'cli', wait: bool = True) -> dict:
    from YouSnipeCommands import CommandDispatcher, CommandError
    new_dispatcher = dispatcher is None
    dispatcher = dispatcher or CommandDispatcher()
    if new_dispatcher and command == 'start update':
        dispatcher.restart_mode = 'headless'
    if command in ('download', 'confirm playlist download') and not dispatcher.started:
        await dispatcher.manager.start()
        dispatcher.started = True
    try:
        result = await dispatcher.execute(command, args, origin=origin)
    except CommandError as exc:
        if exc.code != 'CONFIRMATION_REQUIRED' or not sys.stdin or not sys.stdin.isatty():
            raise
        print(f'{exc}: ', end='', flush=True)
        if input('Approve? [y/N] ').casefold().strip() not in {'y', 'yes'}:
            raise CommandError('USER_DECLINED', 'Operation not approved')
        result = await dispatcher.execute('confirm operation', {'approvalId': exc.details['approvalId']}, origin='cli')
    if wait and command in ('download', 'confirm playlist download') and result.get('jobId'):
        job_id = result['jobId']
        from YouSnipeCommon import safe_json_dumps
        signatures = {}
        print(safe_json_dumps({'queued': result}), flush=True)
        while True:
            job = dispatcher.manager.get_job(job_id)
            if job.get('status') in {'completed', 'failed', 'cancelled', 'partial'}:
                result = {**result, 'finalStatus': job['status'], 'job': job}
                break
            current = dispatcher.manager.db.list_download_items_for_job(int(job['id']))
            for item in current:
                signature = (item.get('status'), item.get('stage'), int(float(item.get('progress_percent') or 0) // 5) * 5)
                item_key = item.get('item_uuid')
                if signatures.get(item_key) != signature:
                    signatures[item_key] = signature
                    print(safe_json_dumps({'progress': {'itemId': item_key, 'status': signature[0], 'stage': signature[1], 'percent': item.get('progress_percent')}}), flush=True)
            await asyncio.sleep(0.8)
    return result


class _ConsoleEventSink:
    async def send(self, payload: str) -> None:
        print(payload, flush=True)


async def run_headless(server: bool = False, on_ready=None) -> None:
    from YouSnipeCommands import CommandDispatcher, error_response
    from YouSnipeCommon import safe_json_dumps
    dispatcher = CommandDispatcher()
    dispatcher.restart_mode = 'headless-server' if server else 'headless'
    if server:
        from YouSnipeServer import start_server
        await start_server(dispatcher=dispatcher, on_ready=on_ready)
        return
    await dispatcher.manager.start()
    dispatcher.started = True
    sink = _ConsoleEventSink()
    dispatcher.manager.subscribe(sink)
    if on_ready:
        on_ready()
    if sys.stdin is None:
        await dispatcher.shutdown_requested.wait()
        return
    interactive = bool(sys.stdin.isatty())
    try:
        while not dispatcher.shutdown_requested.is_set():
            if interactive:
                print('YouSnipe> ', end='', flush=True)
            line = await asyncio.to_thread(sys.stdin.readline)
            if not line:
                break
            if line.strip().casefold() in {'exit', 'quit'}:
                break
            if not line.strip():
                continue
            try:
                request_id = None
                if line.lstrip().startswith('{'):
                    message = json.loads(line)
                    if not isinstance(message, dict):
                        raise ValueError('Expected a JSON object')
                    command = str(message.get('command') or '')
                    arguments = message.get('args') or {}
                    request_id = message.get('requestId')
                else:
                    command, arguments = parse_command_tokens(line)
                    request_id = None
                result = await dispatcher.execute(command, arguments, origin='cli')
                response = {'requestId': request_id, 'success': True, 'data': result}
            except Exception as exc:
                response = {'requestId': locals().get('request_id'), 'success': False,
                            'error': error_response(exc)}
            print(safe_json_dumps(response), flush=True)
    finally:
        dispatcher.manager.unsubscribe(sink)
        if dispatcher.manager._tasks:
            await asyncio.gather(*list(dispatcher.manager._tasks.values()), return_exceptions=True)


def _dependency_display_name(value: str) -> str:
    original = str(value or '')
    names = {
        'yt-dlp': 'Yt-dlp',
        'ffmpeg': 'Ffmpeg',
        'ffprobe': 'Ffprobe',
        'deno': 'Deno',
        'pillow': 'Pillow',
        'websockets': 'Websockets',
        '7zip': '7-Zip',
        'python packages': 'Python Packages',
    }
    if original.endswith(' (Python package)'):
        return _dependency_display_name(original[:-17]) + ' (Python package)'
    return names.get(original.casefold(), original)


def confirm_dependency_install(plan: list[str], gui: bool, preapproved: bool = False) -> bool:
    message = 'YouSnipe needs the following components to run:\n\n' + '\n'.join('  - ' + _dependency_display_name(item) for item in plan)
    if '7zip' in plan:
        message += '\n\n7-Zip will be installed system-wide and Windows will request administrator approval.'
    message += '\n\nInstall the missing components now? Choosing No will close YouSnipe.'
    if preapproved:
        print(message)
        return True
    if gui:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        from YouSnipeWindowIcon import apply_window_icon
        apply_window_icon(root)
        root.withdraw()
        try:
            return bool(messagebox.askyesno('YouSnipe - Dependencies Required', message, parent=root))
        finally:
            root.destroy()
    if not sys.stdin or not sys.stdin.isatty():
        print(message, file=sys.stderr)
        print('Noninteractive startup: use --install-dependencies to approve installation.', file=sys.stderr)
        return False
    print(message)
    return input('Install? [y/N]: ').strip().casefold() in {'y', 'yes'}


def install_with_progress(plan: list[str], runtime: dict, gui: bool, python_packages: list[str] | None = None):
    python_packages = python_packages or []

    def install_all(progress=None):
        results = install_missing_dependencies(runtime, progress=progress) if plan else []
        if python_packages:
            results.extend(install_python_packages(python_packages, progress=progress))
        return results

    if not gui:
        progress_steps = {}

        def show_progress(event):
            name = str(event.get('dependency') or '')
            stage = str(event.get('stage') or '').replace('_', ' ').title()
            percent = event.get('percent')
            current = int(float(percent) // 10) * 10 if percent is not None else None
            signature = (stage, current)
            if progress_steps.get(name) == signature:
                return
            progress_steps[name] = signature
            amount = f' {current}%' if current is not None else ''
            print(f'[{event.get("dependencyIndex", 0)}/{event.get("dependencyCount", len(plan))}] {_dependency_display_name(name)}: {stage}{amount}', flush=True)

        return install_all(progress=show_progress)

    import tkinter as tk
    from tkinter import ttk

    accent = get_accent_color()
    updates = queue.Queue()
    result = {}
    window = tk.Tk()
    from YouSnipeWindowIcon import apply_window_icon
    apply_window_icon(window)
    window.title('YouSnipe - Installing Dependencies')
    window.geometry('660x275')
    window.minsize(530, 235)
    window.configure(bg='#0d1117')
    window.protocol('WM_DELETE_WINDOW', lambda: None)
    frame = tk.Frame(window, bg='#0d1117', padx=22, pady=20)
    frame.pack(fill='both', expand=True)
    heading = tk.Label(frame, text='Installing Required Dependencies', bg='#0d1117', fg='#e6edf3',
                       font=('Segoe UI', 14, 'bold'), anchor='w')
    heading.pack(fill='x', pady=(0, 16))
    current_value = tk.StringVar(master=window, value='Preparing installation...')
    tk.Label(frame, textvariable=current_value, bg='#0d1117', fg=accent,
             font=('Segoe UI', 11), anchor='w').pack(fill='x', pady=(0, 10))
    style = ttk.Style(window)
    style.theme_use('clam')
    style.configure('YouSnipe.Horizontal.TProgressbar', background=accent,
                    troughcolor='#151b23', bordercolor='#30363d', lightcolor=accent, darkcolor=accent)
    bar = ttk.Progressbar(frame, maximum=100, mode='indeterminate', length=580,
                          style='YouSnipe.Horizontal.TProgressbar')
    bar.pack(fill='x', pady=(0, 12))
    details_value = tk.StringVar(master=window, value='YouSnipe is verifying the required packages for your operating system.')
    tk.Label(frame, textvariable=details_value, bg='#0d1117', fg='#8b949e',
             font=('Segoe UI', 10), anchor='w', justify='left', wraplength=590).pack(fill='x')
    bar.start(12)

    def worker():
        try:
            installed = install_all(progress=lambda event: updates.put(('progress', event)))
            updates.put(('success', installed))
        except BaseException as exc:
            updates.put(('error', exc))

    def render(event):
        name = str(event.get('dependency') or 'Dependency')
        stage = str(event.get('stage') or '').replace('_', ' ').title()
        index = event.get('dependencyIndex')
        count = event.get('dependencyCount')
        prefix = f'{index} of {count}: ' if index and count else ''
        current_value.set(f'{prefix}{_dependency_display_name(name)} - {stage}')
        done = event.get('downloadedBytes')
        total = event.get('totalBytes')
        if event.get('stage') == 'downloading' and total:
            percent = min(100, max(0, float(done or 0) * 100 / float(total)))
            bar.stop()
            bar.configure(mode='determinate', value=percent)
            details_value.set(f'{(done or 0) / 1048576:.1f} MB / {total / 1048576:.1f} MB  ({percent:.0f}%)')
        else:
            bar.configure(mode='indeterminate')
            bar.start(12)
            details_value.set('Checking package and executable integrity. Please wait.')

    def pump():
        try:
            while True:
                kind, value = updates.get_nowait()
                if kind == 'progress':
                    render(value)
                else:
                    result['value' if kind == 'success' else 'error'] = value
                    bar.stop()
                    window.destroy()
                    return
        except queue.Empty:
            pass
        window.after(75, pump)

    threading.Thread(target=worker, name='YouSnipe-Dependency-Install', daemon=True).start()
    window.after(75, pump)
    window.mainloop()
    if 'error' in result:
        raise result['error']
    if 'value' not in result:
        raise RuntimeError('Dependency installation stopped unexpectedly.')
    return result['value']


def ensure_dependencies(gui: bool, preapproved: bool = False, server: bool = False) -> bool:
    try:
        settings = get_effective_settings()
        plan = installation_plan(settings['runtime'])
        python_packages = missing_python_packages(gui=gui, server=server, all_packages=preapproved)
        if not plan and not python_packages:
            return True
        display_plan = [*plan, *(name + ' (Python package)' for name in python_packages)]
        if not confirm_dependency_install(display_plan, gui, preapproved):
            return False
        if gui:
            gc.collect()
        results = install_with_progress(plan, settings['runtime'], gui, python_packages)
        if gui:
            gc.collect()
        for item in results:
            print(f"Installed {_dependency_display_name(item['dependency'])} {item['version']}: {item['path']}")
        refreshed = dependency_report(get_effective_settings()['runtime'])
        errors = [name for name, value in refreshed.items() if not value['ok']]
        if errors:
            raise RuntimeError('Installed files could not be validated: ' + ', '.join(errors))
        return True
    except Exception as exc:
        from YouSnipePaths import appdata_subdirectory
        path = appdata_subdirectory('Logs') / 'YouSnipeDependencies.log'
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('a', encoding='utf-8') as handle:
                handle.write(traceback.format_exc() + '\n')
        except OSError:
            pass
        message = 'YouSnipe dependency installation failed: ' + str(exc) + '\n\nDetails: ' + str(path)
        if gui:
            from tkinter import messagebox
            messagebox.showerror('YouSnipe - Dependency Error', message)
        else:
            print(message, file=sys.stderr)
        return False
    finally:
        if gui:
            gc.collect()


def _updater_process_alive(pid: int) -> bool:
    if pid <= 0 or pid == os.getpid():
        return False
    if sys.platform == 'win32':
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x00100000, False, pid)
        if not handle:
            return False
        try:
            return ctypes.windll.kernel32.WaitForSingleObject(handle, 0) == 0x102
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _finish_updated_startup(pid: int | None, updater_path: str | None = None, previous_version: str | None = None) -> None:
    from YouSnipeUpdater import _version_key
    if previous_version and _version_key(previous_version) > _version_key(CURRENT_VERSION):
        raise RuntimeError('Previous YouSnipe version is newer than the installed application')
    if pid:
        deadline = time.monotonic() + 30
        while _updater_process_alive(pid) and time.monotonic() < deadline:
            time.sleep(0.15)
        if _updater_process_alive(pid):
            print('Updater is still running; keeping the rollback runtime for safety.')
            return
    appimage = os.environ.get('APPIMAGE') if sys.platform.startswith('linux') else None
    target = Path(appimage or sys.executable if getattr(sys, 'frozen', False) else __file__).resolve()
    if not getattr(sys, 'frozen', False):
        return
    backup = target.with_name('YouSnipeTemp' + target.suffix)
    if backup.is_file():
        try:
            backup.unlink()
        except OSError as exc:
            print('Could not remove the previous runtime backup: ' + str(exc))
    if updater_path:
        from YouSnipeUpdater import expected_updater_name
        candidate = Path(updater_path).expanduser().resolve()
        if candidate == target.parent / expected_updater_name() and candidate.is_file():
            try:
                candidate.unlink()
            except OSError as exc:
                print('Updater executable was retained for safety: ' + str(exc))


def _updated_ready_callback(args):
    def acknowledge():
        if args.update_health_token:
            import re
            from YouSnipeUpdater import runtime_application_path
            if not re.fullmatch(r'[0-9a-f]{32}', args.update_health_token):
                raise RuntimeError('Update health token is invalid')
            target = runtime_application_path()
            path = target.parent / f'.YouSnipeUpdateHealth_{args.updater_pid}.json'
            pending = path.with_suffix('.tmp')
            pending.write_text(json.dumps({'token': args.update_health_token,
                                           'pid': os.getpid(), 'version': CURRENT_VERSION}), encoding='utf-8')
            os.replace(pending, path)
        _finish_updated_startup(args.updater_pid, args.updater_path, args.previous_version)
    return acknowledge


def main(argv: list[str] | None = None) -> int:
    from YouSnipeCommands import COMMANDS, error_response
    from YouSnipeCommon import safe_json_dumps
    parser = cli_parser()
    raw = list(sys.argv[1:] if argv is None else argv)
    if not raw:
        from YouSnipeDesktop import ensure_linux_desktop_integration
        ensure_linux_desktop_integration()
        prepare_windows_gui()
        if not ensure_dependencies(gui=True):
            return 1
        from YouSnipeGUI import main as gui_main
        gui_main()
        return 0
    args, remainder = parser.parse_known_args(raw)
    if args.updated and (not args.updater_pid or not args.updater_path or not args.previous_version or not args.update_health_token):
        parser.error('--updated requires valid updater PID, updater path, previous version and health token')
    if args.mode == 'check-image-support':
        try:
            from PIL import Image, ImageTk, ImageOps
            from io import BytesIO
            for file_format in ('JPEG', 'PNG'):
                target = BytesIO()
                Image.new('RGB', (8, 8), '#e53935').save(target, format=file_format)
                with Image.open(BytesIO(target.getvalue())) as loaded:
                    loaded.load()
                    ImageOps.contain(loaded, (4, 4))
            print('Pillow JPEG/PNG and ImageTk: OK', flush=True)
            return 0
        except Exception as exc:
            print('Pillow thumbnail verification failed: ' + repr(exc), file=sys.stderr, flush=True)
            return 1
    if args.mode in ('install-desktop', 'remove-desktop'):
        try:
            from YouSnipeDesktop import install_desktop, remove_desktop
            result = install_desktop() if args.mode == 'install-desktop' else remove_desktop()
            print(result, flush=True)
            return 0
        except Exception as exc:
            print('Desktop integration failed: ' + str(exc), file=sys.stderr, flush=True)
            return 1
    if args.mode == 'diagnostics':
        from YouSnipePaths import APPDATA_DIR, PROJECT_ROOT
        settings = get_effective_settings()
        report = {'application': 'YouSnipe', 'version': CURRENT_VERSION,
                  'appData': str(APPDATA_DIR), 'projectRoot': str(PROJECT_ROOT or ''),
                  'server': settings['server'], 'aiToolEnabled': settings['aiTool']['enabled'],
                  'dependencies': dependency_report(settings['runtime'])}
        print(json.dumps(report, indent=2), flush=True)
        return 0 if all(value['ok'] for value in report['dependencies'].values()) else 1
    if args.mode == 'check-update':
        try:
            print(safe_json_dumps(check_update()), flush=True)
            return 0
        except Exception as exc:
            print(safe_json_dumps({'success': False, 'error': {'code': 'UPDATE_CHECK_FAILED', 'message': str(exc)}}), file=sys.stderr)
            return 1
    if args.mode == 'install-dependencies':
        if remainder:
            parser.error('--install-dependencies does not take commands')
        return 0 if ensure_dependencies(gui=False, preapproved=True) else 1
    if args.mode in ('headless', 'headless-server'):
        if remainder and args.mode == 'headless-server':
            parser.error('--headless-server does not accept one-shot commands')
        if remainder:
            try:
                command, data = parse_command_tokens(remainder)
                if command in ('download', 'download playlist', 'get metadata', 'confirm playlist download'):
                    if not ensure_dependencies(gui=False, preapproved=False):
                        return 1
                result = asyncio.run(run_one_shot(command, data))
                print(safe_json_dumps(result), flush=True)
                return 0 if result.get('finalStatus') not in ('failed', 'partial', 'cancelled') else 1
            except Exception as exc:
                print(safe_json_dumps({'success': False, 'error': error_response(exc)}), file=sys.stderr)
                return 1
        if not ensure_dependencies(gui=False, preapproved=False, server=args.mode == 'headless-server'):
            return 1
        callback = None
        if args.updated:
            from YouSnipeDB import ensure_database
            ensure_database()
            callback = _updated_ready_callback(args)
        try:
            asyncio.run(run_headless(server=args.mode == 'headless-server', on_ready=callback))
        except KeyboardInterrupt:
            return 0
        return 0
    if remainder:
        try:
            command, data = parse_command_tokens(remainder)
            if command not in COMMANDS:
                parser.error('Unknown command')
            if command in ('download', 'download playlist', 'get metadata', 'confirm playlist download'):
                if not ensure_dependencies(gui=False, preapproved=False):
                    return 1
            result = asyncio.run(run_one_shot(command, data))
            print(safe_json_dumps(result), flush=True)
            return 0 if result.get('finalStatus') not in ('failed','partial','cancelled') else 1
        except Exception as exc:
            print(safe_json_dumps({'success': False, 'error': error_response(exc)}), file=sys.stderr)
            return 1
    if args.updated:
        from YouSnipeDesktop import ensure_linux_desktop_integration
        ensure_linux_desktop_integration()
        prepare_windows_gui()
        if not ensure_dependencies(gui=True):
            return 1
        from YouSnipeDB import ensure_database
        ensure_database()
        from YouSnipeGUI import main as gui_main
        gui_main(on_ready=_updated_ready_callback(args))
        return 0
    parser.error('No command supplied. Use YouSnipe.py without arguments to open the GUI.')
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
