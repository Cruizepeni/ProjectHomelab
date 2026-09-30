import argparse
import hashlib
import os
import platform
import re
import shutil
import subprocess
import sys
import urllib.request
import venv
import zipfile
from pathlib import Path

BUILDER_VERSION = "1.0.0"
PYINSTALLER_VERSION = "6.22.3"
FOLDER_PATTERN = re.compile(r"^TerminalSSUpdater_(\d+\.\d+\.\d+)$", re.IGNORECASE)
VERSION_PATTERN = re.compile(r'^\s*TERMINALSS_UPDATER_VERSION\s*=\s*["\'](\d+\.\d+\.\d+)["\']', re.MULTILINE)
ICON_URL = "https://raw.githubusercontent.com/Cruizepeni/ProjectHomelab/main/Resources/Icons/Shared/Updater/Icon_Updater.ico"


def show(label, value=""):
    print(f"[{label}] {value}" if value else f"[{label}]")


def run(command, cwd=None, env=None, capture=False):
    command = [str(part) for part in command]
    show("RUN", " ".join(command))
    result = subprocess.run(command, cwd=str(cwd) if cwd else None, env=env, text=True, capture_output=capture)
    if result.returncode != 0:
        if capture and result.stdout:
            print(result.stdout)
        if capture and result.stderr:
            print(result.stderr, file=sys.stderr)
        raise RuntimeError(f"Command failed with exit code {result.returncode}: " + " ".join(command))
    return result


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def detect_target_version(root):
    match = FOLDER_PATTERN.fullmatch(root.name)
    if not match:
        raise RuntimeError("Copy this build tool into a TerminalSSUpdater_X.Y.Z source folder before running it.")
    return match.group(1)


def find_source(root, version):
    path = root / f"TerminalSSUpdater_{version}.py"
    if not path.is_file():
        raise RuntimeError(f"{path.name} was not found beside this build tool.")
    text = path.read_text(encoding="utf-8")
    match = VERSION_PATTERN.search(text)
    if not match:
        raise RuntimeError(f"{path.name} does not declare TERMINALSS_UPDATER_VERSION.")
    source_version = match.group(1)
    if source_version != version:
        text = text[:match.start(1)] + version + text[match.end(1):]
        path.write_text(text, encoding="utf-8")
        show("VERSION", f"Normalized updater source version {source_version} -> {version}")
    return path


def detect_architecture():
    machine = str(platform.machine() or "").strip().lower()
    if machine in ("amd64", "x86_64", "x64"):
        return "x86_64"
    raise RuntimeError(f"This build tool targets Windows x86_64 only. Detected architecture: {machine or 'Unknown'}")


def ensure_build_environment(cache_dir):
    venv_dir = cache_dir / "venv"
    python_path = venv_dir / "Scripts" / "python.exe"
    rebuild = not python_path.is_file()
    if not rebuild:
        probe = subprocess.run([python_path, "-m", "pip", "--version"], text=True, capture_output=True)
        rebuild = probe.returncode != 0
    if rebuild:
        if venv_dir.exists():
            shutil.rmtree(venv_dir)
        show("SETUP", "Creating isolated build environment")
        venv.create(str(venv_dir), with_pip=True, clear=True)
    run([python_path, "-m", "pip", "install", "--disable-pip-version-check", f"pyinstaller=={PYINSTALLER_VERSION}"])
    return python_path


def find_icon(root, work_dir):
    for candidate_root in (root, *root.parents):
        candidate = candidate_root / "Resources" / "Icons" / "Shared" / "Updater" / "Icon_Updater.ico"
        if candidate.is_file():
            return candidate
    icon = work_dir / "Icon_Updater.ico"
    request = urllib.request.Request(ICON_URL, headers={"User-Agent": f"TerminalSSUpdaterBuild/{BUILDER_VERSION}"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response, icon.open("wb") as handle:
            shutil.copyfileobj(response, handle)
    except Exception as exc:
        raise RuntimeError("Could not find or download the shared ProjectHomelab updater icon.") from exc
    if not icon.is_file() or icon.stat().st_size == 0:
        raise RuntimeError("Updater icon download failed.")
    return icon


def test_version_command(command, cwd, version):
    result = run(command, cwd=cwd, capture=True)
    output = ((result.stdout or "") + (result.stderr or "")).strip()
    if version not in output:
        raise RuntimeError("Updater --version test failed.")


def build_binary(python_path, source, icon, work_dir):
    dist_dir = work_dir / "dist"
    pyinstaller_work = work_dir / "pyinstaller-work"
    spec_dir = work_dir / "spec"
    for path in (dist_dir, pyinstaller_work, spec_dir):
        path.mkdir(parents=True, exist_ok=True)
    run([
        python_path, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--console",
        "--name", "TerminalSSUpdater", "--icon", icon, "--distpath", dist_dir,
        "--workpath", pyinstaller_work, "--specpath", spec_dir, source,
    ], cwd=source.parent)
    binary = dist_dir / "TerminalSSUpdater.exe"
    if not binary.is_file():
        raise RuntimeError("PyInstaller did not create TerminalSSUpdater.exe.")
    return binary


def create_zip(binary, destination):
    if destination.exists():
        destination.unlink()
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.write(binary, arcname="TerminalSSUpdater.exe")
    with zipfile.ZipFile(destination, "r") as archive:
        names = [info.filename for info in archive.infolist() if not info.is_dir()]
    if names != ["TerminalSSUpdater.exe"]:
        raise RuntimeError("Updater release ZIP validation failed.")


def parse_args():
    parser = argparse.ArgumentParser(prog="Build_TerminalSSUpdater_Windows_x86_64_1.0.0")
    parser.add_argument("--clean-cache", action="store_true")
    parser.add_argument("--keep-work", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    if platform.system() != "Windows":
        raise RuntimeError("This build tool must be run on Windows.")
    root = Path(__file__).resolve().parent
    version = detect_target_version(root)
    source = find_source(root, version)
    architecture = detect_architecture()
    cache_dir = root / ".terminalss-updater-windows-build"
    work_dir = cache_dir / "work"
    if args.clean_cache and cache_dir.exists():
        shutil.rmtree(cache_dir)
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    icon = find_icon(root, work_dir)
    zip_output = root / f"TerminalSSUpdater_{version}_Windows_{architecture}.zip"
    print()
    print(f"TerminalSSUpdater Windows x86_64 Build Tool {BUILDER_VERSION}")
    print("=" * 58)
    show("SOURCE", source.name)
    show("VERSION", version)
    show("ICON", icon.name)
    show("TARGET", f"Windows_{architecture}")
    print()
    python_path = ensure_build_environment(cache_dir)
    show("TEST", "Source")
    test_version_command([python_path, source, "--version"], source.parent, version)
    show("BUILD", "PyInstaller EXE")
    binary = build_binary(python_path, source, icon, work_dir)
    show("TEST", "PyInstaller EXE")
    test_version_command([binary, "--version"], binary.parent, version)
    show("BUILD", zip_output.name)
    create_zip(binary, zip_output)
    zip_hash = sha256_file(zip_output)
    binary_hash = sha256_file(binary)
    binary_size = binary.stat().st_size
    if not args.keep_work and cache_dir.exists():
        shutil.rmtree(cache_dir)
    print()
    print("=" * 58)
    print("READY TO REVIEW")
    print("=" * 58)
    print(f"ZIP: {zip_output.name}")
    print(f"ZIP SHA-256: {zip_hash}")
    print(f"ZIP bytes: {zip_output.stat().st_size}")
    print("Contained EXE: TerminalSSUpdater.exe")
    print(f"EXE SHA-256: {binary_hash}")
    print(f"EXE bytes: {binary_size}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Build cancelled.", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print("BUILD FAILED: " + str(exc), file=sys.stderr)
        raise SystemExit(1)
