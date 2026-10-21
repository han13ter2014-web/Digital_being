# Этап 8 — отчёт: интеграция Delamain-local и цикл исполняемых целей

**Дата:** 2026-10-21.
**Статус:** интеграция готова; слой выключен по умолчанию.

## 1. Цель этапа

Подключить детерминированное ядро `src/delamain/` к существующему агенту,
не меняя поведение по умолчанию, и замкнуть минимальный цикл цели:

```text
очередь цели → выбор одной pending-цели → план/команда → действие
             → результат → статус done/failed → skill
```

Границы этапа:

* не подключать LLM;
* не включать слой без явного решения пользователя;
* не ломать существующие тесты и трей-режим;
* не выдавать агенту неограниченный доступ к файлам;
* не смешивать когнитивные цели `GoalSubsystem` с исполняемыми целями
  Delamain без отдельного проекта миграции.

## 2. Что сделано

### 2.1. `DelamainSubsystem`

Добавлен `src/delamain/subsystem.py` — нативная подсистема `Subsystem`
(priority 200), а не `LegacySubsystemAdapter`.

Ключевые свойства:

* **ленивость:** `__init__` не создаёт SQLite и не трогает workspace;
* **выключена по умолчанию:** `DELAMAIN_LOCAL_ENABLED=False`;
* **явное включение:** env `DELAMAIN_ENABLED=1`, config или `/delamain on`;
* **один runtime на подсистему**, закрывается в `teardown()`;
* **пути:** `data/delamain/workspace` и
  `data/delamain/delamain.sqlite3` по умолчанию;
* **sandbox:** лимит файла задаётся через `DELAMAIN_MAX_FILE_BYTES`.

Методы:

| Метод | Назначение |
|---|---|
| `enable()` / `disable()` | включение и выключение автономных тиков |
| `queue_goal(title, command=..., plan=...)` | durable-цель в SQLite |
| `run_now(task, plan=...)` | разовое выполнение вне очереди |
| `run_pending_goal()` | выполнить до `max_goals_per_tick` готовых целей |
| `tick(cycle, context)` | раз в N циклов запустить очередь |
| `status()` | состояние, пути, счётчики целей, последний результат |
| `teardown()` | закрыть SQLite |

### 2.2. Цикл цели

Цель считается исполняемой, если в `metadata` есть:

* `command` — строка для `HeuristicPlanner`;
* `plan` — явный список шагов `{"action": ..., "args": ...}`.

При выполнении:

1. `DelamainRuntime.run_task()` пишет `task.start`;
2. выполняет шаги до первой ошибки;
3. пишет эпизоды и `task.finish`;
4. подсистема обновляет `goals.status` → `done` или `failed`;
5. `skills` получает успех или неудачу;
6. событие `delamain_goal` возвращается в `PluginRegistry` и логируется
   `AgentRunner`.

Планы из `ActionRequest` нормализуются в JSON-совместимые словари перед
записью в SQLite, поэтому цель можно безопасно восстановить после рестарта.

### 2.3. Интеграция с `DigitalBeing`

В `_register_all_subsystems_in_registry()` добавлена прямая регистрация
`DelamainSubsystem`:

* `self.delamain` всегда доступен как атрибут агента;
* подсистема попадает в `PluginRegistry` и `status_all()`;
* при выключенном флаге `tick_all()` её не вызывает;
* при ошибке импорта/инициализации агент продолжает работу, а причина
  попадает в лог.

### 2.4. Команды `/delamain`

В `AgentRunner.handle_command()` добавлены:

```text
/delamain
/delamain status
/delamain on
/delamain off
/delamain run <задача>
/delamain goal <название> | <команда>
/delamain goals
```

Оригинальный регистр задачи берётся из `cmd_raw`, поэтому команды planner
не ломаются. Результаты и события Delamain логируются в
`_log_autonomous_events()`.

## 3. Конфигурация

В `config/simulation_config.py` добавлены:

```python
DELAMAIN_LOCAL_ENABLED = False
DELAMAIN_TICK_INTERVAL = 20
DELAMAIN_MAX_GOALS_PER_TICK = 1
DELAMAIN_MAX_FILE_BYTES = 1_000_000
DELAMAIN_WORKSPACE = ""
DELAMAIN_DB = ""
```

Env-переменные с теми же именами имеют приоритет. Это позволяет включать
слой на один запуск, не меняя конфиг:

```powershell
$env:DELAMAIN_ENABLED = "1"
python main_tray.py
```

## 4. Проверки

### 4.1. Целевые тесты

```text
python -m pytest tests/test_delamain_subsystem.py -q
12 passed
```

Покрыто:

* выключенность и ленивость по умолчанию;
* создание runtime при `enable()`, остановка тиков при `disable()`;
* очередь цели и выполнение на tick;
* соблюдение интервала tick;
* успешная цель → `done` + skill success;
* ошибочная цель → `failed` + skill failure;
* явный план без planner, включая нормализацию `ActionRequest` в JSON;
* `run_now()` и `status()`;
* требование command/plan при постановке цели;
* закрытие runtime в `teardown()`;
* регистрация в реальном `DigitalBeing`;
* команды `/delamain` через `AgentRunner`.

### 4.2. Регрессионный срез

```text
python -m pytest tests/test_integration.py tests/test_delamain_*.py -q
55 passed
```

### 4.3. Полный набор тестов

```text
python -m pytest -q
468 passed, 2 skipped in 472.44s (0:07:52)
```

Это на 12 тестов больше, чем после этапа 7 (456 passed, 2 skipped);
регрессий в существующем наборе нет. Отдельно проверены
`test_plugin_system`, `test_health_endpoint`, `test_web_dashboard`,
`test_metrics_endpoint` и `test_tray_foundation` — 86 passed.

## 5. Что не сделано

* LLM-планировщик не подключён;
* нет автоматического порождения целей: очередь пополняет пользователь
  или внешний код;
* когнитивные цели `GoalSubsystem` и исполняемые цели Delamain пока не
  связаны;
* нет approval-политики для перезаписи файлов;
* нет retry/backoff и перепланирования после ошибки;
* `skills` записываются, но ещё не используются для выбора плана.

## 6. Следующий этап

1. LLM-планировщик с JSON-схемой действий и fallback на эвристики.
2. Явная связь когнитивных и исполняемых целей либо разделение их в UI.
3. Approval для записи/удаления/запуска кода.
4. Использование `skills` при планировании.
5. Retry/backoff и политика ошибок.
6. Полный прогон и фиксация этапа.

## 7. Файлы этапа

Добавлены:

* `src/delamain/subsystem.py`
* `tests/test_delamain_subsystem.py`
* `docs/STAGE8_REPORT.md`

Изменены:

* `src/delamain/__init__.py`
* `src/core/agent.py`
* `src/core/agent_runner.py`
* `config/simulation_config.py`
* `docs/DELAMAIN_LOCAL.md`
* `docs/INDEX.md`
* `docs/ARCHITECTURE.md`
* `docs/BASELINE.md`
* `docs/USAGE.md`
* `README.md`
* `CHANGELOG.md`
