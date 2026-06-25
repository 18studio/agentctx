"""Profile model operations for agentctx."""

import json
import os
import re
import shutil
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from agentctx import auth, paths
from agentctx.errors import InvalidProfileName, NoCurrentProfile, ProfileAlreadyExists, ProfileNotFound, UnsafeAuthFile

PROFILE_RE = re.compile(r"^[A-Za-z0-9._-]+$")
LEGACY_WORDS = {"save", "use", "sync", "backup", "doctor", "rename", "delete", "list", "current"}
UNKNOWN_ACTIVE_PROFILE = "Unknown active profile"


def validate_profile_name(name: str) -> None:
    if (
        not name
        or not PROFILE_RE.match(name)
        or name in {".", ".."}
        or name.startswith("-")
        or name in LEGACY_WORDS
    ):
        raise InvalidProfileName("invalid profile name: {0}".format(name))


def _reject_unsafe_profile_dir(name: str) -> None:
    pdir = paths.profile_dir(name)
    if pdir.is_symlink():
        raise UnsafeAuthFile("refusing to use symlink: {0}".format(pdir))
    if pdir.exists() and not pdir.is_dir():
        raise UnsafeAuthFile("not a directory: {0}".format(pdir))


def profile_exists(name: str) -> bool:
    try:
        validate_profile_name(name)
    except InvalidProfileName:
        return False
    pdir = paths.profile_dir(name)
    return (not pdir.is_symlink()) and pdir.is_dir() and paths.profile_auth_path(name).exists()


def _require_profile_locked(name: str) -> None:
    validate_profile_name(name)
    _reject_unsafe_profile_dir(name)
    if not profile_exists(name):
        raise ProfileNotFound("profile not found: {0}".format(name))
    auth.validate_auth_json(paths.profile_auth_path(name))


def _ensure_target_available(name: str) -> None:
    validate_profile_name(name)
    if paths.profile_dir(name).exists() or paths.profile_dir(name).is_symlink():
        raise ProfileAlreadyExists("profile already exists: {0}".format(name))


def list_profiles() -> List[str]:
    auth.init_storage()
    result = []
    for child in paths.profiles_dir().iterdir():
        if child.is_dir() and not child.is_symlink() and profile_exists(child.name):
            result.append(child.name)
    return sorted(result)


def _read_marker(path: Path) -> Optional[str]:
    if not path.exists() and not path.is_symlink():
        return None
    auth.reject_unsafe_existing_file(path)
    value = path.read_text(encoding="utf-8").strip()
    return value or None


def _write_marker(path: Path, name: str) -> None:
    validate_profile_name(name)
    auth.atomic_write_text(path, name + "\n", 0o600)


def _clear_marker(path: Path) -> None:
    if path.exists() or path.is_symlink():
        auth.reject_unsafe_existing_file(path)
        path.unlink()
        auth.fsync_dir(path.parent)


def get_current_marker() -> Optional[str]:
    marker = _read_marker(paths.current_file())
    return marker if marker and profile_exists(marker) else None


def get_previous_profile() -> Optional[str]:
    previous = _read_marker(paths.previous_file())
    return previous if previous and profile_exists(previous) else None


def _set_current(name: str) -> None:
    _write_marker(paths.current_file(), name)


def _set_previous(name: Optional[str]) -> None:
    if name and profile_exists(name):
        _write_marker(paths.previous_file(), name)
    else:
        _clear_marker(paths.previous_file())


def clear_current() -> None:
    with auth.lock():
        _clear_marker(paths.current_file())
        previous = _read_marker(paths.previous_file())
        if previous and not profile_exists(previous):
            _clear_marker(paths.previous_file())


def _profile_hash(name: str) -> Optional[str]:
    if not profile_exists(name):
        return None
    return auth.sha256_file(paths.profile_auth_path(name))


def detect_current_by_hash() -> Optional[str]:
    active = paths.codex_auth_path()
    if not active.exists() and not active.is_symlink():
        return None
    try:
        active_hash = auth.sha256_file(active)
    except Exception:
        return None
    matches = [name for name in list_profiles() if _profile_hash(name) == active_hash]
    return matches[0] if len(matches) == 1 else None


def get_current_profile() -> Optional[str]:
    # Marker-first: Codex can refresh auth.json, changing the hash. The marker is
    # authoritative while it points at an existing profile so auto-sync can update
    # that profile before the next switch.
    marker = get_current_marker()
    if marker:
        return marker
    return detect_current_by_hash()


def current_profile_text() -> str:
    return get_current_profile() or UNKNOWN_ACTIVE_PROFILE


def _metadata(name: str, created_at: Optional[str] = None) -> Dict[str, str]:
    now = auth.utc_now()
    return {
        "name": name,
        "created_at": created_at or now,
        "updated_at": now,
        "source": str(paths.codex_auth_path()),
        "auth_sha256": auth.sha256_file(paths.profile_auth_path(name)),
    }


def _read_created_at(name: str) -> Optional[str]:
    metadata = paths.profile_metadata_path(name)
    if not metadata.exists() and not metadata.is_symlink():
        return None
    try:
        auth.reject_unsafe_existing_file(metadata)
        value = json.loads(metadata.read_text(encoding="utf-8"))
    except Exception:
        return None
    created_at = value.get("created_at")
    return created_at if isinstance(created_at, str) else None


def _write_metadata(name: str, created_at: Optional[str] = None) -> None:
    text = json.dumps(_metadata(name, created_at=created_at), indent=2, sort_keys=True) + "\n"
    auth.atomic_write_text(paths.profile_metadata_path(name), text, 0o600)


def _save_current_as_profile_locked(name: str) -> None:
    _ensure_target_available(name)
    auth.validate_auth_json(paths.codex_auth_path())
    auth.chmod(paths.codex_auth_path(), auth.AUTH_MODE)
    auth.ensure_private_dir(paths.profile_dir(name))
    auth.copy_auth_atomic(paths.codex_auth_path(), paths.profile_auth_path(name))
    _write_metadata(name)
    _set_current(name)


def save_current_as_profile(name: str) -> None:
    with auth.lock():
        _save_current_as_profile_locked(name)


def _sync_current_marker_if_changed_locked() -> Optional[str]:
    marker = get_current_marker()
    active = paths.codex_auth_path()
    if not marker or (not active.exists() and not active.is_symlink()):
        return None
    _require_profile_locked(marker)
    active_hash = auth.sha256_file(active)
    profile_hash = auth.sha256_file(paths.profile_auth_path(marker))
    if active_hash != profile_hash:
        created_at = _read_created_at(marker)
        auth.copy_auth_atomic(active, paths.profile_auth_path(marker))
        _write_metadata(marker, created_at=created_at)
        return marker
    return None


def _switch_profile_locked(name: str) -> Optional[Path]:
    old_current = get_current_profile()
    _require_profile_locked(name)
    _sync_current_marker_if_changed_locked()

    if old_current == name:
        _set_current(name)
        return None

    backup = None
    if paths.codex_auth_path().exists() or paths.codex_auth_path().is_symlink():
        backup = auth.create_backup(paths.codex_auth_path())
    auth.copy_auth_atomic(paths.profile_auth_path(name), paths.codex_auth_path())
    if old_current and old_current != name:
        _set_previous(old_current)
    _set_current(name)
    return backup


def switch_profile(name: str) -> Optional[Path]:
    validate_profile_name(name)
    with auth.lock():
        return _switch_profile_locked(name)


def switch_previous() -> Tuple[Optional[Path], str]:
    with auth.lock():
        previous = get_previous_profile()
        if not previous:
            raise NoCurrentProfile("previous profile is not set")
        backup = _switch_profile_locked(previous)
        return backup, previous


def _rename_profile_locked(old: str, new: str) -> None:
    _require_profile_locked(old)
    _ensure_target_available(new)
    current_marker = get_current_marker()
    previous = get_previous_profile()
    created_at = _read_created_at(old)
    shutil.move(str(paths.profile_dir(old)), str(paths.profile_dir(new)))
    _write_metadata(new, created_at=created_at)
    if current_marker == old or detect_current_by_hash() == new:
        _set_current(new)
    if previous == old:
        _set_previous(new)


def rename_profile(old: str, new: str) -> None:
    validate_profile_name(new)
    with auth.lock():
        _rename_profile_locked(old, new)


def save_or_rename_current(new: str) -> str:
    validate_profile_name(new)
    with auth.lock():
        current = get_current_profile()
        if current:
            _rename_profile_locked(current, new)
            return "renamed"
        _save_current_as_profile_locked(new)
        return "saved"


def delete_profiles(requested_names: Iterable[str]) -> List[str]:
    requested = list(requested_names)
    if not requested:
        raise ProfileNotFound("profile name is required")

    with auth.lock():
        current = get_current_profile()
        resolved = []  # type: List[str]
        for requested_name in requested:
            if requested_name == ".":
                if not current:
                    raise NoCurrentProfile("current profile is not set")
                name = current
            else:
                name = requested_name
            _require_profile_locked(name)
            if name not in resolved:
                resolved.append(name)

        if current in resolved and (paths.codex_auth_path().exists() or paths.codex_auth_path().is_symlink()):
            auth.create_backup(paths.codex_auth_path())

        previous = get_previous_profile()
        for name in resolved:
            pdir = paths.profile_dir(name)
            _reject_unsafe_profile_dir(name)
            shutil.rmtree(str(pdir))
            auth.fsync_dir(paths.profiles_dir())

        if current in resolved:
            _clear_marker(paths.current_file())
        if previous in resolved:
            _clear_marker(paths.previous_file())
        return resolved


def format_profile_list(colored: bool = False) -> str:
    current = get_current_profile()
    lines = []
    current_fg = os.environ.get("KUBECTX_CURRENT_FGCOLOR", "\033[33m")
    current_bg = os.environ.get("KUBECTX_CURRENT_BGCOLOR", "\033[40m")
    normal = "\033[0m"
    for name in list_profiles():
        if colored and name == current:
            lines.append("{0}{1}{2}{3}".format(current_bg, current_fg, name, normal))
        else:
            lines.append(name)
    return "\n".join(lines)
