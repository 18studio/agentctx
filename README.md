# agentctx

`agentctx` is a kubectx-like CLI for saving and switching local Codex auth profiles.

It manages copies of `~/.codex/auth.json` under `~/.agentctx` and atomically swaps the active auth file when you switch profiles. Token contents are never printed.

## Install

```bash
pipx install agentctx
```

For local development:

```bash
poetry install
poetry run agentctx --help
```

## Usage

```bash
agentctx                 # list profiles or open fzf selector when interactive
agentctx work            # switch to profile
agentctx -               # switch to previous profile
agentctx -c              # show current profile
agentctx work=.          # save current Codex auth as profile, or rename current profile
agentctx prod=work       # rename profile
agentctx -d old-profile  # delete profile
agentctx -u              # unset current marker
agentctx -V              # show version
```

Long aliases:

```bash
agentctx --current
agentctx --unset
agentctx --version
```

CRUD-style subcommands are intentionally not part of the public CLI.

## Storage

```text
~/.agentctx/
  profiles/
    <name>/
      auth.json
      metadata.json
  backups/
    auth-<timestamp>.json
  current
  previous
  lock
```

Active Codex auth remains:

```text
~/.codex/auth.json
```

## Security behavior

- validates JSON before saving or switching;
- rejects symlinks and non-regular auth files;
- writes auth files atomically with temporary files in the target directory;
- uses `0600` permissions for active, profile, and backup auth files where supported;
- creates backups before switching profiles;
- never prints token contents.

## Development

```bash
poetry check
poetry run pytest
poetry build
```

## Publish

```bash
make publish
```

`make publish` bumps the minor version, syncs `agentctx.__version__`, runs checks/tests, builds a clean `dist/`, and publishes with `poetry publish`.
