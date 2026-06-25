"""Safe operations for Codex auth.json files."""

import contextlib
import datetime as _dt
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Iterator, Optional

from agentctx import paths
from agentctx.errors import InvalidAuthJson, LockError, UnsafeAuthFile

DIR_MODE = 0o700
AUTH_MODE = 0o600


def utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def safe_timestamp() -> str:
    return utc_now().replace(":", "-")


def chmod(path: Path, mode: int) -> None:
    try:
        os.chmod(str(path), mode)
    except (AttributeError, NotImplementedError, PermissionError):
        return


def ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    chmod(path, DIR_MODE)


def init_storage() -> None:
    ensure_private_dir(paths.agentctx_home())
    ensure_private_dir(paths.profiles_dir())
    ensure_private_dir(paths.backups_dir())


def reject_unsafe_existing_file(path: Path) -> None:
    if path.is_symlink():
        raise UnsafeAuthFile("refusing to use symlink: {0}".format(path))
    if not path.exists():
        raise FileNotFoundError("file not found: {0}".format(path))
    if not path.is_file():
        raise UnsafeAuthFile("not a regular file: {0}".format(path))


def reject_unsafe_target(path: Path) -> None:
    if path.exists() or path.is_symlink():
        reject_unsafe_existing_file(path)


def read_valid_auth_bytes(path: Path) -> bytes:
    reject_unsafe_existing_file(path)
    data = path.read_bytes()
    try:
        json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidAuthJson("invalid JSON in {0}".format(path)) from exc
    return data


def validate_auth_json(path: Path) -> None:
    read_valid_auth_bytes(path)


def sha256_file(path: Path) -> str:
    reject_unsafe_existing_file(path)
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fsync_dir(path: Path) -> None:
    if not hasattr(os, "O_DIRECTORY"):
        return
    try:
        fd = os.open(str(path), os.O_RDONLY | os.O_DIRECTORY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def atomic_write_bytes(dst: Path, data: bytes, mode: int = AUTH_MODE) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    reject_unsafe_target(dst)

    fd = None  # type: Optional[int]
    tmp_name = None  # type: Optional[str]
    try:
        fd, tmp_name = tempfile.mkstemp(prefix=".{0}.".format(dst.name), suffix=".tmp", dir=str(dst.parent))
        tmp_path = Path(tmp_name)
        chmod(tmp_path, mode)
        with os.fdopen(fd, "wb") as fh:
            fd = None
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, str(dst))
        tmp_name = None
        chmod(dst, mode)
        fsync_dir(dst.parent)
    finally:
        if fd is not None:
            os.close(fd)
        if tmp_name is not None:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(tmp_name)


def atomic_write_text(dst: Path, text: str, mode: int = AUTH_MODE) -> None:
    atomic_write_bytes(dst, text.encode("utf-8"), mode)


def copy_auth_atomic(src: Path, dst: Path) -> None:
    data = read_valid_auth_bytes(src)
    atomic_write_bytes(dst, data, AUTH_MODE)


def create_backup(src: Path) -> Path:
    data = read_valid_auth_bytes(src)
    ensure_private_dir(paths.backups_dir())
    timestamp = safe_timestamp()
    target = paths.backups_dir() / "auth-{0}.json".format(timestamp)
    counter = 1
    while target.exists():
        target = paths.backups_dir() / "auth-{0}-{1}.json".format(timestamp, counter)
        counter += 1
    atomic_write_bytes(target, data, AUTH_MODE)
    return target


@contextlib.contextmanager
def lock() -> Iterator[None]:
    init_storage()
    lock_path = paths.lock_file()
    try:
        fd = os.open(str(lock_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, AUTH_MODE)
    except FileExistsError as exc:
        raise LockError("another agentctx operation is running: {0}".format(lock_path)) from exc

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"pid": os.getpid(), "created_at": utc_now()}, fh)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        yield
    finally:
        with contextlib.suppress(FileNotFoundError):
            lock_path.unlink()
        fsync_dir(lock_path.parent)
