# База знаний agentctx — Google OKF

> OKF здесь используется как практический формат базы знаний: **Objective → Key Facts → Key Flows → Failure modes → Follow-ups**.  
> Цель документа — быстро передать контекст проекта человеку или агенту, который будет чинить `agentctx`.

---

## O1. Product Objective

Сделать `agentctx` kubectx-like CLI для безопасного переключения локальных Codex auth-профилей.

### Key Facts

- Активный auth Codex находится в `~/.codex/auth.json`.
- `agentctx` хранит копии auth-файлов в `~/.agentctx/profiles/<profile>/auth.json`.
- Секреты и токены нельзя печатать в stdout/stderr/logs.
- Перед переключением активный auth должен бэкапиться.
- Если текущий Codex auth обновился, он должен автоматически синхронизироваться в текущий профиль перед switch.
- UX должен быть похож на `kubectx`: минимум подкоманд, управление через позиционные аргументы и флаги.

### Key Result / Acceptance

- `agentctx` без аргументов показывает список профилей или открывает interactive selector через `fzf`.
- `agentctx <NAME>` переключает профиль.
- `agentctx -` переключает на предыдущий профиль.
- `agentctx -c` / `--current` показывает текущий профиль.
- `agentctx -d <NAME>` удаляет профиль.
- `agentctx -u` / `--unset` очищает current marker.
- `agentctx =.` сохраняет или переименовывает текущий auth в профиль с именем email из JWT.

---

## O2. Command Contract

### `agentctx`

List or interactive mode.

#### Key Facts

- Если `stdin` и `stdout` — TTY, `fzf` доступен, и `AGENTCTX_IGNORE_FZF` не задан, должен открыться interactive selector.
- Если interactive невозможен, выводится plain list.

#### Expected Output

```text
work@example.com
personal@example.com
```

---

### `agentctx <NAME>`

Switch to profile `<NAME>`.

#### Key Flow

1. Проверить имя профиля.
2. Взять lock.
3. Проверить profile auth JSON.
4. Auto-sync текущего marker profile, если active auth изменился.
5. Создать backup текущего active auth.
6. Атомарно заменить `~/.codex/auth.json`.
7. Обновить `current` и `previous` markers.

---

### `agentctx =.`

Save or rename current active auth using email from JWT.

#### Required Behavior

- Имя профиля должно быть email пользователя из JWT claim `email`.
- Пользователь не обязан передавать имя вручную.
- Если текущий auth ещё не связан с профилем — создать профиль `<jwt-email>`.
- Если текущий auth уже связан с профилем с другим именем — переименовать профиль в `<jwt-email>`.
- Если текущий профиль уже называется `<jwt-email>` — обновить сохранённый auth из active auth.

#### Example

```bash
agentctx =.
```

```text
Saved current Codex auth as profile "user@example.com".
```

---

### `agentctx <EMAIL>=.`

Same as `agentctx =.`, but validates explicit email.

#### Required Behavior

- `<EMAIL>` должен совпадать с `email` из JWT.
- Если не совпадает — ошибка, профиль не создаётся и не переименовывается.

#### Example

```bash
agentctx user@example.com=.
```

```text
Saved current Codex auth as profile "user@example.com".
```

Mismatch:

```bash
agentctx other@example.com=.
```

```text
error: profile name must match JWT email: user@example.com
```

---

### `agentctx <NEW_NAME>=<NAME>`

Rename existing profile.

#### Key Facts

- Это обычный rename и не обязан использовать JWT email.
- Если `<NEW_NAME>` уже существует — операция должна завершиться ошибкой без перезаписи.

---

## O3. JWT Email Extraction

### Objective

Надёжно получать email пользователя из JWT внутри `auth.json`.

### Key Facts

- JWT может лежать не только в верхнем ключе.
- Нужно искать рекурсивно по JSON.
- Приоритетные ключи:
  - `id_token`
  - `jwt`
  - `token`
  - `access_token`
- JWT payload декодируется как base64url без проверки подписи.
- Для имени профиля используется claim `email`.
- Email нормализуется в lowercase.

### Failure Modes

- Invalid JSON → ошибка `invalid JSON`.
- Symlink active auth → ошибка, операция запрещена.
- JWT не найден → ошибка `JWT email not found`.
- JWT найден, но claim `email` отсутствует → ошибка `JWT email not found`.
- Email невалиден как имя профиля → ошибка invalid profile name.

---

## O4. Profile Name Rules

### Key Facts

Разрешённые символы для профиля:

```text
A-Z a-z 0-9 . _ % + @ -
```

Запрещено:

- пустое имя;
- `.`;
- `..`;
- имя, начинающееся с `-`;
- legacy CRUD words:
  - `save`
  - `use`
  - `sync`
  - `backup`
  - `doctor`
  - `rename`
  - `delete`
  - `list`
  - `current`

Для email-профиля дополнительно требуется форма:

```text
local@domain.tld
```

---

## O5. Storage Model

### Paths

```text
~/.codex/auth.json
~/.agentctx/
  profiles/
    <profile>/
      auth.json
      metadata.json
  backups/
    auth-<timestamp>.json
  current
  previous
  lock
```

### Metadata

`metadata.json` не должен содержать токены.

Допустимые поля:

```json
{
  "name": "user@example.com",
  "created_at": "2026-06-25T14:30:00Z",
  "updated_at": "2026-06-25T14:30:00Z",
  "source": "~/.codex/auth.json",
  "auth_sha256": "..."
}
```

---

## O6. Security Requirements

### Must Have

- Не печатать token/JWT/auth content.
- Reject symlink для active auth и profile auth.
- Reject non-regular files.
- Валидировать JSON перед копированием.
- Atomic writes через temp file + `os.replace`.
- Permissions:
  - dirs: `0700`
  - auth/profile/backup files: `0600`
- Lock на операции save/switch/rename/delete/unset.
- Backup перед switch.

---

## O7. Interactive Mode

### Objective

Сделать UX как у `kubectx`.

### Key Facts

- `agentctx` без аргументов в interactive terminal должен открывать `fzf`.
- Выбранный профиль сразу становится активным.
- Если пользователь отменил выбор — вернуть ошибку.
- Если `fzf` недоступен или shell не interactive — показать список.

### Env

```bash
AGENTCTX_IGNORE_FZF=1
```

Отключает interactive selector.

---

## O8. Versioning / Release

### Known Issue

`pip3 install agentctx` не обновляет уже установленную версию, если пакет уже установлен.

### Correct Commands

Обновить из PyPI:

```bash
pip3 install --upgrade agentctx
```

Установить локальный build:

```bash
pip3 install --force-reinstall dist/agentctx-<version>-py3-none-any.whl
```

Опубликовать текущую версию:

```bash
poetry publish
```

Не использовать `make publish`, если версия уже поднята вручную: target дополнительно делает `poetry version minor`.

---

## O9. Current Implementation Files

### Core

- `agentctx/cli.py` — routing команд.
- `agentctx/profiles.py` — profile model operations.
- `agentctx/auth.py` — safe auth operations, JSON/JWT helpers, atomic writes.
- `agentctx/paths.py` — filesystem paths and test env overrides.
- `agentctx/errors.py` — domain exceptions.

### Tests

- `tests/test_cli.py` — CLI behavior.
- `tests/test_auth_safety.py` — security behavior.
- `tests/test_paths.py` — path overrides.

---

## O10. QA Checklist

```bash
poetry check
poetry run pytest
poetry build
```

Manual QA:

```bash
agentctx =.
agentctx -c
agentctx
agentctx other@example.com=.
agentctx user@example.com
agentctx -
agentctx -d user@example.com
agentctx -u
agentctx -V
```

---

## O11. Open Questions

1. Нужно ли полностью запретить ручные non-email profile names для rename `NEW=OLD`?
2. Нужно ли искать email не только в JWT claim `email`, но и в других полях auth JSON?
3. Нужно ли показывать текущий профиль с маркером `*` в plain list, как в старом плане?
4. Нужно ли заменить `fzf` на встроенный interactive selector, если `fzf` не установлен?
5. Нужно ли мигрировать старые профили `work`, `personal` в email-профили автоматически?
