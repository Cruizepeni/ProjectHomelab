import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import urllib.request
import venv
import zipfile
from pathlib import Path

BUILDER_VERSION = "1.0.0"
PYINSTALLER_VERSION = "6.22.3"
ICON_URL = (
    "https://raw.githubusercontent.com/"
    "Cruizepeni/ProjectHomelab/main/"
    "Resources/Icons/Features/PythoFetch/"
    "Icon_PythoFetch.png"
)
PILLOW_VERSION = "11.3.0"
APPIMAGETOOL_VERSION = "1.9.1"
APPIMAGE_RUNTIME_BUILD = "2026-06-23-75849dc"
TERMINAL_COLUMNS = 120
TERMINAL_ROWS = 34
APPIMAGE_RUNTIME_ASSETS = {
    "x86_64": {
        "url": "https://github.com/AppImage/type2-runtime/releases/download/continuous/runtime-x86_64",
        "sha256": "1cc49bcf1e2ccd593c379adb17c9f85a36d619088296504de95b1d06215aebbf",
    },
}
SOURCE_PATTERN = re.compile(r"^PythoFetch(?:_[^/]+)?\.py$", re.IGNORECASE)
DATABASE_PATTERN = re.compile(r"^PythoFetchArt_(\d+\.\d+\.\d+)\.db$", re.IGNORECASE)
VERSION_PATTERN = re.compile(r'^\s*PYTHOFETCH_VERSION\s*=\s*["\'](\d+(?:\.\d+)*)["\']', re.MULTILINE)


def version_key(value):
    parts = str(value).strip().split(".")
    if not parts or any(not part.isdigit() for part in parts):
        raise RuntimeError(f"Invalid numeric version: {value}")
    return tuple(int(part) for part in parts)


def show(label, value=""):
    print(f"[{label}] {value}" if value else f"[{label}]")


def run(command, cwd=None, env=None, capture=False):
    command = [str(part) for part in command]
    show("RUN", " ".join(command))
    result = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        env=env,
        text=True,
        capture_output=capture,
    )
    if result.returncode != 0:
        if capture:
            if result.stdout:
                print(result.stdout)
            if result.stderr:
                print(result.stderr, file=sys.stderr)
        raise RuntimeError(f"Command failed with exit code {result.returncode}: {' '.join(command)}")
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


def record(path):
    path = Path(path)
    return {
        "file": path.name,
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def find_source(root):
    candidates = []
    build_tool_name = Path(__file__).name.lower()

    for path in root.iterdir():
        if not path.is_file():
            continue
        if path.name.lower() == build_tool_name:
            continue
        if not SOURCE_PATTERN.match(path.name):
            continue

        source_text = path.read_text(encoding="utf-8")
        match = VERSION_PATTERN.search(source_text)

        if not match:
            continue

        source_version = match.group(1)

        candidates.append(
            (
                version_key(source_version),
                source_version,
                path,
            )
        )

    if not candidates:
        raise RuntimeError(
            "No PythoFetch Python source containing PYTHOFETCH_VERSION "
            "was found beside this build tool."
        )

    highest_key = max(
        item[0]
        for item in candidates
    )

    highest = [
        item
        for item in candidates
        if item[0] == highest_key
    ]

    version = highest[0][1]
    canonical_name = f"PythoFetch_{version}.py"

    canonical = [
        item
        for item in highest
        if item[2].name.lower() == canonical_name.lower()
    ]

    if len(canonical) == 1:
        return canonical[0][2], version

    if len(highest) == 1:
        return highest[0][2], version

    names = ", ".join(
        sorted(
            item[2].name
            for item in highest
        )
    )

    raise RuntimeError(
        "Multiple PythoFetch source files declare the same highest version "
        f"{version}: {names}. Keep one source file or use the canonical "
        f"filename {canonical_name}."
    )


def find_database(root):
    candidates = []
    for path in root.iterdir():
        if not path.is_file():
            continue
        match = DATABASE_PATTERN.match(path.name)
        if match:
            candidates.append((version_key(match.group(1)), path))
    if not candidates:
        raise RuntimeError("No PythoFetchArt_<version>.db file was found beside this compiler.")
    candidates.sort(key=lambda item: item[0])
    return candidates[-1][1]


def validate_icon(icon):
    with icon.open("rb") as handle:
        signature = handle.read(8)

    if signature != b"\x89PNG\r\n\x1a\n":
        raise RuntimeError(
            "Icon_PythoFetch.png is not "
            "a valid PNG file."
        )


def find_icon(
    root,
    work_dir,
):
    local_icon = (
        root
        / "Icon_PythoFetch.png"
    )

    if local_icon.is_file():
        validate_icon(
            local_icon
        )

        return local_icon

    downloaded_icon = (
        work_dir
        / "Icon_PythoFetch.png"
    )

    download(
        ICON_URL,
        downloaded_icon,
    )

    validate_icon(
        downloaded_icon
    )

    return downloaded_icon


def prepare_linux_icon(python_path, icon, work_dir):
    icon_dir = work_dir / "icon"
    icon_dir.mkdir(parents=True, exist_ok=True)
    output = icon_dir / "pythofetch.png"
    script = "\n".join([
        "from PIL import Image",
        "import sys",
        "source = Image.open(sys.argv[1]).convert('RGBA')",
        "source.thumbnail((256, 256), Image.Resampling.LANCZOS)",
        "canvas = Image.new('RGBA', (256, 256), (0, 0, 0, 0))",
        "x = (256 - source.width) // 2",
        "y = (256 - source.height) // 2",
        "canvas.alpha_composite(source, (x, y))",
        "canvas.save(sys.argv[2], format='PNG', optimize=True)",
    ])
    run([python_path, "-c", script, icon, output])
    with output.open("rb") as handle:
        data = handle.read(24)
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise RuntimeError("Generated Linux icon is not a valid PNG file.")
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    if width != 256 or height != 256:
        raise RuntimeError("Generated Linux icon is not 256x256.")
    return output


def detect_architecture():
    machine = str(platform.machine() or "").strip().lower()
    if machine in ("x86_64", "amd64", "x64"):
        return "x86_64", "x86_64"
    raise RuntimeError(
        "This build tool targets Linux x86_64 only. "
        f"Detected architecture: {machine or 'Unknown'}"
    )


def ensure_build_environment(cache_dir):
    venv_dir = cache_dir / "venv"
    python_path = venv_dir / "bin" / "python"
    if not python_path.is_file():
        show("SETUP", "Creating isolated build environment")
        venv.create(str(venv_dir), with_pip=True, clear=False)
    run([
        python_path,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        f"pyinstaller=={PYINSTALLER_VERSION}",
        f"pillow=={PILLOW_VERSION}",
    ])
    return python_path


def download(url, destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".download")
    if temporary.exists():
        temporary.unlink()
    request = urllib.request.Request(
        url,
        headers={"User-Agent": f"PythoFetchLinuxBuildTool/{BUILDER_VERSION}"},
    )
    show("DOWNLOAD", url)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            with temporary.open("wb") as handle:
                shutil.copyfileobj(response, handle)
        if not temporary.is_file() or temporary.stat().st_size == 0:
            raise RuntimeError("Downloaded file is empty.")
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    return destination


def ensure_appimagetool(cache_dir, appimage_arch):
    filename = f"appimagetool-{appimage_arch}.AppImage"
    tool = cache_dir / "tools" / filename
    if not tool.is_file():
        url = (
            "https://github.com/AppImage/appimagetool/releases/download/"
            f"{APPIMAGETOOL_VERSION}/{filename}"
        )
        download(url, tool)
    tool.chmod(tool.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return tool


def ensure_appimage_runtime(cache_dir, appimage_arch):
    entry = APPIMAGE_RUNTIME_ASSETS.get(appimage_arch)
    if not entry:
        raise RuntimeError(f"No pinned AppImage runtime is configured for {appimage_arch}.")
    runtime = cache_dir / "tools" / f"runtime-{appimage_arch}"
    expected_hash = entry["sha256"].lower()
    if runtime.is_file() and sha256_file(runtime).lower() != expected_hash:
        runtime.unlink()
    if not runtime.is_file():
        download(entry["url"], runtime)
    actual_hash = sha256_file(runtime).lower()
    if actual_hash != expected_hash:
        if runtime.exists():
            runtime.unlink()
        raise RuntimeError(
            "Pinned AppImage runtime checksum mismatch. "
            "The upstream continuous asset changed; update this build tool before building."
        )
    return runtime


def verify_embedded_runtime(appimage, runtime):
    runtime_size = runtime.stat().st_size

    if appimage.stat().st_size <= runtime_size:
        raise RuntimeError(
            "Generated AppImage is too small to contain the runtime and filesystem."
        )

    with appimage.open("rb") as handle:
        elf_magic = handle.read(4)
        handle.seek(8)
        appimage_magic = handle.read(3)

    if elf_magic != b"\x7fELF":
        raise RuntimeError("Generated AppImage does not have a valid ELF runtime header.")

    if appimage_magic != b"AI\x02":
        raise RuntimeError("Generated file is not a type 2 AppImage.")

    result = run(
        [appimage, "--appimage-offset"],
        cwd=appimage.parent,
        capture=True,
    )

    offset_text = (result.stdout or "").strip()

    try:
        filesystem_offset = int(offset_text)
    except Exception as exc:
        raise RuntimeError(
            "Could not read the generated AppImage filesystem offset."
        ) from exc

    if filesystem_offset != runtime_size:
        raise RuntimeError(
            "Generated AppImage runtime size does not match the pinned runtime."
        )


def test_json_command(command, cwd, label, env=None):
    result = run(command, cwd=cwd, env=env, capture=True)
    try:
        payload = json.loads(result.stdout)
    except Exception as exc:
        raise RuntimeError(f"{label} returned invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{label} returned an invalid payload.")


def test_source(python_path, source, version):
    result = run([python_path, source, "--version"], cwd=source.parent, capture=True)
    if version not in (result.stdout or ""):
        raise RuntimeError("Source --version test failed.")
    test_json_command(
        [python_path, source, "--headless", "--info", "--format", "json"],
        source.parent,
        "Source headless test",
    )


def build_binary(python_path, source, database, work_dir, version):
    dist_dir = work_dir / "dist"
    pyinstaller_work = work_dir / "pyinstaller-work"
    spec_dir = work_dir / "spec"
    dist_dir.mkdir(parents=True, exist_ok=True)
    pyinstaller_work.mkdir(parents=True, exist_ok=True)
    spec_dir.mkdir(parents=True, exist_ok=True)
    name = f"PythoFetch_{version}"
    run([
        python_path,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name",
        name,
        "--distpath",
        dist_dir,
        "--workpath",
        pyinstaller_work,
        "--specpath",
        spec_dir,
        "--add-data",
        f"{database}:.",
        source,
    ], cwd=source.parent)
    binary = dist_dir / name
    if not binary.is_file():
        raise RuntimeError("PyInstaller completed but the expected Linux binary was not created.")
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return binary


def test_binary(binary, version):
    result = run([binary, "--version"], cwd=binary.parent, capture=True)
    if version not in (result.stdout or ""):
        raise RuntimeError("Compiled binary --version test failed.")
    test_json_command(
        [binary, "--headless", "--all", "--format", "json"],
        binary.parent,
        "Compiled binary headless test",
    )


def desktop_text(version):
    return "\n".join([
        "[Desktop Entry]",
        "Type=Application",
        "Name=PythoFetch",
        "Comment=Project HomeLab system information fetcher",
        "Exec=PythoFetch",
        "Icon=pythofetch",
        "Terminal=true",
        "Categories=System;",
        "StartupNotify=true",
        f"X-AppImage-Version={version}",
        "",
    ])


def apprun_text():
    geometry = f"{TERMINAL_COLUMNS}x{TERMINAL_ROWS}"

    return "\n".join([
        "#!/bin/sh",
        "",
        'BIN="$APPDIR/usr/bin/PythoFetch"',
        'APP="${APPIMAGE:-}"',
        "",
        'if [ "${PYTHOFETCH_APPIMAGE_TERMINAL:-}" = "1" ]; then',
        '    sleep 0.30',
        '    exec "$BIN" "$@"',
        "fi",
        "",
        'if [ "$#" -gt 0 ]; then',
        '    exec "$BIN" "$@"',
        "fi",
        "",
        'if [ -t 0 ] || [ -t 1 ] || [ -t 2 ]; then',
        '    exec "$BIN"',
        "fi",
        "",
        'if [ -z "$APP" ]; then',
        '    exec "$BIN"',
        "fi",
        "",
        "if command -v gnome-terminal >/dev/null 2>&1; then",
        f'    exec gnome-terminal --title=PythoFetch --geometry={geometry} -- env PYTHOFETCH_APPIMAGE_TERMINAL=1 "$APP"',
        "fi",
        "",
        "if command -v kgx >/dev/null 2>&1; then",
        '    exec kgx -- env PYTHOFETCH_APPIMAGE_TERMINAL=1 "$APP"',
        "fi",
        "",
        "if command -v x-terminal-emulator >/dev/null 2>&1; then",
        '    exec x-terminal-emulator -e env PYTHOFETCH_APPIMAGE_TERMINAL=1 "$APP"',
        "fi",
        "",
        "if command -v konsole >/dev/null 2>&1; then",
        '    exec konsole -e env PYTHOFETCH_APPIMAGE_TERMINAL=1 "$APP"',
        "fi",
        "",
        "if command -v xterm >/dev/null 2>&1; then",
        f'    exec xterm -T PythoFetch -geometry {geometry} -e env PYTHOFETCH_APPIMAGE_TERMINAL=1 "$APP"',
        "fi",
        "",
        'exec "$BIN"',
        "",
    ])


def build_appdir(binary, icon, work_dir, version):
    appdir = work_dir / "PythoFetch.AppDir"
    if appdir.exists():
        shutil.rmtree(appdir)
    bin_dir = appdir / "usr" / "bin"
    app_dir = appdir / "usr" / "share" / "applications"
    icon_dir = appdir / "usr" / "share" / "icons" / "hicolor" / "256x256" / "apps"
    bin_dir.mkdir(parents=True, exist_ok=True)
    app_dir.mkdir(parents=True, exist_ok=True)
    icon_dir.mkdir(parents=True, exist_ok=True)
    deployed_binary = bin_dir / "PythoFetch"
    shutil.copy2(binary, deployed_binary)
    deployed_binary.chmod(deployed_binary.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    shutil.copy2(icon, appdir / "pythofetch.png")
    shutil.copy2(icon, icon_dir / "pythofetch.png")
    text = desktop_text(version)
    (appdir / "pythofetch.desktop").write_text(text, encoding="utf-8")
    (app_dir / "pythofetch.desktop").write_text(text, encoding="utf-8")
    dir_icon = appdir / ".DirIcon"
    if dir_icon.exists() or dir_icon.is_symlink():
        dir_icon.unlink()
    dir_icon.symlink_to("pythofetch.png")
    apprun = appdir / "AppRun"
    apprun.write_text(apprun_text(), encoding="utf-8")
    apprun.chmod(apprun.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return appdir


def validate_appdir(appdir):
    required = [
        appdir / "AppRun",
        appdir / ".DirIcon",
        appdir / "pythofetch.png",
        appdir / "pythofetch.desktop",
        appdir / "usr" / "bin" / "PythoFetch",
        appdir / "usr" / "share" / "applications" / "pythofetch.desktop",
        appdir / "usr" / "share" / "icons" / "hicolor" / "256x256" / "apps" / "pythofetch.png",
    ]
    missing = [str(path) for path in required if not (path.exists() or path.is_symlink())]
    if missing:
        raise RuntimeError("AppDir validation failed. Missing: " + ", ".join(missing))
    if not os.access(appdir / "AppRun", os.X_OK):
        raise RuntimeError("AppRun is not executable.")
    if not os.access(appdir / "usr" / "bin" / "PythoFetch", os.X_OK):
        raise RuntimeError("Bundled PythoFetch binary is not executable.")


def build_appimage(tool, runtime, appdir, output, appimage_arch, version):
    if output.exists():
        output.unlink()
    env = os.environ.copy()
    env["ARCH"] = appimage_arch
    env["VERSION"] = version
    env["APPIMAGE_EXTRACT_AND_RUN"] = "1"
    run(
        [
            tool,
            "--runtime-file",
            runtime,
            "--no-appstream",
            appdir,
            output,
        ],
        cwd=appdir.parent,
        env=env,
    )
    if not output.is_file():
        raise RuntimeError("appimagetool completed but the AppImage was not created.")
    output.chmod(output.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    verify_embedded_runtime(output, runtime)


def test_appimage(appimage, version):
    extracted_env = os.environ.copy()
    extracted_env["APPIMAGE_EXTRACT_AND_RUN"] = "1"
    result = run(
        [appimage, "--appimage-version"],
        cwd=appimage.parent,
        env=extracted_env,
        capture=True,
    )
    if not ((result.stdout or "") + (result.stderr or "")).strip():
        raise RuntimeError("AppImage runtime version test returned no output.")
    result = run(
        [appimage, "--version"],
        cwd=appimage.parent,
        env=extracted_env,
        capture=True,
    )
    if version not in (result.stdout or ""):
        raise RuntimeError("AppImage extract-and-run --version test failed.")
    test_json_command(
        [appimage, "--headless", "--all", "--format", "json"],
        appimage.parent,
        "AppImage extract-and-run headless test",
        env=extracted_env,
    )
    direct_env = os.environ.copy()
    direct_env.pop("APPIMAGE_EXTRACT_AND_RUN", None)
    result = run(
        [appimage, "--version"],
        cwd=appimage.parent,
        env=direct_env,
        capture=True,
    )
    if version not in (result.stdout or ""):
        raise RuntimeError("AppImage normal mounted --version test failed.")


def create_zip(appimage, destination):
    if destination.exists():
        destination.unlink()
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.write(appimage, arcname=appimage.name)
    with zipfile.ZipFile(destination, "r") as archive:
        names = [info.filename for info in archive.infolist() if not info.is_dir()]
    if names != [appimage.name]:
        raise RuntimeError("Release ZIP validation failed.")


def build_report(
    version,
    asset_key,
    release_zip,
    appimage,
    runtime,
):
    zip_record = record(
        release_zip
    )

    app_record = record(
        appimage
    )

    runtime_record = record(
        runtime
    )

    return {
        "builder_version":
            BUILDER_VERSION,
        "version":
            version,
        "asset_key":
            asset_key,
        "file":
            zip_record["file"],
        "sha256":
            zip_record["sha256"],
        "size_bytes":
            zip_record["size_bytes"],
        "executable":
            app_record["file"],
        "executable_sha256":
            app_record["sha256"],
        "executable_size_bytes":
            app_record["size_bytes"],
        "appimage_runtime_build":
            APPIMAGE_RUNTIME_BUILD,
        "appimage_runtime_sha256":
            runtime_record["sha256"],
        "appimage_runtime_size_bytes":
            runtime_record["size_bytes"],
        "appimage_runtime_static":
            True,
        "appimage_mount_helper":
            "fusermount3 or fusermount",
    }


def parse_args():
    parser = argparse.ArgumentParser(prog="Build_PythoFetch_Linux_x86_64_1.0.0")
    parser.add_argument("--clean-cache", action="store_true")
    parser.add_argument("--keep-work", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()

    if platform.system() != "Linux":
        raise RuntimeError(
            "This build tool must be run "
            "on Linux."
        )

    root = Path(
        __file__
    ).resolve().parent

    source, version = find_source(
        root
    )

    database = find_database(
        root
    )

    release_arch, appimage_arch = (
        detect_architecture()
    )

    asset_key = (
        f"Linux_{release_arch}"
    )

    cache_dir = (
        root
        / ".pythofetch-linux-build"
    )

    work_dir = (
        cache_dir
        / "work"
    )

    if (
        args.clean_cache
        and cache_dir.exists()
    ):
        shutil.rmtree(
            cache_dir
        )

    if work_dir.exists():
        shutil.rmtree(
            work_dir
        )

    work_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    icon = find_icon(
        root,
        work_dir,
    )

    appimage_name = (
        f"PythoFetch_{version}"
        f"_Linux_{release_arch}.AppImage"
    )

    zip_name = (
        f"PythoFetch_{version}"
        f"_Linux_{release_arch}.zip"
    )

    report_name = (
        f"PythoFetch_{version}"
        f"_Linux_{release_arch}"
        "_Build.json"
    )

    appimage_output = (
        work_dir
        / appimage_name
    )

    zip_output = (
        root
        / zip_name
    )

    for stale in (
        root / appimage_name,
        root / report_name,
    ):
        if stale.is_file():
            stale.unlink()

    print()

    print(
        "PythoFetch Linux x86_64 Build Tool "
        f"{BUILDER_VERSION}"
    )

    print(
        "=" * 40
    )

    show(
        "SOURCE",
        source.name,
    )

    show(
        "VERSION",
        version,
    )

    show(
        "DATABASE",
        database.name,
    )

    show(
        "ICON",
        (
            icon.name
            if icon.parent == root
            else "GitHub fallback"
        ),
    )

    show(
        "TARGET",
        asset_key,
    )

    print()

    python_path = (
        ensure_build_environment(
            cache_dir
        )
    )

    show(
        "PREPARE",
        "256x256 Linux icon",
    )

    linux_icon = prepare_linux_icon(
        python_path,
        icon,
        work_dir,
    )

    show(
        "TEST",
        "Source",
    )

    test_source(
        python_path,
        source,
        version,
    )

    show(
        "BUILD",
        "PyInstaller binary",
    )

    binary = build_binary(
        python_path,
        source,
        database,
        work_dir,
        version,
    )

    show(
        "TEST",
        "PyInstaller binary",
    )

    test_binary(
        binary,
        version,
    )

    show(
        "BUILD",
        "AppDir",
    )

    appdir = build_appdir(
        binary,
        linux_icon,
        work_dir,
        version,
    )

    validate_appdir(
        appdir
    )

    show(
        "SETUP",
        f"appimagetool "
        f"{APPIMAGETOOL_VERSION}",
    )

    tool = ensure_appimagetool(
        cache_dir,
        appimage_arch,
    )

    show(
        "SETUP",
        "AppImage runtime "
        f"{APPIMAGE_RUNTIME_BUILD}",
    )

    runtime = ensure_appimage_runtime(
        cache_dir,
        appimage_arch,
    )

    show(
        "BUILD",
        appimage_name,
    )

    build_appimage(
        tool,
        runtime,
        appdir,
        appimage_output,
        appimage_arch,
        version,
    )

    show(
        "TEST",
        "AppImage",
    )

    test_appimage(
        appimage_output,
        version,
    )

    show(
        "BUILD",
        zip_name,
    )

    create_zip(
        appimage_output,
        zip_output,
    )

    report = build_report(
        version,
        asset_key,
        zip_output,
        appimage_output,
        runtime,
    )

    if (
        not args.keep_work
        and cache_dir.exists()
    ):
        shutil.rmtree(
            cache_dir
        )

    print()
    print(
        "=" * 40
    )
    print(
        "READY TO REVIEW"
    )
    print(
        "=" * 40
    )

    print(
        f"ZIP: {zip_output.name}"
    )

    print()

    print(
        "ZIP SHA-256:"
    )

    print(
        report["sha256"]
    )

    print(
        "ZIP bytes:"
    )

    print(
        report["size_bytes"]
    )

    print()

    print(
        "Contained AppImage:"
    )

    print(
        report["executable"]
    )

    print(
        "AppImage SHA-256:"
    )

    print(
        report[
            "executable_sha256"
        ]
    )

    print(
        "AppImage bytes:"
    )

    print(
        report[
            "executable_size_bytes"
        ]
    )

    print()

    print(
        "AppImage runtime: "
        f"{APPIMAGE_RUNTIME_BUILD}"
    )

    print(
        "Runtime libfuse dependency: "
        "bundled/static"
    )

    print(
        "OS mount helper: "
        "fusermount3 or fusermount"
    )

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print()
        print("Build cancelled.", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print()
        print("BUILD FAILED: " + str(exc), file=sys.stderr)
        raise SystemExit(1)
