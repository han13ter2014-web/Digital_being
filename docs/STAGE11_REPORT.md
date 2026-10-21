# Этап 11 — отчёт: approval для опасных действий

**Дата:** 2026-10-21.
**Статус:** готово; approval выключен по умолчанию (`off`), поведение
этапов 7–10 сохранено.

## 1. Цель этапа

После этапа 10 агент умел получать план от локальной LLM, но любой
валидный план сразу исполнялся. `write_file` мог перезаписать файл, а
`set_self_model` — изменить самоописание без отдельного решения
пользователя. Нужен был барьер, который:

* стоит **до** первого действия и до `task.start`;
* применяется к любому источнику плана — эвристике, явному
  `metadata.plan` или LLM;
* хранит pending approval в SQLite, а не только в памяти процесса;
* позволяет approve/reject из трей-чата;
* не ломает существующее поведение по умолчанию;
* не даёт повторно исполнить один и тот же approval.

Этап не добавляет новых опасных возможностей (удаление, запуск кода,
сеть). Он вводит политику для уже существующих действий.

## 2. Что сделано

### 2.1. `ApprovalPolicy`

Новый `src/delamain/approval.py`:

* `VALID_APPROVAL_MODES = ("off", "dangerous", "all")`;
* `normalize_approval_mode()` возвращает режим и ошибку; при некорректном
  явном значении подсистема использует `dangerous` (fail closed);
* `ApprovalPolicy.bind_registry()` получает live `ActionRegistry`;
* `evaluate(requests)` возвращает `(requires_approval,
  dangerous_action_names)`.

Правила:

| Режим | Approval нужен |
|---|---|
| `off` | никогда |
| `dangerous` | если есть действие с `dangerous=True` |
| `all` | если есть хотя бы одно известное действие |

Неизвестные действия не создают approval: они не могут выполниться и
получают обычную ошибку `unknown action`. Это не ослабляет защиту,
потому что план останавливается на таком шаге.

`write_file` и `set_self_model` помечены `dangerous=True`. `read_file`,
`search_files`, память и цели пока не считаются опасными.

### 2.2. Хранение approvals

В `MemoryStore._init_schema()` добавлена таблица:

```sql
CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    decided_at TEXT,
    consumed_at TEXT,
    task_id TEXT NOT NULL,
    goal_id INTEGER,
    title TEXT NOT NULL DEFAULT '',
    task TEXT NOT NULL DEFAULT '',
    plan_json TEXT NOT NULL,
    dangerous_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'pending',
    reason TEXT,
    meta_json TEXT NOT NULL DEFAULT '{}'
);
```

Методы:

* `create_approval()` — pending-запись с нормализованным планом;
* `get_approval()`, `list_approvals(status=...)`;
* `update_approval()` — привязка к цели и merge audit-metadata;
* `approve_approval()` — только `pending → approved`;
* `reject_approval()` — `pending|approved → rejected` с причиной;
* `consume_approval()` — атомарно `approved → consumed`;
* `count_approvals()`;
* `get_goal()` — нужен для завершения связанной цели после approve/reject.

Статус `consumed` означает, что план уже передан на исполнение и не может
быть использован повторно.

### 2.3. Runtime preflight

`DelamainRuntime.run_task()` переработан:

1. `task_id` создаётся;
2. план получается от planner или принимается явно;
3. **весь** план нормализуется;
4. `ApprovalPolicy.evaluate()` проверяет план;
5. если approval нужен — создаётся pending-запись, пишется эпизод
   `approval.requested`, возвращается `TaskResult` с `pending_approval`;
6. иначе пишется `task.start` и начинается исполнение.

Ключевые свойства:

* при pending approval нет ни одного `ActionResult`, ни одного действия и
  ни `task.start`;
* в `TaskResult` добавлены `pending_approval` и `approval_id`;
* `run_approved(id)` загружает сохранённый план, проверяет статус
  `approved`, атомарно вызывает `consume_approval()` и только затем
  выполняет шаги;
* повторный `run_approved(id)` возвращает ошибку, а не повторяет действие;
* ошибка планирования/невалидный план теперь тоже не создаёт
  `task.start`, потому что preflight идёт раньше записи начала задачи.

Ошибка `unknown action` остаётся ошибкой исполнения, как раньше.

### 2.4. Подсистема и цели

`DelamainSubsystem` получила:

* параметр `approval_mode`;
* env/config `DELAMAIN_APPROVAL_MODE`;
* `list_approvals()`, `approve()`, `reject()`;
* `status()["approval"]` с режимом, ошибкой конфигурации и счётчиками
  `pending/approved/rejected/consumed`.

Поведение целей:

* если runtime вернул `pending_approval`, цель остаётся `pending`;
* `attempts` не увеличивается, failure в `skills` не пишется;
* approval привязывается к цели (`goal_id`, `title`);
* следующие tick'и не создают второй approval для той же цели;
* `/delamain approve` выполняет сохранённый план и завершает цель обычным
  путём: `done` + skill success, либо retry/failed при ошибке действия;
* `/delamain reject` переводит связанную цель в `failed` без skill-failure.

Если процесс перезапустился после approve, но до исполнения, следующий
tick увидит `approved` и выполнит план. Pending approval переживает
перезапуск, потому что хранится в SQLite.

### 2.5. Команды и статус

В `/delamain` добавлены:

```text
/delamain approvals [status]
/delamain approve <id>
/delamain reject <id> [причина]
```

`/delamain status` показывает режим approval и число pending.
`/delamain goals` показывает `approval=<id>` у ожидающей цели.
`/delamain run` при опасном плане печатает `⏸` и подсказывает approve/reject.

### 2.6. CLI и конфигурация

CLI:

```text
python -m src.delamain --approval-mode dangerous --task "..."
```

CLI только создаёт pending approval; approve/reject выполняются в
трей-чате. Это сделано намеренно: предпросмотр и решение пользователя не
смешиваются в одну команду.

Конфигурация:

```python
DELAMAIN_APPROVAL_MODE = "off"  # off | dangerous | all
```

Env имеет приоритет. Некорректное значение трактуется как `dangerous`,
чтобы опечатка не отключала защиту.

## 3. Поведение

| Сценарий | Результат |
|---|---|
| `off`, любой план | выполняется как на этапе 10 |
| `dangerous`, план только из read/search/memory | выполняется сразу |
| `dangerous`, есть `write_file`/`set_self_model` | pending approval, действий нет |
| `all`, любое известное действие | pending approval |
| approve | план выполняется один раз, статус `consumed` |
| повторный approve | ошибка, действий нет |
| reject | план не выполняется, цель `failed` |
| pending approval у цели | цель остаётся `pending`, второй approval не создаётся |
| перезапуск процесса | pending/approved approval сохраняются |
| неизвестный action | обычная ошибка, approval не создаётся |

## 4. Проверки

### 4.1. Целевые тесты

```text
python -m pytest tests/test_delamain_approval.py tests/test_delamain_runtime.py tests/test_delamain_subsystem.py tests/test_delamain_memory.py tests/test_delamain_planner.py tests/test_delamain_llm_planner.py -q
55 passed
```

Новый файл `tests/test_delamain_approval.py` содержит 12 тестов:

1. `write_file`/`set_self_model` помечены dangerous, `off` работает как
   раньше;
2. опасный план не выполняет действия и не пишет `task.start`;
3. approve выполняет план ровно один раз;
4. reject предотвращает выполнение;
5. `all` требует approval даже для чтения;
6. план planner/LLM проходит тот же preflight;
7. pending approval переживает перезапуск runtime;
8. цель ждёт approval и завершается после approve;
9. reject завершает цель как failed без skill-failure;
10. некорректный режим fail-closed;
11. команды `/delamain approvals|approve|reject` в `AgentRunner`;
12. неизвестный approval id даёт понятную ошибку.

### 4.2. Регрессионный срез

```text
python -m pytest tests/test_integration.py tests/test_delamain_memory.py tests/test_delamain_planner.py tests/test_delamain_runtime.py tests/test_delamain_sandbox.py tests/test_delamain_llm_planner.py tests/test_delamain_approval.py tests/test_delamain_subsystem.py -q
84 passed
```

### 4.3. Полный набор тестов

```text
python -m pytest -q
496 passed, 2 skipped in 496.94s (0:08:16, включая benchmarks)
```

Это 484 теста этапа 10 плюс 12 новых тестов этапа 11.

### 4.4. Гигиена и ссылки

```text
python -m compileall -q src tests config
python tools/hygiene_scan.py --path src/delamain --path config/simulation_config.py --path src/core/agent_runner.py --path tests/test_delamain_approval.py --path tests/test_delamain_subsystem.py
15 проверок; проблем: 0
```

## 5. Что не сделано

* approval по умолчанию выключен; это осознанный компромисс ради
  совместимости, а не «защита всегда включена»;
* нет approve/reject из CLI и веб-дашборда — только трей-чат и Python API;
* нет срока истечения approval;
* нет отдельного действия удаления файла или запуска кода, поэтому
  политика проверена только на текущем реестре;
* approval не делает sandbox ОС-изоляцией;
* нет автоматического перепланирования после ошибки действия.

## 6. Следующий этап

1. Связать когнитивные цели `GoalSubsystem` с исполняемыми целями
   Delamain или явно разделить их в UI.
2. Добавить backoff и перепланирование по результату ошибки действия.
3. Расширить сопоставление навыков по аргументам.
4. Поддержать OpenAI-совместимый endpoint как альтернативу Ollama.
5. Добавить удаление/запуск кода только вместе с отдельной политикой и
   тестами.
6. Прогнать полный набор и зафиксировать этап.

## 7. Файлы этапа

Добавлены:

* `src/delamain/approval.py`
* `tests/test_delamain_approval.py`
* `docs/STAGE11_REPORT.md`

Изменены:

* `src/delamain/models.py`
* `src/delamain/actions.py`
* `src/delamain/memory.py`
* `src/delamain/runtime.py`
* `src/delamain/subsystem.py`
* `src/delamain/__init__.py`
* `src/delamain/__main__.py`
* `src/core/agent_runner.py`
* `config/simulation_config.py`
* `docs/DELAMAIN_LOCAL.md`
* `docs/INDEX.md`
* `docs/ARCHITECTURE.md`
* `docs/BASELINE.md`
* `docs/USAGE.md`
* `README.md`
* `CHANGELOG.md`
