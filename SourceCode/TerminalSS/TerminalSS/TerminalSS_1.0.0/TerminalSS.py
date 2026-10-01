from __future__ import annotations

import argparse
import copy
import importlib
import os
import re
import select
import shutil
import subprocess
import sys
import time
from pathlib import Path

from TerminalSSAssetManager import TerminalSSAssetManager
from TerminalSSSettings import TerminalSSSettings
from TerminalSSRuntime import prepare_runtime
from TerminalSSUpdateManager import complete_post_update, start_external_update
from TerminalSSUI import COLOUR_KEYS, TerminalSSUI, cycle_colour


APP_VERSION = "1.0.0"
IS_WINDOWS = os.name == "nt"
IS_LINUX = sys.platform.startswith("linux")
IS_MACOS = sys.platform == "darwin"
FULLSCREEN_METHOD = None
CLEAR_SCREEN = "\033[2J"
CURSOR_HOME = "\033[H"
HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"
ENTER_ALT_SCREEN = "\033[?1049h"
EXIT_ALT_SCREEN = "\033[?1049l"
MAXIMIZE_WINDOW = "\033[9;1t"
RESTORE_WINDOW = "\033[9;0t"
FULLSCREEN_WINDOW = "\033[10;1t"
EXIT_FULLSCREEN_WINDOW = "\033[10;0t"
RESET = "\033[0m"
FRAME_TIME = 0.040


def discover_protocol_classes() -> dict[str, type]:
    runtime = Path(__file__).resolve().parent
    discovered = {}
    for path in sorted(runtime.glob("TerminalSS*Protocol.py")):
        if path.name == Path(__file__).name:
            continue
        try:
            module = importlib.import_module(path.stem)
        except Exception:
            continue
        protocol_class = getattr(module, "PROTOCOL_CLASS", None)
        protocol_id = getattr(protocol_class, "PROTOCOL_ID", None) if protocol_class is not None else None
        key = getattr(protocol_class, "KEY", None) if protocol_class is not None else None
        contract = getattr(protocol_class, "settings_contract", None) if protocol_class is not None else None
        if isinstance(protocol_id, str) and protocol_id and isinstance(key, str) and key and callable(contract):
            discovered[protocol_id] = protocol_class
    return dict(sorted(discovered.items(), key=lambda item: str(getattr(item[1], "KEY", "99"))))


PROTOCOL_CLASSES = discover_protocol_classes()
PROTOCOL_KEYS = {protocol_class.KEY: name for name, protocol_class in PROTOCOL_CLASSES.items()}
PROTOCOL_CONTRACTS = {name: protocol_class.settings_contract() for name, protocol_class in PROTOCOL_CLASSES.items()}


def enable_ansi() -> None:
    if not IS_WINDOWS:
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        pass


def tap_f11_windows() -> bool:
    if not IS_WINDOWS:
        return False
    try:
        import ctypes
        user32 = ctypes.windll.user32
        user32.keybd_event(0x7A, 0, 0, 0)
        time.sleep(0.03)
        user32.keybd_event(0x7A, 0, 0x0002, 0)
        return True
    except Exception:
        return False


def run_window_command(command: list[str], timeout: float = 2.0) -> bool:
    try:
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
        return result.returncode == 0
    except Exception:
        return False


def terminal_program() -> str:
    values = [
        os.environ.get("TERM_PROGRAM", ""),
        os.environ.get("COLORTERM", ""),
        os.environ.get("TERM", ""),
    ]
    if os.environ.get("GNOME_TERMINAL_SERVICE") or os.environ.get("GNOME_TERMINAL_SCREEN"):
        return "gnome-terminal"
    if os.environ.get("KONSOLE_VERSION"):
        return "konsole"
    if os.environ.get("KITTY_WINDOW_ID") or "kitty" in os.environ.get("TERM", "").casefold():
        return "kitty"
    joined = " ".join(values).casefold()
    for name in ("gnome-terminal", "konsole", "xfce4-terminal", "kitty", "alacritty", "wezterm", "tilix"):
        if name in joined:
            return name
    if IS_MACOS:
        if "iterm" in joined:
            return "iterm2"
        if "apple_terminal" in joined:
            return "terminal.app"
    return ""


def launch_fullscreen_terminal(executable: str, arguments: list[str], runtime: Path, env: dict[str, str]) -> bool:
    try:
        subprocess.Popen(
            [executable, *arguments],
            cwd=str(runtime),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return True
    except Exception:
        return False


def relaunch_linux_fullscreen() -> bool:
    if not IS_LINUX or os.environ.get("TERMINALSS_FULLSCREEN_CHILD") == "1":
        return False
    runtime = Path(__file__).resolve().parent
    script = str(Path(__file__).resolve())
    command = [sys.executable, script, *sys.argv[1:]]
    env = os.environ.copy()
    env["TERMINALSS_FULLSCREEN_CHILD"] = "1"
    program = terminal_program()

    launchers: list[tuple[str, list[str]]] = []
    if program == "gnome-terminal":
        launchers.append(("gnome-terminal", ["--full-screen", f"--working-directory={runtime}", "--", *command]))
    elif program == "konsole":
        launchers.append(("konsole", ["--fullscreen", "--workdir", str(runtime), "-e", *command]))
    elif program == "kitty":
        launchers.append(("kitty", ["--start-as=fullscreen", "--directory", str(runtime), *command]))

    for executable, arguments in launchers:
        if shutil.which(executable) and launch_fullscreen_terminal(executable, arguments, runtime, env):
            return True
    return False


def toggle_macos_fullscreen() -> bool:
    if not IS_MACOS or not shutil.which("osascript"):
        return False
    program = terminal_program()
    if program == "iterm2":
        script = 'tell application "System Events" to key code 36 using {command down}'
    elif program == "wezterm":
        script = 'tell application "System Events" to key code 36 using {option down}'
    else:
        script = 'tell application "System Events" to keystroke "f" using {control down, command down}'
    if run_window_command(["osascript", "-e", script], timeout=4.0):
        time.sleep(0.35)
        return True
    return False


def enter_fullscreen() -> bool:
    global FULLSCREEN_METHOD
    FULLSCREEN_METHOD = None
    if IS_WINDOWS:
        if tap_f11_windows():
            FULLSCREEN_METHOD = "windows-f11"
            return True
        return False
    if IS_MACOS:
        if toggle_macos_fullscreen():
            FULLSCREEN_METHOD = "macos-shortcut"
            return True
        return False
    if IS_LINUX:
        if os.environ.get("TERMINALSS_FULLSCREEN_CHILD") == "1":
            FULLSCREEN_METHOD = "launcher"
            return True
        if shutil.which("wmctrl") and run_window_command(["wmctrl", "-r", ":ACTIVE:", "-b", "add,fullscreen"]):
            FULLSCREEN_METHOD = "wmctrl"
            time.sleep(0.08)
            return True
        if shutil.which("xdotool") and run_window_command(["xdotool", "key", "F11"]):
            FULLSCREEN_METHOD = "xdotool"
            time.sleep(0.08)
            return True
    try:
        sys.stdout.write(MAXIMIZE_WINDOW + FULLSCREEN_WINDOW)
        sys.stdout.flush()
        FULLSCREEN_METHOD = "ansi"
        return True
    except Exception:
        return False


def exit_fullscreen() -> None:
    global FULLSCREEN_METHOD
    method = FULLSCREEN_METHOD
    FULLSCREEN_METHOD = None
    if IS_WINDOWS:
        if method == "windows-f11":
            tap_f11_windows()
        return
    if IS_MACOS:
        if method == "macos-shortcut":
            toggle_macos_fullscreen()
        return
    if method == "launcher":
        return
    if method == "wmctrl":
        if run_window_command(["wmctrl", "-r", ":ACTIVE:", "-b", "remove,fullscreen"]):
            return
    elif method == "xdotool":
        if run_window_command(["xdotool", "key", "F11"]):
            return
    try:
        sys.stdout.write(EXIT_FULLSCREEN_WINDOW + RESTORE_WINDOW)
        sys.stdout.flush()
    except Exception:
        pass



class ModifierReader:
    def __init__(self):
        self.alt_down = False
        self.shift_down = False
        self.alt_used = False
        self.shift_used = False

    def observe_key(self, key) -> None:
        if key is None:
            return
        if self.alt_down:
            self.alt_used = True
        if self.shift_down:
            self.shift_used = True

    def poll(self) -> tuple[bool, bool]:
        if not IS_WINDOWS:
            return False, False
        try:
            import ctypes
            user32 = ctypes.windll.user32
            alt_now = bool(user32.GetAsyncKeyState(0x12) & 0x8000)
            shift_now = bool(user32.GetAsyncKeyState(0x10) & 0x8000)
            if alt_now and not self.alt_down:
                self.alt_used = False
            if shift_now and not self.shift_down:
                self.shift_used = False
            alt_tapped = self.alt_down and not alt_now and not self.alt_used
            shift_tapped = self.shift_down and not shift_now and not self.shift_used
            self.alt_down = alt_now
            self.shift_down = shift_now
            return alt_tapped, shift_tapped
        except Exception:
            return False, False


class KeyboardReader:
    UNIX_ESCAPE_TIMEOUT = 0.08

    def __init__(self):
        self.fd = None
        self.old_settings = None
        self.pending = ""

    def __enter__(self):
        if not IS_WINDOWS and sys.stdin.isatty():
            try:
                import termios
                import tty
                self.fd = sys.stdin.fileno()
                self.old_settings = termios.tcgetattr(self.fd)
                tty.setcbreak(self.fd)
            except Exception:
                self.fd = None
                self.old_settings = None
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.suspend()

    def suspend(self) -> None:
        if not IS_WINDOWS and self.fd is not None and self.old_settings is not None:
            try:
                import termios
                termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old_settings)
            except Exception:
                pass
        self.pending = ""

    def resume(self) -> None:
        if not IS_WINDOWS and self.fd is not None and self.old_settings is not None:
            try:
                import tty
                tty.setcbreak(self.fd)
            except Exception:
                pass
        self.pending = ""

    @staticmethod
    def _decode_escape(sequence: str):
        direct = {
            "\x1b[A": "UP",
            "\x1b[B": "DOWN",
            "\x1b[C": "RIGHT",
            "\x1b[D": "LEFT",
            "\x1b[H": "HOME",
            "\x1b[F": "END",
            "\x1bOA": "UP",
            "\x1bOB": "DOWN",
            "\x1bOC": "RIGHT",
            "\x1bOD": "LEFT",
            "\x1bOH": "HOME",
            "\x1bOF": "END",
            "\x1b[1~": "HOME",
            "\x1b[4~": "END",
            "\x1b[5~": "PAGEUP",
            "\x1b[6~": "PAGEDOWN",
            "\x1b[7~": "HOME",
            "\x1b[8~": "END",
        }
        if sequence in direct:
            return direct[sequence]
        match = re.fullmatch(r"\x1b\[(?:1;[2-8]|[2-8])?([ABCDHF])", sequence)
        if match:
            return {
                "A": "UP",
                "B": "DOWN",
                "C": "RIGHT",
                "D": "LEFT",
                "H": "HOME",
                "F": "END",
            }.get(match.group(1))
        return None

    def _read_unix_sequence(self):
        if self.fd is None:
            return None
        if not self.pending:
            ready, _, _ = select.select([self.fd], [], [], 0)
            if not ready:
                return None
            chunk = os.read(self.fd, 64)
            if not chunk:
                return None
            self.pending += chunk.decode("utf-8", errors="ignore")

        first = self.pending[0]
        if first != "\x1b":
            self.pending = self.pending[1:]
            return first

        deadline = time.monotonic() + self.UNIX_ESCAPE_TIMEOUT
        while time.monotonic() < deadline:
            decoded = self._decode_escape(self.pending)
            if decoded is not None:
                self.pending = ""
                return decoded
            ready, _, _ = select.select([self.fd], [], [], 0.005)
            if not ready:
                continue
            chunk = os.read(self.fd, 64)
            if not chunk:
                break
            self.pending += chunk.decode("utf-8", errors="ignore")

        decoded = self._decode_escape(self.pending)
        if decoded is not None:
            self.pending = ""
            return decoded
        if self.pending == "\x1b":
            self.pending = ""
            return "ESC"
        if len(self.pending) >= 2 and self.pending[0] == "\x1b" and self.pending[1] not in "[O":
            alt_char = self.pending[1]
            self.pending = self.pending[2:]
            return f"ALT_{alt_char}"
        self.pending = ""
        return None

    def read_key(self):
        if IS_WINDOWS:
            try:
                import msvcrt
                if not msvcrt.kbhit():
                    return None
                key = msvcrt.getwch()
                if key in ("\x00", "\xe0"):
                    code = msvcrt.getwch()
                    return {"H": "UP", "P": "DOWN", "K": "LEFT", "M": "RIGHT", "G": "HOME", "O": "END", "I": "PAGEUP", "Q": "PAGEDOWN"}.get(code)
                if key == "\x1b":
                    return "ESC"
                if key == "\t":
                    return "TAB"
                if key == "\b":
                    return "BACKSPACE"
                if key == "\x03":
                    return "CTRL_C"
                if key == "\x12":
                    return "CTRL_R"
                return key
            except Exception:
                return None
        try:
            key = self._read_unix_sequence()
            if key == "\t":
                return "TAB"
            if key in {"\x7f", "\x08"}:
                return "BACKSPACE"
            if key == "\x03":
                return "CTRL_C"
            if key == "\x12":
                return "CTRL_R"
            return key
        except Exception:
            return None


def terminal_size() -> tuple[int, int]:
    size = shutil.get_terminal_size((120, 35))
    return max(20, size.columns), max(10, size.lines)


def set_fixed_colour(runtime_settings: dict, colour: str) -> None:
    runtime_settings["Color"] = colour
    runtime_settings["RGB"] = False
    runtime_settings["CustomColorShift"] = False


def toggle_rgb(runtime_settings: dict) -> None:
    enabled = not bool(runtime_settings.get("RGB", False))
    runtime_settings["RGB"] = enabled
    if enabled:
        runtime_settings["CustomColorShift"] = False


def toggle_custom_shift(runtime_settings: dict) -> None:
    enabled = not bool(runtime_settings.get("CustomColorShift", False))
    runtime_settings["CustomColorShift"] = enabled
    if enabled:
        runtime_settings["RGB"] = False


def write_terminal(text: str) -> None:
    try:
        sys.stdout.write(text)
        sys.stdout.flush()
    except (BrokenPipeError, OSError):
        pass


def ensure_protocol_assets(asset_manager: TerminalSSAssetManager, protocol_name: str, protocol_class: type):
    handler = getattr(protocol_class, "ensure_assets", None)
    if callable(handler):
        return handler(asset_manager)
    return asset_manager.ensure_protocol(protocol_name)


def repair_protocol_assets(asset_manager: TerminalSSAssetManager, protocol_name: str, protocol_class: type):
    handler = getattr(protocol_class, "repair_assets", None)
    if callable(handler):
        return handler(asset_manager)
    return asset_manager.repair_protocol(protocol_name)


def rebuild_protocol_assets(asset_manager: TerminalSSAssetManager, protocol_name: str, protocol_class: type):
    handler = getattr(protocol_class, "rebuild_assets", None)
    if callable(handler):
        return handler(asset_manager)
    return asset_manager.rebuild_protocol(protocol_name)


def is_external_protocol(protocol) -> bool:
    return bool(getattr(protocol, "EXTERNAL_STATIC", False)) and callable(getattr(protocol, "activate_external", None))


def activate_external_protocol(protocol, runtime_settings: dict) -> None:
    write_terminal(SHOW_CURSOR + CLEAR_SCREEN + CURSOR_HOME)
    try:
        return_code = protocol.activate_external(runtime_settings)
        if return_code not in (0, None):
            print()
            print(f"PythoFetch exited with code {return_code}.")
    except Exception as exc:
        print()
        print(f"PythoFetch could not start: {exc}")
    finally:
        write_terminal(HIDE_CURSOR)


def run_visualizer(settings_manager: TerminalSSSettings, asset_manager: TerminalSSAssetManager, start_protocol: str) -> tuple[str, str]:
    ui = TerminalSSUI()
    protocols = {name: protocol_class(asset_manager, ui) for name, protocol_class in PROTOCOL_CLASSES.items()}
    current_name = start_protocol if start_protocol in protocols else "Matrix"
    runtime_settings = settings_manager.protocol(current_name)
    width, height = terminal_size()
    now = time.monotonic()
    protocols[current_name].reset(runtime_settings, width, height, now)
    paused = False
    help_visible = False
    fullscreen = bool(settings_manager.general().get("Fullscreen", True))
    enable_ansi()
    write_terminal(ENTER_ALT_SCREEN + HIDE_CURSOR + CLEAR_SCREEN + CURSOR_HOME)
    if fullscreen:
        enter_fullscreen()
    action = "exit"
    last_canvas = None
    external_active = is_external_protocol(protocols[current_name])
    if external_active:
        activate_external_protocol(protocols[current_name], runtime_settings)
    try:
        with KeyboardReader() as keyboard:
            while True:
                frame_started = time.monotonic()
                key = keyboard.read_key()
                if key in {"ESC", "CTRL_C"}:
                    action = "exit"
                    break
                if key == "TAB":
                    keyboard.suspend()
                    write_terminal(SHOW_CURSOR + CLEAR_SCREEN + CURSOR_HOME)
                    try:
                        settings_manager.protocol_ui(current_name)
                        settings_manager.load()
                        runtime_settings = settings_manager.protocol(current_name)
                    finally:
                        keyboard.resume()
                    width, height = terminal_size()
                    protocols[current_name].reset(runtime_settings, width, height, frame_started)
                    paused = False
                    help_visible = False
                    last_canvas = None
                    external_active = is_external_protocol(protocols[current_name])
                    write_terminal(HIDE_CURSOR + CLEAR_SCREEN + CURSOR_HOME)
                    if external_active:
                        activate_external_protocol(protocols[current_name], runtime_settings)
                    continue
                if key in PROTOCOL_KEYS:
                    requested = PROTOCOL_KEYS[key]
                    if requested == current_name and external_active:
                        activate_external_protocol(protocols[current_name], runtime_settings)
                        time.sleep(FRAME_TIME)
                        continue
                    if requested != current_name:
                        current_name = requested
                        runtime_settings = settings_manager.protocol(current_name)
                        width, height = terminal_size()
                        protocols[current_name].reset(runtime_settings, width, height, frame_started)
                        paused = False
                        help_visible = False
                        last_canvas = None
                        external_active = is_external_protocol(protocols[current_name])
                        write_terminal(CLEAR_SCREEN + CURSOR_HOME)
                        if external_active:
                            activate_external_protocol(protocols[current_name], runtime_settings)
                            time.sleep(FRAME_TIME)
                            continue
                if external_active:
                    time.sleep(FRAME_TIME)
                    continue
                protocol_handled = False
                if key is not None and not help_visible:
                    handler = getattr(protocols[current_name], "handle_runtime_key", None)
                    if callable(handler):
                        protocol_handled = bool(handler(key, runtime_settings))
                if key == "?":
                    help_visible = not help_visible
                elif not protocol_handled:
                    if key == " ":
                        paused = not paused
                    if key == "LEFT":
                        set_fixed_colour(runtime_settings, cycle_colour(str(runtime_settings.get("Color", "Matrix Green")), -1))
                    elif key == "RIGHT":
                        set_fixed_colour(runtime_settings, cycle_colour(str(runtime_settings.get("Color", "Matrix Green")), 1))
                    elif isinstance(key, str) and len(key) == 1 and key.casefold() in COLOUR_KEYS:
                        set_fixed_colour(runtime_settings, COLOUR_KEYS[key.casefold()])
                    elif key == "[":
                        toggle_rgb(runtime_settings)
                    elif key == "]":
                        toggle_custom_shift(runtime_settings)
                width, height = terminal_size()
                if help_visible:
                    help_provider = getattr(protocols[current_name], "help_lines", None)
                    protocol_help = help_provider() if callable(help_provider) else None
                    canvas = ui.help_canvas(width, height, current_name, PROTOCOL_KEYS, protocol_help)
                elif paused:
                    if last_canvas is None or last_canvas.width != width or last_canvas.height != height:
                        last_canvas = protocols[current_name].render(width, height, runtime_settings, frame_started)
                    canvas = copy.deepcopy(last_canvas)
                    canvas.overlay_center_box("PAUSED", [protocols[current_name].primary_speed_label(runtime_settings), "SPACE TO RESUME"])
                else:
                    canvas = protocols[current_name].render(width, height, runtime_settings, frame_started)
                    last_canvas = canvas
                write_terminal(ui.render(canvas, runtime_settings, frame_started))
                remaining = FRAME_TIME - (time.monotonic() - frame_started)
                if remaining > 0:
                    time.sleep(remaining)
    finally:
        if fullscreen:
            exit_fullscreen()
        write_terminal(RESET + SHOW_CURSOR + EXIT_ALT_SCREEN)
    return action, current_name


def parse_arguments(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(prog="TerminalSS")
    parser.add_argument("command", nargs="?", default="")
    parser.add_argument("--protocol", default=None)
    parser.add_argument("--settings", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--repair-assets", default=None)
    parser.add_argument("--rebuild-assets", default=None)
    parser.add_argument("--update", action="store_true")
    parser.add_argument("--target-version", default=None)
    parser.add_argument("--updated", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--updater-pid", type=int, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--previous-version", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--approot-relocated-from", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--approot-relocator-pid", type=int, default=None, help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    raw_arguments = list(sys.argv[1:] if argv is None else argv)
    args = parse_arguments(raw_arguments)
    try:
        runtime_context = prepare_runtime(
            __file__,
            raw_arguments,
            args.approot_relocated_from,
            args.approot_relocator_pid,
        )
    except Exception as exc:
        print(f"TerminalSS could not establish its application root: {exc}")
        return 1
    if runtime_context is None:
        return 0
    if args.updated:
        if args.updater_pid is None or not args.previous_version:
            print("TerminalSS post-update launch is missing updater metadata.")
            return 2
        try:
            complete_post_update(APP_VERSION, args.updater_pid, args.previous_version)
        except Exception as exc:
            print(f"TerminalSS could not complete post-update cleanup: {exc}")
            return 1
    if args.update:
        try:
            installed = start_external_update(APP_VERSION, args.target_version)
        except Exception as exc:
            print(f"TerminalSS update could not start: {exc}")
            return 1
        if installed == APP_VERSION:
            print(f"TerminalSS {APP_VERSION} is already up to date.")
        return 0
    asset_manager = TerminalSSAssetManager(runtime_context.app_root, runtime_context.runtime_directory)
    if not PROTOCOL_CLASSES:
        print("TerminalSS found no protocol modules.")
        return 1
    settings_manager = TerminalSSSettings(asset_manager.project_root, PROTOCOL_CONTRACTS)
    general = settings_manager.general()
    interactive_start = not args.status and not args.repair_assets and not args.rebuild_assets and not args.settings and not args.update and args.command.casefold() != "settings"
    if interactive_start and general.get("Fullscreen", True) and relaunch_linux_fullscreen():
        return 0
    try:
        asset_manager.ensure_shared_assets()
        for protocol_name, protocol_class in PROTOCOL_CLASSES.items():
            try:
                ensure_protocol_assets(asset_manager, protocol_name, protocol_class)
            except Exception:
                if not bool(getattr(protocol_class, "ALLOW_MISSING_ASSETS", False)):
                    raise
    except Exception as exc:
        print(f"TerminalSS could not provision its assets: {exc}")
        return 1
    if args.status:
        status = asset_manager.status()
        print(f"TerminalSS {APP_VERSION}")
        for key, value in status.items():
            print(f"{key}: {value}")
        print(f"Settings: {settings_manager.settings_path}")
        return 0
    if args.repair_assets:
        requested = next((name for name in PROTOCOL_CLASSES if name.casefold() == str(args.repair_assets).casefold()), None)
        if str(args.repair_assets).casefold() == "all":
            targets = tuple(PROTOCOL_CLASSES)
        elif requested:
            targets = (requested,)
        else:
            print("Unknown protocol. Available protocols: " + ", ".join(PROTOCOL_CLASSES))
            return 2
        for protocol in targets:
            version = repair_protocol_assets(asset_manager, protocol, PROTOCOL_CLASSES[protocol])
            print(f"Repaired {protocol} assets from {version}.")
        return 0
    if args.rebuild_assets:
        requested = next((name for name in PROTOCOL_CLASSES if name.casefold() == str(args.rebuild_assets).casefold()), None)
        if str(args.rebuild_assets).casefold() == "all":
            targets = tuple(PROTOCOL_CLASSES)
        elif requested:
            targets = (requested,)
        else:
            print("Unknown protocol. Available protocols: " + ", ".join(PROTOCOL_CLASSES))
            return 2
        for protocol in targets:
            version = rebuild_protocol_assets(asset_manager, protocol, PROTOCOL_CLASSES[protocol])
            print(f"Rebuilt {protocol} assets from {version}.")
        return 0
    if args.settings or args.command.casefold() == "settings":
        settings_manager.interactive_ui()
        return 0
    requested_protocol = next((name for name in PROTOCOL_CLASSES if args.protocol and name.casefold() == str(args.protocol).casefold()), None)
    if args.protocol and requested_protocol is None:
        print("Unknown protocol. Available protocols: " + ", ".join(PROTOCOL_CLASSES))
        return 2
    current_protocol = requested_protocol or "Matrix"
    run_visualizer(settings_manager, asset_manager, current_protocol)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
