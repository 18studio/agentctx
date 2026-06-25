# agentctx

`agentctx` is a kubectx-like CLI for saving and switching local Codex auth profiles.

It stores immutable JWT auth files under `~/.agentctx` and switches `~/.codex/auth.json` by recreating a symlink to the selected profile JWT. Profile names are derived from the user's email claim in the JWT. Token contents are never printed.

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
agentctx user@example.com # switch to profile
agentctx login           # run Codex browser login and save auth as JWT email profile
agentctx -               # switch to previous profile
agentctx -c              # show current profile
agentctx =.              # save current Codex auth as JWT email profile
agentctx user@example.com=. # same, but validate name matches JWT email
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
    <email>/
      auth.json          # symlink to the current immutable JWT file
      jwt-<sha256>.json  # immutable JWT auth file
      metadata.json
  backups/
    auth-<timestamp>.json
  current
  previous
  lock
```

Active Codex auth is a symlink:

```text
~/.codex/auth.json -> ~/.agentctx/profiles/<email>/jwt-<sha256>.json
```

## Security behavior

- validates JSON before saving or switching;
- uses symlinks for profile switching instead of copying JWTs over each other;
- writes immutable JWT files atomically with temporary files in the target directory;
- uses read-only profile JWT files and `0600` backup files where supported;
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
