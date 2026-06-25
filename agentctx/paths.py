"""Filesystem paths for agentctx.

Environment overrides are intentionally small and primarily intended for tests:

- AGENTCTX_HOME: storage for agentctx profiles (default: ~/.agentctx)
- AGENTCTX_CODEX_HOME: Codex home containing auth.json (default: ~/.codex)
"""

import os
from pathlib import Path


def agentctx_home() -> Path:
    return Path(os.environ.get("AGENTCTX_HOME", "~/.agentctx")).expanduser()


def codex_home() -> Path:
    return Path(os.environ.get("AGENTCTX_CODEX_HOME", "~/.codex")).expanduser()


def codex_auth_path() -> Path:
    return codex_home() / "auth.json"


def profiles_dir() -> Path:
    return agentctx_home() / "profiles"


def profile_dir(name: str) -> Path:
    return profiles_dir() / name


def profile_auth_path(name: str) -> Path:
    return profile_dir(name) / "auth.json"


def profile_metadata_path(name: str) -> Path:
    return profile_dir(name) / "metadata.json"


def backups_dir() -> Path:
    return agentctx_home() / "backups"


def current_file() -> Path:
    return agentctx_home() / "current"


def previous_file() -> Path:
    return agentctx_home() / "previous"


def lock_file() -> Path:
    return agentctx_home() / "lock"
