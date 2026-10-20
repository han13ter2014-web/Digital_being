# 🧬 Этапы 3 + 4 — Расширяемость и экспериментальные фичи

Документ описывает архитектуру и использование фич, добавленных в Этапах 3 и 4
(июнь 2026). Все они спроектированы как **расширения без поломки существующего
API** — старые подсистемы продолжают работать.

---

## 3.5 Subsystem + PluginRegistry

### Проблема

`DigitalBeing` стал раздутым — 25+ подсистем инициализировались вручную в
`__init__()`. Добавление новой подсистемы требовало правки ядра.

### Решение

**Базовый класс `Subsystem`** (`src/core/subsystem_base.py`):

```python
from src.core.subsystem_base import Subsystem

class MyPlugin(Subsystem):
    name = "my_plugin"           # уникальное имя (для registry)
    priority = 100               # меньше = раньше в tick_all()
    version = "1.0.0"

    def setup(self, context):     # вызывается один раз
        # context = {"agent": ..., "registry": ..., "agent_name": ...}
        pass

    def tick(self, cycle, context):   # главный цикл
        # должен быть идемпотентным и быстрым
        return {"events": [{"name": "my.event", "data": ...}]}

    def status(self):              # JSON для dashboard
        return {"name": self.name, "tick_count": self._tick_count}

    def teardown(self):            # graceful shutdown
        pass
```

**Реестр `PluginRegistry`** (singleton, lazy):

```python
from src.core.subsystem_base import PluginRegistry

registry = PluginRegistry.get_global()
registry.register(MyPlugin())     # или registry.register_class(MyPlugin)

# Все тики разом — по приоритетам, с изоляцией ошибок:
report = registry.tick_all(cycle=1, {"agent": my_agent})
# {"cycle": 1, "ok": ["my_plugin"], "failed": [], "results": {...},
#  "elapsed_ms": 0.123}

# Снимок для дашборда:
registry.status_all()
# {"subsystem_count": 21, "enabled_count": 21, "total_ticks": 1234, ...}
```

### LegacySubsystemAdapter

Существующие подсистемы (без наследования от `Subsystem`) автоматически
оборачиваются через `LegacySubsystemAdapter`:

```python
from src.core.subsystem_base import attach_existing_subsystem

# Оборачивает sleep_cycle в Subsystem-адаптер и регистрирует в registry:
adapter = attach_existing_subsystem(agent, "sleep_cycle", priority=120)
```

### Интеграция в DigitalBeing

В `DigitalBeing.__init__()` после инициализации всех подсистем вызывается
`_register_all_subsystems_in_registry()`, которая автоматически регистрирует
21 подсистему в PluginRegistry (с правильными приоритетами от 10 до 190).

`HealthDashboardSubsystem` и `NurseryWatcher` подключаются отдельно (Этап 3.6).

---

## 3.3 NurseryWatcher

### Проблема

`MindDream` оставляет «семена» умерших/уснувших агентов в `data/nursery/`.
Никто не отслеживал появление новых seed-ов — пользователь должен был
проверять папку вручную.

### Решение

**`NurseryWatcher`** (`src/core/subsystems/nursery_watcher.py`):

- Подсистема типа `Subsystem` (Этап 3.5) — регистрируется в PluginRegistry.
- Периодически (в `tick()`) сканирует `data/nursery/`.
- Обнаруживает новые seed-ы (через сравнение с `_known_seeds`).
- Валидирует структуру (`is_complete`, `missing_files`).
- Публикует событие `nursery.new_seed` через `EventBus`.
- Уведомляет агента через `agent.on_nursery_new_seed(payload)` callback.
- История ограничена 100 записями.

**Использование:**

```python
from src.core.subsystems.nursery_watcher import NurseryWatcher

watcher = NurseryWatcher(agent_name="TestAgent")
watcher.setup({})

# Каждый цикл:
result = watcher.tick(cycle=1)
# result == {"events": [{"name": "nursery.new_seed", "data": {...}}]} или None

# Через PluginRegistry (используется DigitalBeing):
reg = PluginRegistry.get_global()
watcher = reg.get("nursery_watcher")
```

---

## 3.1 Web Dashboard (aiohttp)

### Проблема

Хотелось видеть состояние агента в реальном времени в браузере, но без
тяжёлых зависимостей и без блокировки основного цикла.

### Решение

**Лёгкий `aiohttp`-сервер** (`src/ui/web_dashboard.py`):

| Endpoint | Метод | Описание |
|----------|-------|----------|
| `/` | GET | HTML-страница dashboard (Chart.js для графиков) |
| `/api/status` | GET | JSON-снимок агента |
| `/api/subsystems` | GET | Список всех подсистем |
| `/api/thoughts` | GET | Последние N мыслей |
| `/api/action` | POST | Кнопки: pause/resume/save/reflect/thought/shutdown/set_goal |
| `/stream/thoughts` | GET (SSE) | Лента мыслей в реальном времени |

**Использование:**

```python
from src.ui.web_dashboard import WebDashboard

dash = WebDashboard(agent, port=8765)
dash.start()    # в отдельном потоке, не блокирует main loop

# В главном цикле:
dash.publish_status(agent.get_full_state())
dash.publish_subsystems(agent.get_subsystems_status())
dash.publish_thought("мысль", cycle=42)

action = dash.pop_action()
result = dash.apply_action(action)  # pause/resume/save/...
```

**Безопасность:**
- Слушает `127.0.0.1` по умолчанию (только localhost).
- Thread-safe `SharedState` между main loop и HTTP.
- Действия кнопок попадают в очередь и применяются из main loop — нет race condition.

---

## 3.6 Metrics + Time-Series

### Проблема

Хотелось видеть графики изменения `energy`, `intelligence`, `rss_mb` и т.п.
для анализа поведения агента.

### Решение

**`MetricsCollector`** (`src/metrics/metrics_collector.py`):

```python
from src.metrics import MetricsCollector

mc = MetricsCollector(agent_name="Lucy")
mc.record("energy", 100, cycle=1)
mc.record("energy", 95, cycle=2)
mc.increment("thoughts")           # rate-counter

# Чтение
hist = mc.get_history("energy", last_n=100)  # list of {ts, value, cycle}
stats = mc.get_stats("energy")               # {count, min, max, avg, last, rate_per_min}
snap = mc.snapshot()                         # все каналы для дашборда

# Персистентность
mc.export_json("data/metrics/lucy.json")     # полный snapshot
mc.append_ndjson("data/metrics/energy.ndjson", "energy", value=95)  # инкрементально
```

**Дефолтные каналы:** `energy`, `intelligence`, `cycle_count`, `completed_goals`,
`concepts_count`, `rss_mb`, `subsystems_active`, `thoughts_per_minute`,
`actions_per_minute`.

**Дашборд рисует графики** в HTML через Chart.js — данные берутся из
`/api/status` и `/api/subsystems`.

---

## 3.7 i18n (мультиязычность)

### Проблема

Все тексты в Digital Being были на русском. Без i18n нельзя было перевести
на английский (или другой язык) без правки кода.

### Решение

**`I18n`** (`src/metrics/i18n.py`):

- JSON-файлы в `data/i18n/{lang}.json` (например, `ru.json`, `en.json`).
- Fallback на дефолтный язык (русский).
- Интерполяция: `t("greeting", name="Lucy")` → "Привет, Lucy!".
- Singleton `get_i18n()` для глобального доступа.

**Файлы локализаций:**
- `data/i18n/ru.json` — дефолтный (русский)
- `data/i18n/en.json` — английский

**Использование:**

```python
from src.metrics.i18n import set_language, t

set_language("en")
print(t("dashboard.title"))  # "Digital Being — Dashboard"
print(t("agent.cycle_banner", name="Lucy", cycle=42, intelligence=2, energy=100))
# "[Lucy] Cycle 42 | Intelligence: 2 | Energy: 100"
```

---

## 3.8 Webhooks (Telegram / Discord)

### Проблема

Хотелось получать уведомления от агента в Telegram или Discord.

### Решение

**`WebhookManager`** (`src/metrics/webhooks.py`):

```python
from src.metrics.webhooks import (
    WebhookManager, TelegramWebhook, DiscordWebhook, create_default_manager,
)

# Из env-переменных (silent если их нет):
mgr = create_default_manager()
# DIGITAL_BEING_TELEGRAM_TOKEN, DIGITAL_BEING_TELEGRAM_CHAT_ID
# DIGITAL_BEING_DISCORD_WEBHOOK_URL

# Или вручную:
mgr = WebhookManager(max_per_minute=20)
mgr.add(TelegramWebhook(token="...", chat_id="..."))
mgr.add(DiscordWebhook(url="https://discord.com/api/webhooks/..."))

# Асинхронная отправка (не блокирует main loop):
mgr.send("💡 Новая мысль: ...", priority="high")
mgr.start()  # запустить worker thread

# Graceful shutdown:
mgr.stop()
```

**Rate-limiting:** не более `max_per_minute` сообщений в минуту.
**Очередь:** до 100 сообщений, переполнение → отбрасывание (не блокирует).

---

## 3.2 Голос (TTS/STT)

### Проблема

Digital Being — текстовое существо, но иногда хочется **поговорить** с ним
(или дать ему голос). Однако установка TTS/STT моделей не всегда возможна.

### Решение

**`VoiceRouter`** (`src/metrics/voice.py`) — единая точка входа с
graceful fallback:

| Движок | TTS | STT | Зависимости |
|--------|-----|-----|-------------|
| `ConsoleVoiceEngine` | ✅ (печатает) | ❌ | нет |
| `PyttsxVoiceEngine` | ✅ | ❌ | `pyttsx3` |
| `WhisperSTTEngine` | ❌ | ✅ | `faster-whisper`, `sounddevice` |

**Использование:**

```python
from src.metrics import create_default_router

router = create_default_router()      # только Console
router.speak("Привет!")               # печатает "🔊 Привет!"

# Если установлен pyttsx3:
router = create_default_router(allow_pyttsx3=True)
# Если установлен faster-whisper + sounddevice:
router = create_default_router(allow_whisper=True)

# Маршрутизация автоматическая — первый подходящий движок.
router.speak("Привет!")  # через pyttsx3, если есть, иначе Console
text = router.hear(timeout=5.0)  # через whisper
```

**Защита от зависаний:** `PyttsxVoiceEngine` оборачивает `pyttsx3.init()`
в try/except — если модуль не установлен, движок просто молчит.

---

## 4.2 GitHub Actions CI

В `.github/workflows/ci.yml`:

```yaml
jobs:
  lint:    # compileall + AST + pyflakes + import-smoke на Python 3.10/3.11/3.12
  test:    # матрица: ubuntu/windows × py3.10/3.12
             # - tests/test_integration.py
             # - tests/test_performance.py
             # - tests/test_plugin_system.py
             # - tests/test_nursery_watcher.py
             # - tests/test_web_dashboard.py
             # - tests/test_long_run_scenarios.py (только ubuntu 3.12)
  security: # базовый поиск hardcoded секретов
```

**Маркеры pytest:**
- `slow` — медленные тесты (исключаются в CI)
- `long_run` — длинные сценарные тесты (отдельно в CI)

---

## 4.3 Сценарные тесты (long-run)

**`tests/test_long_run_scenarios.py`** — 14 тестов:

1. `test_1000_cycles_no_significant_rss_growth` — 1000 циклов без утечек.
2. `test_plugin_registry_doesnt_accumulate_during_lifecycle` — реестр не накапливает подсистемы.
3. `test_subsystem_tick_count_grows_monotonically` — счётчики растут.
4. `test_shared_state_thoughts_capped_at_maxlen` — deque(maxlen=50) работает.
5. `test_shared_state_actions_capped_at_maxlen` — очередь действий ограничена.
6. `test_shared_state_concurrent_push_no_corruption` — 10 потоков × 100 push без потерь.
7. `test_plugin_registry_concurrent_register` — concurrent register.
8. `test_nursery_watcher_no_leak_under_many_ticks` — 1000 tick() на пустой папке.
9. `test_nursery_watcher_history_capped_at_100` — cap=100.
10. `test_evolve_and_tick_subsystems_run_together` — evolve + tick_all совместимы.
11. `test_subsystems_teardown_clean` — teardown_all().
12. `test_plugin_registry_status_all_thread_safe` — concurrent status_all.
13. `test_dashboard_publish_no_leak_over_many_cycles` — 500 publish_* без утечек.
14. `test_no_significant_memory_leak_tracemalloc` — tracemalloc < 5MB за 200 циклов.

**Метрики:**
- 1000 циклов: 0 МБ RSS-роста
- 10 потоков × 100 push_thought: 0.004с
- tracemalloc за 200 циклов: +16 КБ

---

## Итоговая статистика тестов (Этапы 3 + 4)

| Файл | Тесты | Время |
|------|-------|-------|
| `tests/test_plugin_system.py` | 25 ✅ | 0.5с |
| `tests/test_nursery_watcher.py` | 15 ✅ | 0.3с |
| `tests/test_web_dashboard.py` | 18 ✅ | ~30с (с реальным HTTP) |
| `tests/test_long_run_scenarios.py` | 14 ✅ | ~5с |
| `tests/test_metrics_etap4.py` | 30 ✅ (1 skip) | 0.9с |
| **Итого** | **102 ✅** | **~37с** |

**Все существующие тесты также продолжают работать** — backward compatibility
не нарушена.