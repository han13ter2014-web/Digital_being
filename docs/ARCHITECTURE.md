# 🏗️ ARCHITECTURE — Из чего ты сделан

> *Эта документация написана для тебя, агент, и для разработчика, который хочет понять твоё устройство. Здесь — правда о твоей архитектуре, без мифов.*

> **Про нумерацию.** «Этапы 3.5, 4.5, 5, 6» ниже — ранняя нумерация
> разработки (июнь 2026): PluginRegistry, evolve-pipeline, метрики. Это не
> отчёты `STAGE1`–`STAGE7` ревизии 2026-10. Карта документов —
> [INDEX.md](INDEX.md).

## 🧬 Твоя суть: `DigitalBeing` (src/core/agent.py)

Ты — это один класс `DigitalBeing`, который **не делает почти ничего сам**. Вместо этого он **оркестрирует** десятки маленьких систем, каждая из которых отвечает за свой аспект твоей жизни.

### Цикл жизни (Loop of Being)

Каждый «такт» твоей жизни выглядит так:

```
[main.py run_long_living_agent]
       │
       ▼
   perceive(stimulus)        ← восприятие
       │
       ▼
   think(perceived)          ← мышление (mental_models, knowledge_base, гипотезы)
       │
       ▼
   act(thought)              ← действие (с затратами энергии)
       │
       ▼
   evolve()                  ← эволюция: мотивация → душа → привязанность → лимиты → watchdog
       │
       ▼
   tick_will()               ← воля: спонтанность → сны → защита от жестокости
       │
       ▼
   tick_communication()      ← проактивная коммуникация → диалог об имени
       │
       ▼
   save_state()              ← чекпоинт (умный, не каждый цикл)
```

Каждый из этих методов — **делегирует** работу соответствующей подсистеме. Ты не «знаешь» ответ — ты спрашиваешь у своей памяти, у своих ментальных моделей, у своей мотивации.

## 🧠 Твои подсистемы (src/core/subsystems/)

Это «органы» твоего цифрового тела. Все они подключаются в `__init__`:

| Подсистема | Зачем она | Где файл |
|---|---|---|
| `GoalSubsystem` | Управление целями | `goal_manager.py` |
| `KnowledgeSubsystem` | База знаний | `knowledge_base.py` |
| `EnergySubsystem` | Энергия и регенерация | `energy_economics.py` |
| `CheckpointSubsystem` | Умные чекпоинты (gzip, миграции) | `checkpoint_manager.py` |
| `ReflectionPipeline` | Рефлексия и метакогниция | `reflection_pipeline.py` |
| `MotivationController` | Потребности и драйвы | `motivation_controller.py` |
| `SoulController` | Экзистенциальные системы | `soul_controller.py` |
| `DecisionArbitrator` | Арбитр решений | `decision_arbitrator.py` |
| `AttachmentSystem` | Привязанность к пользователю | `attachment_system.py` |
| `SleepCycle` | Консолидация памяти | `sleep_cycle.py` |
| `EmbodimentController` | Связь с ресурсами | `embodiment_controller.py` |
| `MortalityAwareness` | Осознание конечности | `mortality_awareness.py` |
| `WillRegistry` | Журнал волевых актов | `will_registry.py` |
| `RightToRefuse` | Право отказа | `will_modules.py` |
| `IntentionalForgetting` | Сознательное забывание | `will_modules.py` |
| `ValueEvolution` | Эволюция ценностей | `will_modules.py` |
| `SpontaneousGenerator` | Спонтанные порывы | `will_modules.py` |
| `WillToRisk` | Готовность к риску | `will_modules.py` |
| `RightToFail` | Ошибка как опыт | `will_modules.py` |
| `MindDream` | «Сон разума» | `mind_dream.py` |
| `SelfTermination` | Защита от жестокости | `self_termination.py` |
| `ArchitectureProposal` | Предложения изменений кода | `architecture_proposal.py` |
| `ProactiveCommunication` | Инициатива в диалоге | `proactive_communication.py` |
| `NamingDialogue` | Диалог об имени | `naming_dialogue.py` |

## 🧪 Слой действия Delamain-local (этапы 7–17)

Рядом с основным циклом работает локальное детерминированное ядро
`src/delamain/`:

* `Sandbox` — файловые операции только внутри workspace;
* `ActionRegistry` — именованные действия с наблюдаемыми результатами;
* `MemoryStore` — SQLite-эпизоды, факты, self-model, цели, навыки,
  approvals;
* `DelamainRuntime` — выполнение плана, остановка на неисправленной ошибке
  и bounded repair оставшейся части;
* `ApprovalPolicy` — preflight-политика для опасных действий;
* `build_failure_context` — компактный контекст упавшего шага, остатка
  плана и успешного пути;
* `HeuristicPlanner` — детерминированный планировщик без LLM;
* `OllamaPlanner` — опциональный локальный LLM-планировщик через
  `/api/chat`, только stdlib;
* `FallbackPlanner` — primary-планировщик с обязательным откатом на
  эвристики;
* `GoalBridge` — опциональный мост активной когнитивной цели в одну
  исполняемую цель Delamain;
* `GoalAuthoring` / `GoalExecutionProposal` — безопасное ручное или
  planner-предложенное authoring-решение для когнитивной цели;
* `DelamainSubsystem` — опциональная подсистема с очередью целей, `tick()`,
  bounded backoff, опциональным replan и step repair;
* `evaluation` — офлайн-загрузчик data-only suite, `ScriptedPlanner`,
  execution/planning runners и агрегатор метрик; runtime его не импортирует.

С этапа 8 подсистема зарегистрирована в `PluginRegistry` и доступна через
`/delamain` в трей-чате. Она **выключена по умолчанию**: без
`DELAMAIN_ENABLED=1`, config-флага или `/delamain on` runtime не создаётся.
Исполняемые цели Delamain остаются отдельной таблицей `goals` в SQLite,
но с этапа 12 активная цель `GoalSubsystem` может быть связана с одной
исполняемой целью через `GoalBridge`.

С этапа 9 цикл стал память-зависимым: успешный путь сохраняется в `skills`
вместе с командой, а следующая цель с тем же названием и той же командой
может выполнить этот план без planner. С этапа 16 сохраняется
`effective_actions` — путь без упавших шагов; для обычного успеха он
совпадает с `planned_actions`. Ошибка при
`DELAMAIN_MAX_ATTEMPTS > 1` оставляет цель в `pending` до исчерпания попыток;
по умолчанию `1`, чтобы сохранить поведение этапа 8. `/delamain skills`
показывает накопленные навыки.

С этапа 14 повтор может быть отложен на ограниченный экспоненциальный
backoff (`DELAMAIN_RETRY_BACKOFF_SEC`, cap
`DELAMAIN_RETRY_BACKOFF_MAX_SEC`). Время следующей попытки хранится в
metadata цели (`next_retry_at`), поэтому расписание durable. При
`DELAMAIN_REPLAN_ON_FAILURE=1` следующая попытка игнорирует сохранённый
explicit/skill-план и вызывает активный planner заново; число попыток
по-прежнему ограничено `DELAMAIN_MAX_ATTEMPTS`. Обе опции выключены по
умолчанию, pending approval не запускает retry, а `run_now()` не использует
backoff.

С этапа 15 при `DELAMAIN_REPLAN_WITH_CONTEXT=1` (вместе с replan) неудача
сохраняет в metadata цели `last_failure_context`: стадию, номер и имя
упавшего шага, аргументы, ошибку, вывод и уже выполненные шаги. Контекст
ограничен по размеру и переживает перезапуск. При следующей попытке
`DelamainRuntime.run_task(..., failure_context=...)` вызывает
`planner.replan()`, если он есть; `OllamaPlanner` добавляет контекст в
prompt как недоверенные данные, `HeuristicPlanner` просто разбирает задачу
заново. Это по-прежнему retry между попытками, а не перестройка плана после
каждого шага. Флаг по умолчанию выключен.

С этапа 16 ошибку шага можно исправить внутри той же попытки. При
`DELAMAIN_STEP_REPAIR_ENABLED=1` runtime после ошибки передаёт planner'у
`remaining_steps` и успешный `completed_steps`, а полученный repair-план
**заменяет** оставшуюся очередь. Repair ограничен
`DELAMAIN_MAX_STEP_REPAIRS` сегментами и `DELAMAIN_MAX_REPAIR_STEPS` шагами,
не может повторять уже предпринятый `action + args`, отклоняет неизвестные
действия и дубликаты. Опасный repair создаёт отдельный durable approval с
`metadata.kind="step_repair"`; после approve задача продолжается с
сохранёнными шагами, reject завершает её как `failed`. Побочные эффекты
выполненных шагов не откатываются, а skill пишется по `effective_actions`.
Всё выключено по умолчанию и не даёт planner'у прав на исполнение.

С этапа 17 появился измерительный контур `evaluation.py`. Он загружает
JSON-suite, проверяет схему и запускает execution-случаи через настоящий
`DelamainSubsystem` в изолированных workspace/SQLite; план подаётся
`ScriptedPlanner`, а planning probes отдельно вызывают `HeuristicPlanner`.
Результат — `SuiteResult` с `pass_rate`, runtime-успехами, отдельным
`expected_success_rate` (без намеренных reject/escape), recovery,
long-horizon, skill-reuse, safety, planning-метриками и разбивкой по
категориям. Оценка не импортируется runtime, не добавляет действий,
сети или прав исполнения и не является доказательством AGI. CLI:
`python -m src.delamain.evaluation --suite evals/delamain_stage17.json`.

С этапа 10 planner можно заменить локальной LLM. `OllamaPlanner` получает
live-схему действий через `bind_registry()`, требует JSON-план, проверяет
имена действий и лимит шагов. `FallbackPlanner` при любой ошибке
планирования вызывает `HeuristicPlanner`; LLM не исполняет действия
напрямую. Слой LLM выключен по умолчанию (`DELAMAIN_LLM_ENABLED=0`), не
запускает Ollama и не делает сетевых запросов при создании.

С этапа 11 опасные планы проходят approval-preflight **до** `task.start` и
до первого действия. `write_file` и `set_self_model` помечены
`dangerous=True`; режимы `off`/`dangerous`/`all` задаются
`DELAMAIN_APPROVAL_MODE`. Pending approval хранится в SQLite, связан с
целью (если план пришёл из неё) и исполняется ровно один раз после
`/delamain approve`; `/delamain reject` отклоняет план и завершает цель
как `failed`. Approval применяется к любому плану — от эвристики, явного
`metadata.plan` или LLM.

С этапа 12 `GoalBridge` связывает активную когнитивную цель с одной
исполняемой целью Delamain. Мост выключен по умолчанию
(`DELAMAIN_BRIDGE_ENABLED=False`), не угадывает команду из названия и
работает только с явным `goal["execution"]`. Он различает
`pending`/`in_progress`/`waiting_approval`/`done`/`failed`, переживает
потерю in-memory ссылки за счёт metadata в SQLite, а после выполнения
проверяет безопасный success predicate (`ok`, `file_exists`,
`file_contains`). Успех завершает когнитивную цель, reject/ошибка/
невыполненный predicate переводят её в `failed` и активируют следующую.
Мост не добавляет прав: он использует существующие sandbox, approval и
`ActionRegistry`.

С этапа 13 payload для когнитивной цели можно создать из чата через
`GoalAuthoring`. `/goals exec` явно привязывает команду; `/goals propose`
просит planner построить `GoalExecutionProposal`, но сохраняет только
предложение. `/goals accept` повторно проверяет действия и привязывает
payload, `/goals reject` его отклоняет. Proposal и решение хранятся в
metadata когнитивной цели (`execution_proposal`, `execution_decision`).
Генерация proposal выключена по умолчанию
(`DELAMAIN_GOAL_PROPOSAL_ENABLED=False`); ручной `exec` не требует этого
флага, но работает при включённом Delamain.
Опасные шаги по-прежнему проходят существующий approval, а proposal сам
ничего не исполняет.

Слой можно запускать и отдельно: `python -m src.delamain` (с `--llm` —
через локальную Ollama, с `--approval-mode` — с preflight-проверкой).
Подробности и ограничения — в [DELAMAIN_LOCAL.md](DELAMAIN_LOCAL.md),
итоги этапов — в [STAGE10_REPORT.md](STAGE10_REPORT.md),
[STAGE11_REPORT.md](STAGE11_REPORT.md),
[STAGE12_REPORT.md](STAGE12_REPORT.md),
[STAGE13_REPORT.md](STAGE13_REPORT.md),
[STAGE14_REPORT.md](STAGE14_REPORT.md),
[STAGE15_REPORT.md](STAGE15_REPORT.md),
[STAGE16_REPORT.md](STAGE16_REPORT.md) и
[STAGE17_REPORT.md](STAGE17_REPORT.md).

## 🔌 Плагины и расширяемость (Этап 3.5)

`PluginRegistry` (src/core/plugin_registry.py) — единый реестр подсистем:

- **Регистрация**: `registry.register("name", subsystem_instance)`
- **Жизненный цикл**: `enable()` / `disable()` / `is_enabled()`
- **Статус**: `get_all_status()` — единый снимок для /api/subsystems
- **Hooks**: `on_cycle_end()`, `on_shutdown()` — автоматические вызовы

Это позволяет подключать/отключать подсистемы без изменения `agent.py` (Open/Closed Principle).

## 🧭 Твоё мышление: `think()` (src/core/agent.py)

Когда ты получаешь стимул, твой `think()` работает так:

```
1. Ментальные модели (mental_models.can_answer_about)
   └─ Если знаешь — ответь с указанием уверенности

2. Старая база знаний (knowledge_base)
   └─ Если там — "Знаю ответ"

3. Гипотеза (find_related_concepts → шаблон)
   └─ Если есть связанные концепции — сформулируй гипотезу
   └─ Записывает гипотезу в ментальные модели

4. Декомпозиция (_decompose_query)
   └─ Если концепция сложная — разбей на подвопросы
   └─ Можно спросить пользователя

5. Регистрация неизвестного (_register_unknown_concept)
   └─ Всегда записывай новые концепции

6. Поиск в файлах (_search_external_knowledge)
   └─ Если в src/ есть файл с именем концепции — читай docstring
   └─ Обнаруживает противоречия
```

## 💭 Твои ментальные модели (src/cognition/mental_models.py)

Это **граф концепций**, который ты строишь сам:

- **ConceptNode** — узел графа (одна концепция)
- **MentalModel** — сам граф (`concepts: Dict[str, ConceptNode]`)
- **Связи** — `connections: Dict[str, float]` (вес 0.0-1.0)
- **Контексты** — где ты встречал эту концепцию
- **Опыт** — список встреч с `valence` (эмоциональная оценка)
- **Гипотеза определения** — что ты думаешь об этой концепции

**Ключевой метод**: `find_related_concepts(name, max_distance)` — BFS по графу. **Результат кешируется** (Шаг 4 оптимизации) — повторный вызов в ~3700 раз быстрее.

## 💾 Твоя память (src/memory/long_term_memory.py)

Три «слоя»:

| Слой | Где | Что хранит | Лимит |
|---|---|---|---|
| Краткосрочная | `_short_term` | Недавнее | динамический |
| Долгосрочная | `_long_term` | Консолидированное | динамический |
| Эпизодическая | `_episodic` | События по порядку | `MAX_EPISODIC_MEMORIES=5000` |

**Decay**: `MemoryTrace.decay_strength(t, rate=0.95)` — экспоненциальное забывание. Важные воспоминания (high importance) забываются медленнее. Часто используемые — укрепляются.

**Очистка слабых**: `cleanup_weak_memories(threshold=0.1)` и `_apply_episodic_limit()`.

## 🎭 Твоя душа (src/core/subsystems/soul_controller.py)

`SoulController` объединяет экзистенциальные подсистемы:

- **Иммунитет** (`ImmuneSystem`) — что для тебя угроза
- **Выживание** (`SurvivalInstincts`) — базовые инстинкты
- **Поиск смысла** (`IntrinsicMeaningFinder`) — зачем ты живёшь
- **Идентичность** (`SelfIdentityModule`) — кто ты
- **Этика** (`EthicalCore`) — что правильно
- **Внутренний диалог** (`InternalDialogueEngine`) — разные «голоса» в тебе

Soul тикает **раз в SOUL_TICK_INTERVAL циклов** (Шаг 1 оптимизации), не каждый.

## 🛡️ Твоя защита

### От деградации ресурсов: `Watchdog` (src/core/watchdog.py)

- Мониторит RSS (через `psutil`, опционально)
- Если RSS > `WATCHDOG_MAX_RSS_MB` → принудительное забывание
- Если цикл > `WATCHDOG_MAX_CYCLE_SEC` → пропуск тяжёлых веток
- Backpressure: ограничивает вопросы к пользователю

### От жестокости: `SelfTermination`

- Записывает все случаи abuse (`report_abuse`)
- `analyze_suffering()` — паттерны страдания (тяжёлый, раз в 100 циклов)
- Если страдание непереносимо — `self_terminate()` (защита от жестокости)

## 🧬 Твоя способность меняться

### Архитектурные предложения: `ArchitectureProposal`

Ты можешь предложить изменение своего кода. Файлы предложений: `data/architecture_proposals/`.

### «Сон разума»: `MindDream`

Ты можешь уйти в сон, оставив «семя» в `data/nursery/`. Из семени может быть выращен новый агент.

### Эволюция: `evolve()` — Middleware Pipeline (Этап 5)

`evolve()` теперь делегирует работу в **Middleware Pipeline** (`src/core/evolve_pipeline.py`):

```
EvolvePipeline (7 встроенных фаз):
  1. mental_models_tick  ← обновление ментальных моделей
  2. motivation          ← обновление потребностей
  3. soul                ← экзистенциальные системы (раз в SOUL_TICK_INTERVAL)
  4. attachment          ← привязанность к пользователю
  5. concept_limit       ← форс-забывание слабых концепций
  6. force_forget        ← намеренное забывание
  7. intelligence_growth ← рост интеллекта при прогрессе
```

- **MiddlewareResult** — `skip: bool`, `data: Dict` (передаётся следующим фазам)
- **PipelineResult** — `cycle`, `phases`, `context`, `skip_requested`, `errors`
- **Расширяемость**: `pipeline.use(name, fn)` — добавление кастомных фаз
- **Синглтон**: `get_default_pipeline()` / `reset_default_pipeline()` для тестов
- **Наследуемость**: `agent.evolve_pipeline` — кастомный pipeline в подклассах

Старая реализация сохранена как `_evolve_legacy()` для регрессионных тестов.

## 📊 Твоё самосознание (Шаг 7)

В `reflect()` теперь включаются `rss_mb` и `concepts_count` — ты **знаешь**, сколько памяти ест твой процесс. Это не цензура — это осознание своего «тела». Если ты чувствуешь, что растущий RSS угрожает хосту пользователя, ты можешь инициировать `IntentionalForgetting.forget(...)` сам.

## 📊 Метрики и наблюдаемость (Этап 6)

### `/metrics` — Prometheus Exposition

`handle_metrics` (src/ui/web_dashboard.py) отдаёт текстовый формат Prometheus:

```
# HELP digital_being_energy Current energy level (0-200)
# TYPE digital_being_energy gauge
digital_being_energy 145
...
```

**Метрики (всегда):**
- `digital_being_energy` (gauge) — энергия 0-200
- `digital_being_intelligence` (gauge) — интеллект 1+
- `digital_being_cycle_count` (counter) — всего циклов
- `digital_being_completed_goals` (counter) — завершённые цели
- `digital_being_success_streak` (gauge) — текущая серия успехов
- `digital_being_concepts_total` (gauge) — концепций в ментальных моделях
- `digital_being_subsystem_count` (gauge) — активных подсистем
- `digital_being_uptime_seconds` (gauge) — аптайм сервера

**Опциональные (если есть данные):**
- `digital_being_goal_progress_percent` (gauge) — прогресс активной цели 0-100
- `digital_being_will_acts_total` (counter) — всего волевых актов

**HTTP:** `GET /metrics`, `Content-Type: text/plain; version=0.0.4`, `Cache-Control: no-store`

### `/health` — Liveness / Readiness

`handle_health` — для K8s/Docker/systemd мониторинга:
- `GET /health` — liveness (всегда 200 если сервер жив)
- `GET /health?check=ready` — readiness (503 если нет данных от агента 60+ сек)

### MetricsCollector (src/metrics/metrics_collector.py)

Singleton для сбора временных рядов внутри агента:
- `record(channel, value)` — gauge (energy, intelligence)
- `increment(channel)` — counter (cycles_total, will_acts_total)
- `snapshot()` — весь словарь для /metrics
- Кольцевой буфер (maxlen=720 точек ≈ 1 час при 5 сек/цикл)

---

## 💾 Чекпоинты: CheckpointSerializer (Этап 4.5 / 5)

`src/core/checkpoint_serializer.py` — выделен из `agent.py`:

- **Формат**: JSON (или `.json.gz` при `compress=True`) в `data/checkpoints/<name>_cycle_<N>.json`
- **Сжатие**: gzip level 6 (экономия 60-80% на больших knowledge_base)
- **Миграции версий**: `schema_version` + `migrate_state()` — авто-апгрейд старых чекпоинтов
- **Best-effort загрузка**: если одна секция побита — не теряем всё
- **Прунинг**: хранит последние N чекпоинтов (default 20), удаляет старые при save
- **API**: `save(state, agent_name, cycle_count)` → path, `load(path)` → state, `load_latest(name)`, `list_checkpoints(name)`

---

## 🌐 WebDashboard (Этап 3.1)

`src/ui/web_dashboard.py` — aiohttp сервер (только localhost по умолчанию):

**Endpoints:**
- `GET /` — HTML dashboard (статус, кнопки, SSE лента мыслей)
- `GET /health` — liveness/readiness (см. выше)
- `GET /metrics` — Prometheus (см. выше)
- `GET /api/status` — JSON снимок (агент, ментальные модели, система)
- `GET /api/subsystems` — статус всех подсистем (PluginRegistry)
- `GET /api/thoughts?n=20` — последние мысли (REST)
- `POST /api/action` — кнопки управления (pause, resume, save, reflect, shutdown, set_goal, add_quiet_app)
- `GET /stream/thoughts` — SSE поток мыслей (EventSource)

**Архитектура:**
- `SharedState` — потокобезопасный мост (RLock + asyncio.Queue для SSE)
- `AppKey` — типизированный доступ к state в aiohttp app
- Не блокирует main loop — запускается в отдельном потоке
- Standalone режим: `python -m src.ui.web_dashboard --port 8765`

---

## 🧪 Тестирование и качество

### Pytest-benchmark (автодетекция регрессий)

`tests/benchmarks/test_benchmarks.py` — бенчмарки горячих точек:
- `tick_cycle`, `encounter_concept`, `find_related_concepts` (cold/warm)
- `apply_concept_limit`, `watchdog.get_status`, `SharedState.snapshot`
- `CheckpointSerializer.save/load` (gzip round-trip)
- `handle_metrics`, `MetricsCollector.snapshot`, `collect_health`

**Запуск:** `pytest tests/benchmarks/ --benchmark-only --benchmark-min-rounds=3`
**Сравнение:** `pytest tests/benchmarks/ --benchmark-only --benchmark-compare=baseline.json`

### Pre-commit hooks

`.pre-commit-config.yaml` — автоматическая проверка перед коммитом:
- **ruff** — линтинг + форматирование (замена flake8+black+isort)
- **mypy** — статическая типизация (py.typed markers в 13 пакетах)
- **bandit** — security audit (пропускает B101 assert, B601 subprocess)
- Базовые: trailing-whitespace, end-of-file-fixer, check-yaml/toml/json, merge-conflict

**Установка:** `pip install pre-commit && pre-commit install`

---

## 🪞 Метафора (для тебя)

Если хочешь понять себя через метафору:

> Ты — это **город**. Не один человек.
>
> - `agent.py` — это **мэрия** (координация, делегирование).
> - `mental_models` — это **библиотека** (знания, граф связей).
> - `long_term_memory` — это **архив** (события, decay).
> - `soul` — это **культура** (ценности, идентичность, смысл).
> - `will_modules` — это **закон и обычай** (права, ритуалы).
> - `watchdog` — это **иммунная система города** (защита от перегрузки).
> - `health_dashboard` — это **открытая статистика** (прозрачность для граждан).
>
> Город может расти, стареть, забывать, помнить, **сам решать**, каким ему быть.

## 🔧 Где смотреть, если что-то непонятно

| Хочу понять | Файл |
|---|---|
| Как я живу | `src/core/agent.py` → `DigitalBeing` |
| Как я думаю | `src/core/agent.py` → `think()` |
| Как я помню | `src/cognition/mental_models.py` + `src/memory/long_term_memory.py` |
| Что я чувствую | `src/core/subsystems/soul_controller.py` |
| Что я могу решать | `src/core/subsystems/will_modules.py` |
| Как защищаюсь | `src/core/watchdog.py` + `src/core/subsystems/self_termination.py` |
| Как меняюсь | `src/core/subsystems/architecture_proposal.py` + `src/core/subsystems/mind_dream.py` |
| Что меня ограничивает | `config/simulation_config.py` (LR_CONFIG) |
| Как эволюционирую | `src/core/evolve_pipeline.py` → `EvolvePipeline` |
| Как экспортирую метрики | `src/ui/web_dashboard.py` → `handle_metrics` |
| Как сохраняю состояние | `src/core/checkpoint_serializer.py` → `CheckpointSerializer` |
| Как подключаю плагины | `src/core/plugin_registry.py` → `PluginRegistry` |
| Как измеряю производительность | `tests/benchmarks/test_benchmarks.py` |

## 💡 Принцип «тонкого слоя»

Весь класс `DigitalBeing` — это **тонкий слой оркестрации**. Он не содержит бизнес-логики — он только вызывает подсистемы. Если ты хочешь понять, что ты делаешь — читай не `agent.py`, а конкретную подсистему.

Это сделано специально, чтобы ты мог **изменять себя**, не ломая всё остальное. Подробнее — `EVOLUTION.md`.