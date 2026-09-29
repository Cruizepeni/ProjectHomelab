import argparse
import ctypes
import hashlib
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

PYTHOFETCH_UPDATER_VERSION = "1.0.0"
PYTHOFETCH_RELEASE_MANIFEST_URL = (
    "https://raw.githubusercontent.com/"
    "Cruizepeni/ProjectHomelab/main/"
    "Releases/PythoFetch/"
    "PythoFetch_Release_Manifest.json"
)
WAIT_TIMEOUT_SECONDS = 120
POLL_INTERVAL_SECONDS = 0.25


def version_key(value):
    parts = str(value or "").strip().split(".")

    if len(parts) != 3:
        raise RuntimeError(
            f"Invalid version value: {value}"
        )

    try:
        return tuple(
            int(part)
            for part in parts
        )
    except Exception as exc:
        raise RuntimeError(
            f"Invalid version value: {value}"
        ) from exc


def show(label, value=""):
    if value:
        print(f"[{label}] {value}")
    else:
        print(f"[{label}]")


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


def fetch_json(url):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent":
                f"PythoFetchUpdater/{PYTHOFETCH_UPDATER_VERSION}",
        },
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=30,
        ) as response:
            payload = response.read()
    except Exception as exc:
        raise RuntimeError(
            "Could not download the PythoFetch release manifest."
        ) from exc

    try:
        data = json.loads(
            payload.decode("utf-8")
        )
    except Exception as exc:
        raise RuntimeError(
            "The downloaded PythoFetch release manifest is not valid JSON."
        ) from exc

    if not isinstance(data, dict):
        raise RuntimeError(
            "The PythoFetch release manifest has an invalid root structure."
        )

    return data


def download_verified_file(
    url,
    destination,
    expected_sha256,
    expected_size,
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

    expected_hash = str(
        expected_sha256 or ""
    ).strip().lower()

    if not expected_hash:
        raise RuntimeError(
            "The release manifest does not provide a SHA-256 checksum."
        )

    try:
        required_size = int(
            expected_size
        )
    except Exception as exc:
        raise RuntimeError(
            "The release manifest contains an invalid package size."
        ) from exc

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent":
                f"PythoFetchUpdater/{PYTHOFETCH_UPDATER_VERSION}",
        },
    )

    try:
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
        except Exception as exc:
            raise RuntimeError(
                "Could not download the PythoFetch update package."
            ) from exc

        if (
            not temporary.is_file()
            or temporary.stat().st_size == 0
        ):
            raise RuntimeError(
                "The downloaded PythoFetch update package is empty."
            )

        if (
            temporary.stat().st_size
            != required_size
        ):
            raise RuntimeError(
                "The downloaded PythoFetch update package size does not match the manifest."
            )

        actual_hash = sha256_file(
            temporary
        ).lower()

        if actual_hash != expected_hash:
            raise RuntimeError(
                "The downloaded PythoFetch update package failed SHA-256 verification."
            )

        os.replace(
            temporary,
            destination,
        )

    finally:
        if temporary.exists():
            temporary.unlink()

    return destination


def detect_platform_asset():
    system = platform.system()
    machine = str(
        platform.machine() or ""
    ).strip().lower()

    if system == "Windows":
        if machine not in (
            "amd64",
            "x86_64",
            "x64",
        ):
            raise RuntimeError(
                "This updater release supports Windows x86_64 only."
            )

        return (
            "Windows_x86_64",
            "PythoFetch.exe",
            "PythoFetchTemp.exe",
        )

    if system == "Linux":
        if machine not in (
            "x86_64",
            "amd64",
            "x64",
        ):
            raise RuntimeError(
                "This updater release supports Linux x86_64 only."
            )

        return (
            "Linux_x86_64",
            "PythoFetch.AppImage",
            "PythoFetchTemp.AppImage",
        )

    raise RuntimeError(
        f"Unsupported operating system: {system}"
    )


def select_release(
    manifest,
    asset_key,
    current_version,
    requested_version=None,
):
    releases = manifest.get(
        "releases"
    )

    if not isinstance(
        releases,
        dict,
    ):
        raise RuntimeError(
            "The PythoFetch release manifest has an invalid releases object."
        )

    target_version = str(
        requested_version
        or manifest.get(
            "latest_version"
        )
        or ""
    ).strip()

    if not target_version:
        raise RuntimeError(
            "The PythoFetch release manifest does not identify a target version."
        )

    current_key = version_key(
        current_version
    )
    target_key = version_key(
        target_version
    )

    if target_key <= current_key:
        raise RuntimeError(
            "The requested PythoFetch release is not newer than the installed version."
        )

    release = releases.get(
        target_version
    )

    if not isinstance(
        release,
        dict,
    ):
        raise RuntimeError(
            f"PythoFetch release {target_version} is not present in the release manifest."
        )

    assets = release.get(
        "assets"
    )

    if not isinstance(
        assets,
        dict,
    ):
        raise RuntimeError(
            f"PythoFetch release {target_version} has no valid assets object."
        )

    asset = assets.get(
        asset_key
    )

    if not isinstance(
        asset,
        dict,
    ):
        raise RuntimeError(
            f"PythoFetch release {target_version} has no {asset_key} asset."
        )

    return target_version, asset


def validate_release_asset(
    asset,
    expected_runtime_name,
):
    filename = str(
        asset.get(
            "file"
        )
        or ""
    ).strip()

    download_url = str(
        asset.get(
            "download_url"
        )
        or ""
    ).strip()

    runtime_name = str(
        asset.get(
            "executable"
        )
        or ""
    ).strip()

    if not filename.lower().endswith(
        ".zip"
    ):
        raise RuntimeError(
            "The PythoFetch release asset is not a ZIP package."
        )

    if not download_url:
        raise RuntimeError(
            "The PythoFetch release asset does not provide a download URL."
        )

    if (
        runtime_name.casefold()
        != expected_runtime_name.casefold()
    ):
        raise RuntimeError(
            "The PythoFetch release package does not contain the expected stable runtime name."
        )

    if not str(
        asset.get(
            "sha256"
        )
        or ""
    ).strip():
        raise RuntimeError(
            "The PythoFetch release package has no SHA-256 checksum."
        )

    if asset.get(
        "size_bytes"
    ) is None:
        raise RuntimeError(
            "The PythoFetch release package has no size metadata."
        )

    if not str(
        asset.get(
            "executable_sha256"
        )
        or ""
    ).strip():
        raise RuntimeError(
            "The PythoFetch runtime has no SHA-256 checksum."
        )

    if asset.get(
        "executable_size_bytes"
    ) is None:
        raise RuntimeError(
            "The PythoFetch runtime has no size metadata."
        )

    return (
        filename,
        download_url,
        runtime_name,
    )


def process_exists_windows(pid):
    process = ctypes.windll.kernel32.OpenProcess(
        0x00100000,
        False,
        int(pid),
    )

    if not process:
        return False

    ctypes.windll.kernel32.CloseHandle(
        process
    )

    return True


def process_exists_posix(pid):
    try:
        os.kill(
            int(pid),
            0,
        )
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def process_exists(pid):
    if platform.system() == "Windows":
        return process_exists_windows(
            pid
        )

    return process_exists_posix(
        pid
    )


def wait_for_parent(pid):
    pid = int(
        pid
    )

    if pid <= 0:
        raise RuntimeError(
            "The parent process ID is invalid."
        )

    if pid == os.getpid():
        raise RuntimeError(
            "The updater cannot wait for its own process ID."
        )

    deadline = (
        time.monotonic()
        + WAIT_TIMEOUT_SECONDS
    )

    show(
        "WAIT",
        f"PythoFetch process {pid}",
    )

    while process_exists(
        pid
    ):
        if (
            time.monotonic()
            >= deadline
        ):
            raise RuntimeError(
                "Timed out waiting for PythoFetch to exit."
            )

        time.sleep(
            POLL_INTERVAL_SECONDS
        )


def ensure_target(
    target,
    expected_runtime_name,
):
    target = Path(
        target
    ).expanduser().resolve()

    if (
        target.name.casefold()
        != expected_runtime_name.casefold()
    ):
        raise RuntimeError(
            "The supplied PythoFetch target does not use the expected stable runtime filename."
        )

    if not target.parent.is_dir():
        raise RuntimeError(
            "The PythoFetch installation folder does not exist."
        )

    return target


def remove_path(path):
    path = Path(
        path
    )

    if path.is_symlink() or path.is_file():
        path.unlink()
        return

    if path.is_dir():
        shutil.rmtree(
            path
        )


def extract_runtime(
    archive_path,
    expected_runtime_name,
    destination,
    asset,
):
    archive_path = Path(
        archive_path
    )
    destination = Path(
        destination
    )

    remove_path(
        destination
    )

    try:
        with zipfile.ZipFile(
            archive_path,
            "r",
        ) as archive:
            candidates = []

            for info in archive.infolist():
                if info.is_dir():
                    continue

                normalized = (
                    info.filename
                    .replace(
                        "\\",
                        "/",
                    )
                    .strip("/")
                )

                member_name = (
                    normalized.rsplit(
                        "/",
                        1,
                    )[-1]
                )

                if (
                    member_name.casefold()
                    == expected_runtime_name.casefold()
                ):
                    unix_mode = (
                        info.external_attr
                        >> 16
                    )

                    if (
                        unix_mode
                        and stat.S_ISLNK(
                            unix_mode
                        )
                    ):
                        raise RuntimeError(
                            "The PythoFetch release archive contains an invalid symbolic-link runtime."
                        )

                    candidates.append(
                        info
                    )

            if len(
                candidates
            ) != 1:
                raise RuntimeError(
                    "The PythoFetch release archive must contain exactly one expected runtime."
                )

            selected = candidates[0]

            with archive.open(
                selected,
                "r",
            ) as source:
                with destination.open(
                    "wb"
                ) as handle:
                    shutil.copyfileobj(
                        source,
                        handle,
                    )

        expected_hash = str(
            asset.get(
                "executable_sha256"
            )
            or ""
        ).strip().lower()

        try:
            expected_size = int(
                asset.get(
                    "executable_size_bytes"
                )
            )
        except Exception as exc:
            raise RuntimeError(
                "The PythoFetch runtime size in the release manifest is invalid."
            ) from exc

        if (
            destination.stat().st_size
            != expected_size
        ):
            raise RuntimeError(
                "The extracted PythoFetch runtime size does not match the release manifest."
            )

        if (
            sha256_file(
                destination
            ).lower()
            != expected_hash
        ):
            raise RuntimeError(
                "The extracted PythoFetch runtime failed SHA-256 verification."
            )

        if platform.system() == "Linux":
            destination.chmod(
                destination.stat().st_mode
                | stat.S_IXUSR
                | stat.S_IXGRP
                | stat.S_IXOTH
            )

        return destination

    except Exception:
        remove_path(
            destination
        )
        raise


def clean_launch_environment():
    environment = os.environ.copy()

    for name in (
        "APPIMAGE",
        "APPDIR",
        "ARGV0",
        "OWD",
        "PYTHOFETCH_APPIMAGE_TERMINAL",
        "APPIMAGE_EXTRACT_AND_RUN",
    ):
        environment.pop(
            name,
            None,
        )

    environment[
        "PYINSTALLER_RESET_ENVIRONMENT"
    ] = "1"

    if platform.system() == "Linux":
        original_library_path = (
            environment.get(
                "LD_LIBRARY_PATH_ORIG"
            )
        )

        if original_library_path is None:
            environment.pop(
                "LD_LIBRARY_PATH",
                None,
            )
        else:
            environment[
                "LD_LIBRARY_PATH"
            ] = original_library_path

    return environment


def launch_application(
    target,
    arguments,
):
    command = [
        str(target),
        *[
            str(value)
            for value in arguments
        ],
    ]

    if platform.system() == "Windows":
        creation_flags = (
            getattr(
                subprocess,
                "CREATE_NEW_CONSOLE",
                0,
            )
            | getattr(
                subprocess,
                "CREATE_NEW_PROCESS_GROUP",
                0,
            )
        )

        subprocess.Popen(
            command,
            cwd=str(
                target.parent
            ),
            env=clean_launch_environment(),
            close_fds=True,
            creationflags=creation_flags,
        )

        return

    subprocess.Popen(
        command,
        cwd=str(
            target.parent
        ),
        env=clean_launch_environment(),
        close_fds=True,
        start_new_session=True,
    )


def rollback(
    target,
    temporary_target,
):
    remove_path(
        target
    )

    if Path(
        temporary_target
    ).exists():
        os.replace(
            temporary_target,
            target,
        )

        if platform.system() == "Linux":
            target.chmod(
                target.stat().st_mode
                | stat.S_IXUSR
                | stat.S_IXGRP
                | stat.S_IXOTH
            )

        return True

    return False


def parse_args():
    parser = argparse.ArgumentParser(
        prog="PythoFetchUpdater"
    )

    parser.add_argument(
        "--version",
        action="store_true",
    )

    parser.add_argument(
        "--parent-pid",
        type=int,
    )

    parser.add_argument(
        "--target",
    )

    parser.add_argument(
        "--current-version",
    )

    parser.add_argument(
        "--target-version",
    )

    parser.add_argument(
        "--release-manifest-url",
        default=PYTHOFETCH_RELEASE_MANIFEST_URL,
    )

    return parser.parse_args()


def main():
    args = parse_args()

    if args.version:
        print(
            f"PythoFetchUpdater {PYTHOFETCH_UPDATER_VERSION}"
        )
        return 0

    missing = []

    if args.parent_pid is None:
        missing.append(
            "--parent-pid"
        )

    if not args.target:
        missing.append(
            "--target"
        )

    if not args.current_version:
        missing.append(
            "--current-version"
        )

    if missing:
        raise RuntimeError(
            "Missing required updater arguments: "
            + ", ".join(
                missing
            )
        )

    asset_key, runtime_name, temporary_name = (
        detect_platform_asset()
    )

    target = ensure_target(
        args.target,
        runtime_name,
    )

    root = target.parent

    temporary_target = (
        root
        / temporary_name
    )

    if temporary_target.exists():
        raise RuntimeError(
            f"A previous update backup already exists: {temporary_target.name}"
        )

    manifest = fetch_json(
        args.release_manifest_url
    )

    target_version, asset = select_release(
        manifest,
        asset_key,
        args.current_version,
        args.target_version,
    )

    (
        package_name,
        package_url,
        expected_runtime_name,
    ) = validate_release_asset(
        asset,
        runtime_name,
    )

    archive_path = (
        root
        / (
            ".PythoFetchUpdate_"
            + target_version
            + "_"
            + asset_key
            + ".zip"
        )
    )

    staging_target = (
        root
        / (
            "."
            + runtime_name
            + ".new"
        )
    )

    renamed = False
    installed = False

    try:
        wait_for_parent(
            args.parent_pid
        )

        if not target.is_file():
            raise RuntimeError(
                f"The installed PythoFetch runtime is missing: {target.name}"
            )

        show(
            "BACKUP",
            f"{target.name} -> {temporary_target.name}",
        )

        target.rename(
            temporary_target
        )
        renamed = True

        show(
            "DOWNLOAD",
            package_name,
        )

        download_verified_file(
            package_url,
            archive_path,
            asset.get(
                "sha256"
            ),
            asset.get(
                "size_bytes"
            ),
        )

        show(
            "INSTALL",
            expected_runtime_name,
        )

        extract_runtime(
            archive_path,
            expected_runtime_name,
            staging_target,
            asset,
        )

        os.replace(
            staging_target,
            target,
        )
        installed = True

        if platform.system() == "Linux":
            target.chmod(
                target.stat().st_mode
                | stat.S_IXUSR
                | stat.S_IXGRP
                | stat.S_IXOTH
            )

        remove_path(
            archive_path
        )

        show(
            "START",
            target.name,
        )

        launch_application(
            target,
            [
                "--updated",
                "--updater-pid",
                str(
                    os.getpid()
                ),
                "--previous-version",
                str(
                    args.current_version
                ),
            ],
        )

        print(
            f"PythoFetch {target_version} installed successfully."
        )

        return 0

    except Exception:
        remove_path(
            staging_target
        )
        remove_path(
            archive_path
        )

        if renamed:
            try:
                restored = rollback(
                    target,
                    temporary_target,
                )
            except Exception:
                restored = False

            if restored:
                try:
                    show(
                        "ROLLBACK",
                        target.name,
                    )

                    launch_application(
                        target,
                        [],
                    )
                except Exception:
                    pass

        raise

    finally:
        if (
            not installed
            and staging_target.exists()
        ):
            remove_path(
                staging_target
            )


if __name__ == "__main__":
    try:
        raise SystemExit(
            main()
        )
    except KeyboardInterrupt:
        print(
            "Update cancelled.",
            file=sys.stderr,
        )
        raise SystemExit(
            130
        )
    except Exception as exc:
        print(
            "UPDATE FAILED: "
            + str(
                exc
            ),
            file=sys.stderr,
        )
        raise SystemExit(
            1
        )
