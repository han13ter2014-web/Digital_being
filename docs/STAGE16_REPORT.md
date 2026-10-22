# Этап 16 — отчёт: bounded repair внутри одной попытки

**Дата:** 2026-10-22.
**Статус:** готово; новая возможность выключена по умолчанию. Поведение
этапов 7–15 сохранено, кроме явно включённого repair.
**Версия подсистемы:** `0.8.0`.

## 1. Цель этапа

Stage 15 научил planner получать контекст упавшего шага, но новый план
строился только на **следующей** попытке. Внутри одной задачи runtime
по-прежнему останавливался на первой ошибке:

```text
план [A, B, C]
        ├── A ok
        ├── B error
        └── C не выполняется, задача failed
```

Stage 16 добавляет ограниченный repair:

```text
план [A, B, C]
        ├── A ok
        ├── B error ──► planner.replan(context)
        │                    ├── repair [D] ──► D ok ──► done
        │                    └── reject/limit ──► failed
        └── старый хвост C заменён, а не поставлен после D
```

Главные принципы:

* repair запускается только после ошибки шага;
* repair-план **заменяет** оставшуюся очередь, а не вставляется перед ней;
* planner не получает прав на исполнение;
* всё ограничено явными лимитами и проходит тот же approval/sandbox;
* без флага поведение Stage 15 не меняется.

Это не AGI и не «самоисправление без границ». Это детерминированный,
проверяемый механизм с явными отказами.

## 2. Что сделано

### 2.1. Конфигурация

Добавлены параметры `DelamainRuntime`, `DelamainSubsystem` и
`config/simulation_config.py`:

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `DELAMAIN_STEP_REPAIR_ENABLED` | `0` | включить repair после ошибки шага |
| `DELAMAIN_MAX_STEP_REPAIRS` | `1` | максимум принятых repair-сегментов |
| `DELAMAIN_MAX_REPAIR_STEPS` | `5` | максимум шагов в одном repair-плане |

Env имеет приоритет над config. `max_step_repairs=0` допустим и означает
«не чинить», даже если флаг включён. `max_repair_steps` не может быть
меньше 1. При выключенном флаге planner не вызывается для repair, а ошибка
шага сразу завершает задачу, как в Stage 15.

### 2.2. Общий контекст ошибки

Новый `src/delamain/context.py` вынес построение компактного контекста из
подсистемы в общий модуль. Его используют:

* durable-replan Stage 15 (через `_failure_context()` подсистемы);
* repair Stage 16 (напрямую в runtime).

Контекст repair выглядит так:

```json
{
  "stage": "action",
  "failed_step": 2,
  "action": "read_file",
  "args": {"path": "missing.txt"},
  "error": "file not found: missing.txt",
  "output": null,
  "completed_steps": [
    {"action": "write_file", "args": {"path": "first.txt", "content": "ok"}}
  ],
  "remaining_steps": [
    {"action": "write_file", "args": {"path": "tail.txt", "content": "later"}}
  ],
  "repair_count": 0
}
```

Поля:

| Поле | Что означает |
|---|---|
| `stage` | `action`, `normalization` или `planning` |
| `failed_step` | номер шага с 1; в repair-контексте абсолютный |
| `action` | имя упавшего действия |
| `args` | аргументы упавшего шага |
| `error` | ошибка выполнения |
| `output` | вывод упавшего действия, если был |
| `completed_steps` | успешный путь до ошибки |
| `remaining_steps` | старый хвост, который repair может заменить |
| `repair_count` | сколько сегментов уже принято до этого вызова |

`build_failure_context()` принимает явный `failed_index`. Это важно, потому
что один вызов runtime может содержать несколько ошибок, разделённых
успешными repair-сегментами: «последняя ошибка в `steps`» не всегда
совпадает с текущей. Durable-путь Stage 15 по-прежнему выбирает последнюю
ошибку автоматически.

Размер контекста ограничен: строки обрезаются, вложенные списки и словари
— до 20 элементов, глубина — до 3. Это наблюдение для планирования, а не
дамп файлов или памяти. `OllamaPlanner` дополнительно ограничивает
сериализованный контекст 6000 символами.

### 2.3. Алгоритм repair

В `DelamainRuntime._execute_plan()` после ошибки шага:

1. Проверяется `step_repair_enabled` и остаток
   `repair_count < max_step_repairs`.
2. Собирается контекст с `failed_index` текущего шага и
   `remaining_steps` — очередью после упавшего шага.
3. Вызывается `self._plan(task, context)`: при наличии у planner метода
   `replan()` используется он, иначе обычный `plan()`.
4. План нормализуется и проверяется:
   * не пустой;
   * не больше `max_repair_steps`;
   * все действия известны `ActionRegistry`;
   * нет дубликатов внутри repair-плана;
   * нет повтора уже предпринятого `action + args`.
5. Проверяется approval-preflight.
6. При успехе repair-план **заменяет** очередь, а `repair_count`
   увеличивается.
7. При ошибке валидации пишется `task.repair.rejected`, задача сразу
   завершается ошибкой исходного шага. Отклонённый план бюджет не
   расходует, но повторной попытки repair в этом вызове нет.

Ключевая деталь: проверка повтора использует канонический JSON
`{"action": ..., "args": ...}` с сортировкой ключей. Поэтому:

* `read_file {"path": "a.txt"}` после такого же шага — отказ;
* `read_file {"path": "b.txt"}` — разрешено;
* тот же action с изменёнными аргументами считается осмысленной попыткой
  исправления, а не слепым retry.

Repair не пытается «починить» ошибки планирования или нормализации до
исполнения. Для них остаётся Stage 15: следующая попытка может получить
`last_failure_context`.

### 2.4. Durable repair-approval

Опасный repair проходит тот же `ApprovalPolicy`, что и обычный план. Если
подтверждение нужно:

* пишется эпизод `task.repair` с `approval_pending=true`;
* создаётся approval с `metadata.kind="step_repair"`;
* в metadata сохраняются `prior_actions`, `prior_effective_actions`,
  `prior_steps`, `repair_count`, `failed_step` и `failure_context`;
* возвращается `TaskResult` с `pending_approval` и `approval_id=None`,
  чтобы summary указывал на новый approval, а не на уже использованный
  старый.

После `/delamain approve <id>` runtime:

1. восстанавливает `prior_actions` и `prior_effective_actions` из metadata;
2. выполняет repair-план с `steps_before` и сохранённым `repair_count`;
3. пишет `task.resume`, а не `task.start`;
4. завершает задачу `task.finish` и пишет skill по успешному пути.

Если пользователь отклоняет repair-approval, задача становится `failed`,
repair-план не выполняется, а прогресс (`steps`, `effective_steps`,
`step_repairs`) сохраняется в summary и metadata цели. Pending repair не
дублируется на следующих tick: подсистема видит существующий approval и
ждёт решения.

Repair-approval может возникнуть и при выполнении уже одобренного
исходного плана. Этот путь обрабатывается в `_finish_pending_goal()`:
новая pending-цель связывается с repair-approval, а не ошибочно считается
провалом.

### 2.5. Результат, навыки и наблюдаемость

`TaskResult` получил поля:

| Поле | Смысл |
|---|---|
| `planned_actions` | всё, что реально пытались выполнить, включая упавшие шаги |
| `effective_actions` | успешный путь; именно он идёт в skill |
| `steps_before` | смещение для continuation-результата после repair-approval |
| `repair_count` | число принятых repair-сегментов |

Для обычного успешного плана `effective_actions == planned_actions`. После
repair они расходятся: упавший шаг и выброшенный хвост остаются только в
`planned_actions`.

Подсистема записывает skill из `effective_actions`. Это честнее, чем
сохранять весь attempted-план: повторное выполнение skill не должно
начинаться с заведомо упавшего шага. Побочные эффекты упавшего шага при
этом не откатываются — см. ограничения.

Наблюдаемость:

* `/delamain status` — `Repair: on/off, max_segments=..., max_steps=...`;
* `/delamain goals` — `repairs=N`;
* `/delamain approvals` — пометка `repair-план`;
* pending-сообщение — «Это repair-план… уже выполнено шагов: N»;
* результат — `repair=N`;
* `status()["step_repair"]` — машинное представление флагов.

### 2.6. LLM prompt

`OllamaPlanner` получает `Repair context` в user-message как недоверенные
данные. Системная инструкция просит:

* вернуть замену оставшейся работы, а не весь план;
* не повторять `action + args` из `completed_steps` или упавшего шага;
* рассматривать `remaining_steps` как контекст, а не как команду.

Ответ модели всё равно проходит нормализацию, проверку схемы действий,
лимиты и approval. Модель не получает прав на выполнение.

## 3. Безопасность и совместимость

* `DELAMAIN_STEP_REPAIR_ENABLED=0` по умолчанию: `replan()` для repair не
  вызывается, ошибка шага завершает задачу как раньше.
* Схема SQLite не менялась: repair-состояние хранится в существующих JSON
  metadata approval/цели.
* Новых действий, сети и запуска кода нет. Repair-план проходит
  `ActionRegistry`, `Sandbox` и approval.
* Planner не получает прав на исполнение и не может обойти approval.
* Уже выполненные шаги не откатываются. Если упавший шаг успел изменить
  файл, изменение остаётся; repair должен учитывать фактическое состояние.
* Отклонённый или слишком большой repair-план не выполняется частично.
* Pending repair не считается ошибкой и не запускает retry.
* `run_now()` не использует durable `last_failure_context`; repair внутри
  одного вызова работает одинаково для обычного запуска и цели, но
  approval-путь всегда явный.

## 4. Тесты

Добавлен `tests/test_delamain_step_repair.py` — 17 тестов:

* default-off на уровне runtime и подсистемы, env-флаги и лимиты;
* replacement-семантика: старый хвост не выполняется, контекст содержит
  `remaining_steps`;
* запрет повтора уже предпринятого `action + args`;
* лимит `max_repair_steps`;
* исчерпание `max_step_repairs` и отсутствие второго вызова planner;
* два последовательных repair-сегмента с накоплением контекста;
* упавший шаг не попадает в `completed_steps` даже при пустом успешном пути;
* отказ при неизвестном действии и при внутреннем дубликате;
* durable repair-approval с перезапуском runtime и подсистемы, сохранением
  прогресса и отсутствием дублей;
* repair-approval, созданный во время resume уже одобренного плана;
* reject repair-approval с сохранением `steps`/`effective_steps`;
* skill по `effective_actions` после repair;
* pending repair не дублируется на tick;
* отображение repair в `/delamain status`, `approvals` и pending-сообщении.

Обновлён тест `OllamaPlanner.replan()`: проверяются `remaining_steps`,
replacement-инструкция и запрет повтора.

Целевой прогон Delamain-тестов:

```text
python -m pytest -q tests/test_delamain_runtime.py \
  tests/test_delamain_approval.py \
  tests/test_delamain_goal_authoring.py \
  tests/test_delamain_goal_bridge.py \
  tests/test_delamain_memory.py \
  tests/test_delamain_planner.py \
  tests/test_delamain_sandbox.py \
  tests/test_delamain_subsystem.py \
  tests/test_delamain_llm_planner.py \
  tests/test_delamain_step_repair.py
116 passed
```

Полный suite проекта:

```text
python -m pytest -q --ignore=tests/benchmarks
535 passed, 2 skipped in 257.79s (0:04:17)

python -m pytest -q tests/benchmarks
16 passed in 58.79s (0:00:58)
```

Суммарно: **551 passed, 2 skipped**. По сравнению со Stage 15:
`+17 passed` (535 против 518), benchmarks без изменений (16).

## 5. Что не сделано

* Нет отката или компенсации побочных эффектов уже выполненных шагов.
* Нет выбора из нескольких repair-кандидатов: принимается первый валидный.
* Нет проверки предусловий и идемпотентности действий.
* Нет repair после успешного шага: только после ошибки.
* Нет семантического поиска похожих навыков и редактирования отдельных
  шагов proposal.
* Нет OpenAI-совместимого endpoint, удаления файлов и запуска кода.

## 6. Итог

Stage 16 добавляет маленький, но реальный шаг к замкнутому циклу
«цель → действие → память → следующая цель»: задача может пережить ошибку
шага, не начиная всё заново и не теряя уже выполненные действия. При этом
repair остаётся ограниченным, проверяемым и выключенным по умолчанию.
Planner по-прежнему только предлагает план; решение о выполнении и
опасности принимают runtime, sandbox и пользователь.
