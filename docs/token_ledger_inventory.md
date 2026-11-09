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

**Точки создания — две:** в жизненном контуре — одна,
`DelamainSubsystem._build_planner()` (`src/delamain/subsystem.py:466–488`);
standalone CLI (`src/delamain/__main__.py:114–123`, `--llm` →
`FallbackPlanner(OllamaPlanner(...))`) собирает стек вне жизненного контура
DigitalBeing. При `llm_enabled=False` (дефолт,
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
  *(Обновлено k16-37: точка выбрана — `_plan`, см. §8.1; `_build_planner`
  телеметрию не касается. Лимитов-«кошелька» до сих пор нет, см. §8.3.1.)*
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
| Подсчёт токенов | **есть** — врезка k16-36 (см. §8); `tests/test_ledger_hook.py` |
| Журнал обращений к LLM | **частично** — токены считаются, журнал вызовов нет (§8.4) |
| Кумулятивный счётчик обращений | **есть** — `TokenLedger` (k16-33, §8.2) |
| Eval-счётчики ScriptedPlanner | используются в evaluation.py; пин зоны дублирования в этом тикете |

---

## 8. Актуальное состояние: врезка k16-36 + покрытие k16-37

Раздел 8 **дополняет** карту k16-31 (разделы 1–7 остаются каноном
инвентаризации на 2026-11-09). Всё, что ниже, — состояние после мержа
k16-36 (`ab188bc`) и тикета k16-37. Где §8 расходится с §1/§5 — верен §8:
это и есть зафиксированный дрейф, а не переписывание карты.
§7: три строки таблицы покрытия заменены в k16-37 (дрейф задокументирован в §8.2).

### 8.1 Точка врезки и семантика записи

**Единственная точка — `OllamaPlanner._plan()`** (`src/delamain/llm_planner.py`),
между успешным ответом транспорта и парсингом плана. Других перехватов нет:
`FallbackPlanner` делегирует primary, поэтому CLI-путь (`__main__.py`,
`--llm`) и жизненный контур покрываются одной врезкой — двойной телеметрии
нет ни через `plan()`, ни через `replan()`-канал.

- **Где пишем.** После `self._requester(...)` вернул словарь; **до**
  `_extract_content`/`_parse_plan`. Семантика: токены потрачены самим
  ответом, поэтому запись не зависит от исхода парсинга. Ответ с битым
  JSON плана **даёт запись** и уходит в fallback — это норма, а не дефект.
- **Что пишем.** `prompt_eval_count` → `in`, `eval_count` → `out`,
  `src="planner"`, `cycle=None` (в журнале — `cycle=-1`). `_extract_usage`
  принимает только настоящие `int` (`bool` отсекается первым) и
  неотрицательные; **нули `{0, 0}` — валидные данные** и пишутся.
- **Когда не пишем.** Нет ответа (транспорт/HTTP/JSON-ошибка) → 0 записей;
  отсутствует или невалиден `usage` → 0 записей. Это «нет данных», а не
  «потеря данных»; отдельного счётчика «нет usage» нет.
- **Отказ телеметрии пассивен и наблюдаем.** Ошибка `record()`/резолва
  синглтона не ре-рейзится и не меняет исполнителя: план возвращается,
  отказ фиксируется в `OllamaPlanner.last_ledger_error` (липкий) + одна
  строка `token_ledger: <ExcType>: ...` в stderr. В `FallbackPlanner`
  такой отказ **не** виден как `last_used=fallback`.
- **Резолв леджера ленивый.** `token_ledger=None` → `get_token_ledger()`
  в момент первого реального `_plan` с валидным usage; не при
  конструировании, не при импорте, не при `_build_planner()`.
- **Закрытый набор источников:** `TOKEN_SOURCES = {"unmapped", "planner"}`
  (`src/core/token_ledger.py`). Метка вне набора санитизируется в
  `unmapped` — «planner» обязан оставаться в наборе.

### 8.2 Что снимает дрейф §1/§5

| §1/§5 (k16-31) | Факт после k16-33/k16-36 |
|---|---|
| «Учёта токенов нет; `eval_count` не читается» | читается в `_extract_usage`, пишется в `TokenLedger` |
| «Журнала обращений нет» | есть `TokenLedger`: журнал `data/logs/token_journal.txt`, replay, счётчики, `silent_losses` (k16-33) |
| «Счётчики только в eval-харнессе» | появился прод-счётчик `TokenLedger.count_calls()`; eval-счётчики остались своими |
| §5 «создать модуль-счётчик» | создан: `src/core/token_ledger.py` |
| «точка перехвата — `_plan` **или** `_build_planner`» | выбрана `_plan`; `_build_planner` телеметрию не касается |

### 8.3 Что **не** сделано (граница v1)

1. **Нет журнала вызовов как такового.** Токены и число записей есть
   (`call=<n>`), но нет per-call `kind=plan/replan`, модели, длительности и
   `ok/error`. История исходов по-прежнему только `last_error`/`last_used`.
2. **Нет учёта запросной стороны без ответа.** Упавший вызов (timeout,
   HTTP 5xx) токенов не пишет — `prompt_eval_count` приходит только с
   ответом. Оценки по символам нет.
3. **Нет лимитов/квот/алертов** по токенам: `ActionBudget` про энергию
   действий, не про вызовы планнера.
4. **`src=planner` виден только вне жизненного контура.** При
   `llm_enabled=False` (дефолт, NO_LLM_LIFE) `_build_planner()` → `None`,
   врезка недостижима; записи идут лишь из CLI `--llm` и прямых
   конструкторов `OllamaPlanner`. Тишина в журнале при штатном проде
   означает «LLM выключен», а не «токенов не было» — метки-различителя нет.
5. **Читателей леджера в `src/` нет:** `get_token_ledger()`/`snapshot()`
   никто не опрашивает, `journal.silent_losses` наружу не выводится
   (наблюдаемость есть только на инстансе).

### 8.4 Покрытие (k16-37)

`tests/test_ledger_hook.py`, 15 тестов: 9 ранних (k16-36) + 6 пинов
k16-37:

| Пин | Тест |
|---|---|
| replan-канал: `replan()` → ровно 1 запись, исполнитель primary | `test_replan_channel_single_record` |
| запись до парсинга: битый JSON → 1 запись, `last_used=fallback`, `last_ledger_error=None` | `test_record_precedes_plan_parsing` |
| транспорт-отказ primary → 0 записей, fallback, отказ телеметрии не подмешан | `test_transport_failure_records_nothing` |
| матрица невалидного usage (оба поля × `False`/`None`/`"45"`/`0.0`) → 0 записей | `test_invalid_usage_matrix` |
| нули `{0, 0}` валидны → 1 запись `in=0 out=0` | `test_zero_usage_is_valid` |
| NO_LLM_LIFE: `llm_enabled=False` → `_build_planner()` → `None`, синглтон не резолвится, журнала в data-каталоге нет | `test_llm_disabled_tap_unreachable` |

Не покрыто пинами (кандидаты в следующий тикет): «нет usage → 0 записей»
различается ли от «usage невалиден» (сейчас одинаково — по дизайну);
повторная врезка при `replan`-отказе **после** успешной записи (нет
повторного вызова primary — проверено кодом, пина нет); `src=planner` в
реальном журнале при живом синглтоне (пин только через инъекцию/`tmp_path`).
