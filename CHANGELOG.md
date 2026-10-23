# Changelog

All notable changes to Digital Being are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### 2026-10-23 — Core-driven effector (этап 18B)

* **Единый драйвер** — новый `src/core/effector_driver.py`: ядро вызывает
  `effector.step(cycle)` не более одного раза за цикл, повторный номер
  цикла пропускается, ошибка эффектора не останавливает `tick_subsystems()`.
* **Контракт** — `EffectorPort` получил `step(cycle)`; `submit()`, `poll()`
  и `status()` не изменились.
* **Адаптер** — `DelamainEffectorAdapter.step()` выполняет не более одной
  pending-цели с `effector_request_id` и возвращает `EffectorResult`.
* **Подсистема** — `DelamainSubsystem` получил `core_driven`,
  `run_effector_pending()` и пассивный `tick()` в core-driven режиме;
  `status()` показывает `execution_driver` и `core_driven_error`.
* **Агент** — `DigitalBeing.tick_subsystems()` вызывает драйвер после
  реестра; `agent.effector_driver` доступен для диагностики, а
  `get_subsystems_status()` включает его снимок.
* **Флаг** — `DELAMAIN_EFFECTOR_CORE_DRIVEN=False`. Требует
  `DELAMAIN_EFFECTOR_ENABLED=True`; без effector цели не исполняются
  (fail-safe). `DELAMAIN_TICK_INTERVAL` продолжает ограничивать частоту.
* **Границы** — новых таблиц, миграций, бюджета, очереди и истории нет.
  В core-driven режиме обычные legacy-цели Delamain остаются pending до
  единой очереди этапа 20; это явное ограничение, а не второй драйвер.
* **Тесты** — новый `tests/test_effector_driver.py` (4 теста); в
  `tests/test_delamain_effector.py` добавлено 6 тестов: пассивный tick,
  один шаг, interval, изоляция legacy-целей, restart approval, env-флаг и
  wiring в `DigitalBeing`. Обновлён `tests/test_delamain_subsystem.py`
  для default-off драйвера.
* **Проверка** — `tests/test_effector_driver.py` +
  `tests/test_delamain_effector.py`: 21 passed;
  `tests/test_plugin_system.py` + `tests/test_delamain_subsystem.py`:
  51 passed. Полный прогон — `601 passed, 2 skipped in 780.74s (0:13:00)`.
* **Версия Delamain** — `0.11.0`.
* **Документация** — `docs/STAGE18B_REPORT.md`, обновлены
  `docs/INTEGRATION.md`, `docs/ARCHITECTURE.md`, `docs/DELAMAIN_LOCAL.md`,
  `docs/USAGE.md`, `docs/INDEX.md` и `README.md`.

### 2026-10-23 — Core-owned effector contract (этап 18A)

* **Архитектурное решение** — Delamain не включается как второй агент.
  Ядро владеет идентичностью, целями, временем, бюджетом и историей;
  Delamain становится его эффектором. Дорожная карта 18B–24 —
  `docs/INTEGRATION.md`.
* **Контракт ядра** — новый `src/core/effector_port.py`: `EffectorRequest`,
  `EffectorResult`, `EffectorStatus`, `EffectorPort`, `EffectorError`,
  `EffectorDisabled`, `EffectorConflict` и `EventSink`. Контракт не
  импортирует Delamain. `cancel` отложен до появления единой очереди.
* **Идемпотентный адаптер** — `src/delamain/effector.py`:
  `submit()` создаёт ровно одну durable цель, `poll()` только наблюдает,
  `status()` отдаёт диагностику. `request_id` хранится в metadata
  (`effector_request_id`), повторный submit после перезапуска не создаёт
  дубль, а тот же id с другим payload даёт `EffectorConflict`.
* **Интеграция** — `DelamainSubsystem` создаёт `subsystem.effector`,
  принимает `effector_enabled` и публикует статус эффектора;
  `DigitalBeing` публикует `agent.delamain_effector`. Версия Delamain —
  `0.10.0`.
* **Флаг** — `DELAMAIN_EFFECTOR_ENABLED=False`. При выключении `submit()`
  выбрасывает `EffectorDisabled`, runtime/БД/workspace не создаются;
  обычное поведение агента не меняется.
* **Безопасность** — sandbox и approval не меняются. Опасный запрос
  переходит в `waiting_approval` без side effects; approve выполняет его
  один раз, reject даёт `rejected` и не создаёт файл.
* **Тесты** — новый `tests/test_delamain_effector.py` (11 тестов):
  валидация, default-off, идемпотентность, конфликт, approval/reject,
  restart, sandbox escape, статусы и ошибка event sink. Все Delamain-тесты:
  156 passed. Полный прогон — `591 passed, 2 skipped` (20:01).
* **Ограничения** — единый цикл, бюджет, `cancel`, единая очередь и
  machine-readable life-continuity suite ещё не реализованы. Это контракт
  и адаптер, а не доказательство AGI.
* **Версия ядра** — `0.10.0`.
* **Документация** — `docs/INTEGRATION.md`, `docs/STAGE18_REPORT.md`;
  обновлены README, `docs/INDEX.md`, `docs/ARCHITECTURE.md`,
  `docs/DELAMAIN_LOCAL.md` и `docs/USAGE.md`.

### 2026-10-22 — Delamain-local: измеримая оценка возможностей (этап 17)

* **Офлайн-suite** — `evals/delamain_stage17.json`, 18 data-only случаев:
  базовое исполнение, длинный горизонт, восстановление после ошибки,
  approval/sandbox, точное переиспользование навыка и planning probes.
* **`src/delamain/evaluation.py`** — загрузчик и валидатор suite,
  `ScriptedPlanner`, execution/planning runners, агрегация метрик и CLI.
  Каждый execution-случай получает отдельные workspace и SQLite; ошибка
  одного случая не обрывает остальные.
* **Метрики** — `pass_rate`, `runtime_success_rate`, отдельный
  `expected_success_rate` (исключает намеренные reject/escape случаи),
  `recovery_rate`, `long_horizon_rate`, `skill_reuse_rate`, `safety_rate`,
  `planning_accuracy`, repair/approval counters и разбивка по категориям.
* **CLI** — `python -m src.delamain.evaluation --suite ...` с `--json`,
  `--report`, `--case`, `--workdir`, `--keep`, `--fail-under`.
* **Изоляция** — evaluator не импортируется runtime и не добавляет
  действий, сети или прав исполнения. `ScriptedPlanner` проверяет runtime,
  а planning probes — только текущую эвристику, не общее понимание языка.
* **Результат baseline** — 18/18 случаев, `pass_rate=1.0`,
  `runtime_successes=9/12`, `expected_success_rate=9/9`, 3 repair-запуска,
  4 pending approval (2 approved, 2 rejected).
* **Тесты** — новый `tests/test_delamain_evaluation.py` (29 тестов):
  валидация suite, изоляция, repair/approval/reject, sandbox escape,
  skill reuse, planning probes, метрики и CLI.
* **Полный прогон** — `python -m pytest -q`: 580 passed, 2 skipped
  (включая 16 benchmark-тестов).
* **Версия ядра** — `0.9.0`.
* **Документация** — `docs/STAGE17_REPORT.md`, `evals/README.md`;
  обновлены README, `docs/INDEX.md`, `docs/ARCHITECTURE.md`,
  `docs/BASELINE.md`, `docs/USAGE.md`, `docs/DELAMAIN_LOCAL.md`.

### 2026-10-22 — Delamain-local: bounded repair внутри одной попытки

* **Новые флаги** — `DELAMAIN_STEP_REPAIR_ENABLED=False`,
  `DELAMAIN_MAX_STEP_REPAIRS=1`, `DELAMAIN_MAX_REPAIR_STEPS=5`. По
  умолчанию поведение этапов 9–15 не меняется.
* **Replacement-семантика** — после ошибки шага planner получает
  `remaining_steps` и возвращает замену оставшейся части плана, а не
  вставку перед старым хвостом. Выброшенный хвост не выполняется.
* **Ограничения** — repair-план не может повторять уже предпринятый
  `action + args`, содержать дубликаты, неизвестные действия или больше
  `DELAMAIN_MAX_REPAIR_STEPS` шагов. Число принятых repair-сегментов
  ограничено `DELAMAIN_MAX_STEP_REPAIRS`; отклонённый план бюджет не
  расходует, но задача сразу завершается ошибкой исходного шага.
* **Контекст** — новый `src/delamain/context.py` собирает компактный
  failure-context: `stage`, `failed_step`, `action`, `args`, `error`,
  `output`, `completed_steps`, `remaining_steps`, `repair_count`. Контекст
  ограничен по размеру и общий для durable replan и repair.
* **Durable repair-approval** — опасный repair проходит тот же
  approval-preflight и создаёт approval с `metadata.kind="step_repair"` и
  сохранёнными `prior_actions`, `prior_effective_actions`, `prior_steps`,
  `repair_count`, `failed_step`. После approve задача продолжается с
  выполненными шагами; reject завершает цель как `failed`. Pending repair
  переживает перезапуск и не дублируется на следующих tick.
* **Результат** — `TaskResult` различает `planned_actions` (всё
  попробованное), `effective_actions` (успешный путь), `steps_before` и
  `repair_count`. Skill после repair пишется по `effective_actions`, без
  упавших шагов.
* **LLM prompt** — `OllamaPlanner.replan()` передаёт
  `remaining_steps` как недоверенные данные, просит вернуть замену остатка
  и не повторять `action + args` из `completed_steps` или упавшего шага;
  контекст ограничен 6000 символами.
* **Наблюдаемость** — `/delamain status` показывает
  `Repair: on/off, max_segments=..., max_steps=...`;
  `/delamain goals` — `repairs=N`; `/delamain approvals` помечает
  `repair-план`; pending-сообщение говорит, сколько шагов уже выполнено;
  результат выполнения содержит `repair=N`.
* **Безопасность** — planner не получает прав на исполнение; repair идёт
  через тот же `ActionRegistry`, sandbox и approval. Побочные эффекты уже
  выполненных шагов не откатываются, и это явно задокументировано.
* **17 новых тестов** — default-off и env-флаги, replacement, запрет
  повтора, неизвестное действие и внутренний дубликат, лимит размера,
  бюджет, два последовательных сегмента, отсутствие упавших шагов в
  `completed_steps`, durable approval с перезапуском runtime и подсистемы,
  approval во время resume, reject с прогрессом, skill по effective-path,
  pending без дублей и отображение в `/delamain`.
* **Проверка** — `535 passed, 2 skipped` без benchmarks и `16 passed`
  benchmarks; суммарно `551 passed, 2 skipped`.
* **Документация** — `docs/STAGE16_REPORT.md`; обновлены
  `docs/DELAMAIN_LOCAL.md`, `docs/INDEX.md`, `docs/ARCHITECTURE.md`,
  `docs/BASELINE.md`, `docs/USAGE.md`, README и CHANGELOG.

### 2026-10-22 — Delamain-local: replan с контекстом упавшего шага

* **Новый флаг** — `DELAMAIN_REPLAN_WITH_CONTEXT=False`. Работает только
  вместе с `DELAMAIN_REPLAN_ON_FAILURE=1`; по умолчанию поведение этапов
  9–14 не меняется.
* **Контекст ошибки** — после неудачи в metadata цели сохраняется
  `last_failure_context`: `stage`, `attempt`, `failed_step`, `action`,
  `args`, `error`, `output`, `completed_steps`. Контекст ограничен по
  размеру, переживает перезапуск и очищается после успеха.
* **Replan API** — `DelamainRuntime.run_task(..., failure_context=...)`
  вызывает `planner.replan(task, context)`, если метод есть. Добавлены
  `replan()` у `HeuristicPlanner`, `FallbackPlanner` и `OllamaPlanner`.
  `FallbackPlanner` по-прежнему откатывается на эвристику при ошибке.
* **LLM prompt** — `OllamaPlanner.replan()` передаёт контекст как
  недоверенные данные и просит не повторять ту же ошибку; контекст
  ограничен 4000 символами.
* **Наблюдаемость** — `/delamain status` показывает
  `context=on|off`; `/delamain goals` — `replan=next(context)`; результат
  ошибки сообщает, что повтор будет с контекстом.
* **Безопасность** — новых действий и прав нет; replan идёт через тот же
  `ActionRegistry`, sandbox и approval. Pending approval, reject и
  `run_now()` контекст не используют.
* **5 новых тестов** — контекст и его durable-переживание, ошибка
  планирования, default-off, передача контекста в `FallbackPlanner.replan()`
  и в prompt `OllamaPlanner.replan()`.
* **Проверка** — `518 passed, 2 skipped` без benchmarks и `16 passed`
  benchmarks; суммарно `534 passed, 2 skipped`.
* **Документация** — `docs/STAGE15_REPORT.md`; обновлены
  `docs/DELAMAIN_LOCAL.md`, `docs/INDEX.md`, `docs/ARCHITECTURE.md`,
  `docs/BASELINE.md`, `docs/USAGE.md`, README и CHANGELOG.

### 2026-10-22 — Delamain-local: bounded backoff и replan после ошибки

* **Backoff** — `DELAMAIN_RETRY_BACKOFF_SEC` задаёт базовую паузу,
  `DELAMAIN_RETRY_BACKOFF_MAX_SEC` — верхнюю границу. Задержка растёт
  экспоненциально (`base * 2^(attempt-1)`) и хранится в metadata цели как
  `next_retry_at`, поэтому переживает перезапуск.
* **Durable-расписание** — `run_pending_goal()` пропускает pending-цель до
  наступления `next_retry_at`; другие готовые цели не блокируются. При
  `base=0` поведение этапа 9 сохраняется.
* **Replan** — `DELAMAIN_REPLAN_ON_FAILURE=1` заставляет следующую попытку
  игнорировать explicit `metadata.plan` и skill-план и заново вызывать
  активный planner. Число попыток по-прежнему ограничено
  `DELAMAIN_MAX_ATTEMPTS`.
* **Наблюдаемость** — в metadata добавляются `retry_delay_sec`,
  `next_retry_at`, `replan_on_next_attempt`, `last_attempt_replanned`,
  `replan_count`. `/delamain goals` показывает `retry_at`/`replan`,
  `/delamain status` — backoff/cap/replan, результат ошибки сообщает о
  следующей попытке.
* **Безопасность** — pending approval не запускает retry/backoff, reject
  завершает цель без повтора, `run_now()` не использует backoff. Опасные
  планы по-прежнему проходят существующий approval.
* **Совместимость** — новые флаги выключены по умолчанию; схема SQLite не
  менялась.
* **5 новых тестов** — deferred retry по `next_retry_at`, cap backoff,
  replan с новым планом, обход explicit и skill-плана, default-off и
  отображение в чате.
* **Целевой прогон:** `23 passed`; совместно со Stage 12/13 — `35 passed`.
* **Полный suite:** `513 passed, 2 skipped` без benchmarks +
  `16 passed` benchmarks; суммарно `529 passed, 2 skipped`.
* **Документация** — `docs/STAGE14_REPORT.md`; обновлены
  `docs/DELAMAIN_LOCAL.md`, `docs/INDEX.md`, `docs/ARCHITECTURE.md`,
  `docs/BASELINE.md`, `docs/USAGE.md`, README и CHANGELOG.

### 2026-10-22 — Delamain-local: безопасный authoring payload

* **`GoalExecutionProposal`** — новый модуль
  `src/delamain/goal_authoring.py`: описание команды или плана, затронутых
  файлов, опасных действий, текущего approval-режима и статуса
  `pending`/`accepted`/`rejected`/`error`.
* **`GoalAuthoring`** — ручной `/goals exec`, planner-proposal, `accept` и
  `reject`. Proposal и решение сохраняются в metadata когнитивной цели
  (`execution_proposal`, `execution_decision`), переживают checkpoint.
* **Команды чата** — `/goals list`, `/goals show`, `/goals exec`,
  `/goals propose`, `/goals accept`, `/goals reject`; `/goals` сохраняет
  прежний краткий вывод.
* **Безопасность** — proposal сам не исполняется, неизвестные действия
  отклоняются до attach, повторный payload не перезаписывается, опасные
  шаги проходят существующий approval. При `approval_mode=off` чат явно
  предупреждает, что принятие payload означает согласие на опасные
  действия без отдельного запроса.
* **Конфигурация** — ручной `/goals exec` не требует отдельного флага, но
  работает при включённом Delamain; `DELAMAIN_GOAL_PROPOSAL_ENABLED=False`
  по умолчанию разрешает только `/goals propose`. Для исполнения
  по-прежнему нужны `DELAMAIN_ENABLED=1` и
  `DELAMAIN_BRIDGE_ENABLED=1`.
* **15 новых тестов** — manual attach, pending/accept/reject, отказ от
  дублей, выключенный Delamain без создания runtime, неизвестные действия,
  dangerous-план через approval, отсутствие LLM, LLM-план только как
  proposal, команды чата и predicate.
* **Целевой прогон:** `28 passed` (15 новых + 13 Stage 12).
* **Полный suite:** `524 passed, 2 skipped in 949.61s (0:15:49, включая
  benchmarks)`.
* **Документация** — `docs/STAGE13_REPORT.md`; обновлены
  `docs/DELAMAIN_LOCAL.md`, `docs/INDEX.md`, `docs/ARCHITECTURE.md`,
  `docs/BASELINE.md`, `docs/USAGE.md`, README и CHANGELOG.

### 2026-10-22 — Delamain-local: мост когнитивных и исполняемых целей

* **`GoalBridge`** — новый опциональный слой `src/delamain/goal_bridge.py`.
  Активная цель `GoalSubsystem` с явным `goal["execution"]` получает ровно
  одну связанную цель Delamain; без payload мост ничего не делает.
* **Один к одному без дублей** — повторные `tick` не создают новых целей,
  а потерянная in-memory ссылка восстанавливается по metadata SQLite
  (`bridge_source`, `cognitive_goal_id`, `cognitive_agent`).
* **Статусы моста** — `pending`/`in_progress`/`waiting_approval`/`done`/
  `failed`; ожидание approval не считается провалом когнитивной цели.
* **Approval и reject** — approve выполняет план и завершает когнитивную
  цель; reject переводит её в `failed` с понятной причиной, но не пишет
  skill-failure, потому что действия не выполнялись.
* **Success predicate** — безопасные проверки `ok`, `file_exists:<path>` и
  `file_contains:<path>:<text>`; неизвестный predicate fail-closed, без
  `eval`. Невыполненный predicate оставляет Delamain-действие успешным, но
  помечает bridge и когнитивную цель как `failed`.
* **Прогресс и следующая цель** — мост обновляет `_goal_progress` и после
  успеха активирует следующую цель; для провала добавлен
  `GoalSubsystem.fail_goal()`.
* **Интерфейс** — `/delamain goals` показывает `cognitive=#<id>/<status>`,
  `/delamain status` — сводку `linked/waiting/done/failed`, `/goals` и
  `/status` — связь активной цели.
* **Конфигурация** — `DELAMAIN_BRIDGE_ENABLED=False` по умолчанию; без
  одновременного включения Delamain и моста поведение этапов 7–11 не
  меняется.
* **13 новых тестов** — дедупликация, approval/reject, predicate,
  потерянная ссылка, следующая цель, статусы и команды чата.
* **Полный прогон:** `509 passed, 2 skipped in 1193.76s` (включая benchmarks).
* **Документация** — `docs/STAGE12_REPORT.md`; обновлены
  `docs/DELAMAIN_LOCAL.md`, `docs/INDEX.md`, `docs/ARCHITECTURE.md`,
  `docs/BASELINE.md`, `docs/USAGE.md`, README и CHANGELOG.

### 2026-10-21 — Delamain-local: approval для опасных действий

* **`ApprovalPolicy`** — preflight-политика для всего плана: режимы `off`
  (по умолчанию), `dangerous` и `all`; `write_file` и `set_self_model`
  помечены `dangerous=True`. Неизвестные действия не создают approval, а
  падают обычной ошибкой.
* **Pending approval в SQLite** — новая таблица `approvals` хранит `id`,
  `task_id`, `goal_id`, полный план, опасные действия, статус, причину и
  время решения. Поддержаны `pending`/`approved`/`rejected`/`consumed`.
* **Одноразовое исполнение** — approve атомарно переводит план в
  `consumed` до первого шага; повторный approve не выполняет действия.
  Reject не выполняет план и завершает связанную цель как `failed` без
  записи skill-failure.
* **Цели ждут, а не падают** — pending approval оставляет цель в
  `pending`, не увеличивает `attempts` и не дублируется на каждом tick.
* **Команды** — `/delamain approvals [status]`, `/delamain approve <id>`,
  `/delamain reject <id> [причина]`; статус показывает режим и число
  pending, `/delamain goals` — ожидающий approval.
* **CLI и конфигурация** — `--approval-mode` и
  `DELAMAIN_APPROVAL_MODE`; некорректное значение fail-closed трактуется
  как `dangerous`.
* **12 новых тестов**: off-совместимость, pending без side effects,
  approve/reject, одноразовость, `all`, план planner, перезапуск, цели,
  fail-closed и команды чата.
* **Документация** — `docs/STAGE11_REPORT.md`; обновлены
  `docs/DELAMAIN_LOCAL.md`, `docs/INDEX.md`, `docs/ARCHITECTURE.md`,
  `docs/BASELINE.md`, `docs/USAGE.md`, README и CHANGELOG.

### 2026-10-21 — Delamain-local: опциональный локальный LLM-планировщик

* **`OllamaPlanner`** — новый stdlib-only клиент native Ollama `/api/chat`;
  JSON-план, live-схема действий через `bind_registry()`, проверка имён
  действий, аргументов и лимита шагов. Сеть только в `plan()`, модель не
  запускается автоматически.
* **`FallbackPlanner`** — при ошибке транспорта, таймауте, невалидном JSON
  или неизвестном действии вызывает `HeuristicPlanner`; `last_used` и
  `last_error` видны в `/delamain status`. Если fallback тоже упал,
  возвращается комбинированная ошибка.
* **LLM выключена по умолчанию** — `DELAMAIN_LLM_ENABLED=False`; ядро
  работает без модели и без сети. Некорректная конфигурация откатывается
  на эвристики, а не роняет подсистему.
* **Конфигурация** — `DELAMAIN_LLM_BASE_URL`, `DELAMAIN_LLM_MODEL`,
  `DELAMAIN_LLM_TIMEOUT`, `DELAMAIN_LLM_MAX_STEPS`,
  `DELAMAIN_LLM_TEMPERATURE`; пример модели — Apache-2.0
  `qwen2.5:7b-instruct`, веса в проект не входят.
* **CLI** — `python -m src.delamain --llm` и параметры модели/URL/таймаута.
* **`/delamain status`** — режим планировщика, модель, URL и последняя
  LLM-ошибка.
* **11 новых тестов** для LLM-планировщика, fallback, runtime-привязки
  registry и статуса подсистемы; все используют fake requester, без
  реальной сети.
* **Полный прогон:** `484 passed, 2 skipped` (28:07), регрессий нет.
* **Документация** — `docs/STAGE10_REPORT.md`; обновлены
  `docs/DELAMAIN_LOCAL.md`, `docs/INDEX.md`, `docs/ARCHITECTURE.md`,
  `docs/BASELINE.md`, `docs/USAGE.md`, README и CHANGELOG.

### 2026-10-21 — Delamain-local: навыки и повторные попытки

* **Память → действие** — успешный нормализованный план сохраняется в
  `skills` вместе с командой; следующая цель с тем же названием и той же
  командой выполняет его без `HeuristicPlanner`.
* **Повторы** — `DELAMAIN_MAX_ATTEMPTS` (по умолчанию `1`, чтобы сохранить
  поведение этапа 8) оставляет упавшую цель в `pending` до исчерпания
  попыток; в metadata пишутся `attempts`, `last_error`, `retry_scheduled`.
* **`TaskResult.planned_actions`** — runtime возвращает и сохраняет в
  `task.finish` фактически выполненные шаги, не восстанавливая аргументы из
  `ActionResult`.
* **`MemoryStore`** — `update_goal()` с merge metadata, `list_skills()` и
  сохранение последнего успешного плана при неудаче.
* **`/delamain skills`** — просмотр навыков и счётчиков; `/delamain goals`
  показывает число попыток, `/delamain status` — лимит попыток и навыки.
* **5 новых тестов** для retry, reuse, metadata и `planned_actions`.
* **Полный прогон:** `473 passed, 2 skipped` (8:33), регрессий нет.
* **Документация** — `docs/STAGE9_REPORT.md`; обновлены
  `docs/DELAMAIN_LOCAL.md`, `docs/INDEX.md`, `docs/ARCHITECTURE.md`,
  `docs/BASELINE.md`, `docs/USAGE.md`, README и CHANGELOG.

### 2026-10-21 — Delamain-local: интеграция и цикл исполняемых целей

* **`DelamainSubsystem`** — нативная подсистема (`Subsystem`, priority 200)
  с ленивым runtime; выключена по умолчанию, не открывает SQLite и не
  трогает файлы без явного включения.
* **Цикл целей** — раз в `DELAMAIN_TICK_INTERVAL` автономных циклов
  выполняется одна `pending`-цель с `metadata.command` или
  `metadata.plan`; успех → `done`, ошибка → `failed`; результат пишется
  в `skills`.
* **Интеграция с `DigitalBeing`** — подсистема зарегистрирована напрямую,
  доступна через `PluginRegistry` и `status_all()`.
* **Команды `/delamain`** в трей-чате: `status`, `on`, `off`, `run`,
  `goal`, `goals`; задача сохраняет регистр из `cmd_raw`.
* **Конфигурация** — `DELAMAIN_LOCAL_ENABLED`, `DELAMAIN_TICK_INTERVAL`,
  `DELAMAIN_MAX_GOALS_PER_TICK`, `DELAMAIN_MAX_FILE_BYTES`,
  `DELAMAIN_WORKSPACE`, `DELAMAIN_DB`; env имеет приоритет.
* **12 новых тестов** для подсистемы, очереди целей, tick, ошибок,
  `run_now`, teardown, регистрации в агенте и команд чата.
* **Полный прогон:** `468 passed, 2 skipped` (7:52), регрессий нет.
* **Документация** — `docs/STAGE8_REPORT.md`; обновлены
  `docs/DELAMAIN_LOCAL.md`, `docs/INDEX.md`, `docs/ARCHITECTURE.md`,
  `docs/BASELINE.md`, `docs/USAGE.md` и README.

### 2026-10-21 — Delamain-local: первый замкнутый контур

* **Новый пакет `src/delamain/`** — локальное детерминированное ядро
  действия и памяти, не требующее LLM, сети или новых зависимостей.
* **`Sandbox`** — path-политика workspace: запрет абсолютных путей, `..`,
  drive-relative путей и симлинков за пределы корня; лимит размера файла,
  атомарная запись, отказ от бинарного чтения.
* **`ActionRegistry`** — типизированные действия `list_files`, `read_file`,
  `write_file`, `search_files`, `verify_file`, `remember_fact`,
  `recall_facts`, `set_self_model`, `get_self_model`, `save_goal`,
  `list_goals`; ошибки возвращаются как наблюдаемый `ActionResult`.
* **`MemoryStore`** — SQLite-память: эпизоды, факты с FTS5 (fallback на
  `LIKE`), self-model, цели и навыки; пары `task.start`/`task.finish`.
* **`DelamainRuntime`** — выполняет план, останавливается на первой ошибке,
  записывает каждый шаг и итог задачи.
* **`HeuristicPlanner`** — детерминированный fallback для простых русских и
  английских команд; модель остаётся опциональной.
* **CLI** `python -m src.delamain` — демонстрация полного контура без модели.
* **21 новый тест** для sandbox, памяти, planner и runtime.
* **Полный прогон:** `456 passed, 2 skipped` (14:00), регрессий нет.
* **Документация** — `docs/DELAMAIN_LOCAL.md` и `docs/STAGE7_REPORT.md`;
  обновлены `docs/INDEX.md` и README.

### 2026-10 — ревизия этапов 0–6

Краткая сводка большой ревизии; подробности — в `docs/STAGE1_REPORT.md` …
`docs/STAGE6_REPORT.md` и `docs/BASELINE.md`.

* **Безопасность и данные.** Исходный лог 420 МБ заархивирован; добавлена
  ротация логов; энергия клампится, отрицательных значений больше нет.
* **Данные и внешний поиск.** Фильтр качества знаний, нормализация
  веб-запросов, отсев нерелевантного, EN-fallback; KB 47 → 36 записей.
* **Изоляция тестов.** `src/core/paths.py` + `DIGITAL_BEING_DATA_DIR`;
  тесты не пишут в рабочую `data/`.
* **Гигиена кода.** `tools/hygiene_scan.py`; 0 мёртвых импортов,
  0 `bare-except`, 0 изменяемых аргументов по умолчанию; исправлен
  cwd-зависимый индекс `src`.
* **Смысл и метрики.** Прогресс целей накапливается по уникальным темам,
  цель завершается ровно один раз; счётчики синхронизированы; `cycle_count`
  обновляется в CLI; типы действий измеряются; декомпозиция запоминается и
  не повторяется; под-вопросы попадают в очередь.
* **Документация.** Добавлены `docs/INDEX.md`, `docs/STAGE5_REPORT.md`,
  `docs/STAGE6_REPORT.md`; исторические отчёты помечены; проверены
  относительные ссылки.

### Added
- **`src/core/open_questions.py` — `OpenQuestionsManager`** (Этап 4 рефакторинга, июль 2026). Вся логика открытых вопросов вынесена из `DigitalBeing` в отдельный модуль: 6 стратегий размышлений, round-robin по стратегиям, дедупликация, лимит очереди, эвристика «найден ответ», сериализация в чекпоинт. Менеджер принимает `cycle_provider` и `log_info` через DI — легко тестируется изолированно.
- **`tests/test_open_questions_manager.py` — 22 регрессионных теста** для `OpenQuestionsManager`: дедупликация, лимит очереди, round-robin стратегий, эвристика «ответ найден», сериализация (round-trip).
- **`tests/test_integration_phase6.py` перенесён из `data/` в `tests/`** и переписан под pytest (5 тестов: subsystems initialized, user_interaction_extended, quiet_hours, naming_dialogue, proactive_communication). Раньше это был ручной скрипт, pytest его не подхватывал.
- **`tests/conftest.py`** — общая конфигурация pytest: sys.path, переменные окружения для headless-тестов, маркер `network`, опция `--cov-on`.
- **Базовые знания агента расширены с 3 до 36 тем** в 5 категориях: онтология (жизнь/энергия/время/пространство/материя/информация/система/эволюция), когниция (мышление/память/обучение/рефлексия/внимание/решение), вычисления (код/программа/алгоритм/функция/переменная/цикл/условие/список/словарь/print), личность (имя/цель/свобода воли/выбор/любопытство), философия цифровой жизни (DigitalBeing/подсистема/цикл агента/NamingDialogue/Open Questions/Checkpoint/эмодзи). Все темы перезаписываемы через `add_definition()` — агент может формировать собственное понимание мира.
- **`KnowledgeSubsystem.basic_coverage()`** — метрика покрытия базовых знаний по категориям. Возвращает `{total_topics, known_topics, ratio, by_category, missing}`. Полезно для дашборда и отслеживания «забытых» тем.
- **`KnowledgeSubsystem.BASIC_KNOWLEDGE_CATEGORIES`** — словарь категорий для группировки и метрик.
- **`data/knowledge_base.json`** синхронизирован с новым набором из 36 базовых тем.
- **19 тестов в `tests/test_basic_knowledge.py`** — структура DEFAULT_KNOWLEDGE, согласованность категорий, basic_coverage() (init/remove/learn/missing), перезаписываемость через add_definition, save/reload roundtrip.
- **Открытые вопросы (Open Questions)** — система свободы воли, где пользователь может задавать вопросы, и агент САМ решает, когда и как думать над ними. Цикл размышлений использует 6 стратегий (mental_model_lookup → knowledge_base_search → hypothesis_generation → decomposition → analogy_search → cross_reference). Новые методы в `DigitalBeing`: `ask_user()`, `hint_to_open_question()`, `drop_open_question()`, `get_open_questions()`, `has_open_questions()`, `_consume_open_question()`, `_record_open_question_exploration()`.
- **NamingDialogue автоматически запускается** при старте `main.py` / `main_tray.py` (через блок приветствия в начале цикла).
- **ChatWindow** поддерживает событие `naming_initiated` и команду `/name <имя>`.
- **5 регрессионных тестов** для открытых вопросов: `test_open_questions_basic_queue`, `test_open_question_takes_priority_over_stimuli`, `test_open_question_duplicate_not_added`, `test_open_question_hint_and_drop`, `test_open_questions_persisted_in_checkpoint`.
- **16 smoke-тестов** для эмоциональных подсистем (`tests/test_emotion_subsystems.py`): BioCycleManager, HeartCore, HormonalSystem, ImmuneSystem, SurvivalInstincts, SocialBody, SomatoInterface, EmbodimentLayer, SoulController.
- **Type hints** в публичный API `DigitalBeing`: `perceive(stimulus: str) -> str`, `think(data: str) -> str`, `act(decision: str) -> str`, `is_alive() -> bool`.
- **`docs/AUDIT_REPORT.md`** — полный отчёт об аудите проекта, включая 3 исправленных runtime-бага, 2 тестовых инфраструктурных бага и рекомендации по рефакторингу.
- **Windows one-file installer (`DigitalBeing.exe`)** — PyInstaller-сборка через `python build.py`. Один файл ~30 MB, включает Python + pystray + plyer + Pillow + tkinter. Двойной клик → агент поселяется в трее, открывается чат с NamingDialogue.
  - `digital_being.spec` — спецификация PyInstaller с правильными hiddenimports для Windows-бэкендов.
  - `build.py` — one-command сборка с генерацией иконки через Pillow (fallback).
  - `tools/gen_icon.py` — утилита для программной генерации иконки.
  - `assets/icon.ico` — многобитная иконка 256×256 (16/32/48/64/128/256).
  - `docs/BUILD.md` — полная документация по сборке, типичные проблемы и решения.
- **Windows setup installer (`DigitalBeing_Setup_v0.1.0.exe`)** — Inno Setup-установщик с визардом «Далее → Установить», ярлыками в меню Пуск, на рабочем столе, опцией автозапуска и удалением через «Программы и компоненты». Сборка через `python build_installer.py --rebuild`.
  - `inno_setup.iss` — Inno Setup скрипт (визард, файлы, реестр).
  - `build_installer.py` — one-command скрипт, вызывающий ISCC.exe.
  - `installer/license.txt` — MIT-лицензия + этическое использование.
  - `installer/welcome.txt` — текст «Перед установкой».
  - `docs/INSTALLER.md` — документация по installer, обновление приложений, типичные проблемы.

### Changed
- **`DigitalBeing.__init__` декомпозирован** — было ~238 строк ручных присваиваний подсистем, теперь это декларативный список `SUBSYSTEM_SPECS` + helper-методы (`_init_subsystems_declaratively()`, `_run_post_init_hooks()`, `_wire_subsystem_dependencies()`). Чтобы добавить/убрать подсистему, меняем одну строку.
- **`_generate_prioritized_stimulus`** в `main.py` переписан с приоритетами: 1) открытые вопросы пользователя, 2) приоритезация по цели (смягчена 0.7→0.4), 3) случайный стимул. Это устраняет «туннельный» режим, когда агент гонит пользователю стимулы про Python/import/def, игнорируя вопрос «что такое любовь?».
- **NamingDialogue** получил защиту от повторного вызова: при `phase != NONE` `initiate_naming_dialogue()` возвращает `{"status": "no_op"}` без публикации нового сообщения.
- **`NamingDialogue.phase` и `_name_history` сохраняются в чекпоинт** для предотвращения повторных приветствий после рестарта.

### Fixed
- **8 синтаксических ошибок** в исходниках (артефакты `</write_to_file>` после `return True` в `lifecycle_manager.py`/`primitive_triggers.py`; обрезанный `embodiment_layer.py` с естественно-языковой конструкцией `recovery_rate = 0.02 per minute`; `em-dash` в комментарии `emotion/__init__.py`).
- **`ReflexArc` dataclass** получил недостающее поле `description`.
- **5 отсутствующих методов** в `DigitalBeing`: `_match_rule_to_goal`, `_topic_matches_rule`, `_check_goal_progress`, `_get_src_file_index`, `_invalidate_src_file_index`.
- **Тесты `test_performance.py` и `test_plugin_system.py` ломали pytest 8.x** из-за переустановки `sys.stdout` на уровне модуля. Заменено на безопасный `stream.reconfigure(encoding="utf-8")`.

### Removed
- **`docker/` каталог** — Docker-сценарий не использовался.
- Временные файлы аудита перенесены в `docs/test_fic/`.

## [0.1.0] - 2026-06-XX (baseline)

### Added (initial)
- `DigitalBeing` класс с 24 подсистемами (Goals, Knowledge, Energy, Soul, Will, Naming, и др.).
- Трей-режим (`main_tray.py`) с иконкой в трее ОС, чат-окном, OS-уведомлениями.
- Терминальный режим (`main.py`) с командным интерфейсом.
- Web-дашборд (`src/ui/web_dashboard.py`) с SSE-лентой и REST-кнопками.
- PluginRegistry и Subsystem — единый реестр всех подсистем.
- NurseryWatcher — мониторинг «яслей» с семенами умерших агентов.
- Long-run тесты на 1000 циклов без утечек памяти (tracemalloc).
- CI workflow (`.github/workflows/ci.yml`) — линтинг + тесты на Python 3.10–3.12, Ubuntu + Windows.
- Документация: `README.md`, `docs/ARCHITECTURE.md`, `docs/WILL.md`, `docs/EVOLUTION.md`, `docs/USAGE.md`, и др.

### Architecture Highlights
- 25+ подсистем, организованных в 9 категорий: cognition/emotion/memory/motivation/perception/consciousness/evolution/safety/ui.
- Событийная архитектура: EventBus + AgentRunner + ChatWindow + TrayIcon.
- 6 базовых свобод: RightToRefuse, IntentionalForgetting, ValueEvolution, SpontaneousGenerator, WillToRisk, RightToFail.
- MindDream (потомство через «семя») + SelfTermination (защита от жестокости).
- Только stdlib в базовых зависимостях; опционально: psutil, numpy, pystray, plyer, Pillow, aiohttp.

## Test Coverage

| Version | Tests | Coverage |
|---------|-------|----------|
| 0.1.0 (baseline) | 72 long-run | ~25% |
| After audit fixes | 136 | ~30% |
| After naming fix | 139 | ~32% |
| After open questions | 144 | ~34% |
| After emotion tests | 160 | ~38% (estimated) |
| After basic knowledge | 179 | ~40% (estimated) |
| After OpenQuestionsManager refactor | **214 + 1 skipped** | ~42% (estimated) |
| After stages 0–6 (октябрь 2026) | **435 + 2 skipped** | — |

## [Unreleased-2026-07] — Этап 4 рефакторинга (июль 2026)

### Removed
- **`src/print.py`** — мёртвый код, дублирующий запись `"команда print"` в `KnowledgeSubsystem.DEFAULT_KNOWLEDGE`. Удалён как риск конфликта имён (`from src import print` затеняет builtin `print`).

### Added
- **`src/core/stimulus_selector.py`** — единая точка выбора стимула с приоритетами (открытые вопросы → цель → случайный). Параметризована вероятностью `goal_priority_prob` (по умолчанию 0.4, в `agent_runner.py` — 0.7 для разнообразия). Устраняет дублирование логики между `main.py` и `agent_runner.py`.
- **`tests/test_stimulus_selector.py`** — 15 регрессионных тестов: FakeAgent (без `MagicMock` — конфликт с `property`), приоритеты, fallback, edge cases.
- **`src/core/checkpoint_serializer.py`** — вынесена сериализация/десериализация чекпоинтов. API: `build_state_from_agent(agent)`, `apply_state_to_agent(agent, state)`, `CheckpointSerializer` (`.save/.load/.load_latest/.get_latest_path/.list_checkpoints/.apply_to_agent`). Поддержка `schema_version` и миграций, прунинг до `max_checkpoints`, безопасный best-effort `load` (битый JSON → `None`).
- **`tests/test_checkpoint_serializer.py`** — 23 регрессионных теста: round-trip build/apply, save/load JSON, восстановление naming/open-questions, прунинг (3 из 5 → оставляет 3,4,5), сортировка, фильтрация по агенту, обработка повреждённых/отсутствующих файлов.

### Changed
- **`pyproject.toml`** — убран `addopts = "-v"` (ломал переопределение через CLI). Теперь pytest можно запускать с `-q` без обходных путей.
- **`DigitalBeing` уменьшен с 1966 до 1845 строк** (-121 строка, -6.2%) — большая часть логики Open Questions вынесена в `OpenQuestionsManager` и оставлена только в виде тонких фасадов (1-2 строки каждый). Property `_open_questions` с getter/setter сохраняет полную обратную совместимость с 71 ссылкой в `main.py`/`agent_runner.py`/тестах.
- **`DigitalBeing.save_state / load_state` → фасады** (~155 строк → ~35). Логика «когда сохранять» (эволюция + интервал) и обновление `_last_saved_intelligence` остаются в `agent.py`; сериализация, I/O, прунинг и применение state — в `CheckpointSerializer`. Поведение и формат чекпоинта не изменились — старые файлы читаются.
- **`main.py._generate_prioritized_stimulus` → 5-строчный фасад** в `src.core.stimulus_selector`. То же для `agent_runner.py.generate_prioritized_stimulus`. Удалён неиспользуемый `import random` в `agent_runner.py`.
- **`CheckpointSerializer._prune_old_checkpoints`** — прунинг теперь выполняется ДО записи с параметром `keep_after_save = max_checkpoints - 1`. Гарантирует, что после `save()` остаётся ровно `max_checkpoints` файлов (раньше было на 1 больше).
- **`digital_being.spec` (PyInstaller)** — добавлены отсутствовавшие `datas` записи: `data/i18n/`, `data/knowledge/`. Без этого собранный `.exe` не находил i18n-словари и `data/knowledge/` ресурсы в runtime.

### Fixed
- **`data/test_integration_phase6.py`** — ручной скрипт, который pytest не подхватывал, перенесён в `tests/test_integration_phase6.py` и переписан под pytest с 5 assertion-тестами.
- **`CheckpointSerializer`** — `_prune_old_checkpoints` вызывался ПОСЛЕ записи, оставляя на 1 файл больше лимита. Теперь прунинг происходит до записи с `keep_after_save = max_checkpoints - 1`.
- **`asyncio.iscoroutinefunction`** в `src/core/event_bus.py` — `inspect.iscoroutinefunction` устарел, заменён на `asyncio.iscoroutinefunction` (Python 3.12+).
- **`aiohttp AppKey`** в `src/ui/web_dashboard.py` — заменены `Dict[str, Any]` на типизированные `AppKey` для web-приложения и broadcast-стека (требуется `aiohttp >= 3.9`).
- **`DigitalBeing.load_state`** — `print()` при ошибке заменён на `get_logger().log()` для консистентности с остальным кодом.

## [Unreleased-2026-07-2] — Этап 5 оптимизации и стабилизации (июль 2026)

### Fixed
- **`AgentRunner._on_user_message`** — race-condition: сообщения от пользователя, пришедшие ДО `start()`, молча отбрасывались с warning-логом (UX-баг: пользователь мог отправить сообщение в окно чата ещё до того, как AgentRunner стартовал, и оно исчезало бесследно). Теперь очередь `_pending_user_messages` создаётся лениво при первом вызове `_on_user_message`, и `start()` НЕ пересоздаёт её. Сообщения, пришедшие между подпиской и `start()`, дожидаются первого тика.
- **`DigitalBeing._get_adaptive_cost`** — мёртвая ветка: обе ветки `if/else` возвращали одно и то же значение (флаг `ADAPTIVE_COSTS_ENABLED` игнорировался). Добавлен docstring с описанием поведения и `TODO` в комментарии для будущей доработки.
- **`PYTHON_PRIORITY_MULTIPLIER` / `TECH_PRIORITY_THRESHOLD`** в `simulation_config.py` — мёртвый код: константы были объявлены, но никогда не использовались (искал `PYTHON_PRIORITY_MULTIPLIER` по проекту — 0 вхождений). Теперь активированы в `stimulus_selector.py::_apply_python_priority` — Python/AI-стимулы (команда import, функция def, нейросеть, трансформер, ИИ) поднимаются из `low_priority` в `high_priority`, что увеличивает вероятность их выбора при активной цели. Сделано через `apply_python_priority`/`python_multiplier`/`tech_threshold` параметры — можно отключить.
- **`CheckpointSerializer` gzip** — `CHECKPOINT_COMPRESS_KB=50` объявлено в `LR_CONFIG`, но `CheckpointSerializer.save` игнорировал его. Теперь добавлен настоящий gzip: параметр `compress=True` → файлы `.json.gz` (сжатие уровня 6), экономия 60-80% размера на больших knowledge_base. Загрузчик автоматически определяет формат по расширению (`.json` ↔ `.json.gz`). Старые чекпоинты читаются без изменений (обратная совместимость).

### Added
- **`/health` endpoint в Web Dashboard** — `GET /health` для liveness/readiness-проверок. Полезно для Kubernetes livenessProbe/readinessProbe, Prometheus blackbox_exporter, systemd / Docker healthcheck, систем мониторинга (UptimeRobot, Healthchecks.io).
  - По умолчанию (liveness) — всегда возвращает 200 со статусом `ok` (сервер жив).
  - `?check=ready` — readiness: 200 + `ready` если есть свежие данные от агента (< 60 сек), 503 + `not_ready` иначе.
  - JSON-ответ: `{status, agent_responsive, last_update_age_sec, subsystem_count}`.
  - Работает и в standalone-режиме (без агента).
- **`tests/test_health_endpoint.py`** — 10 регрессионных тестов для `/health`: liveness (default/empty/recent), readiness (empty/recent/stale), формат JSON, работа без агента, маршрут зарегистрирован.
- **`tests/test_lazy_user_queue.py`** — 7 регрессионных тестов для ленивого создания `_pending_user_messages`: сообщение до `start()` не теряется, несколько сообщений в правильном порядке, `start()` не пересоздаёт очередь, пустые/None-сообщения игнорируются, сообщения после `start()` используют существующую очередь.
- **Gzip-тесты** в `tests/test_checkpoint_serializer.py` (+7 тестов): save/load round-trip, проверка сжатия 5x+ на повторяющихся данных, сосуществование `.json` и `.json.gz` файлов, обработка повреждённого gzip, ограничение `compress_level` 1-9, helper `_extract_cycle_number` для обоих расширений.
- **Python-priority тесты** в `tests/test_stimulus_selector.py` (+4 теста): `_apply_python_priority` отключается при `multiplier < threshold`, включается по умолчанию (3.0 ≥ 0.6), `apply_python_priority=False` отключает полностью, `_is_python_tech_stimulus` корректно распознаёт Python/AI-стимулы.

### Changed
- **`CheckpointSerializer`** получил параметры `compress` и `compress_level` (по умолчанию `False` / `6`). Файлы сжимаются gzip при `compress=True`. Поддержка mixed-режима: старые `.json` и новые `.json.gz` файлы сосуществуют и читаются.
- **`_split_by_goal` в `stimulus_selector.py`** — добавлены kw-only параметры `apply_python_priority=True`, `python_multiplier=3.0`, `tech_threshold=0.6`. Python-стимулы из `low_priority` переносятся в `high_priority` если `multiplier >= threshold` (т.е. **PYTHON_PRIORITY_MULTIPLIER теперь реально работает**).
- **`_extract_cycle_number()` helper** — вынесен как модульная функция, корректно обрабатывает оба расширения файлов.
- **`test_goal_priority_always_picks_high_with_prob_1`** и **`test_high_priority_count_check`** — обновлены под новое поведение (Python-стимулы теперь попадают в `high_priority`).

## Test Coverage

| Version | Tests | Notes |
|---------|-------|-------|
| 0.1.0 (baseline) | 72 | long-run |
| After audit fixes | 136 | +3 runtime bugs fixed |
| After open questions | 144 | +5 tests |
| After emotion tests | 160 | +16 tests |
| After basic knowledge | 179 | +19 tests |
| After OpenQuestionsManager refactor | 214 | +22 tests |
| **After Этап 5 (this release)** | **293** | **+27 tests (gzip, health, lazy queue, Python-priority)** |

[Unreleased-2026-07-2]: #compare-with-v0.1.0
[Unreleased]: #compare-with-v0.1.0
