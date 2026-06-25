# Action plan: `agentctx` как kubectx для Codex auth-профилей

## Review текущего `plan.md`

Текущий план слишком похож на обычный CRUD CLI и расходится с референсом `kubectx`.
Главная проблема: в MVP попали лишние пользовательские команды:

```text
list current save use sync delete rename backup doctor
```

Для `kubectx` важна не внутренняя модель, а UX:

- без подкоманд для частых операций;
- `agentctx` без аргументов показывает список;
- `agentctx <NAME>` переключает профиль;
- `agentctx -` возвращает предыдущий профиль;
- операции rename/delete/current/unset оформлены флагами или специальным синтаксисом, а не отдельными глаголами.

Поэтому `agentctx` должен не изобретать новый интерфейс, а повторять surface area kubectx настолько близко, насколько это безопасно для `~/.codex/auth.json`.

Использован Context7: `/ahmetb/kubectx`. По документации kubectx поддерживает позиционное переключение, `-` для предыдущего контекста, rename через `NEW=OLD`, interactive/fzf mode и минимальный CLI без CRUD-подкоманд.

---

## Цель MVP

Сделать CLI `agentctx`, который управляет локальными Codex auth-профилями в стиле `kubectx`.

Источник истины активной Codex-сессии:

```text
~/.codex/auth.json
```

Хранилище профилей `agentctx`:

```text
~/.agentctx/
  profiles/
    work/
      auth.json
      metadata.json
    personal/
      auth.json
      metadata.json
  backups/
    auth-2026-06-25T14-30-00Z.json
  current
  previous
  lock
```

Секреты никогда не печатаются.

---

## CLI contract: как kubectx

Итоговая справка должна быть близка к kubectx:

```text
Manage and switch between Codex auth profiles.

USAGE:
  agentctx                       : list the profiles
  agentctx <NAME>                : switch to profile <NAME>
  agentctx -                     : switch to the previous profile
  agentctx -c, --current         : show the current profile name
  agentctx -u, --unset           : unset the current profile
  agentctx <NEW_NAME>=<NAME>     : rename profile <NAME> to <NEW_NAME>
  agentctx <NEW_NAME>=.          : save or rename current active auth to <NEW_NAME>
  agentctx -d <NAME> [<NAME...>] : delete profile <NAME> ('.' for current profile)
  agentctx -h, --help            : show this message
  agentctx -V, --version         : show version
```

### Не добавлять в MVP как публичные команды

Эти команды из старого плана убрать из пользовательского API:

```text
save
use
sync
backup
doctor
rename
delete
list
current
```

Причина: они дублируют kubectx-стиль и создают «много лишних команд».

Public CLI должен явно reject-ить эти legacy CRUD words как unsupported subcommands, а не пытаться обрабатывать их как старый API. Чтобы поведение было однозначным, эти слова зарезервированы и не могут быть именами профилей.

Внутри проекта могут быть функции `save_profile`, `switch_profile`, `create_backup`, но пользовательский CLI должен оставаться kubectx-like.

---

## Поведение команд

### `agentctx`

Поведение повторяет kubectx/fzf:

- если stdin и stdout являются TTY, `fzf` доступен в `PATH`, и env `AGENTCTX_IGNORE_FZF` не равен `1`, открыть interactive selector; выбранный профиль сразу становится active profile;
- если stdin/stdout не TTY, `fzf` недоступен или interactive mode отключён через env, показать простой список профилей по алфавиту.

Простой list output:

```text
* personal
  test-account
  work
```

`*` означает текущий активный профиль по marker/hash rules ниже.

---

### `agentctx <NAME>`

Переключает активный Codex auth на профиль `<NAME>`.

Пример:

```bash
agentctx personal
```

Вывод:

```text
Switched to profile "personal".
```

Flow:

1. Проверить синтаксис имени профиля.
2. Взять lock.
3. Проверить внутри lock, что профиль существует и его `auth.json` безопасный/валидный.
4. Если `current` marker указывает на существующий профиль и активный `~/.codex/auth.json` изменился — автоматически сохранить обновлённый auth обратно в этот current profile.
5. Создать backup текущего `~/.codex/auth.json`, если файл существует.
6. Атомарно заменить `~/.codex/auth.json` выбранным profile auth.
7. Записать `previous` и `current`.
8. Отпустить lock.

Важно: отдельной команды `sync` не нужно. Обновления токенов сохраняются автоматически перед переключением.

---

### `agentctx -`

Переключает на предыдущий профиль.

```bash
agentctx -
```

Вывод:

```text
Switched to profile "work".
```

Если предыдущего профиля нет:

```text
error: previous profile is not set
```

---

### `agentctx -c`, `agentctx --current`

Показывает текущий профиль.

```bash
agentctx -c
```

Вывод:

```text
work
```

Current semantics:

1. Если `~/.agentctx/current` указывает на существующий профиль, этот marker считается источником текущего профиля даже если hash активного `~/.codex/auth.json` уже изменился после refresh токена Codex. Это нужно, чтобы auto-sync мог сохранить обновлённый auth обратно в правильный профиль перед следующим switch.
2. Если marker отсутствует или stale, `agentctx` пробует hash-detection: сравнивает active auth с сохранёнными profile auth files.
3. Если ни marker, ни hash-detection не дают профиль, выводится:

```text
Unknown active profile
```

---

### `agentctx <NEW_NAME>=<NAME>`

Переименовывает профиль `<NAME>` в `<NEW_NAME>`.

```bash
agentctx prod=work
```

Вывод:

```text
Profile "work" renamed to "prod".
```

Если переименован текущий профиль, marker `current` обновляется.
Если переименован previous профиль, marker `previous` обновляется.
Если `<NEW_NAME>` уже существует, операция должна завершиться ошибкой и ничего не перезаписывать.

---

### `agentctx <NEW_NAME>=.`

Поведение адаптирует kubectx `NEW_NAME=.` под Codex auth.

Если `current` marker указывает на существующий профиль или active auth соответствует сохранённому профилю по hash:

- переименовать этот текущий профиль в `<NEW_NAME>`;
- обновить markers `current` и `previous`, если они указывали на старое имя.

Если active `~/.codex/auth.json` не связан ни с одним профилем:

- сохранить текущий `~/.codex/auth.json` как новый профиль `<NEW_NAME>`;
- сделать `<NEW_NAME>` текущим.

Если `<NEW_NAME>` уже существует, операция должна завершиться ошибкой и не перезаписывать существующий профиль.

Это заменяет старую команду:

```text
agentctx save <name>
```

Пример:

```bash
agentctx work=.
```

Вывод для нового профиля:

```text
Saved current Codex auth as profile "work".
```

---

### `agentctx -d <NAME> [<NAME...>]`

Удаляет один или несколько профилей.

```bash
agentctx -d old test
```

Вывод:

```text
Deleted profile "old".
Deleted profile "test".
```

`agentctx -d .` удаляет текущий профиль.

Удаление профиля не должно удалять backup-и и не должно печатать содержимое auth.

Если удаляется текущий профиль:

1. Сначала создать backup активного `~/.codex/auth.json`.
2. Удалить profile dir.
3. Очистить marker `current`.
4. Если удалённый профиль был записан в `previous`, очистить marker `previous`.
5. Оставить активный `~/.codex/auth.json` на месте, если он всё ещё валиден.

Если удаляется не-current профиль, но он записан в `previous`, marker `previous` тоже очищается.

Это ближе к kubectx: delete удаляет context entry, но не обязательно разрушает связанные сущности.

---

### `agentctx -u`, `agentctx --unset`

Сбрасывает текущий marker `current` без удаления профилей.

MVP-поведение:

- не удалять `~/.codex/auth.json`;
- не менять auth-файл;
- очистить `~/.agentctx/current`;
- сохранить `previous` как есть или очистить, если он указывает на несуществующий профиль.

Вывод:

```text
Unset current profile.
```

Почему так: для Codex удаление `auth.json` слишком разрушительно. В отличие от kubeconfig current-context, `auth.json` содержит реальные credentials.

---

### `agentctx -h`, `agentctx --help`

Показывает kubectx-like usage.

---

### `agentctx -V`, `agentctx --version`

Показывает версию пакета.

```text
agentctx 0.1.0
```

---

## Отложить после MVP

Эти пункты не должны попадать в текущий публичный API, чтобы не раздувать CLI:

### `-s`, `--shell`

В kubectx это shell scoped to context. Для Codex безопасная реализация зависит от того, можно ли запустить Codex с альтернативным home/config/auth path.

До подтверждения механизма не добавлять флаг в MVP.

### `-r`, `--readonly`

Read-only shell для Codex auth-профиля не имеет очевидного безопасного аналога в MVP.

Отложить.

### `doctor`

Полезно для разработки, но это лишняя публичная команда для kubectx-like MVP.

Если нужен debug, добавить позже как скрытый или advanced subcommand, но не в основной help.

### `backup`

Backup должен быть автоматическим внутренним механизмом, а не пользовательской командой MVP.

### `sync`

Sync должен быть автоматическим только перед switch, а не отдельной командой MVP. Rename/delete/unset не выполняют implicit sync, кроме явно описанных backup/marker updates.

---

## Storage layout

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

### `metadata.json`

```json
{
  "name": "work",
  "created_at": "2026-06-25T14:30:00Z",
  "updated_at": "2026-06-25T14:30:00Z",
  "source": "~/.codex/auth.json",
  "auth_sha256": "..."
}
```

Секреты в metadata хранить нельзя.

`auth_sha256` нужен для fallback hash-detection и для понимания, что active auth изменился после token refresh. Это hash файла, не токен. Current marker остаётся authoritative, пока указывает на существующий профиль.

---

## Profile name validation

Разрешённые имена:

```text
[a-zA-Z0-9._-]+
```

Reject:

- пустое имя;
- `/` и path separators;
- `.` и `..`;
- whitespace;
- любое имя, начинающееся с `-`, потому что `agentctx -` и flags зарезервированы;
- legacy CRUD words `save`, `use`, `sync`, `backup`, `doctor`, `rename`, `delete`, `list`, `current`.

`.` разрешён только как специальный operand в `agentctx <NEW_NAME>=.` и `agentctx -d .`; он не является именем профиля.

---

## Security requirements

Реализация должна:

1. Никогда не печатать содержимое `auth.json`.
2. Никогда не логировать токены.
3. Валидировать JSON перед сохранением или переключением.
4. Reject invalid JSON.
5. Reject symlink для active auth и profile auth files.
6. Reject non-regular files.
7. Использовать temp file в той же директории, что и target.
8. Выставлять `chmod 0600` до replacement.
9. Использовать `os.replace` для atomic replacement.
10. Создавать backup перед переключением.
11. Сохранять старый auth при ошибке replacement.
12. Использовать lock file во время операций switch/save-current/delete/rename/unset.
13. Не использовать symlink для `~/.codex/auth.json`, потому что Codex может перезаписывать файл и ломать связь.

Обязательные permissions:

```text
~/.agentctx                  0700
~/.agentctx/profiles         0700
~/.agentctx/backups          0700
profile auth.json files      0600
backup auth.json files       0600
~/.codex/auth.json           0600
```

На платформах без POSIX permissions тесты должны быть условными.

---

## Internal module plan

Публичный CLI kubectx-like, но внутри можно использовать понятные функции.

```text
agentctx/
  __init__.py
  cli.py        # argparse + kubectx-like routing
  paths.py      # paths + env overrides
  auth.py       # safe auth file operations
  profiles.py   # profile model operations
  errors.py     # domain exceptions
```

### `paths.py`

Env overrides для тестов:

```bash
AGENTCTX_HOME=/tmp/agentctx
AGENTCTX_CODEX_HOME=/tmp/codex
```

### `auth.py`

Отвечает за:

- JSON validation;
- symlink/non-regular rejection;
- atomic write;
- backup creation;
- chmod;
- fsync там, где поддерживается;
- lock handling.

### `profiles.py`

Внутренние функции:

```python
list_profiles()
switch_profile(name)
switch_previous()
current_profile()
rename_profile(old, new)
save_current_as_profile(name)
delete_profiles(names)
unset_current()
```

Важно: эти функции не диктуют CLI-команды. CLI остаётся kubectx-like.

### `cli.py`

Routing:

```text
no args              -> list
NAME                 -> switch
-                    -> switch_previous
-c / --current       -> current
-u / --unset         -> unset
NEW=OLD              -> rename
NEW=.                -> save current or rename current
-d names...          -> delete
-h / --help          -> help
-V / --version       -> version
```

---

## Package changes

Обновить `pyproject.toml`:

```toml
version = "0.1.0"

[tool.poetry.scripts]
agentctx = "agentctx.cli:main"
```

Исправить metadata inconsistency:

- оставить `python = "^3.8"`;
- удалить classifier `Programming Language :: Python :: 3.7`.

Обновить description:

```toml
description = "kubectx-like CLI for switching Codex auth profiles"
```

---

## Tests

Добавить `pytest` dev dependency.

Тесты должны проверять kubectx-like UX, а не старые subcommands.

```text
tests/
  test_cli.py
  test_paths.py
  test_profiles.py
  test_auth_safety.py
```

Required cases:

### CLI routing

- `agentctx` lists profiles when non-TTY, `fzf` is unavailable, or `AGENTCTX_IGNORE_FZF=1`;
- `agentctx` opens fzf selector and switches selected profile when stdin/stdout are TTY and fzf is available;
- `agentctx work` switches profile;
- `agentctx -` switches previous profile;
- `agentctx -c` prints current profile;
- `agentctx --current` prints current profile;
- `agentctx work=.` saves current auth as profile if unknown;
- `agentctx work=.` renames the known current profile and updates `current`/`previous` markers when active auth is already linked to a profile;
- `agentctx prod=work` renames profile;
- rename/save via `NEW=...` fail without clobbering when target name already exists;
- `agentctx -d work` deletes profile;
- `agentctx -d old test` deletes multiple profiles;
- `agentctx -d .` deletes current profile;
- delete clears `previous` when the deleted profile was previous;
- `agentctx -u` unsets current marker;
- `agentctx --unset` unsets current marker;
- `agentctx -V` prints version;
- `agentctx --version` prints version;
- legacy CRUD subcommands `save`, `use`, `sync`, `backup`, `doctor`, `rename`, `delete`, `list`, `current` are rejected/not supported as subcommands and are not documented.

### Switching

- switch takes lock before checking mutable filesystem state;
- switch replaces current `~/.codex/auth.json`;
- switch creates backup internally;
- switch updates `current` and `previous`;
- switch rejects missing profile;
- switch rejects invalid profile auth;
- switch preserves old auth if replacement fails.

### Current detection and auto-sync

- `current` marker is trusted while it points to an existing profile, even when active auth hash differs after token refresh;
- hash detection is used only when marker is absent or stale;
- `agentctx -c` prints `Unknown active profile` only when neither marker nor hash detection identifies a profile;
- if active auth changed while current profile is selected, `agentctx other` saves updated auth into current profile before switching;
- auto-sync is required before switch only;
- no token content appears in output.

### Security

- invalid JSON rejected;
- symlink profile auth rejected;
- symlink active auth rejected;
- non-regular file rejected;
- permissions are `0600` for active, profile, and backup auth files where supported;
- output does not contain token strings.

---

## QA commands

```bash
poetry check
poetry run pytest
poetry build
```

Manual QA:

```bash
poetry install
poetry run agentctx work=.
poetry run agentctx
poetry run agentctx -c
poetry run agentctx personal
poetry run agentctx -
poetry run agentctx prod=work
poetry run agentctx -d prod
poetry run agentctx -u
```

---

## README updates

README должен показывать именно kubectx-like UX:

````markdown
## Usage

```bash
agentctx                 # list profiles or open fzf selector when interactive
agentctx work            # switch to profile
agentctx -               # switch to previous profile
agentctx -c              # show current profile
agentctx work=.          # save current Codex auth as profile
agentctx prod=work       # rename profile
agentctx -d old-profile  # delete profile
agentctx -u              # unset current marker
```
````

Не добавлять в README legacy CRUD subcommands `save/use/sync/backup/doctor/rename/delete/list/current`.

---

## CHANGELOG.md

```markdown
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
```

---

## Definition of Done

MVP готов, когда:

- `poetry run agentctx` показывает профили или открывает fzf selector при interactive TTY;
- `poetry run agentctx work=.` сохраняет текущий `~/.codex/auth.json` как профиль, если active auth неизвестен;
- `poetry run agentctx work=.` переименовывает known current profile и обновляет markers `current`/`previous`, если active auth уже связан с профилем;
- `poetry run agentctx work` безопасно переключает auth;
- `poetry run agentctx -` возвращает предыдущий профиль;
- `poetry run agentctx -c` показывает current marker profile, hash-detected profile или `Unknown active profile`;
- `poetry run agentctx prod=work` переименовывает профиль;
- `poetry run agentctx -d prod` удаляет профиль;
- `poetry run agentctx -d old test` удаляет несколько профилей;
- `poetry run agentctx -u` и `poetry run agentctx --unset` очищают current marker;
- `poetry run agentctx -V` и `poetry run agentctx --version` показывают версию;
- backup создаётся автоматически перед switch и имеет permissions `0600` where supported;
- обновлённый активный auth автоматически синхронизируется в текущий профиль перед switch only;
- invalid JSON rejected;
- symlinks and non-regular files rejected;
- auth files written with `0600` where supported;
- token contents are never printed;
- README содержит только kubectx-like команды и не содержит legacy CRUD subcommands;
- tests pass.
