# Этап 9 — отчёт: навыки, повторные попытки и память-зависимый цикл

**Дата:** 2026-10-21.
**Статус:** готово; слой по-прежнему выключен по умолчанию.

## 1. Цель этапа

Сделать следующий шаг после интеграции этапа 8: не просто выполнять цель,
а **использовать память результата** и **не терять цель после случайной
ошибки**. Модель на этом этапе не подключается.

Границы этапа:

* сохранить поведение по умолчанию (одна попытка, ошибка → `failed`);
* не добавлять обязательных зависимостей;
* не переиспользовать план для другой команды;
* не выдавать агенту новые права в sandbox;
* не смешивать исполняемые цели Delamain с `GoalSubsystem`.

## 2. Что сделано

### 2.1. `TaskResult.planned_actions`

В `src/delamain/models.py` добавлено поле `planned_actions` — список
нормализованных шагов, которые runtime реально попытался выполнить.

Зачем это нужно:

* `ActionResult` намеренно не хранит аргументы запроса;
* восстановить план из `steps` было бы ненадёжно;
* без плана нельзя честно записать навык и переиспользовать его.

`DelamainRuntime.run_task()` теперь:

1. нормализует каждый шаг;
2. добавляет его в `planned_actions`;
3. выполняет шаг;
4. сохраняет `planned_actions` в `TaskResult` и в `task.finish`.

При ошибке в `planned_actions` остаются только реально начатые шаги. Это
делает историю точнее, чем «план, который когда-то был задуман».

### 2.2. `MemoryStore`

Добавлены методы:

| Метод | Назначение |
|---|---|
| `update_goal(..., status=..., metadata=..., priority=...)` | атомарно обновить цель, **сливая** metadata |
| `list_skills(limit=...)` | инспекция накопленных навыков |

`record_skill()` изменён так, чтобы неудачная попытка увеличивала
`failure_count`, но **не стирала последний успешный план**. Для совершенно
нового навыка без плана хранится JSON `null`.

### 2.3. Переиспользование навыков

Успешная цель записывает в `skills`:

```json
{
  "version": 1,
  "command": "запиши в notes/a.txt: привет",
  "steps": [{"action": "write_file", "args": {"path": "notes/a.txt", "content": "привет"}}]
}
```

Перед выполнением новой цели без `metadata.plan` подсистема ищет навык по
названию. План переиспользуется только при одновременном выполнении условий:

1. `success_count > 0` и `success_count >= failure_count`;
2. сохранённый `command` **точно совпадает** с командой новой цели;
3. в навыке есть непустой список шагов.

Если условие нарушено, работает обычный `HeuristicPlanner`. Это защищает от
ситуации «одинаковое название, другая задача — выполнили старый план».

Событие цели содержит `reused_skill`, поэтому решение видно в логе и
тестах, а не только в SQLite.

### 2.4. Повторные попытки

Добавлен параметр `DELAMAIN_MAX_ATTEMPTS`:

* `1` — значение по умолчанию, поведение этапа 8: ошибка → `failed`;
* `2+` — ошибка → `pending`, пока попытки не исчерпаны.

При каждой попытке обновляются:

```text
attempts
last_attempt_at
last_error
last_ok
retry_scheduled
```

Первая попытка сохраняет совместимый `task_id` `goal-<id>`; повторные
получают суффикс (`goal-<id>-attempt-<n>`), чтобы эпизоды разных попыток
не смешивались. Повтор происходит на следующем разрешённом `tick`, без
отдельного таймера. Экспоненциального backoff пока нет.

### 2.5. Команды и статус

В `/delamain` добавлено:

```text
/delamain skills
```

`/delamain goals` теперь показывает `attempts=N/M`, а `/delamain status` —
лимит попыток и количество навыков. События `delamain_goal` логируются с
номером попытки и пометкой «будет повтор».

## 3. Конфигурация

В `config/simulation_config.py` добавлено:

```python
DELAMAIN_MAX_ATTEMPTS = 1   # 1 = поведение этапа 8; 2+ = retry
```

Env-переменная `DELAMAIN_MAX_ATTEMPTS` имеет приоритет. Пример:

```powershell
$env:DELAMAIN_ENABLED = "1"
$env:DELAMAIN_MAX_ATTEMPTS = "2"
python main_tray.py
```

## 4. Проверки

### 4.1. Целевые тесты

```text
python -m pytest tests/test_delamain_memory.py tests/test_delamain_runtime.py tests/test_delamain_subsystem.py -q
26 passed
```

Покрыто:

* `planned_actions` в `TaskResult` и `task.finish`;
* merge metadata и приоритета цели;
* сохранение успешного плана после неудачи;
* повтор до успеха и повтор до исчерпания попыток;
* переиспользование навыка только для той же команды;
* отказ от переиспользования при другой команде;
* команды `/delamain goals` и `/delamain skills`.

### 4.2. Регрессионный срез

```text
python -m pytest tests/test_integration.py tests/test_delamain_memory.py tests/test_delamain_planner.py tests/test_delamain_runtime.py tests/test_delamain_sandbox.py tests/test_delamain_subsystem.py -q
61 passed
```

### 4.3. Полный набор тестов

```text
python -m pytest -q
473 passed, 2 skipped in 513.52s (0:08:33)
```

Это на 5 тестов больше, чем после этапа 8 (`468 passed, 2 skipped`);
регрессий в существующем наборе нет.

## 5. Что не сделано

* LLM-планировщик не подключён;
* нет автоматического порождения целей;
* когнитивные цели `GoalSubsystem` и исполняемые цели Delamain не связаны;
* нет approval-политики для перезаписи файлов;
* нет backoff и перепланирования по результату ошибки;
* нет семантического поиска похожих навыков.

## 6. Следующий этап

1. LLM-планировщик с JSON-схемой действий и fallback на эвристики.
2. Явная связь когнитивных и исполняемых целей либо разделение их в UI.
3. Approval для записи/удаления/запуска кода.
4. Backoff и перепланирование после ошибки.
5. Сопоставление навыков по команде и аргументам, а не только по точному
   тексту.
6. Полный прогон и фиксация этапа.

## 7. Файлы этапа

Изменены:

* `src/delamain/models.py`
* `src/delamain/memory.py`
* `src/delamain/runtime.py`
* `src/delamain/subsystem.py`
* `src/core/agent_runner.py`
* `config/simulation_config.py`
* `tests/test_delamain_memory.py`
* `tests/test_delamain_runtime.py`
* `tests/test_delamain_subsystem.py`
* `docs/DELAMAIN_LOCAL.md`
* `docs/INDEX.md`
* `docs/ARCHITECTURE.md`
* `docs/BASELINE.md`
* `docs/USAGE.md`
* `README.md`
* `CHANGELOG.md`

Добавлен:

* `docs/STAGE9_REPORT.md`
