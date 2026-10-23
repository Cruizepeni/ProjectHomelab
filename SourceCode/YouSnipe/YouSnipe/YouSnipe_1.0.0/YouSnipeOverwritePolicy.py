
import errno
import os
from pathlib import Path


class YouSnipeFileExistsError(FileExistsError):
    code = "FILE_ALREADY_EXISTS"


def overwrite_enabled(settings: dict) -> bool:
    return bool((settings or {}).get("downloadDefaults", {}).get("overwriteExisting", False))


def assert_output_available(path: str, overwrite: bool) -> None:
    if os.path.exists(path) and not overwrite:
        raise YouSnipeFileExistsError(f"Destination file already exists: {path}")


def replace_completed_output(source_path: str, destination_path: str, overwrite: bool) -> str:
    
    if overwrite:
        os.replace(source_path, destination_path)
        return destination_path

    base = Path(destination_path)
    for index in range(1, 10001):
        destination = base if index == 1 else base.with_name(f"{base.stem} ({index}){base.suffix}")
        try:
            os.link(source_path, destination)
        except FileExistsError:
            continue
        except OSError as exc:
            
            
            
            unsupported = {getattr(errno, name) for name in
                ("EPERM", "EOPNOTSUPP", "ENOTSUP", "EXDEV", "EACCES", "ENOSYS")
                if hasattr(errno, name)}
            if exc.errno not in unsupported:
                raise
            try:
                with open(destination, "xb"):
                    pass
            except FileExistsError:
                continue
            try:
                os.replace(source_path, destination)
            except BaseException:
                os.unlink(destination)
                raise
            return str(destination)
        os.unlink(source_path)
        return str(destination)
    raise YouSnipeFileExistsError("Too many files with the same output name")
