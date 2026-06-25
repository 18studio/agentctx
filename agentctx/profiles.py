"""Profile model operations for agentctx."""

import contextlib
import json
import os
import re
import shutil
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from agentctx import auth, paths
from agentctx.errors import InvalidAuthJson, InvalidProfileName, NoCurrentProfile, ProfileAlreadyExists, ProfileNotFound, UnsafeAuthFile

PROFILE_RE = re.compile(r"^[A-Za-z0-9._%+@-]+$")
EMAIL_PROFILE_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z0-9.-]+$")
LEGACY_WORDS = {"save", "use", "sync", "backup", "doctor", "rename", "delete", "list", "current", "login"}
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


def validate_jwt_email_profile_name(name: str) -> None:
    validate_profile_name(name)
    if not EMAIL_PROFILE_RE.match(name):
        raise InvalidProfileName("invalid JWT email for profile name: {0}".format(name))


def _active_auth_email_profile_name() -> str:
    name = auth.email_from_auth_jwt(paths.codex_auth_path())
    validate_jwt_email_profile_name(name)
    return name


def _reject_unsafe_profile_dir(name: str) -> None:
    pdir = paths.profile_dir(name)
    if pdir.is_symlink():
        raise UnsafeAuthFile("refusing to use symlink: {0}".format(pdir))
    if pdir.exists() and not pdir.is_dir():
        raise UnsafeAuthFile("not a directory: {0}".format(pdir))


def profile_exists(name: str) -> bool:
    try:
        validate_jwt_email_profile_name(name)
    except InvalidProfileName:
        return False
    pdir = paths.profile_dir(name)
    profile_auth = paths.profile_auth_path(name)
    if pdir.is_symlink() or not pdir.is_dir() or not profile_auth.exists():
        return False
    try:
        return auth.email_from_auth_jwt(profile_auth) == name.lower()
    except Exception:
        return False


def _require_profile_locked(name: str) -> None:
    validate_profile_name(name)
    _reject_unsafe_profile_dir(name)
    if not profile_exists(name):
        raise ProfileNotFound("profile not found: {0}".format(name))
    auth.validate_auth_json(paths.profile_auth_path(name))
    email = auth.email_from_auth_jwt(paths.profile_auth_path(name))
    if email != name.lower():
        raise InvalidAuthJson("profile JWT email does not match profile name: {0}".format(name))


def _ensure_target_available(name: str) -> None:
    validate_jwt_email_profile_name(name)
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


def _replace_symlink(path: Path, target: Path) -> None:
    if path.exists() or path.is_symlink():
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.symlink_to(target.resolve())
    auth.fsync_dir(path.parent)


def _profile_jwt_path(name: str, digest: str) -> Path:
    return paths.profile_dir(name) / "jwt-{0}.json".format(digest)


def _profile_auth_target(name: str) -> Path:
    _require_profile_locked(name)
    profile_auth = paths.profile_auth_path(name)
    if not profile_auth.is_symlink():
        # Migrate pre-symlink profile storage to immutable JWT storage lazily.
        digest = auth.sha256_file(profile_auth)
        jwt_path = _profile_jwt_path(name, digest)
        if not jwt_path.exists():
            data = auth.read_valid_auth_bytes(profile_auth)
            auth.atomic_write_bytes(jwt_path, data, 0o400)
        else:
            auth.chmod(jwt_path, 0o400)
        _replace_symlink(profile_auth, jwt_path)
    return profile_auth.resolve()


def _link_active_auth_to_profile_locked(name: str) -> None:
    target = _profile_auth_target(name)
    _replace_symlink(paths.codex_auth_path(), target)


def _store_auth_as_jwt_email_profile_locked(src: Path, link_active: bool = True) -> Tuple[str, str]:
    name = auth.email_from_auth_jwt(src)
    validate_jwt_email_profile_name(name)
    data = auth.read_valid_auth_bytes(src)
    digest = auth.sha256_file(src)

    pdir = paths.profile_dir(name)
    if pdir.is_symlink() or (pdir.exists() and not pdir.is_dir()):
        raise UnsafeAuthFile("not a directory: {0}".format(pdir))
    auth.ensure_private_dir(pdir)

    jwt_path = _profile_jwt_path(name, digest)
    if jwt_path.exists() or jwt_path.is_symlink():
        auth.reject_unsafe_existing_file(jwt_path)
        if auth.sha256_file(jwt_path) != digest:
            raise UnsafeAuthFile("refusing to overwrite JWT file: {0}".format(jwt_path))
        auth.chmod(jwt_path, 0o400)
        outcome = "updated"
    else:
        auth.atomic_write_bytes(jwt_path, data, 0o400)
        outcome = "saved" if not paths.profile_auth_path(name).exists() else "updated"

    _replace_symlink(paths.profile_auth_path(name), jwt_path)
    _write_metadata(name, created_at=_read_created_at(name))
    if link_active:
        _replace_symlink(paths.codex_auth_path(), jwt_path)
    return outcome, name


def _save_current_as_profile_locked(name: str) -> None:
    # Kept for the legacy internal API. The public save path is JWT-email based.
    validate_jwt_email_profile_name(name)
    actual = auth.email_from_auth_jwt(paths.codex_auth_path())
    if actual != name.lower():
        raise InvalidProfileName("profile name must match JWT email: {0}".format(actual))
    _store_auth_as_jwt_email_profile_locked(paths.codex_auth_path())
    _set_current(name)


def save_current_as_profile(name: str) -> None:
    with auth.lock():
        _save_current_as_profile_locked(name)


def prepare_login_auth() -> None:
    """Detach active auth before `codex login` so login cannot overwrite a profile JWT."""
    with auth.lock():
        active = paths.codex_auth_path()
        if active.exists() or active.is_symlink():
            with contextlib.suppress(Exception):
                auth.create_backup(active)
            active.unlink()
            auth.fsync_dir(active.parent)


def _switch_profile_locked(name: str) -> Optional[Path]:
    old_current = get_current_profile()
    _require_profile_locked(name)

    backup = None
    if paths.codex_auth_path().exists() or paths.codex_auth_path().is_symlink():
        backup = auth.create_backup(paths.codex_auth_path())
    _link_active_auth_to_profile_locked(name)
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
    jwt_email = auth.email_from_auth_jwt(paths.profile_auth_path(old))
    validate_jwt_email_profile_name(new)
    if new.lower() != jwt_email:
        raise InvalidProfileName("profile name must match JWT email: {0}".format(jwt_email))
    _ensure_target_available(new)
    current_marker = get_current_marker()
    previous = get_previous_profile()
    created_at = _read_created_at(old)
    shutil.move(str(paths.profile_dir(old)), str(paths.profile_dir(new)))
    auth_link = paths.profile_auth_path(new)
    if auth_link.is_symlink() and not auth_link.exists():
        jwt_files = sorted(paths.profile_dir(new).glob("jwt-*.json"))
        if jwt_files:
            _replace_symlink(auth_link, jwt_files[-1])
    _write_metadata(new, created_at=created_at)
    if current_marker == old or detect_current_by_hash() == new:
        _set_current(new)
    if previous == old:
        _set_previous(new)


def rename_profile(old: str, new: str) -> None:
    validate_jwt_email_profile_name(new)
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


def save_or_rename_current_from_jwt_email(expected_name: Optional[str] = None) -> Tuple[str, str]:
    with auth.lock():
        name = _active_auth_email_profile_name()
        if expected_name:
            validate_jwt_email_profile_name(expected_name)
            if expected_name.lower() != name:
                raise InvalidProfileName(
                    "profile name must match JWT email: {0}".format(name)
                )
        previous = get_current_marker()
        outcome, name = _store_auth_as_jwt_email_profile_locked(paths.codex_auth_path())
        if previous and previous != name:
            _set_previous(previous)
        _set_current(name)
        return outcome, name


def save_login_auth_from_jwt_email() -> Tuple[str, str]:
    """Save freshly logged-in active auth as an immutable JWT-email profile."""
    with auth.lock():
        previous = get_current_marker()
        outcome, name = _store_auth_as_jwt_email_profile_locked(paths.codex_auth_path())
        if previous and previous != name:
            _set_previous(previous)
        _set_current(name)
        return outcome, name


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
            if paths.codex_auth_path().is_symlink():
                paths.codex_auth_path().unlink()
                auth.fsync_dir(paths.codex_auth_path().parent)

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
