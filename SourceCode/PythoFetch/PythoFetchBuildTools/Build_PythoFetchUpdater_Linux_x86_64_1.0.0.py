import argparse
import hashlib
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import time
import urllib.request
import venv
import zipfile
from pathlib import Path

BUILDER_VERSION = "1.0.0"
PYINSTALLER_VERSION = "6.22.3"
PILLOW_VERSION = "11.3.0"
APPIMAGETOOL_VERSION = "1.9.1"
APPIMAGE_RUNTIME_BUILD = "2026-09-28-8f39b89"
ICON_URL = (
    "https://raw.githubusercontent.com/"
    "Cruizepeni/ProjectHomelab/main/"
    "Resources/Icons/Shared/Updater/"
    "Icon_Updater.png"
)
APPIMAGE_RUNTIME_ASSETS = {
    "x86_64": {
        "url": (
            "https://github.com/AppImage/"
            "type2-runtime/releases/download/"
            "continuous/runtime-x86_64"
        ),
        "sha256": (
            "156f4bdbde9c52d01814600013e0a273"
            "f0118dc2de98975f3c8c63427ec79074"
        ),
        "size_bytes": 944632,
    },
}
APPIMAGETOOL_ASSETS = {
    "x86_64": {
        "url": (
            "https://github.com/AppImage/"
            "appimagetool/releases/download/"
            "1.9.1/appimagetool-x86_64.AppImage"
        ),
        "sha256": (
            "ed4ce84f0d9caff66f50bcca6ff6f35a"
            "ae54ce8135408b3fa33abfc3cb384eb0"
        ),
        "size_bytes": 15092216,
    },
}
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


def validate_icon(icon):
    with icon.open(
        "rb"
    ) as handle:
        signature = handle.read(
            8
        )

    if (
        signature
        != b"\x89PNG\r\n\x1a\n"
    ):
        raise RuntimeError(
            "Icon_Updater.png is not a valid PNG file."
        )


def download(
    url,
    destination,
    attempts=4,
):
    destination = Path(
        destination
    )

    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = destination.with_name(
        destination.name
        + ".download"
    )

    if temporary.exists():
        temporary.unlink()

    show(
        "DOWNLOAD",
        url,
    )

    last_error = None

    for attempt in range(
        1,
        attempts + 1,
    ):
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent":
                    f"PythoFetchUpdaterLinuxBuildTool/{BUILDER_VERSION}",
            },
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

            return destination

        except Exception as exc:
            last_error = exc

            if temporary.exists():
                temporary.unlink()

            if attempt >= attempts:
                break

            delay = (
                2 ** attempt
            )

            show(
                "RETRY",
                f"{attempt}/{attempts} failed; retrying in {delay}s",
            )

            time.sleep(
                delay
            )

    raise RuntimeError(
        f"Download failed after {attempts} attempts: {last_error}"
    )


def find_icon(
    root,
    cache_dir,
):
    local = (
        root
        / "Icon_Updater.png"
    )

    if local.is_file():
        validate_icon(
            local
        )

        return local

    target = (
        cache_dir
        / "tools"
        / "Icon_Updater.png"
    )

    if target.is_file():
        try:
            validate_icon(
                target
            )

            return target
        except Exception:
            target.unlink()

    download(
        ICON_URL,
        target,
    )

    validate_icon(
        target
    )

    return target


def detect_architecture():
    machine = str(
        platform.machine() or ""
    ).strip().lower()

    if machine in (
        "x86_64",
        "amd64",
        "x64",
    ):
        return (
            "x86_64",
            "x86_64",
        )

    raise RuntimeError(
        "This build tool targets Linux x86_64 only. "
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
                "The isolated build environment was created without pip. "
                "Install Python venv support for this interpreter and rerun the build tool."
            )

    run(
        [
            python_path,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            f"pyinstaller=={PYINSTALLER_VERSION}",
            f"pillow=={PILLOW_VERSION}",
        ]
    )

    return python_path


def prepare_linux_icon(
    python_path,
    icon,
    work_dir,
):
    icon_dir = (
        work_dir
        / "icon"
    )

    icon_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    output = (
        icon_dir
        / "pythofetchupdater.png"
    )

    script = "\n".join(
        [
            "from PIL import Image",
            "import sys",
            "source = Image.open(sys.argv[1]).convert('RGBA')",
            "source.thumbnail((256, 256), Image.Resampling.LANCZOS)",
            "canvas = Image.new('RGBA', (256, 256), (0, 0, 0, 0))",
            "x = (256 - source.width) // 2",
            "y = (256 - source.height) // 2",
            "canvas.alpha_composite(source, (x, y))",
            "canvas.save(sys.argv[2], format='PNG', optimize=True)",
        ]
    )

    run(
        [
            python_path,
            "-c",
            script,
            icon,
            output,
        ]
    )

    validate_icon(
        output
    )

    return output


def ensure_appimagetool(
    cache_dir,
    appimage_arch,
):
    entry = APPIMAGETOOL_ASSETS.get(
        appimage_arch
    )

    if not entry:
        raise RuntimeError(
            f"No pinned appimagetool asset is configured for {appimage_arch}."
        )

    filename = (
        f"appimagetool-{appimage_arch}.AppImage"
    )

    tool = (
        cache_dir
        / "tools"
        / filename
    )

    expected_hash = (
        entry[
            "sha256"
        ].lower()
    )

    expected_size = int(
        entry[
            "size_bytes"
        ]
    )

    if tool.is_file():
        valid_cached_tool = (
            tool.stat().st_size
            == expected_size
            and sha256_file(
                tool
            ).lower()
            == expected_hash
        )

        if not valid_cached_tool:
            tool.unlink()

    if not tool.is_file():
        download(
            entry[
                "url"
            ],
            tool,
        )

    actual_size = (
        tool.stat().st_size
    )

    actual_hash = sha256_file(
        tool
    ).lower()

    if (
        actual_size
        != expected_size
        or actual_hash
        != expected_hash
    ):
        if tool.exists():
            tool.unlink()

        raise RuntimeError(
            "Pinned appimagetool verification failed. "
            f"Expected {expected_size} bytes and {expected_hash}, "
            f"received {actual_size} bytes and {actual_hash}."
        )

    tool.chmod(
        tool.stat().st_mode
        | stat.S_IXUSR
        | stat.S_IXGRP
        | stat.S_IXOTH
    )

    return tool


def ensure_appimage_runtime(
    cache_dir,
    appimage_arch,
):
    entry = APPIMAGE_RUNTIME_ASSETS.get(
        appimage_arch
    )

    if not entry:
        raise RuntimeError(
            f"No pinned AppImage runtime is configured for {appimage_arch}."
        )

    runtime = (
        cache_dir
        / "tools"
        / f"runtime-{appimage_arch}"
    )

    expected_hash = (
        entry[
            "sha256"
        ].lower()
    )

    expected_size = int(
        entry[
            "size_bytes"
        ]
    )

    if runtime.is_file():
        valid_cached_runtime = (
            runtime.stat().st_size
            == expected_size
            and sha256_file(
                runtime
            ).lower()
            == expected_hash
        )

        if not valid_cached_runtime:
            runtime.unlink()

    if not runtime.is_file():
        download(
            entry[
                "url"
            ],
            runtime,
        )

    actual_size = (
        runtime.stat().st_size
    )

    actual_hash = sha256_file(
        runtime
    ).lower()

    if (
        actual_size
        != expected_size
        or actual_hash
        != expected_hash
    ):
        if runtime.exists():
            runtime.unlink()

        raise RuntimeError(
            "Pinned AppImage runtime verification failed. "
            f"Expected {expected_size} bytes and {expected_hash}, "
            f"received {actual_size} bytes and {actual_hash}."
        )

    return runtime


def verify_embedded_runtime(
    appimage,
    runtime,
):
    runtime_size = (
        runtime.stat().st_size
    )

    if (
        appimage.stat().st_size
        <= runtime_size
    ):
        raise RuntimeError(
            "Generated AppImage is too small."
        )

    with appimage.open(
        "rb"
    ) as handle:
        elf_magic = handle.read(
            4
        )

        handle.seek(
            8
        )

        appimage_magic = handle.read(
            3
        )

    if elf_magic != b"\x7fELF":
        raise RuntimeError(
            "Generated AppImage has an invalid ELF header."
        )

    if appimage_magic != b"AI\x02":
        raise RuntimeError(
            "Generated file is not a type 2 AppImage."
        )

    result = run(
        [
            appimage,
            "--appimage-offset",
        ],
        cwd=appimage.parent,
        capture=True,
    )

    try:
        offset = int(
            (
                result.stdout
                or ""
            ).strip()
        )
    except Exception as exc:
        raise RuntimeError(
            "Could not read AppImage filesystem offset."
        ) from exc

    if offset != runtime_size:
        raise RuntimeError(
            "Generated AppImage runtime size does not match pinned runtime."
        )


def test_version_command(
    command,
    cwd,
    version,
    env=None,
):
    result = run(
        command,
        cwd=cwd,
        env=env,
        capture=True,
    )

    output = (
        (
            result.stdout
            or ""
        )
        + (
            result.stderr
            or ""
        )
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


def desktop_text(version):
    return "\n".join(
        [
            "[Desktop Entry]",
            "Type=Application",
            "Name=PythoFetchUpdater",
            "Comment=ProjectHomelab PythoFetch updater",
            "Exec=PythoFetchUpdater",
            "Icon=pythofetchupdater",
            "Terminal=false",
            "Categories=System;",
            "StartupNotify=false",
            f"X-AppImage-Version={version}",
            "",
        ]
    )


def apprun_text():
    return "\n".join(
        [
            "#!/bin/sh",
            'exec "$APPDIR/usr/bin/PythoFetchUpdater" "$@"',
            "",
        ]
    )


def build_appdir(
    binary,
    icon,
    work_dir,
    version,
):
    appdir = (
        work_dir
        / "PythoFetchUpdater.AppDir"
    )

    if appdir.exists():
        shutil.rmtree(
            appdir
        )

    bin_dir = (
        appdir
        / "usr"
        / "bin"
    )

    app_dir = (
        appdir
        / "usr"
        / "share"
        / "applications"
    )

    icon_dir = (
        appdir
        / "usr"
        / "share"
        / "icons"
        / "hicolor"
        / "256x256"
        / "apps"
    )

    bin_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    app_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    icon_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    deployed = (
        bin_dir
        / "PythoFetchUpdater"
    )

    shutil.copy2(
        binary,
        deployed,
    )

    deployed.chmod(
        deployed.stat().st_mode
        | stat.S_IXUSR
        | stat.S_IXGRP
        | stat.S_IXOTH
    )

    shutil.copy2(
        icon,
        appdir
        / "pythofetchupdater.png",
    )

    shutil.copy2(
        icon,
        icon_dir
        / "pythofetchupdater.png",
    )

    text = desktop_text(
        version
    )

    (
        appdir
        / "pythofetchupdater.desktop"
    ).write_text(
        text,
        encoding="utf-8",
    )

    (
        app_dir
        / "pythofetchupdater.desktop"
    ).write_text(
        text,
        encoding="utf-8",
    )

    dir_icon = (
        appdir
        / ".DirIcon"
    )

    if (
        dir_icon.exists()
        or dir_icon.is_symlink()
    ):
        dir_icon.unlink()

    dir_icon.symlink_to(
        "pythofetchupdater.png"
    )

    apprun = (
        appdir
        / "AppRun"
    )

    apprun.write_text(
        apprun_text(),
        encoding="utf-8",
    )

    apprun.chmod(
        apprun.stat().st_mode
        | stat.S_IXUSR
        | stat.S_IXGRP
        | stat.S_IXOTH
    )

    return appdir


def build_appimage(
    tool,
    runtime,
    appdir,
    output,
    appimage_arch,
    version,
):
    if output.exists():
        output.unlink()

    env = os.environ.copy()
    env[
        "ARCH"
    ] = appimage_arch
    env[
        "VERSION"
    ] = version
    env[
        "APPIMAGE_EXTRACT_AND_RUN"
    ] = "1"

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
        raise RuntimeError(
            "appimagetool did not create PythoFetchUpdater.AppImage."
        )

    output.chmod(
        output.stat().st_mode
        | stat.S_IXUSR
        | stat.S_IXGRP
        | stat.S_IXOTH
    )

    verify_embedded_runtime(
        output,
        runtime,
    )


def create_zip(
    appimage,
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
            appimage,
            arcname="PythoFetchUpdater.AppImage",
        )

    with zipfile.ZipFile(
        destination,
        "r",
    ) as archive:
        names = [
            info.filename
            for info in archive.infolist()
            if not info.is_dir()
        ]

    if names != [
        "PythoFetchUpdater.AppImage"
    ]:
        raise RuntimeError(
            "Updater release ZIP validation failed."
        )


def parse_args():
    parser = argparse.ArgumentParser(
        prog="Build_PythoFetchUpdater_Linux_x86_64_1.0.0"
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

    release_arch, appimage_arch = (
        detect_architecture()
    )

    cache_dir = (
        root
        / ".pythofetch-updater-linux-build"
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
        cache_dir,
    )

    appimage_output = (
        work_dir
        / "PythoFetchUpdater.AppImage"
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
        "PythoFetchUpdater Linux x86_64 "
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
        "ICON",
        (
            icon.name
            if icon.parent == root
            else "GitHub fallback"
        ),
    )
    show(
        "TARGET",
        f"Linux_{release_arch}",
    )

    print()

    show(
        "PREFLIGHT",
        "Caching pinned AppImage build dependencies",
    )

    python_path = ensure_build_environment(
        cache_dir
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
        "PyInstaller binary",
    )

    binary = build_binary(
        python_path,
        source,
        work_dir,
    )

    show(
        "TEST",
        "PyInstaller binary",
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
        "AppDir",
    )

    appdir = build_appdir(
        binary,
        linux_icon,
        work_dir,
        version,
    )

    show(
        "SETUP",
        f"appimagetool {APPIMAGETOOL_VERSION}",
    )

    tool = ensure_appimagetool(
        cache_dir,
        appimage_arch,
    )

    show(
        "SETUP",
        f"AppImage runtime {APPIMAGE_RUNTIME_BUILD}",
    )

    runtime = ensure_appimage_runtime(
        cache_dir,
        appimage_arch,
    )

    show(
        "BUILD",
        "PythoFetchUpdater.AppImage",
    )

    build_appimage(
        tool,
        runtime,
        appdir,
        appimage_output,
        appimage_arch,
        version,
    )

    extracted_env = os.environ.copy()
    extracted_env[
        "APPIMAGE_EXTRACT_AND_RUN"
    ] = "1"

    show(
        "TEST",
        "AppImage",
    )

    test_version_command(
        [
            appimage_output,
            "--version",
        ],
        appimage_output.parent,
        version,
        env=extracted_env,
    )

    show(
        "BUILD",
        zip_name,
    )

    create_zip(
        appimage_output,
        zip_output,
    )

    zip_hash = sha256_file(
        zip_output
    )

    appimage_hash = sha256_file(
        appimage_output
    )

    appimage_size = (
        appimage_output.stat().st_size
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
        f"ZIP bytes: {zip_output.stat().st_size}"
    )
    print(
        "Contained AppImage: PythoFetchUpdater.AppImage"
    )
    print(
        f"AppImage SHA-256: {appimage_hash}"
    )
    print(
        f"AppImage bytes: {appimage_size}"
    )
    print(
        f"AppImage runtime: {APPIMAGE_RUNTIME_BUILD}"
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
