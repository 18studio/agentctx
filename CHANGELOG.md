# Changelog

## 0.1.0

### Added

- Kubectx-like CLI entrypoint `agentctx`.
- Profile listing via `agentctx`.
- Profile switching via `agentctx <NAME>`.
- Previous profile switch via `agentctx -`.
- Current profile display via `agentctx -c` / `--current`.
- Profile save/rename via `agentctx <NEW_NAME>=.` and `agentctx <NEW_NAME>=<NAME>`.
- Profile deletion via `agentctx -d`.
- Current marker unset via `agentctx -u` / `--unset`.
- Local profile storage in `~/.agentctx`.
- Atomic replacement of `~/.codex/auth.json`.
- Automatic backups before profile switch.
- Automatic sync of updated active auth before switch.
- JSON validation and restrictive permissions.
