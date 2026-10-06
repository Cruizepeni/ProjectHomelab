import argparse
import hashlib
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import venv
import zipfile
from pathlib import Path

BUILDER_VERSION = "1.0.0"
PYINSTALLER_VERSION = "6.22.3"
FOLDER_PATTERN = re.compile(
    r"^PythoFetchUpdater_(\d+\.\d+\.\d+)$",
    re.IGNORECASE,
)
VERSION_PATTERN = re.compile(
    r'^\s*PYTHOFETCH_UPDATER_VERSION\s*=\s*["\'](\d+\.\d+\.\d+)["\']',
    re.MULTILINE,
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
        " ".join(
            command
        ),
    )

    result = subprocess.run(
        command,
        cwd=(
            str(cwd)
            if cwd
            else None
        ),
        env=env,
        text=True,
        capture_output=capture,
    )

    if result.returncode != 0:
        if capture:
            if result.stdout:
                print(
                    result.stdout
                )

            if result.stderr:
                print(
                    result.stderr,
                    file=sys.stderr,
                )

        raise RuntimeError(
            "Command failed with exit code "
            f"{result.returncode}: "
            + " ".join(
                command
            )
        )

    return result


def sha256_file(path):
    digest = hashlib.sha256()

    with Path(path).open(
        "rb"
    ) as handle:
        while True:
            chunk = handle.read(
                1024 * 1024
            )

            if not chunk:
                break

            digest.update(
                chunk
            )

    return digest.hexdigest()


def detect_target_version(root):
    match = FOLDER_PATTERN.fullmatch(
        root.name
    )

    if not match:
        raise RuntimeError(
            "Copy this build tool into a PythoFetchUpdater_X.Y.Z source folder before running it."
        )

    return match.group(1)


def find_source(root, version):
    path = (
        root
        / f"PythoFetchUpdater_{version}.py"
    )

    if not path.is_file():
        raise RuntimeError(
            f"{path.name} was not found beside this build tool."
        )

    text = path.read_text(
        encoding="utf-8"
    )

    match = VERSION_PATTERN.search(
        text
    )

    if not match:
        raise RuntimeError(
            f"{path.name} does not declare PYTHOFETCH_UPDATER_VERSION."
        )

    source_version = match.group(1)

    if source_version != version:
        text = (
            text[:match.start(1)]
            + version
            + text[match.end(1):]
        )

        path.write_text(
            text,
            encoding="utf-8",
        )

        show(
            "VERSION",
            "Normalized updater source version "
            f"{source_version} -> {version}",
        )

    return path


def detect_architecture():
    machine = str(
        platform.machine() or ""
    ).strip().lower()

    if machine in (
        "arm64",
        "aarch64",
    ):
        return "arm64"

    raise RuntimeError(
        "This build tool targets Linux arm64 only. "
        f"Detected architecture: {machine or 'Unknown'}"
    )


def ensure_build_environment(cache_dir):
    venv_dir = (
        cache_dir
        / "venv"
    )

    python_path = (
        venv_dir
        / "bin"
        / "python"
    )

    rebuild = (
        not python_path.is_file()
    )

    if not rebuild:
        probe = subprocess.run(
            [
                python_path,
                "-m",
                "pip",
                "--version",
            ],
            text=True,
            capture_output=True,
        )

        rebuild = (
            probe.returncode
            != 0
        )

    if rebuild:
        if venv_dir.exists():
            show(
                "RECOVER",
                "Removing incomplete build environment",
            )

            shutil.rmtree(
                venv_dir
            )

        show(
            "SETUP",
            "Creating isolated build environment",
        )

        venv.create(
            str(
                venv_dir
            ),
            with_pip=True,
            clear=True,
        )

        probe = subprocess.run(
            [
                python_path,
                "-m",
                "pip",
                "--version",
            ],
            text=True,
            capture_output=True,
        )

        if probe.returncode != 0:
            raise RuntimeError(
                "The isolated build environment was created without pip. Install Python venv support for this interpreter and rerun the build tool."
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


def test_version_command(
    command,
    cwd,
    version,
):
    result = run(
        command,
        cwd=cwd,
        capture=True,
    )

    output = (
        (result.stdout or "")
        + (result.stderr or "")
    ).strip()

    if version not in output:
        raise RuntimeError(
            "Updater --version test failed."
        )


def build_binary(
    python_path,
    source,
    work_dir,
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

    run(
        [
            python_path,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onefile",
            "--name",
            "PythoFetchUpdater",
            "--distpath",
            dist_dir,
            "--workpath",
            pyinstaller_work,
            "--specpath",
            spec_dir,
            source,
        ],
        cwd=source.parent,
    )

    binary = (
        dist_dir
        / "PythoFetchUpdater"
    )

    if not binary.is_file():
        raise RuntimeError(
            "PyInstaller did not create PythoFetchUpdater."
        )

    binary.chmod(
        binary.stat().st_mode
        | stat.S_IXUSR
        | stat.S_IXGRP
        | stat.S_IXOTH
    )

    return binary


def validate_binary(binary):
    if not binary.is_file():
        raise RuntimeError(
            "PythoFetchUpdater binary is missing."
        )

    if not os.access(
        binary,
        os.X_OK,
    ):
        raise RuntimeError(
            "PythoFetchUpdater binary is not executable."
        )

    with binary.open(
        "rb"
    ) as handle:
        magic = handle.read(
            4
        )

    if magic != b"\x7fELF":
        raise RuntimeError(
            "PythoFetchUpdater is not a Linux ELF executable."
        )


def create_zip(
    binary,
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
            binary,
            arcname="PythoFetchUpdater",
        )

    with zipfile.ZipFile(
        destination,
        "r",
    ) as archive:
        files = [
            info
            for info in archive.infolist()
            if not info.is_dir()
        ]

    if len(files) != 1:
        raise RuntimeError(
            "Updater release ZIP validation failed."
        )

    info = files[0]

    if info.filename != "PythoFetchUpdater":
        raise RuntimeError(
            "Updater release ZIP contains an unexpected payload name."
        )


def parse_args():
    parser = argparse.ArgumentParser(
        prog="Build_PythoFetchUpdater_Linux_arm64_1.0.0"
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

    if platform.system() != "Linux":
        raise RuntimeError(
            "This build tool must be run on Linux."
        )

    root = Path(
        __file__
    ).resolve().parent

    version = detect_target_version(
        root
    )

    source = find_source(
        root,
        version,
    )

    release_arch = detect_architecture()

    cache_dir = (
        root
        / ".pythofetch-updater-linux-arm64-build"
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

    zip_name = (
        f"PythoFetchUpdater_{version}_"
        f"Linux_{release_arch}.zip"
    )

    zip_output = (
        root
        / zip_name
    )

    print()
    print(
        "PythoFetchUpdater Linux arm64 "
        f"Build Tool {BUILDER_VERSION}"
    )
    print(
        "=" * 58
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
        "TARGET",
        f"Linux_{release_arch}",
    )

    print()

    python_path = ensure_build_environment(
        cache_dir
    )

    show(
        "TEST",
        "Source",
    )

    test_version_command(
        [
            python_path,
            source,
            "--version",
        ],
        source.parent,
        version,
    )

    show(
        "BUILD",
        "PythoFetchUpdater ELF",
    )

    binary = build_binary(
        python_path,
        source,
        work_dir,
    )

    validate_binary(
        binary
    )

    show(
        "TEST",
        "PythoFetchUpdater ELF",
    )

    test_version_command(
        [
            binary,
            "--version",
        ],
        binary.parent,
        version,
    )

    show(
        "BUILD",
        zip_name,
    )

    create_zip(
        binary,
        zip_output,
    )

    zip_hash = sha256_file(
        zip_output
    )

    binary_hash = sha256_file(
        binary
    )

    binary_size = (
        binary.stat().st_size
    )

    zip_size = (
        zip_output.stat().st_size
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
        "=" * 58
    )
    print(
        "READY TO REVIEW"
    )
    print(
        "=" * 58
    )
    print(
        f"ZIP: {zip_output.name}"
    )
    print(
        f"ZIP SHA-256: {zip_hash}"
    )
    print(
        f"ZIP bytes: {zip_size}"
    )
    print(
        "Contained executable: PythoFetchUpdater"
    )
    print(
        f"Executable SHA-256: {binary_hash}"
    )
    print(
        f"Executable bytes: {binary_size}"
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
        raise SystemExit(
            130
        )
    except Exception as exc:
        print()
        print(
            "BUILD FAILED: "
            + str(
                exc
            ),
            file=sys.stderr,
        )
        raise SystemExit(
            1
        )
