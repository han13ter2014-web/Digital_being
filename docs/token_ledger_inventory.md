# Инвентаризация: лимиты, токены и журнал обращений (k16-31)

Дата: 2026-11-09. Ветка: `feature/k16-31-token-ledger-inventory` от main @ 0af11c9.
Прикладная часть k16-13 (механика токенов и журнала обращений) — инвентаризация
перед implementation (k16-32+). Метод: grep по `token|usage|ledger|budget|journal|log_call|llm|eval_count`
по `src/`, чтение найденных зон, сверка с тестовым покрытием.

## 1. Единственная точка обращений к LLM

**`src/delamain/llm_planner.py` — `OllamaPlanner`** (класс: строки 62–313).

- HTTP POST на Ollama `/api/chat`, только stdlib (`_post_json`, строки 26–59).
- Вызовы идут через `_plan()` (111–177): `plan()` и `replan()`.
- Ограничения запроса: `timeout`, `max_steps`, `max_task_chars=8000`,
  `num_predict=512` (параметр запроса, не учёт).
- **Учёта токенов нет**: ответ Ollama несёт `prompt_eval_count` / `eval_count` —
  код их не читает (grep `eval_count` по `src/` — 0 совпадений).
- **Журнала обращений нет**: каждый вызов не записывается никуда; observable-состояние
  — только `last_error` и `status()` (179–186) с прошлым/последним исходом.

**Точка создания — одна:** `DelamainSubsystem._build_planner()`
(`src/delamain/subsystem.py:466–488`). При `llm_enabled=False` (дефолт,
`DELAMAIN_LLM_ENABLED`, subsystem.py:281–287) планнер-стек не создаётся вовсе
(`None` → heuristic); при включённом флаге — `FallbackPlanner(OllamaPlanner, HeuristicPlanner)`.
Канон `docs/DECISION_NO_LLM_LIFE.md` соблюдён: LLM — только планнер Delamain,
жизненный контур детерминирован.

**Классификация источника плана** (не счётчик): `goal_authoring._planner_info()`
(`src/delamain/goal_authoring.py:713–730`) выводит `source` ∈ {llm, planner,
heuristic} из `FallbackPlanner.last_used`. `FallbackPlanner` хранит только
`last_error` / `last_used` / `last_context` (`src/delamain/planner.py:235–237`,
`status()` — 302–310).

## 2. Бюджет: энергия действий, не токены

**`src/core/action_budget.py` — `ActionBudget`** (361 строка, весь файл).

- Политика расхода существующей `DigitalBeing.energy` на действие;
  второй бухгалтерии нет по дизайну (docstring модуля, 20–22).
- Счётчики: `_allowed_count`, `_denied_count`, `_spent_total` (100–102);
  `status()` (263–280) — снимок без побочных эффектов.
- Идемпотентность: повторный `charge()` с тем же `action_id` — `duplicate`,
  энергия не списывается дважды; кэш `_approved` — OrderedDict на 128 записей
  (163–179, 324–328). Отказ намеренно не кэшируется (342–343).
- `refund()` (232–261) уменьшает `_spent_total` на фактически применённую сумму.
- In-process: не сериализуется, транзакционной защиты нет (явно оговорено
  в docstring, 20–22).
- Потребители: `agent_act.py:199–212` (charge перед действием),
  `agent.py:1143–1145` (refund «право на ошибку»),
  `delamain/subsystem.py:_budget_gate` (961–1036) — **fail-closed** при сломанном
  budget: «a broken ledger must fail closed, not spend» (999).

**Покрытие:** `tests/test_action_budget.py`, `test_action_budget_agent.py`,
`test_delamain_budget.py`.

## 3. Журналы (существующие)

| Журнал | Файл | Что пишет | Чего не пишет |
|---|---|---|---|
| `BufferedLogger` | `src/core/buffered_logger.py` | действия агента в `data/logs/agent_log.txt`, ротация | обращения к LLM |
| `MemoryStore` (SQLite WAL) | `src/delamain/memory.py:134–154` | таблица `episodes` — выполненные действия Delamain (task_id, action, ok, meta) | обращения к планнеру/LLM |
| `_last_tick_ledger` | `src/core/agent_runner.py:1681–1700, 1790, 1827` | последний тик (kind, energy before/after, error) → `data/logs/dialogue_cycles.jsonl` (1613–1625) | только последний тик, не кумулятивно |
| Webhooks | `src/metrics/webhooks.py` | Telegram-уведомления | «token» здесь — токен бота, ложное совпадение |

**Покрытие BufferedLogger:** `test_logger_lock.py` (k16-21),
`test_logger_silent_loss.py` (k16-23), `test_flush_immediate_observable.py`
(k16-27), `test_log_encoding.py`.

## 4. Eval-only счётчики (зона дублирования)

`src/delamain/evaluation.py` — `ScriptedPlanner.plan_calls` / `replan_calls`
(623–624, инкременты 635/646). Это счётчики вызовов планнера, но **только в
evaluation-харнессе**: продовые `OllamaPlanner` / `FallbackPlanner` /
`HeuristicPlanner` таких счётчиков не имеют. Зафиксировано пином
`tests/test_token_ledger_inventory.py::test_call_counters_exist_only_in_evaluation_harness`.

## 5. Список «не существует, нужно создать» (для k16-32+)

1. **Модуль-счётчик обращений к LLM** — ни файла `token_ledger` / `call_journal`
   / `usage_ledger` в `src/`, ни импортируемого модуля (пин
   `test_no_token_ledger_module_yet`).
2. **Учёт токенов**: чтение `prompt_eval_count` / `eval_count` из ответа
   Ollama; оценка запросной стороны (хотя бы по символам/словам, без
   токенизатора — канон запрещает внешние зависимости в контуре).
3. **Журнал обращений**: запись каждого вызова {ts, модель, kind=plan/replan,
   ok, error, duration, tokens} — сейчас виден только последний исход
   (`last_error`/`last_used`), история безвозвратно теряется (пины
   `test_ollama_planner_keeps_no_call_journal`,
   `test_fallback_planner_reports_only_last_call_state`).
4. **Лимиты на LLM-вызовы**: бюджет/кулдаун обращений как таковой —
   `ActionBudget` покрывает энергию действий, но не вызовы планнера;
   единственные предохранители — `max_task_chars`, `timeout`, `num_predict`.
5. **Сериализация счётчиков**: всё перечисленное сейчас in-process;
   рестарт обнуляет (как и `ActionBudget._spent_total`).

## 6. Риски пересечения с инвариантами конвейера

- **RLock (k16-21).** Если будущий журнал обращений пишет в файл, брать паттерн
  `BufferedLogger`: один `threading.RLock` на инстанс, не `Lock` — реентрантные
  вызовы (auto-flush из-под `log()`) на обычном Lock дадут взаимоблокировку.
  Глобальный инстанс — только double-check под модульным локом
  (`_GET_LOGGER_LOCK`).
- **silent_losses (k16-23/k16-27).** Потери записей журнала обращений не должны
  молчать: счётчик на инстансе + одна строка в stderr, формат общий с
  k16-23/k16-27. Если журнал пойдёт через существующий `BufferedLogger` —
  наблюдаемость потерь уже есть; если свой writer — своя по той же конвенции.
- **MemoryStore WAL.** Если журнал LLM-вызовов ляжет в SQLite Delamain —
  отдельная таблица, а не смешение с `episodes` (эпизоды — выполненные
  действия, не обращения); `_ThreadSafeConnection.lock` (`memory.py:100–112`)
  уже сериализует методы и реентрантен.
- **ActionBudget vs будущий LLM-бюджет.** Не плодить вторую политику там же:
  граница ActionBudget — энергия действий; лимит обращений к LLM — отдельная
  зона с явной точкой перехвата (`OllamaPlanner._plan` или `_build_planner`),
  иначе два независимых «кошелька» начнут конфликтовать в `_budget_gate`.
- **tempfile/tmp_path.** Тесты новой механики — в `tmp_path`, `data/` не
  трогать (инвариант конвейера; в этом тикете соблюдён).
- **Классификация source.** `goal_authoring._planner_info()` и
  `FallbackPlanner.last_used` вычисляют источник плана независимо; при
  появлении журнала обращений источник истины — одна запись журнала, иначе
  «llm»/«planner» в summary и фактические вызовы разойдутся.

## 7. Что покрыто тестами / что нет

| Зона | Покрытие |
|---|---|
| ActionBudget (charge/refund/идемпотентность) | `test_action_budget*.py`, `test_delamain_budget.py` + пины этого тикета |
| BufferedLogger (RLock, silent_losses, flush_immediate) | `test_logger_lock.py`, `test_logger_silent_loss.py`, `test_flush_immediate_observable.py` |
| OllamaPlanner (парсинг, ошибки, fallback) | `test_delamain_llm_planner.py` |
| Подсчёт токенов | **нет — механики нет** (пин отсутствия) |
| Журнал обращений к LLM | **нет — механики нет** (пин отсутствия) |
| Кумулятивный счётчик обращений | **нет — механики нет** (пин отсутствия) |
| Eval-счётчики ScriptedPlanner | используются в evaluation.py; пин зоны дублирования в этом тикете |
