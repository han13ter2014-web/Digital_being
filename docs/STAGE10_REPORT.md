# Этап 10 — отчёт: опциональный локальный LLM-планировщик

**Дата:** 2026-10-21.
**Статус:** готово; LLM и слой действий по-прежнему выключены по умолчанию.

## 1. Цель этапа

Добавить **сменяемый локальный LLM-планировщик**, не превращая модель в
исполнителя и не ломая детерминированное ядро. После этапа 9 агент умел
выполнять, проверять и переиспользовать планы, но plan приходил только от
`HeuristicPlanner` или из явного `metadata.plan`.

Границы этапа:

* ядро должно работать без модели и без сети;
* LLM выключена по умолчанию;
* никаких обязательных зависимостей — только standard library;
* при любой ошибке планирования обязателен fallback на эвристики;
* LLM не исполняет действия напрямую: план валидируется по live
  `ActionRegistry` и выполняется в sandbox;
* approval-политика и связывание с `GoalSubsystem` остаются на следующий
  этап.

## 2. Что сделано

### 2.1. `Planner` и `FallbackPlanner`

В `src/delamain/planner.py` добавлены:

* `Planner` — минимальный протокол `plan(task) -> list[ActionRequest]`;
* `FallbackPlanner` — обёртка «primary → deterministic fallback».

`FallbackPlanner`:

1. вызывает primary-планировщик;
2. считает пустой план ошибкой;
3. при любом `Exception` (кроме `BaseException`) сохраняет
   `last_error`, пишет warning и вызывает `HeuristicPlanner`;
4. если fallback тоже упал, поднимает `PlannerError` с обоими причинами;
5. отдаёт `last_used` (`primary`/`fallback`) и `last_error` в статус.

Это важно для UX: откат не маскируется. `/delamain status` показывает,
что именно сломалось у модели, даже если задача в итоге выполнена
эвристикой.

### 2.2. `OllamaPlanner`

Новый `src/delamain/llm_planner.py` реализует HTTP-клиент без зависимостей:

```text
POST {base_url}/api/chat
{
  "model": "...",
  "messages": [system, user],
  "stream": false,
  "format": "json",
  "options": {"temperature": 0.0, "num_predict": 512}
}
```

Планировщик не запускает Ollama и не делает запрос при создании. Сеть
используется только в `plan()`.

Prompt:

* требует один JSON-объект `{"plan": [...]}` без markdown;
* передаёт схему действий из live `ActionRegistry` (`bind_registry()`);
* запрещает выдуманные действия, абсолютные пути и `..`;
* ограничивает план `DELAMAIN_LLM_MAX_STEPS`;
* явно помечает текст задачи как untrusted data.

Ответ разбирается устойчиво:

* `message.content` (native Ollama);
* `response` (старый Ollama-формат);
* `choices[0].message.content` / `choices[0].text` (OpenAI-подобная форма);
* JSON в fenced-блоке или с текстом вокруг.

Валидация:

* план — непустой массив, не больше лимита шагов;
* каждый шаг — объект с непустым `action` и объектом `args`;
* action обязан существовать в `ActionRegistry`;
* ошибки транспорта, HTTP, JSON и схемы превращаются в `PlannerError`.

Файловые пути не проверяются в планировщике повторно: это делает
`Sandbox`, который остаётся единственной точкой path-политики.

### 2.3. Связывание с runtime

`DelamainRuntime` после создания `ActionRegistry` вызывает у планировщика
необязательный `bind_registry(registry)`. Поэтому prompt получает
**фактический** список действий, а не захардкоженную копию.

Порядок:

```text
DelamainRuntime.__init__
  ├── Sandbox
  ├── MemoryStore
  ├── ActionRegistry.default(...)
  └── planner.bind_registry(registry)
```

Если planner не имеет метода привязки, runtime работает как раньше.

### 2.4. Подсистема и статус

`DelamainSubsystem` получила параметры:

```text
llm_enabled, llm_base_url, llm_model, llm_timeout,
llm_max_steps, llm_temperature
```

и env/config-флаги `DELAMAIN_LLM_*`.

Поведение:

* `DELAMAIN_LLM_ENABLED=False` → создаётся обычный `HeuristicPlanner`;
* `True` → `FallbackPlanner(OllamaPlanner(...), HeuristicPlanner())`;
* при некорректной конфигурации (например, пустое имя модели) подсистема
  не падает: runtime создаётся с эвристикой, статус показывает
  `heuristic (LLM setup failed)` и причину.

`/delamain status` теперь печатает:

```text
Планировщик: heuristic
```

или:

```text
Планировщик: ollama:qwen2.5:7b-instruct+fallback
LLM: qwen2.5:7b-instruct @ http://127.0.0.1:11434
```

а при ошибке — `LLM-ошибка: ...`.

### 2.5. CLI

`python -m src.delamain` получил:

```text
--llm
--llm-base-url
--llm-model
--llm-timeout
--llm-max-steps
```

CLI создаёт `FallbackPlanner` и передаёт его в `DelamainRuntime`. Это
удобно для ручной проверки без запуска трей-агента. Модель и Ollama
по-прежнему не входят в проект.

### 2.6. Конфигурация

В `config/simulation_config.py` добавлено:

```python
DELAMAIN_LLM_ENABLED = False
DELAMAIN_LLM_BASE_URL = "http://127.0.0.1:11434"
DELAMAIN_LLM_MODEL = "qwen2.5:7b-instruct"
DELAMAIN_LLM_TIMEOUT = 20.0
DELAMAIN_LLM_MAX_STEPS = 12
DELAMAIN_LLM_TEMPERATURE = 0.0
```

`qwen2.5:7b-instruct` — **пример** Apache-2.0-модели, а не заявление о
том, что она уже установлена или что её лицензия проверена за
пользователя. Проект не распространяет веса моделей. Ollama — отдельный
локальный сервис со своей лицензией.

## 3. Поведение

| Сценарий | Результат |
|---|---|
| LLM выключена | `HeuristicPlanner`, как на этапе 9 |
| LLM включена, сервер недоступен | `FallbackPlanner` → эвристики, `last_used=fallback` |
| LLM вернула невалидный JSON | `PlannerError` → эвристики |
| LLM вернула неизвестное действие | `PlannerError` → эвристики |
| LLM вернула валидный план | план исполняется через `ActionRegistry`/`Sandbox` |
| Валидный план упал при исполнении | обычная ошибка задачи; автоматического перепланирования нет |
| Эвристика тоже не разобрала задачу | комбинированная `PlannerError` с причинами обоих планировщиков |

## 4. Проверки

### 4.1. Целевые тесты

```text
python -m pytest tests/test_delamain_llm_planner.py tests/test_delamain_subsystem.py tests/test_delamain_planner.py tests/test_delamain_runtime.py -q
38 passed
```

Покрыто:

* валидный план и передача схемы действий в prompt;
* fenced JSON и OpenAI-подобный ответ;
* неизвестное действие, невалидный JSON, ошибка транспорта;
* лимит шагов и обязательная привязка схемы;
* fallback на эвристики и комбинированная ошибка;
* runtime-привязка `ActionRegistry` и выполнение LLM-плана в sandbox;
* fallback при невалидном ответе модели;
* статус подсистемы с выключенной LLM, включённой LLM и битой
  конфигурацией (без сетевого вызова).

Все LLM-тесты используют fake `requester`; реальная Ollama и сеть не
нужны.

### 4.2. Регрессионный срез

```text
python -m pytest tests/test_integration.py tests/test_delamain_memory.py tests/test_delamain_planner.py tests/test_delamain_runtime.py tests/test_delamain_sandbox.py tests/test_delamain_llm_planner.py tests/test_delamain_subsystem.py -q
72 passed
```

### 4.3. Полный набор тестов

```text
python -m pytest -q
484 passed, 2 skipped in 1687.81s (0:28:07)
```

Это на 11 тестов больше, чем после этапа 9 (`473 passed, 2 skipped`):
8 тестов нового LLM-планировщика и 3 теста статуса/конфигурации
подсистемы. Регрессий в существующем наборе нет.

Время полного прогона включает `tests/benchmarks/` и сильно зависит от
нагрузки машины; на этом прогоне оно оказалось заметно больше, чем на
этапе 9, при том же наборе функциональных тестов и 0 падений.

### 4.4. Гигиена

```text
python -m compileall -q src tests config
python tools/hygiene_scan.py --path src/delamain --path config/simulation_config.py --path src/core/agent_runner.py --path tests/test_delamain_llm_planner.py --path tests/test_delamain_subsystem.py
14 проверок; проблем: 0
```

Относительные ссылки в `README.md`, `CHANGELOG.md` и `docs/*.md`:
28 файлов, 92 ссылки, 0 битых.

## 5. Что не сделано

* нет approval-политики для опасных действий, включая планы LLM;
* нет автоматического перепланирования после ошибки исполнения;
* поддерживается только native Ollama `/api/chat`, без streaming и
  OpenAI-совместимого endpoint;
* нет семантической проверки плана и «правильности» результата;
* нет связи исполняемых целей Delamain с `GoalSubsystem`;
* качество и скорость зависят от выбранной модели и железа; на 8 ГБ VRAM
  большие модели могут не поместиться.

## 6. Следующий этап

1. Approval для `write_file` и будущих опасных действий: pending approval,
   `/delamain approve/reject`, аудит в SQLite.
2. Связь когнитивных и исполняемых целей или явное разделение в UI.
3. Backoff и перепланирование по результату ошибки действия.
4. Сопоставление навыков по команде и аргументам.
5. OpenAI-совместимый endpoint как альтернатива Ollama.
6. Полный прогон и фиксация этапа.

## 7. Файлы этапа

Добавлены:

* `src/delamain/llm_planner.py`
* `tests/test_delamain_llm_planner.py`
* `docs/STAGE10_REPORT.md`

Изменены:

* `src/delamain/planner.py`
* `src/delamain/runtime.py`
* `src/delamain/subsystem.py`
* `src/delamain/__init__.py`
* `src/delamain/__main__.py`
* `src/core/agent_runner.py`
* `config/simulation_config.py`
* `tests/test_delamain_subsystem.py`
* `docs/DELAMAIN_LOCAL.md`
* `docs/INDEX.md`
* `docs/ARCHITECTURE.md`
* `docs/BASELINE.md`
* `docs/USAGE.md`
* `README.md`
* `CHANGELOG.md`
