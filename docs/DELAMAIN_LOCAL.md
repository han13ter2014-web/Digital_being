# Delamain-local: локальное ядро действия и памяти

> **Статус:** этапы 18A–19 — core-owned effector contract, core-driven шаг
> ядра и бюджет действия, 2026-10-24.
> Это не «сильный ИИ» и не доказательство сознания. Это детерминированное
> ядро, которое умеет выполнить задачу, проверить результат, записать опыт
> в локальную память, повторить/переиспользовать успешный план, — при
> желании — получить план от локальной модели, остановить опасный план до
> явного подтверждения пользователя, связать активную когнитивную цель с
> одной исполняемой целью и безопасно привязать к ней команду из чата.
> Модель не обязательна: ядро полностью работает без неё.
>
> С этапа 14 неудачные действия могут повторяться с ограниченным
> экспоненциальным backoff. Опциональное перепланирование на повторе
> строит новый план через активный planner, а не переигрывает сохранённый
> explicit/skill-план. С этапа 15 planner может дополнительно получить
> компактный результат упавшего шага: действие, аргументы, ошибку,
> вывод и уже выполненные шаги. С этапа 16 ошибка шага может быть
> исправлена **внутри той же попытки**: planner получает остаток плана и
> возвращает ограниченную замену, а runtime не повторяет уже выполненные
> действия с теми же аргументами. Все эти возможности выключены по
> умолчанию.
>
> Слой **выключен по умолчанию**. Без явного включения он не открывает
> SQLite и не трогает файлы. LLM-планировщик тоже выключен по умолчанию.
> Approval выключен по умолчанию (`DELAMAIN_APPROVAL_MODE=off`), мост
> когнитивных целей — тоже (`DELAMAIN_BRIDGE_ENABLED=False`), а генерация
> proposal планировщиком — `DELAMAIN_GOAL_PROPOSAL_ENABLED=False`. Все
> возможности включаются явно; ручной `/goals exec` не требует отдельного
> флага proposal, но работает при включённом Delamain и является прямым
> решением пользователя.
>
> С этапа 17 добавлен офлайн-контур оценки `evaluation.py`: data-only
> suite, изолированные workspace, `ScriptedPlanner`, метрики и CLI. Он не
> импортируется runtime, не добавляет прав и не является доказательством
> AGI; planning probes измеряют только текущую эвристику.
>
> С этапа 18A Delamain получает core-owned effector contract:
> `EffectorRequest`/`EffectorPort` задают границу власти, а
> `DelamainEffectorAdapter` делает явный `submit()` идемпотентным и
> переживающим перезапуск. С этапа 18B флаг
> `DELAMAIN_EFFECTOR_CORE_DRIVEN` позволяет ядру делать один шаг
> эффектора за цикл, а `tick()` подсистемы в этом режиме только
> синхронизирует мост и не исполняет цели. Оба флага выключены по
> умолчанию.
>
> С этапа 19 попытка цели Delamain проходит через `ActionBudget` ядра.
> Бюджет не создаёт второй запас энергии: он читает и списывает
> существующий `self.energy`, соблюдает резерв и потолок стоимости и
> оставляет цель `pending` при отказе. Флаг `ACTION_BUDGET_ENABLED=False`
> по умолчанию. Единая очередь и `cancel` ещё не реализованы.

## 1. Зачем этот слой

До этого этапа у проекта была богатая симуляция познания, но почти не было
замкнутого контура «действие → наблюдение → память → следующее решение».
Агент много думал и описывал действия, но редко менял что-то вне себя и почти
не использовал результаты своих действий.

`src/delamain/` — первый честный слой действия. Его задача не «стать
сверхразумом», а доказать, что локальная система может:

1. получить задачу;
2. разложить её на проверяемые шаги;
3. выполнить шаг в ограниченном workspace;
4. увидеть результат;
5. записать эпизод в SQLite;
6. остановиться при ошибке, а не имитировать успех.

Этот слой сознательно сделан на стандартной библиотеке Python. Никаких
обязательных зависимостей, облачных API или загрузки модели.

## 2. Архитектура

```text
задача
  │
  ▼
planner (эвристики + опциональная LLM + fallback)
  │  список ActionRequest
  ▼
DelamainRuntime
  ├── ApprovalPolicy ──► pending approval в SQLite
  │        │                    │
  │        │              /delamain approve
  │        ▼                    ▼
  ├── ActionRegistry ──► Sandbox ──► файлы workspace
  │        │
  │        └──────────► MemoryStore ──► SQLite
  │
  └── ActionResult ──► episode в памяти
                         │
                         ▼
                   task.finish / task.start
```

Ключевая идея: **модель — не агент**. Модель может быть планировщиком,
но исполнение, проверка и память остаются детерминированными и
инспектируемыми.

## 3. Компоненты

| Файл | Роль |
|---|---|
| `src/delamain/models.py` | `ActionSpec`, `ActionRequest`, `ActionResult`, `TaskResult`, время UTC |
| `src/delamain/sandbox.py` | path-политика, чтение/запись/список/поиск файлов |
| `src/delamain/actions.py` | реестр действий и типовые файловые/памятные действия |
| `src/delamain/approval.py` | `ApprovalPolicy`: режимы `off`/`dangerous`/`all`, поиск опасных шагов |
| `src/delamain/memory.py` | SQLite: эпизоды, факты+FTS5, self-model, цели, навыки, approvals |
| `src/delamain/planner.py` | `Planner`-протокол, `HeuristicPlanner`, `FallbackPlanner` |
| `src/delamain/llm_planner.py` | опциональный `OllamaPlanner`: HTTP, JSON-схема, валидация плана |
| `src/delamain/context.py` | компактный failure-context: упавший шаг, остаток плана, успешный путь |
| `src/delamain/runtime.py` | preflight approval, выполнение плана, bounded repair, запись эпизодов |
| `src/delamain/subsystem.py` | опциональная `DelamainSubsystem`: lazy runtime, очередь целей, tick |
| `src/delamain/goal_authoring.py` | `GoalExecutionProposal` и `GoalAuthoring`: manual/propose/accept/reject для когнитивных целей |
| `src/delamain/__main__.py` | CLI-демо; по умолчанию без модели, с `--llm` — Ollama |

### 3.1. Sandbox

Все пути трактуются относительно одного workspace. Запрещены:

* абсолютные пути;
* Windows drive-relative пути (`C:foo`);
* выход через `..`;
* симлинки, ведущие за пределы workspace.

Дополнительно: лимит размера файла (по умолчанию 1 МБ), отказ от бинарных
файлов при чтении, атомарная запись через временный файл и `os.replace`.

Это **не** полноценная ОС-песочница. Это защитная политика путей для
локального однопользовательского агента. Запуск кода и сеть сюда пока не
входят.

### 3.2. Действия

Сейчас доступны:

* `list_files` — список файлов по glob;
* `read_file` — чтение UTF-8 текста;
* `write_file` — атомарная запись;
* `search_files` — регистронезависимый поиск по файлам;
* `verify_file` — проверка существования, размера и подстроки;
* `remember_fact` / `recall_facts` — семантическая память;
* `set_self_model` / `get_self_model` — самоописание;
* `save_goal` / `list_goals` — устойчивые цели.

`ActionRegistry` превращает исключения в `ActionResult(ok=False)`, поэтому
один сбой не разрушает весь цикл и остаётся видимым в истории.

`write_file` и `set_self_model` помечены `dangerous=True`. Это не меняет
поведение по умолчанию (approval `off`), но позволяет `ApprovalPolicy`
найти опасный шаг до выполнения плана.

### 3.3. Память

SQLite-база содержит:

| Таблица | Что хранит |
|---|---|
| `episodes` | каждый шаг: задача, действие, аргументы, результат, ошибка |
| `facts` | явные факты, ключ/значение, источник, уверенность |
| `facts_fts` | FTS5-индекс для поиска фактов (с fallback на `LIKE`) |
| `self_model` | текущие представления агента о себе |
| `goals` | цели, статус, предикат успеха, приоритет |
| `skills` | успешные планы и счётчики успехов/неудач |
| `approvals` | pending/approved/rejected/consumed планы, опасные действия, решение |

С этапа 9 успешный план сохраняется в `skills` в виде:

```json
{
  "version": 1,
  "command": "запиши в notes/a.txt: привет",
  "steps": [{"action": "write_file", "args": {"path": "notes/a.txt", "content": "привет"}}]
}
```

`command` нужен, чтобы не переиспользовать старый план для другой задачи с
тем же названием. Неудачная попытка увеличивает `failure_count`, но не
стирает последний успешный план.

Пара `task.start` / `task.finish` позволяет восстановить историю задачи,
не читая весь журнал. В `task.finish` теперь также сохраняется
`planned_actions` — нормализованный план, который реально был выполнен.

### 3.4. Runtime

`DelamainRuntime.run_task()`:

1. создаёт `task_id`;
2. получает и нормализует план от planner или принимает готовый список;
3. спрашивает `ApprovalPolicy`, нужен ли approval для всего плана;
4. если нужен — сохраняет pending approval и возвращает результат **без**
   `task.start` и без выполнения действий;
5. иначе пишет `task.start` и выполняет шаги по одному;
6. после каждого шага пишет эпизод;
7. при ошибке шага может попросить planner о bounded repair-плане на
   оставшуюся работу; принятый repair продолжает задачу, а отклонённый или
   исчерпанный бюджет завершает её;
8. при успехе пишет `task.finish(ok=True)` и возвращает `TaskResult`.

Ошибка планирования или невалидный план не создают `task.start`: runtime
сначала проверяет план, а затем фиксирует начало задачи. Это нужно, чтобы
approval-preflight не оставлял ложных следов выполнения.

Это всё ещё не адаптивный цикл после каждого успешного шага: план
перестраивается только после ошибки и только в пределах лимита. С этапа 14
planner может построить новый план между попытками, с этапа 15 — получить
компактный контекст упавшего шага (`last_failure_context`), а с этапа 16 —
заменить оставшуюся часть текущего плана (`task.repair`). Любой новый план
проходит тот же approval/sandbox.

`TaskResult` с этапа 16 различает:

* `planned_actions` — всё, что реально пытались выполнить, включая упавшие
  шаги;
* `effective_actions` — успешный путь; именно он записывается как skill;
* `steps_before` — смещение для continuation-результата после repair
  approval;
* `repair_count` — сколько repair-сегментов принято.

### 3.5. Интеграция с `DigitalBeing` (этапы 8–9)

`DelamainSubsystem` — нативная подсистема (`Subsystem`, priority 200),
которую `DigitalBeing` регистрирует напрямую, без `LegacySubsystemAdapter`.

Что важно:

* **Выключена по умолчанию.** `DELAMAIN_LOCAL_ENABLED=False`; runtime
  создаётся лениво, только при включении.
* **Свои пути.** Workspace по умолчанию — `data/delamain/workspace`, база —
  `data/delamain/delamain.sqlite3`. Оба пути можно переопределить через
  env или config.
* **Один шаг за тик.** Раз в `DELAMAIN_TICK_INTERVAL` автономных циклов
  подсистема берёт одну `pending`-цель, у которой есть `metadata.command`
  или `metadata.plan`, выполняет её и обновляет статус.
* **Честный результат.** Успех → `done`, ошибка → `failed` или `pending`
  при включённых повторах; в `skills` пишется успех или неудача.
* **Повторы, backoff и навыки.** С этапа 9 подсистема умеет повторять
  упавшую цель и переиспользовать успешный план. По умолчанию
  `DELAMAIN_MAX_ATTEMPTS=1`, то есть поведение этапа 8 сохранено; при `2+`
  ошибка оставляет цель в `pending` до исчерпания попыток. С этапа 14
  повтор можно отложить (`DELAMAIN_RETRY_BACKOFF_SEC`) и перепланировать
  (`DELAMAIN_REPLAN_ON_FAILURE`), с этапа 15 — передать planner'у
  контекст упавшего шага (`DELAMAIN_REPLAN_WITH_CONTEXT`), а с этапа 16 —
  попытаться заменить оставшуюся часть плана после ошибки
  (`DELAMAIN_STEP_REPAIR_ENABLED`). Все эти опции по умолчанию выключены.
* **Мост когнитивных целей (этап 12).** Исполняемые цели по-прежнему
  лежат в таблице `goals` SQLite Delamain, а не в `agent.goals`. При
  включённом `DELAMAIN_BRIDGE_ENABLED=1` активная цель `GoalSubsystem`
  с явным executable-payload получает ровно одну связанную Delamain-цель;
  без payload мост ничего не делает.

Пример цикла:

```text
/delamain goal Проверить README | прочитай README.md
        │
        ▼
goals(status=pending, metadata.command="прочитай README.md")
        │  tick каждые N циклов
        ▼
DelamainRuntime.run_task → read_file → episode
        │
        ├── ok  → goals.status = done,   skills.success_count += 1
        └── err → goals.status = failed, skills.failure_count += 1
```

`DelamainSubsystem.run_now()` выполняет задачу сразу, не создавая цель;
`queue_goal()` создаёт durable-цель; `tick()` двигает очередь.

### 3.6. Навыки, повторы, backoff и контекст ошибки (этапы 9, 14 и 15)

Перед выполнением цели без явного `metadata.plan` подсистема ищет навык с
тем же названием. План переиспользуется только если:

1. `skills.success_count > 0` и `success_count >= failure_count`;
2. сохранённый `command` совпадает с командой новой цели;
3. в навыке есть непустой список шагов.

Если план найден, planner (LLM или эвристический) не вызывается. Если навык
устарел или провалился, следующая попытка снова идёт через planner. Это
маленький, но настоящий цикл «опыт → повторное действие», а не имитация
обучения.

Повторы управляются `DELAMAIN_MAX_ATTEMPTS`:

```text
попытка 1 → ошибка → attempts=1, status=pending, retry_scheduled=true
попытка 2 → ошибка → attempts=2, status=failed
```

Первая попытка сохраняет совместимый `task_id` `goal-<id>`; повторные
получают суффикс `-attempt-<n>`, поэтому эпизоды разных попыток не
смешиваются.

С этапа 14 повтор может быть отложен и перепланирован, а с этапа 15 — ещё
и получить контекст упавшего шага. По умолчанию все возможности выключены,
поэтому поведение этапа 9 не меняется:

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `DELAMAIN_RETRY_BACKOFF_SEC` | `0` | базовая пауза; `0` = повтор на следующем tick |
| `DELAMAIN_RETRY_BACKOFF_MAX_SEC` | `300` | верхняя граница паузы |
| `DELAMAIN_REPLAN_ON_FAILURE` | `0` | на повторе построить новый план |
| `DELAMAIN_REPLAN_WITH_CONTEXT` | `0` | передать planner'у результат упавшего шага |

Backoff экспоненциальный и ограниченный:

```text
delay = min(base * 2^(attempt-1), cap)
```

Например, при `base=60` и `cap=300`: 60, 120, 240, 300, 300… Пауза
записывается в metadata цели как `next_retry_at` (UTC ISO-8601), поэтому
переживает перезапуск. `run_pending_goal()` не берёт цель, пока этот
момент не наступил; остальные готовые цели при этом не блокируются.
При `base=0` поле `next_retry_at` не создаётся и повтор снова доступен на
следующем tick, как в этапе 9.

Если включён `DELAMAIN_REPLAN_ON_FAILURE`, то перед следующей попыткой
подсистема:

* игнорирует сохранённый `metadata.plan`;
* не переиспользует skill-план;
* вызывает активный runtime planner (эвристику или LLM) заново.

Это всё ещё ограниченный retry: число попыток задаёт
`DELAMAIN_MAX_ATTEMPTS`, а planner не получает новых прав. Если новый план
тоже падает, цикл продолжается до лимита. В metadata видны
`replan_on_next_attempt`, `last_attempt_replanned`, `replan_count`,
`retry_delay_sec` и `next_retry_at`.

С этапа 15 при включённых `DELAMAIN_REPLAN_ON_FAILURE=1` и
`DELAMAIN_REPLAN_WITH_CONTEXT=1` неудачная попытка сохраняет в metadata
цели `last_failure_context`:

```json
{
  "stage": "action",
  "attempt": 1,
  "failed_step": 2,
  "action": "read_file",
  "args": {"path": "missing.txt"},
  "error": "file not found: missing.txt",
  "output": null,
  "completed_steps": [
    {"action": "write_file", "args": {"path": "first.txt", "content": "ok"}}
  ]
}
```

Контекст ограничен по размеру: строки обрезаются, вложенные списки и
словари — до 20 элементов. Это не дамп памяти, а компактное наблюдение
для следующего планирования. `stage` различает ошибку действия
(`action`), невалидный план (`normalization`) и ошибку планирования
(`planning`); в двух последних случаях `failed_step` может отсутствовать.

При следующей попытке `DelamainRuntime.run_task(..., failure_context=...)`
вызывает `planner.replan(task, context)`, если planner его поддерживает.
`OllamaPlanner` добавляет контекст в prompt как **недоверенные данные** и
просит не повторять ту же ошибку. `HeuristicPlanner` не умеет учиться на
результате и просто разбирает задачу заново. `FallbackPlanner` пробует
`replan()` у primary, затем у fallback; если метода нет, используется
обычный `plan()`. Контекст хранится в SQLite и переживает перезапуск;
успешная попытка очищает его (`last_failure_context=null`).

`DELAMAIN_REPLAN_WITH_CONTEXT` не включает replan сам по себе. Нужны оба
флага, поэтому по умолчанию поведение этапов 9–15 не меняется. Контекст
не используется в `run_now()`, при pending approval и при выполнении уже
одобренного плана: это не новые попытки планирования.

Pending approval не считается ошибкой действия: цель ждёт решения без
backoff и без replan. Reject завершает цель как `failed` без retry.
Ручной `run_now()` также не использует backoff/replan: это немедленный
вызов вне очереди целей.

### 3.6.1. Repair внутри одной попытки (этап 16)

Stage 15 умеет перепланировать только **следующую** попытку. Stage 16
добавляет осторожный repair **текущей** задачи: после ошибки шага runtime
может один раз (или несколько, если увеличен лимит) попросить planner
заменить оставшуюся часть плана. Это не «самоисправление без границ» и не
право planner'а выполнять действия.

Правила:

1. Repair запускается только после ошибки шага; ошибки планирования и
   нормализации внутри попытки не чинятся — для них остаётся Stage 15.
2. Repair-план **заменяет** оставшуюся очередь, а не вставляется перед ней.
   Старый хвост передаётся planner'у как `remaining_steps`; если он не нужен,
   его можно не включать в ответ.
3. Repair-план не может повторять уже предпринятый `action + args`. Шаг с
   изменёнными аргументами разрешён: это осмысленная попытка исправления, а
   не слепой retry.
4. Repair-план отклоняется, если содержит неизвестное действие, дубликаты
   внутри себя или больше `DELAMAIN_MAX_REPAIR_STEPS` шагов.
5. Число принятых repair-сегментов ограничено `DELAMAIN_MAX_STEP_REPAIRS`.
   Отклонённый план бюджет не расходует, но задача сразу завершается
   ошибкой исходного шага.
6. Repair проходит тот же approval-preflight. Если план опасный (или режим
   `all`), создаётся отдельный durable approval с
   `metadata.kind="step_repair"`. После approve задача продолжается с
   сохранением уже выполненных шагов; reject завершает цель как `failed`.
7. Побочные эффекты уже выполненных шагов не откатываются. Если упавший шаг
   успел что-то изменить, это остаётся в workspace; repair должен учитывать
   фактическое состояние, а не предполагать откат.
8. Skill записывается по `effective_actions` — успешному пути без упавших
   шагов. Упавший шаг и выброшенный старый хвост в skill не попадают.

Схема:

```text
план [A, B, C]
        │
        ├── A ok
        ├── B error ──► planner.replan(context)
        │                    │
        │                    ├── repair [D] ──► D ok ──► task.finish(ok=True)
        │                    │                    effective = [A, D]
        │                    └── reject/limit ──► task.finish(ok=False)
        │
        └── C не выполняется, если repair заменил хвост
```

Контекст repair содержит `stage`, `failed_step`, `action`, `args`,
`error`, `output`, `completed_steps` (успешный путь), `remaining_steps` и
`repair_count`. Он ограничен по размеру так же, как durable-контекст
Stage 15. `OllamaPlanner` получает его как недоверенные данные и явно
просят вернуть замену остатка, а не повторять весь план.

Новые флаги:

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `DELAMAIN_STEP_REPAIR_ENABLED` | `0` | включить repair после ошибки шага |
| `DELAMAIN_MAX_STEP_REPAIRS` | `1` | сколько repair-сегментов разрешено |
| `DELAMAIN_MAX_REPAIR_STEPS` | `5` | максимум шагов в одном repair-плане |

По умолчанию всё выключено: без `DELAMAIN_STEP_REPAIR_ENABLED=1` ошибка
шага ведёт себя точно как в Stage 15, даже если у planner есть `replan()`.
Repair не даёт planner'у новых прав: действия всё равно проверяются
`ActionRegistry`, `Sandbox` и approval.

### 3.7. Опциональный LLM-планировщик (этап 10)

LLM — сменяемый **планировщик**, а не исполнитель. По умолчанию он
выключен; при включении используется локальный Ollama через native
`/api/chat`. Сетевой запрос делается только в момент `plan()`, не при
создании подсистемы или runtime.

```text
задача
  │
  ▼
FallbackPlanner
  ├── OllamaPlanner ──► POST http://127.0.0.1:11434/api/chat
  │        │                 format=json, temperature=0
  │        └── ошибка/невалидный план ──┐
  │                                      ▼
  └────────────────────────────► HeuristicPlanner
                                         │
                                         ▼
                              список ActionRequest
```

Что именно проверяется:

* план должен быть JSON-объектом с массивом `plan` (допускаются также
  `actions`, `steps` и одиночный `action`);
* каждый шаг — объект с непустым `action` и объектом `args`;
* имя действия должно быть в **живом** `ActionRegistry`; выдуманные
  действия отклоняются;
* число шагов не больше `DELAMAIN_LLM_MAX_STEPS`;
* ответ может быть в fenced-блоке или в OpenAI-подобном
  `choices[0].message.content`, но это не делает endpoint OpenAI-совместимым:
  сейчас поддерживается именно Ollama `/api/chat`.

`FallbackPlanner` ловит ошибку транспорта, таймаут, невалидный JSON и
неизвестное действие, после чего вызывает `HeuristicPlanner`. Если и
эвристика не смогла разобрать задачу, возвращается комбинированная ошибка:
видно, что именно сломалось у модели и что не удалось детерминированно.
`last_used` (`primary`/`fallback`) и `last_error` попадают в
`/delamain status`, поэтому откат не скрыт. С этапа 15 у
`OllamaPlanner` есть метод `replan(task, failure_context)`: контекст
упавшего шага добавляется в user-message как недоверенные данные, а не
как часть системной инструкции. С этапа 16 контекст может содержать
`remaining_steps`; системная инструкция просит вернуть замену остатка и не
повторять `action + args` из `completed_steps` или упавшего шага. Контекст
по-прежнему ограничен (6000 символов) и не даёт модели прав на исполнение.
Если модель не ответит или план будет невалиден, `FallbackPlanner` снова
использует эвристику, а runtime может отклонить repair-план.

Планировщик не получает права на исполнение. Полученный план всё равно
проходит через `ActionRegistry`, а файловые действия — через `Sandbox`.
Модель не может выйти из workspace, запустить код или обратиться к сети:
таких действий в реестре пока нет. С этапа 11 план модели с `write_file`
или `set_self_model` также проходит approval-preflight, как и любой другой
план.

Важно про данные: при включённом LLM текст задачи и схема доступных
действий отправляются локальному Ollama. Облачных API в этой реализации
нет. Не передавайте модели секреты, если не доверяете локальному сервису.

### 3.8. Approval для опасных действий (этап 11)

Approval — это **preflight всего плана**, а не проверка отдельного шага
после начала выполнения. Если в плане есть опасное действие, runtime
создаёт запись в `approvals` и возвращает `TaskResult` с
`pending_approval`; ни один шаг не выполняется.

Режимы `DELAMAIN_APPROVAL_MODE`:

| Режим | Когда нужен approval |
|---|---|
| `off` | никогда; поведение этапов 7–10 сохраняется |
| `dangerous` | если в плане есть действие с `dangerous=True` |
| `all` | если в плане есть хотя бы одно известное действие |

Неизвестное действие не создаёт approval: оно всё равно не сможет
выполниться и даст обычную ошибку `unknown action`. Это не ослабляет
защиту, потому что выполнение до такого шага не дойдёт.

Что происходит с планом:

```text
план [write_file, verify_file]
        │
        ▼
ApprovalPolicy.evaluate ──► нужен approval?
        │                         │
        │ да                      │ нет
        ▼                         ▼
approvals(status=pending)     task.start → шаги → task.finish
        │
        ├── /delamain approve <id> → статус approved → consume → выполнение
        └── /delamain reject <id>  → статус rejected, план не выполняется
```

Детали:

* `approvals` хранит `id`, `task_id`, `goal_id`, `task`, полный
  нормализованный `plan`, `dangerous_actions`, статус, причину и время
  решения;
* approval связан с целью Delamain, если план пришёл из очереди целей;
  ожидающая цель остаётся `pending` и **не** увеличивает `attempts` и не
  пишет failure в `skills`;
* после approve план выполняется ровно один раз: статус `approved`
  атомарно переходит в `consumed` до первого шага; повторный
  `/delamain approve` вернёт ошибку;
* reject переводит план в `rejected`, а связанную цель — в `failed` без
  записи skill-failure, потому что действия не выполнялись;
* approval применяется к планам от `HeuristicPlanner`, явного
  `metadata.plan` и `OllamaPlanner` — источник плана не важен;
* с этапа 16 repair-план проходит approval отдельно. Если он опасный,
  создаётся approval с `metadata.kind="step_repair"`; в metadata также
  лежат `prior_actions`, `prior_effective_actions`, `prior_steps`,
  `repair_count` и `failed_step`, поэтому после перезапуска задача
  продолжается с уже выполненными шагами. Pending repair не дублируется на
  каждом tick; reject завершает цель без выполнения repair-плана;
* `off` остаётся значением по умолчанию. Некорректное значение режима
  трактуется как `dangerous` (fail closed), а не как `off`.

Approval не является полноценной ОС-песочницей и не отменяет path-политику
`Sandbox`. Это дополнительный барьер перед необратимыми или
чувствительными действиями.

### 3.9. Мост когнитивных целей (этап 12)

`GoalBridge` связывает активную цель `GoalSubsystem` с очередью
Delamain. Мост **выключен по умолчанию** и включается отдельно:

```powershell
$env:DELAMAIN_ENABLED = "1"
$env:DELAMAIN_BRIDGE_ENABLED = "1"
python main_tray.py
```

Или `DELAMAIN_BRIDGE_ENABLED = True` в `config/simulation_config.py`.
Флаг читается при создании подсистемы; `/delamain on` включает runtime,
но не включает мост. Включать мост при выключенном Delamain бессмысленно:
без runtime и SQLite он ничего не делает.

Связь не угадывается по названию. Когнитивная цель должна явно нести
executable-payload:

```python
agent.set_goal(
    "Написать отчёт",
    command="запиши в notes/report.txt: ready",
    success_predicate="file_contains:notes/report.txt:ready",
)
```

Или payload можно добавить позже:

```python
agent.goal_subsystem.attach_execution(
    goal_id,
    command="проверь notes/report.txt на ready",
    success_predicate="file_contains:notes/report.txt:ready",
)
```

Поддерживаются `command`, явный `plan` и `success_predicate`. Если
payload нет, цель остаётся чисто когнитивной и в очередь не попадает.

Одна когнитивная цель порождает не более одной исполняемой цели.
Повторные `tick` не создают дублей; при потере in-memory ссылки мост
находит существующую цель по metadata в SQLite
(`bridge_source=goal_subsystem`, `cognitive_goal_id`, `cognitive_agent`).

Статусы моста:

| Статус | Что означает |
|---|---|
| `pending` | связанная цель создана, ещё не выполнялась |
| `in_progress` | была попытка или approval уже одобрен |
| `waiting_approval` | ждёт `/delamain approve` или `/delamain reject` |
| `done` | действие выполнено и predicate пройден |
| `failed` | reject, ошибка действия или невыполненный predicate |

`waiting_approval` не считается провалом когнитивной цели. Пока approval
не решён, цель остаётся активной и не дублируется. После approve мост
сразу синхронизируется: успех завершает когнитивную цель и активирует
следующую; reject переводит её в `failed` с причиной, но **не** пишет
skill-failure, потому что действия не выполнялись.

Success predicate проверяется только после успешного выполнения:

| Predicate | Проверка |
|---|---|
| пусто / `ok` / `execution_ok` | задача завершилась успешно |
| `file_exists:<path>` | файл существует в workspace |
| `file_contains:<path>:<text>` | файл содержит подстроку |

Неизвестный predicate трактуется fail-closed и не вызывает `eval`.
Если действие выполнено, а predicate не пройден, Delamain-цель остаётся
`done`, skill success сохраняется, но bridge-статус и когнитивная цель
становятся `failed` — агент переходит к следующей цели, а не зависает.

Связь видна в интерфейсе:

* `/delamain goals` — `cognitive=#<id>/<bridge_status>`;
* `/delamain status` — `linked`, `waiting`, `done`, `failed`;
* `/goals` — Delamain-цель активной когнитивной цели;
* `/goals list` и `/goals show <id>` — payload, proposal и решение;
* `/status` — сводка моста, если он включён.

Мост не является новым планировщиком и не добавляет прав: он вызывает
существующие `queue_goal()`, approval и `ActionRegistry`. Проваленная
когнитивная цель не перезапускается автоматически; для повтора нужна
новая цель или явное действие пользователя.

### 3.10. Authoring payload из чата (этап 13)

До этапа 13 payload приходилось добавлять из кода. Теперь его можно
привязать из чата явно:

```text
/goals exec 2 | запиши в notes/report.txt: ready
```

Или попросить planner построить **предложение**, а не выполнить его:

```text
/goals propose 2
/goals show 2
/goals accept 2
```

`GoalAuthoring` хранит в когнитивной цели два metadata-поля:

* `execution_proposal` — план, источник, файлы, опасные действия,
  `requires_approval`, `planner_error` и статус
  `pending`/`accepted`/`rejected`/`error`;
* `execution_decision` — кто и когда принял решение, какие опасные
  действия были видны и требовался ли approval.

Proposal **не исполняется** сам. До `accept` в SQLite Delamain не
создаётся ни одной цели. `accept` заново проверяет имена действий по
живому `ActionRegistry` и привязывает payload через
`GoalSubsystem.attach_execution()`. При наличии pending proposal ручной
`exec` просит сначала принять или отклонить его, а повторный `exec` не
перезаписывает существующий payload.

Ручной preview использует только `HeuristicPlanner`, чтобы `/goals exec`
не вызывал LLM неожиданно. Генерация proposal планировщиком выключена по
умолчанию:

```powershell
$env:DELAMAIN_GOAL_PROPOSAL_ENABLED = "1"
```

При выключенном флаге `/goals propose` возвращает ошибку; `/goals exec`
продолжает работать при включённом Delamain, потому что это явное действие
пользователя. Если preview построил план с неизвестным действием, payload
не привязывается.
Если эвристика вообще не поняла команду, payload привязывается с
`planner_error`: runtime planner попробует разобрать её при выполнении.

Опасные шаги, найденные в preview, видны в proposal даже при
`approval_mode=off`. Если preview не удался, proposal содержит
`planner_error`, а опасность будет проверена при выполнении. Если режим
`dangerous` или `all`, выполнение по-прежнему ждёт
`/delamain approve <id>`. При `off` чат явно предупреждает, что принятие
payload означает согласие на опасные действия без отдельного запроса.

### 3.11. Оценка возможностей (этап 17)

`src/delamain/evaluation.py` — офлайн-инструмент, который не входит в
runtime и не включается флагами. Он читает JSON-suite, валидирует схему и
запускает случаи в изолированных workspace/SQLite.

Execution-случай проходит через настоящий `DelamainSubsystem`, поэтому
проверяются sandbox, `ActionRegistry`, память, approval, repair и навыки.
План задаётся `ScriptedPlanner`; это измеряет исполнение, а не понимание
языка. Planning-случай отдельно вызывает `HeuristicPlanner` и сравнивает
план с ожидаемым.

```powershell
python -m src.delamain.evaluation --suite evals/delamain_stage17.json
```

`--json` печатает полный отчёт, `--report` сохраняет его, `--case`
фильтрует случаи, `--workdir` сохраняет артефакты, `--keep` оставляет
временный каталог, `--fail-under` задаёт порог pass rate.

`SuiteResult` содержит `pass_rate`, `runtime_success_rate`,
`expected_success_rate` (намеренные reject/escape исключены),
`recovery_rate`, `long_horizon_rate`, `skill_reuse_rate`, `safety_rate`,
`planning_accuracy`, счётчики repair/approval и разбивку по категориям.
Это regression-baseline, а не доказательство AGI.

### 3.12. Effector-контракт и core-driven шаг (этапы 18A–18B)

`src/core/effector_port.py` задаёт границу между ядром и слоем действия:
`EffectorRequest`, `EffectorResult`, `EffectorPort`, `step(cycle)` и
необязательный `EventSink`. Ядро владеет целями, временем и историей;
эффектор только исполняет явный запрос.

`DelamainEffectorAdapter` (`src/delamain/effector.py`) реализует контракт
поверх подсистемы:

* `submit()` создаёт ровно одну цель и сохраняет `request_id` в metadata
  (`effector_request_id`);
* повторный `submit()` с тем же payload после перезапуска возвращает
  текущее состояние, а не создаёт дубль;
* тот же id с другим payload даёт `EffectorConflict`;
* `poll()` только наблюдает и отображает `queued`, `waiting_approval`,
  `succeeded`, `failed`, `rejected`, `disabled` или `not_found`;
* `step(cycle)` делает не более одного шага за цикл и возвращает
  `EffectorResult` либо `None`;
* `status()` показывает флаг, `core_driven`, готовность runtime,
  счётчики запросов и последний шаг.

Адаптер доступен как `subsystem.effector` и `agent.delamain_effector`.
Флаг `DELAMAIN_EFFECTOR_ENABLED` по умолчанию `False`: без него
`submit()` выбрасывает `EffectorDisabled`, а runtime/БД/workspace не
создаются. Approval и sandbox не меняются.

При `DELAMAIN_EFFECTOR_CORE_DRIVEN=True` (тоже `False` по умолчанию)
`src/core/effector_driver.py` вызывает `step()` один раз за цикл ядра из
`DigitalBeing.tick_subsystems()`. Повторный цикл с тем же номером
пропускается. `DelamainSubsystem.tick()` в этом режиме исполняет только
мост и не вызывает `run_pending_goal()`. `run_effector_pending()`
выбирает лишь цели с `effector_request_id`; обычные legacy-цели остаются
pending до единой очереди этапа 20. `DELAMAIN_TICK_INTERVAL` продолжает
ограничивать частоту шагов. Новых таблиц, бюджета и истории нет. Если
core-driven включён без effector, цели не исполняются: это fail-safe,
видимый в `status()` как `core_driven_error`. `cancel` пока не
реализован: для него нужна единая очередь целей. Подробнее —
[INTEGRATION.md](INTEGRATION.md).

### 3.13. Бюджет действия (этап 19)

`src/core/action_budget.py` добавляет `ActionBudget` — единственную
точку решения о том, можно ли потратить энергию на попытку действия.
Ресурсом остаётся существующий `EnergySubsystem` агента: бюджет получает
getter/setter и не заводит второй запас, таблицу или очередь.

Флаг `ACTION_BUDGET_ENABLED=False` по умолчанию. Пока он выключен,
`DigitalBeing.act()` и Delamain расходуют энергию как раньше, а новые
резерв и потолок стоимости не применяются (legacy-путь сохранён
намеренно).

При включённом флаге:

* обычная попытка разрешается, только если после списания останется
  `ACTION_BUDGET_MIN_RESERVE` (по умолчанию `5.0`);
* стоимость одной попытки ограничивается
  `ACTION_BUDGET_MAX_ACTION_COST` (по умолчанию `20.0`), а факт
  усечения виден в `BudgetDecision.capped`;
* восстановительные действия (`repair`, `deep_rest`,
  `checkpoint_now`) могут пройти ниже резерва, иначе система потеряла бы
  способность восстанавливаться;
* отказ не списывает энергию и не выполняет побочный эффект;
* нулевая стоимость разрешена всегда, нечисловая или не конечная —
  отклоняется как `invalid_cost` (fail-closed);
* повторный вызов с тем же `action_id` в пределах процесса не списывает
  энергию второй раз.

В Delamain бюджет проверяется перед каждой попыткой цели: в `tick()`
(`_run_goal`), `run_now()`, `approve()` и в шаге эффектора. Идентификатор
попытки — `delamain-goal-<id>-attempt-<n>`; при отказе цель остаётся
`pending`, `summary["budget_denied"]` равен `True`, а `detail["budget"]`
содержит решение. Отказ не создаёт эпизод и не расходует approval:
после восстановления энергии ту же попытку можно повторить. Тик
останавливает перебор целей после первого отказа, потому что следующая
цель имеет ту же стоимость.

`subsystem.status()["budget"]` и
`agent.get_subsystems_status()["action_budget"]` показывают политику,
счётчики и последнее решение.

Границы этапа:

* решения и `action_id` живут только в памяти процесса; durable-таблицы
  бюджета нет, и перезапуск может списать ту же попытку снова;
* списание энергии и её чекпоинт не являются одной транзакцией;
* резерв проверяется в момент решения и не резервируется на будущее;
* несколько одновременных процессов не защищены общей транзакцией;
* бюджет не добавляет прав: sandbox и approval остаются обязательными.

## 4. Как запустить

Из корня проекта:

```powershell
# Список файлов в workspace
python -m src.delamain --root workspace --task "список файлов"

# Записать файл
python -m src.delamain --root workspace --task "запиши в notes/hello.txt: привет"

# Проверить результат
python -m src.delamain --root workspace --task "проверь notes/hello.txt на привет"

# Запомнить и вспомнить факт
python -m src.delamain --root workspace --task "запомни проект = Digital Being"
python -m src.delamain --root workspace --task "вспомни проект"
```

В CLI по умолчанию память лежит в `data/delamain/delamain.sqlite3`,
workspace — в `workspace/`. У подсистемы другие значения по умолчанию
(см. раздел 3.5). Оба пути CLI можно переопределить:

```powershell
python -m src.delamain `
  --root .\tmp\workspace `
  --db .\tmp\memory.sqlite3 `
  --task "список файлов"
```

Можно передать готовый план в JSON и обойти planner:

```powershell
@'
[
  {"action": "write_file", "args": {"path": "a.txt", "content": "hi"}},
  {"action": "verify_file", "args": {"path": "a.txt", "contains": "hi"}}
]
'@ | Set-Content -Encoding utf8 plan.json

python -m src.delamain `
  --root .\workspace `
  --task demo `
  --plan-file plan.json
```

Опциональный LLM-планировщик в CLI:

```powershell
# Один раз: скачать модель (пример, Apache-2.0; лицензию проверяйте сами)
ollama pull qwen2.5:7b-instruct

# Запустить задачу через локальную модель; при ошибке — эвристики
python -m src.delamain `
  --root .\workspace `
  --task "запиши в notes/llm.txt: привет" `
  --llm `
  --llm-model qwen2.5:7b-instruct
```

CLI не запускает Ollama сам. Если сервер не запущен или модель не скачана,
`FallbackPlanner` попробует эвристический план; это видно по результату,
но не по отдельному полю CLI. Для диагностики используйте
`/delamain status` в трей-режиме.

CLI умеет включать approval-preflight:

```powershell
python -m src.delamain `
  --root .\workspace `
  --task "запиши в notes/approval.txt: привет" `
  --approval-mode dangerous
```

Такой запуск выведет JSON с `pending_approval` и не создаст файл.
Подтвердить и выполнить план можно из трей-чата командой
`/delamain approve <id>`; approve/reject в CLI не добавлялись, чтобы не
смешивать предпросмотр и решение пользователя.

### 4.1. Команды в трей-чате

Если агент запущен через `main_tray.py`, слой доступен командами:

| Команда | Что делает |
|---|---|
| `/delamain` или `/delamain status` | состояние, пути, счётчики целей |
| `/delamain on` | включить и создать runtime |
| `/delamain off` | выключить автономные тики (runtime не закрывается) |
| `/delamain run <задача>` | выполнить задачу сразу |
| `/delamain goal <название> \| <команда>` | поставить durable-цель в очередь |
| `/delamain goals` | показать цели, попытки, `retry_at`, replan, approval и связь с когнитивной целью |
| `/delamain skills` | показать навыки, успехи/ошибки и сохранённые шаги |
| `/delamain approvals [status]` | показать approvals; по умолчанию `pending` |
| `/delamain approve <id>` | подтвердить и выполнить сохранённый план один раз |
| `/delamain reject <id> [причина]` | отклонить план и завершить его цель как `failed` |
| `/goals list` | все когнитивные цели, payload и proposal |
| `/goals show <id>` | подробности цели, команды, плана и proposal |
| `/goals exec <id> \| <команда>` | явно привязать payload к когнитивной цели |
| `/goals exec <id> \| <команда> \| <predicate>` | то же с success predicate |
| `/goals propose <id> [\| <задача>]` | сохранить proposal без исполнения |
| `/goals accept <id>` | принять proposal и привязать payload |
| `/goals reject <id> [причина]` | отклонить proposal |

Примеры:

```text
/delamain run запиши в notes/hello.txt: привет
/delamain goal Проверить заметку | проверь notes/hello.txt на привет
/delamain goals
/delamain approvals
/delamain approve appr-0123456789ab
/delamain reject appr-0123456789ab не сейчас
/goals exec 2 | запиши в notes/report.txt: ready | file_contains:notes/report.txt:ready
/goals propose 2
/goals accept 2
```

### 4.2. Включение через окружение и config

```powershell
# Только на текущий запуск
$env:DELAMAIN_ENABLED = "1"
python main_tray.py
```

Переменные окружения:

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `DELAMAIN_ENABLED` | `0` | главный выключатель (алиас: `DELAMAIN_LOCAL_ENABLED`) |
| `DELAMAIN_TICK_INTERVAL` | `20` | раз в сколько автономных циклов пробовать цель |
| `DELAMAIN_MAX_GOALS_PER_TICK` | `1` | сколько целей максимум за один tick |
| `DELAMAIN_MAX_ATTEMPTS` | `1` | попыток на цель; `1` = без повторов |
| `DELAMAIN_RETRY_BACKOFF_SEC` | `0` | базовая пауза между попытками; `0` = без паузы |
| `DELAMAIN_RETRY_BACKOFF_MAX_SEC` | `300` | верхняя граница экспоненциальной паузы |
| `DELAMAIN_REPLAN_ON_FAILURE` | `0` | на повторе строить новый план вместо сохранённого |
| `DELAMAIN_REPLAN_WITH_CONTEXT` | `0` | передать planner'у контекст упавшего шага (вместе с replan) |
| `DELAMAIN_STEP_REPAIR_ENABLED` | `0` | repair оставшейся части плана после ошибки шага |
| `DELAMAIN_MAX_STEP_REPAIRS` | `1` | сколько repair-сегментов разрешено в одной задаче |
| `DELAMAIN_MAX_REPAIR_STEPS` | `5` | максимум шагов в одном repair-плане |
| `DELAMAIN_MAX_FILE_BYTES` | `1000000` | лимит файла в песочнице |
| `DELAMAIN_WORKSPACE` | `data/delamain/workspace` | корень файловой песочницы |
| `DELAMAIN_DB` | `data/delamain/delamain.sqlite3` | путь к SQLite |
| `DELAMAIN_LLM_ENABLED` | `0` | включить Ollama-планировщик (нужен и `DELAMAIN_ENABLED`) |
| `DELAMAIN_LLM_BASE_URL` | `http://127.0.0.1:11434` | базовый URL Ollama |
| `DELAMAIN_LLM_MODEL` | `qwen2.5:7b-instruct` | имя модели; пример, не входит в проект |
| `DELAMAIN_LLM_TIMEOUT` | `20.0` | таймаут HTTP-запроса, секунд |
| `DELAMAIN_LLM_MAX_STEPS` | `12` | максимум шагов в плане модели |
| `DELAMAIN_LLM_TEMPERATURE` | `0.0` | температура генерации |
| `DELAMAIN_APPROVAL_MODE` | `off` | approval: `off`, `dangerous` или `all` |
| `DELAMAIN_BRIDGE_ENABLED` | `0` | мост активной когнитивной цели в Delamain |
| `DELAMAIN_GOAL_PROPOSAL_ENABLED` | `0` | разрешить `/goals propose`; ручной `exec` работает без этого флага при включённом Delamain |
| `DELAMAIN_EFFECTOR_ENABLED` | `0` | включить core-owned effector adapter; без него `submit()` даёт `EffectorDisabled` |
| `DELAMAIN_EFFECTOR_CORE_DRIVEN` | `0` | ядро делает один шаг эффектора за цикл; требует `DELAMAIN_EFFECTOR_ENABLED=1` |

Те же значения есть в `config/simulation_config.py` как `DELAMAIN_*`.
Env имеет приоритет над config.

Пример включения:

```powershell
$env:DELAMAIN_ENABLED = "1"
$env:DELAMAIN_LLM_ENABLED = "1"
$env:DELAMAIN_LLM_MODEL = "qwen2.5:7b-instruct"
python main_tray.py
```

Если Ollama недоступен, подсистема продолжит работать на эвристиках.
`/delamain status` покажет режим планировщика, модель, URL и последнюю
ошибку модели.

Пример с approval:

```powershell
$env:DELAMAIN_ENABLED = "1"
$env:DELAMAIN_APPROVAL_MODE = "dangerous"
python main_tray.py
```

Теперь `/delamain run запиши в a.txt: x` и опасные цели будут ждать
`/delamain approve <id>`. `dangerous` включает approval для `write_file` и
`set_self_model`; `all` — для любого известного действия.

Пример с repair (по умолчанию выключен):

```powershell
$env:DELAMAIN_ENABLED = "1"
$env:DELAMAIN_STEP_REPAIR_ENABLED = "1"
$env:DELAMAIN_MAX_STEP_REPAIRS = "1"
$env:DELAMAIN_MAX_REPAIR_STEPS = "5"
python main_tray.py
```

`/delamain status` показывает `Repair: on, max_segments=1, max_steps=5`.
Если repair-план опасный, `/delamain approvals` помечает его как
`repair-план`, а pending-сообщение говорит, сколько шагов уже выполнено.

## 5. Тесты

```powershell
python -m pytest `
  tests/test_delamain_sandbox.py `
  tests/test_delamain_memory.py `
  tests/test_delamain_planner.py `
  tests/test_delamain_runtime.py `
  tests/test_delamain_llm_planner.py `
  tests/test_delamain_approval.py `
  tests/test_delamain_goal_bridge.py `
  tests/test_delamain_goal_authoring.py `
  tests/test_delamain_step_repair.py `
  tests/test_delamain_effector.py `
  tests/test_effector_driver.py `
  tests/test_delamain_subsystem.py `
  tests/test_delamain_evaluation.py -q
```

Проверяется:

* запрет выхода из workspace;
* лимиты размера и бинарные файлы;
* список/поиск с исключением служебных каталогов;
* эпизоды, факты, FTS, self-model, цели, навыки;
* остановка плана на первой ошибке;
* запись `task.start` / `task.finish` и `planned_actions`;
* эвристический planner для русских и английских команд;
* ленивое включение подсистемы и отсутствие runtime по умолчанию;
* очередь целей, интервал tick, успех/ошибка и запись skill;
* переиспользование успешного навыка только для той же команды;
* повторные попытки до `DELAMAIN_MAX_ATTEMPTS` и переход в `failed`;
* отложенный retry по durable `next_retry_at` и ограничение backoff;
* replan на повторе строит новый план и обходит explicit/skill-план;
* выключенный replan сохраняет поведение этапа 9;
* отображение `retry_at` и replan в `/delamain goals` и `/delamain status`;
* repair по умолчанию выключен; env-флаги включают его и задают лимиты;
* repair заменяет оставшуюся часть плана и не выполняет выброшенный хвост;
* repair отклоняет повтор `action + args`, дубликаты, неизвестные действия
  и слишком большой план;
* бюджет `DELAMAIN_MAX_STEP_REPAIRS` останавливает повторные repair;
* контекст repair содержит упавший шаг, `remaining_steps` и успешный путь;
* опасный repair создаёт отдельный durable approval; approve продолжает
  задачу с сохранёнными шагами, reject завершает её без выполнения;
* repair approval переживает перезапуск и не дублируется на tick;
* skill после repair пишется по `effective_actions`, без упавшего шага;
* `/delamain status`, `goals`, `approvals` и pending-сообщение показывают
  repair-режим и прогресс;
* evaluation-suite загружается и валидируется, duplicate id и неизвестные
  поля отклоняются;
* execution-случаи изолированы, проверяют файлы/историю/метрики;
* recovery, durable repair-approval, reject и sandbox escape измеряются;
* точный skill reuse не вызывает planner повторно;
* planning probes ловят неподдерживаемую фразу, CLI пишет JSON и соблюдает
  `--fail-under`;
* слияние metadata цели без потери `command`/`plan`;
* регистрация `DelamainSubsystem` в `DigitalBeing` и команды `/delamain`,
  включая `/delamain skills`;
* парсинг и валидация JSON-плана LLM, fenced/OpenAI-подобные ответы,
  неизвестные действия, лимит шагов и ошибки транспорта;
* fallback на эвристики при сбое LLM и комбинированная ошибка, если не
  сработали оба планировщика;
* привязка live `ActionRegistry` к планировщику и выполнение LLM-плана
  в sandbox через fake requester (без реальной сети);
* статус планировщика в подсистеме: выключен по умолчанию, `ollama:...+fallback`
  и откат при некорректной конфигурации;
* `off`-режим approval сохраняет прежнее выполнение `write_file`;
* pending approval не выполняет действия и не пишет `task.start`;
* approve выполняет сохранённый план ровно один раз, reject — не выполняет;
* `all`-режим, план от planner, переживание approval после перезапуска;
* ожидающая approval цель не считается failed и не дублирует approval;
* fail-closed при некорректном `DELAMAIN_APPROVAL_MODE`;
* команды `/delamain approvals`, `approve`, `reject` и статус approval;
* effector Stage 18A: default-off, идемпотентный submit, конфликт payload,
  restart pending approval, reject и sandbox escape;
* core-driven Stage 18B: пассивный tick, один шаг за цикл, duplicate
  cycle, interval, изоляция legacy-целей, fail-safe без effector и
  wiring драйвера в `DigitalBeing`;
* бюджет Stage 19: default-off, резерв, потолок стоимости,
  восстановительные действия, отказ без побочного эффекта, пустая трата
  при невалидной стоимости, идемпотентность `action_id`, `act()`,
  Delamain `tick`/`run_now`/`approve` и шаг эффектора;
* мост Stage 12: дедупликация, approval/reject, predicate, следующая цель;
* ручной `/goals exec`, pending/accept/reject proposal и decision в metadata;
* proposal выключен по умолчанию, неизвестные actions отклоняются до attach;
* опасный proposal проходит существующий approval, а LLM-план не
  исполняется без `accept`;
* команды `/goals list`, `show`, `exec`, `propose`, `accept`, `reject`.

## 6. Что пока не сделано

Честный список ограничений:

* **LLM опционален и ограничен.** Поддерживается только native Ollama
  `/api/chat`; OpenAI-совместимый endpoint, streaming и автоматический
  выбор модели не реализованы. Качество плана зависит от модели; ядро
  не гарантирует, что модель поймёт задачу.
* **Repair ограничен и не откатывает побочные эффекты.** С этапа 16
  planner может заменить оставшуюся часть плана после ошибки, но не после
  каждого успешного шага. Repair не умеет отменять уже выполненные
  действия: если упавший шаг успел изменить файл, это изменение остаётся.
  Нет выбора из нескольких repair-кандидатов, проверки предусловий и
  компенсирующих действий.
* **Автономия ограничена очередью.** Подсистема сама выбирает только уже
  поставленные цели с явной командой или планом. Она не придумывает новые
  цели; связь с когнитивной целью появляется только при явном payload или
  после `/goals accept`.
* **Proposal не автоматический.** `/goals propose` вызывается вручную и по
  умолчанию выключен. Нет фонового «предложи план для каждой новой цели».
* **Approval — не полноценная песочница.** По умолчанию он выключен;
  включение `dangerous`/`all` защищает от случайной перезаписи и
  self-model изменений, но не изолирует процесс ОС. `Sandbox` остаётся
  единственной path-политикой.
* **Действий пока мало.** Нет удаления файлов, запуска кода и сети, поэтому
  approval проверяет только те действия, которые есть в реестре. Новые
  опасные действия должны явно помечаться `dangerous=True`.
* **Повторы ограничены.** Backoff, replan и step repair включаются явно.
  Replan с контекстом срабатывает только на retry и до
  `DELAMAIN_MAX_ATTEMPTS`; repair — только после ошибки шага и до
  `DELAMAIN_MAX_STEP_REPAIRS`. Нет бесконечного самоисправления и нет
  перестройки плана после каждого успешного шага.
* **Переиспользование навыков консервативное.** План берётся только при
  точном совпадении названия и команды; семантического поиска похожих задач
  пока нет.
* **Нет полноценной проверки смысла.** `verify_file` проверяет факт, но не
  «правильность» решения.
* **Оценка узкая.** 18 случаев — smoke/baseline, а не статистически
  значимый бенчмарк. Execution-планы заданы данными, planning probes
  покрывают только регулярные выражения эвристики; общий язык, сеть и
  внешние API не оцениваются.
* **Эффектор — первый единый драйвер, но не вся очередь.** С этапа 18B
  ядро делает один шаг effector-цели за цикл, а tick подсистемы в этом
  режиме пассивен. Однако обычные legacy-цели остаются pending до этапа
  20; нет `cancel` и единой истории; идемпотентность ищет `request_id`
  сканированием metadata, без индекса.
* **Бюджет не durable.** С этапа 19 попытка действия проходит через
  `ActionBudget`, но решения и `action_id` живут только в памяти
  процесса. Перезапуск может списать ту же попытку повторно; списание и
  чекпоинт энергии не атомарны; резерв не резервируется на будущее, а
  проверяется в момент решения.
* **Самоизменение кода не реализовано.** Approval и sandbox для этого уже
  есть, но нужны отдельные тесты и откат; менять исходники агента
  самостоятельно он пока не может.

## 7. Следующие шаги

1. Этап 18B завершён: ядро делает один шаг effector-цели за цикл, без
   второго tick-цикла, дублей и потери pending approval. Ограничение —
   legacy-цели ждут единой очереди.
2. Этап 19 завершён: одно бюджетное решение на попытку поверх
   существующей энергии, с резервом и потолком стоимости. Ограничение —
   бюджет не durable и не атомарен с чекпоинтом.
3. Этап 20: единая очередь когнитивных и исполняемых целей и `cancel`.
4. Этап 21: единая история: связать эпизоды действий с идентичностью,
   целями и временем ядра.
5. После интеграции — параметризованные и составные навыки: переиспользование
   успешного плана для близкой задачи с другими аргументами, без ослабления
   approval, sandbox и проверки предусловий.
6. Расширить evaluation-suite случаями переноса, компенсаций, restart и
   life-continuity; отдельно измерять вклад LLM-планировщика.
7. Развивать repair: компенсирующие действия для уже выполненных шагов,
   проверка предусловий и выбор из нескольких кандидатов вместо первого
   валидного плана.
8. Поддержать OpenAI-совместимый endpoint (llama.cpp/LM Studio) как
   альтернативу Ollama, сохранив fallback и валидацию.
9. Добавить удаление файлов и запуск кода только вместе с отдельной
   политикой sandbox/approval и тестами.
10. Дать возможность редактировать отдельные шаги proposal, а не только
    принимать его целиком.

Дорожная карта перехода к одному существу и границы власти описаны в
[INTEGRATION.md](INTEGRATION.md).
