import argparse
import hashlib
import json
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
ICON_URL = (
    "https://raw.githubusercontent.com/"
    "Cruizepeni/ProjectHomelab/main/"
    "Resources/Icons/Features/PythoFetch/"
    "Icon_PythoFetch.ico"
)

SOURCE_PATTERN = re.compile(
    r"^PythoFetch(?:_[^/]+)?\.py$",
    re.IGNORECASE,
)

DATABASE_PATTERN = re.compile(
    r"^PythoFetchArt_(\d+(?:\.\d+)*)\.db$",
    re.IGNORECASE,
)

VERSION_PATTERN = re.compile(
    r'^\s*PYTHOFETCH_VERSION\s*=\s*["\'](\d+(?:\.\d+)*)["\']',
    re.MULTILINE,
)


def version_key(value):
    parts = str(value).strip().split(".")

    if not parts or any(
        not part.isdigit()
        for part in parts
    ):
        raise RuntimeError(
            f"Invalid numeric version: {value}"
        )

    return tuple(
        int(part)
        for part in parts
    )


def show(label, value=""):
    print(
        f"[{label}] {value}"
        if value
        else f"[{label}]"
    )


def run(
    command,
    cwd=None,
    env=None,
    capture=False,
):
    command = [
        str(part)
        for part in command
    ]

    show(
        "RUN",
        subprocess.list2cmdline(command),
    )

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
                print(
                    result.stderr,
                    file=sys.stderr,
                )

        raise RuntimeError(
            "Command failed with exit code "
            f"{result.returncode}: "
            + subprocess.list2cmdline(command)
        )

    return result


def sha256_file(path):
    digest = hashlib.sha256()

    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(
                1024 * 1024
            )

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
    compiler_name = Path(__file__).name.lower()

    for path in root.iterdir():
        if not path.is_file():
            continue

        if path.name.lower() == compiler_name:
            continue

        if not SOURCE_PATTERN.match(path.name):
            continue

        source_text = path.read_text(
            encoding="utf-8"
        )

        match = VERSION_PATTERN.search(
            source_text
        )

        if not match:
            continue

        source_version = match.group(1)

        candidates.append(
            (
                version_key(
                    source_version
                ),
                source_version,
                path,
            )
        )

    if not candidates:
        raise RuntimeError(
            "No PythoFetch Python source "
            "containing PYTHOFETCH_VERSION "
            "was found beside this compiler."
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
    canonical_name = (
        f"PythoFetch_{version}.py"
    )

    canonical = [
        item
        for item in highest
        if (
            item[2].name.lower()
            == canonical_name.lower()
        )
    ]

    if len(canonical) == 1:
        return (
            canonical[0][2],
            version,
        )

    if len(highest) == 1:
        return (
            highest[0][2],
            version,
        )

    names = ", ".join(
        sorted(
            item[2].name
            for item in highest
        )
    )

    raise RuntimeError(
        "Multiple PythoFetch source files "
        "declare the same highest version "
        f"{version}: {names}. Keep one "
        "source file or use the canonical "
        f"filename {canonical_name}."
    )


def find_database(root):
    candidates = []

    for path in root.iterdir():
        if not path.is_file():
            continue

        match = DATABASE_PATTERN.match(
            path.name
        )

        if match:
            candidates.append(
                (
                    version_key(
                        match.group(1)
                    ),
                    path,
                )
            )

    if not candidates:
        raise RuntimeError(
            "No PythoFetchArt_<version>.db "
            "file was found beside this compiler."
        )

    candidates.sort(
        key=lambda item: item[0]
    )

    return candidates[-1][1]


def validate_icon(icon):
    with icon.open("rb") as handle:
        header = handle.read(4)

    if (
        len(header) != 4
        or header[:2] != b"\x00\x00"
        or header[2:] != b"\x01\x00"
    ):
        raise RuntimeError(
            "Icon_PythoFetch.ico is not "
            "a valid ICO file."
        )


def download(
    url,
    destination,
):
    destination = Path(destination)

    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = destination.with_name(
        destination.name + ".download"
    )

    if temporary.exists():
        temporary.unlink()

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent":
                f"PythoFetchWindowsCompiler/{BUILDER_VERSION}",
        },
    )

    show(
        "DOWNLOAD",
        url,
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=120,
        ) as response:
            with temporary.open(
                "wb"
            ) as handle:
                shutil.copyfileobj(
                    response,
                    handle,
                )

        if (
            not temporary.is_file()
            or temporary.stat().st_size == 0
        ):
            raise RuntimeError(
                "Downloaded file is empty."
            )

        os.replace(
            temporary,
            destination,
        )

    finally:
        if temporary.exists():
            temporary.unlink()

    return destination


def find_icon(
    root,
    work_dir,
):
    local_icon = (
        root
        / "Icon_PythoFetch.ico"
    )

    if local_icon.is_file():
        validate_icon(
            local_icon
        )

        return local_icon

    downloaded_icon = (
        work_dir
        / "Icon_PythoFetch.ico"
    )

    download(
        ICON_URL,
        downloaded_icon,
    )

    validate_icon(
        downloaded_icon
    )

    return downloaded_icon


def detect_architecture():
    machine = str(
        platform.machine() or ""
    ).strip().lower()

    if machine in (
        "amd64",
        "x86_64",
        "x64",
    ):
        return "x86_64"

    if machine in (
        "arm64",
        "aarch64",
    ):
        return "arm64"

    raise RuntimeError(
        "Unsupported Windows architecture: "
        f"{machine or 'Unknown'}"
    )


def ensure_build_environment(
    cache_dir,
):
    venv_dir = (
        cache_dir
        / "venv"
    )

    python_path = (
        venv_dir
        / "Scripts"
        / "python.exe"
    )

    if not python_path.is_file():
        show(
            "SETUP",
            "Creating isolated build environment",
        )

        venv.create(
            str(venv_dir),
            with_pip=True,
            clear=False,
        )

    run(
        [
            python_path,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            f"pyinstaller=={PYINSTALLER_VERSION}",
        ]
    )

    return python_path


def test_json_command(
    command,
    cwd,
    label,
):
    result = run(
        command,
        cwd=cwd,
        capture=True,
    )

    try:
        payload = json.loads(
            result.stdout
        )
    except Exception as exc:
        raise RuntimeError(
            f"{label} returned invalid JSON."
        ) from exc

    if not isinstance(
        payload,
        dict,
    ):
        raise RuntimeError(
            f"{label} returned an "
            "invalid payload."
        )


def test_source(
    python_path,
    source,
    version,
):
    result = run(
        [
            python_path,
            source,
            "--version",
        ],
        cwd=source.parent,
        capture=True,
    )

    if version not in (
        result.stdout or ""
    ):
        raise RuntimeError(
            "Source --version test failed."
        )

    test_json_command(
        [
            python_path,
            source,
            "--headless",
            "--info",
            "--format",
            "json",
        ],
        source.parent,
        "Source headless test",
    )


def build_binary(
    python_path,
    source,
    database,
    icon,
    work_dir,
    version,
):
    dist_dir = (
        work_dir
        / "dist"
    )

    pyinstaller_work = (
        work_dir
        / "pyinstaller-work"
    )

    spec_dir = (
        work_dir
        / "spec"
    )

    dist_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    pyinstaller_work.mkdir(
        parents=True,
        exist_ok=True,
    )

    spec_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    name = f"PythoFetch_{version}"

    run(
        [
            python_path,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onefile",
            "--console",
            "--name",
            name,
            "--icon",
            icon,
            "--distpath",
            dist_dir,
            "--workpath",
            pyinstaller_work,
            "--specpath",
            spec_dir,
            "--add-data",
            f"{database}{os.pathsep}.",
            source,
        ],
        cwd=source.parent,
    )

    binary = (
        dist_dir
        / f"{name}.exe"
    )

    if not binary.is_file():
        raise RuntimeError(
            "PyInstaller completed but the "
            "expected Windows EXE was not created."
        )

    return binary


def test_binary(
    binary,
    version,
):
    result = run(
        [
            binary,
            "--version",
        ],
        cwd=binary.parent,
        capture=True,
    )

    if version not in (
        result.stdout or ""
    ):
        raise RuntimeError(
            "Compiled EXE --version "
            "test failed."
        )

    test_json_command(
        [
            binary,
            "--headless",
            "--all",
            "--format",
            "json",
        ],
        binary.parent,
        "Compiled EXE headless test",
    )


def create_zip(
    executable,
    destination,
):
    if destination.exists():
        destination.unlink()

    with zipfile.ZipFile(
        destination,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        archive.write(
            executable,
            arcname=executable.name,
        )

    with zipfile.ZipFile(
        destination,
        "r",
    ) as archive:
        names = [
            info.filename
            for info
            in archive.infolist()
            if not info.is_dir()
        ]

    if names != [
        executable.name
    ]:
        raise RuntimeError(
            "Release ZIP validation failed."
        )


def build_report(
    version,
    asset_key,
    release_zip,
    executable,
):
    zip_record = record(
        release_zip
    )

    executable_record = record(
        executable
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
            executable_record["file"],
        "executable_sha256":
            executable_record["sha256"],
        "executable_size_bytes":
            executable_record[
                "size_bytes"
            ],
    }


def parse_args():
    parser = argparse.ArgumentParser(
        prog="PythoFetchWindowsCompiler"
    )

    parser.add_argument(
        "--clean-cache",
        action="store_true",
    )

    parser.add_argument(
        "--keep-work",
        action="store_true",
    )

    return parser.parse_args()


def main():
    args = parse_args()

    if platform.system() != "Windows":
        raise RuntimeError(
            "This compiler must be run "
            "on Windows."
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

    release_arch = detect_architecture()
    asset_key = (
        f"Windows_{release_arch}"
    )

    cache_dir = (
        root
        / ".pythofetch-windows-build"
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

    exe_name = (
        f"PythoFetch_{version}.exe"
    )

    zip_name = (
        f"PythoFetch_{version}"
        f"_Windows_{release_arch}.zip"
    )

    report_name = (
        f"PythoFetch_{version}"
        f"_Windows_{release_arch}"
        "_Build.json"
    )

    zip_output = (
        root
        / zip_name
    )

    for stale in (
        root / exe_name,
        root / report_name,
    ):
        if stale.is_file():
            stale.unlink()

    print()

    print(
        "PythoFetch Windows Compiler "
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
        "PyInstaller EXE",
    )

    built_exe = build_binary(
        python_path,
        source,
        database,
        icon,
        work_dir,
        version,
    )

    show(
        "TEST",
        "PyInstaller EXE",
    )

    test_binary(
        built_exe,
        version,
    )

    show(
        "BUILD",
        zip_name,
    )

    create_zip(
        built_exe,
        zip_output,
    )

    report = build_report(
        version,
        asset_key,
        zip_output,
        built_exe,
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
        "Contained EXE:"
    )

    print(
        report["executable"]
    )

    print(
        "EXE SHA-256:"
    )

    print(
        report[
            "executable_sha256"
        ]
    )

    print(
        "EXE bytes:"
    )

    print(
        report[
            "executable_size_bytes"
        ]
    )

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(
            main()
        )
    except KeyboardInterrupt:
        print()
        print(
            "Build cancelled.",
            file=sys.stderr,
        )
        raise SystemExit(130)
    except Exception as exc:
        print()
        print(
            "BUILD FAILED: "
            + str(exc),
            file=sys.stderr,
        )
        raise SystemExit(1)
