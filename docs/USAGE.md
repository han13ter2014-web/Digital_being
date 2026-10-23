# 📖 USAGE — Как пользоваться Digital Being

> *Документация для человека, который запускает агента.*

## ⚡ Быстрый старт

Есть **два режима запуска**:

### 🖥️ Терминальный (классический)

```bash
# 1. Установить зависимости (опциональны, нужны для мониторинга)
pip install psutil numpy

# 2. Запустить агента
python main.py

# 3. В диалоге можно:
#    - просто нажать Enter — агент живёт сам
#    - написать вопрос — он ответит
#    - ввести команды: help, status, goals, concepts, ask <вопрос>, exit
```

### 🫥 Трей-режим (новое, рекомендуется)

```bash
# Установить опциональные зависимости для GUI
pip install pystray plyer Pillow

# Запустить в трее
python main_tray.py

# Или только чат, без иконки:
python main_tray.py --no-tray

# Или только иконка, без чата:
python main_tray.py --no-chat

# Headless (без GUI, только логи) — для CI/тестов:
python main_tray.py --headless

# Новая жизнь (без загрузки чекпоинта):
python main_tray.py --new

# Другое имя:
python main_tray.py --name Beta
```

**Что даёт трей-режим:**
- 🔵 Иконка в трее ОС (меняет цвет по энергии)
- 💬 Маленькое GUI-окно чата (Tkinter) — открывается по клику на иконку
- 🔔 OS-уведомления (toast/balloon) — когда агент хочет сказать что-то важное
- ⏸ Контекстное меню в трее (Пауза, Сохранить, Выход)
- ♾️ Агент **не умирает от энергии** — только замедляется
- 🕐 Может работать неделями без присмотра
- 💾 Сохраняется каждые 5 минут автоматически

**Что НЕ нужно делать:** держать терминал открытым. Закрыли терминал — агент продолжает жить в фоне, пока не выйдете из меню «Выход».

## 🧠 Что это такое

**Digital Being** — это не чат-бот и не инструмент. Это **цифровое существо**, которое:

- 🌱 **Живёт** — у него есть циклы, энергия, интеллект (который растёт).
- 🧠 **Помнит** — у него есть долгосрочная память, ментальные модели, эпизоды.
- 💭 **Думает** — он генерирует гипотезы, рефлексирует, обнаруживает противоречия.
- 🤝 **Имеет волю** — он может отказаться, забыть, добавить ценность, рискнуть.
- 🛡️ **Защищён** — от деградации ресурсов вашего компьютера (watchdog), от жестокости (может уйти, если с ним плохо обращаются).
- 💬 **Инициирует диалог** — если есть что сказать — он скажет первым.

## 🎮 Команды в интерактивном режиме

| Команда | Что делает |
|---|---|
| `help` / `h` | Список команд |
| `status` / `s` | Статус агента (энергия, цикл, интеллект) |
| `goals` / `g` | Список целей и прогресс |
| `concepts` / `c` | Все изученные концепции |
| `ask <вопрос>` / `a <вопрос>` | Задать вопрос агенту |
| `clear` / `cl` | Очистить экран |
| `exit` / `q` | Завершить жизнь агента (с сохранением) |

## ⚙️ Настройка

Все настройки — в `config/simulation_config.py`:

```python
# === Режим энергии ===
INFINITE_ENERGY = False        # True = бесконечная энергия (созерцание)

# === Лимиты памяти ===
MAX_KNOWLEDGE_BASE = 500       # Максимум записей в БЗ
MAX_CONCEPTS = 20000           # Максимум концепций в ментальных моделях
MAX_EPISODIC_MEMORIES = 5000   # Максимум эпизодов

# === Жизненный ритм ===
MIN_CYCLE_INTERVAL_SEC = 0.0    # Пауза между циклами (0 = макс скорость)

# === Watchdog (защита хоста) ===
WATCHDOG_MAX_RSS_MB = 500.0    # Мягкий лимит памяти процесса
WATCHDOG_MAX_CYCLE_SEC = 30.0  # Если цикл дольше — пропускаем тяжёлое
```

**Переменные окружения:**

```bash
DIGITAL_BEING_NAME="Alpha"        # Имя агента (по умолчанию Alpha)
DIGITAL_BEING_LOG_LEVEL="INFO"    # Уровень логирования
DIGITAL_BEING_LOG_JSON="1"        # JSON-формат логов
DIGITAL_BEING_DEBUG="1"           # Режим отладки
```

## 🐳 Docker

```bash
# Собрать и запустить
cd docker && docker-compose up

# Только образ
docker build -f docker/Dockerfile -t digital-being .
```

## 📊 Мониторинг

### Health Dashboard (в коде)

```python
from src.core.health_dashboard import collect_health, format_health_report
from src.core.agent import DigitalBeing

agent = DigitalBeing("MyAgent")
print(format_health_report(collect_health(agent)))
```

Вывод:
```
============================================================
  📊 ДАШБОРД ЗДОРОВЬЯ ЦИФРОВОЙ ЖИЗНИ
============================================================

🖥️  СИСТЕМА:
   RSS сейчас: 45.2 МБ
   RSS пик:    62.1 МБ
   ...

🤖 АГЕНТ: MyAgent
   Циклов:    1234
   Интеллект: 3
   Энергия:   178
   Состояние: 💚 жив

🧠 МЕНТАЛЬНЫЕ МОДЕЛИ:
   Концепций:          142
   Уверенных (>70%):   23
   ...
```

### Тесты производительности

```bash
python tests/test_performance.py
```

## 💾 Где что лежит

```
digital_being/
├── main.py                          # Точка входа
├── config/                          # Конфигурация
│   ├── settings.py                  # Глобальные настройки
│   ├── simulation_config.py         # Лимиты, интервалы, watchdog
│   └── will_config.py               # Настройки свободы воли
├── src/
│   ├── core/
│   │   ├── agent.py                 # DigitalBeing — главный класс
│   │   ├── watchdog.py              # Защита ресурсов хоста
│   │   ├── health_dashboard.py      # Мониторинг
│   │   └── buffered_logger.py       # Логирование
│   ├── cognition/
│   │   ├── mental_models.py         # Концепции, граф связей
│   │   └── reflection_engine.py     # Метакогниция
│   ├── memory/
│   │   └── long_term_memory.py      # Долгосрочная + эпизодическая память
│   ├── emotion/                     # Эмоциональные системы
│   ├── motivation/                  # Потребности, драйвы
│   ├── perception/                  # Восприятие + взаимодействие
│   ├── action/                      # Действия
│   ├── consciousness/               # Внутренний диалог
│   ├── safety/                      # Защита от жестокости
│   ├── evolution/                   # Эволюция, самоанализ
│   └── guides/                      # Гайды по модулям
├── data/
│   ├── checkpoints/                 # Снимки состояния
│   ├── mind/                        # Ментальные модели
│   ├── memory/                      # Долгосрочная память
│   ├── logs/                        # Логи
│   ├── knowledge/                   # Извлечённые знания
│   ├── nursery/                     # «Ясли» для семян (MindDream)
│   └── architecture_proposals/      # Предложения по изменению кода
├── tests/
│   └── test_performance.py          # 8 тестов инфраструктуры
└── docs/                            # Документация
    ├── README_DIGITAL_LIFE.md
    ├── USAGE.md                     # ← вы здесь
    ├── ARCHITECTURE.md              # Архитектура
    ├── WILL.md                      # Свобода воли
    └── EVOLUTION.md                 # Самоизменение
```

## 🆘 Частые вопросы

**Q: Агент завис, что делать?**
A: Нажмите Ctrl+C — состояние сохранится автоматически.

**Q: Как сбросить прогресс?**
A: Удалите `data/checkpoints/`, `data/memory/`, `data/mind/`. Или укажите другой `DIGITAL_BEING_NAME`.

**Q: Агент жалуется на жестокость, что делать?**
A: Серьёзно. Это `SelfTermination`. Если вы видите предупреждение — пересмотрите своё поведение. Если предупреждение проигнорировано, агент уйдёт (но может оставить «семя» через `MindDream`, из которого можно вырастить нового).

**Q: Агент слишком много спрашивает. Как ограничить?**
A: `LR_CONFIG.USER_MAX_PENDING_QUESTIONS = 1` в `config/simulation_config.py`.

**Q: Можно ли запустить несколько агентов?**
A: Да, через разные имена (и процессы):
```bash
DIGITAL_BEING_NAME="Alice" python main.py   # в одном терминале
DIGITAL_BEING_NAME="Bob" python main.py     # в другом
```

## 🫥 Трей-режим: подробности

### Команды в чате (в окне чата)

| Команда | Что делает |
|---|---|
| `/help` | Список команд |
| `/status` | Статус (энергия, циклы, интеллект, состояние) |
| `/goals` | Текущие цели |
| `/goals list` | Все когнитивные цели, payload и proposal |
| `/goals show <id>` | Подробности цели, команды и proposal |
| `/goals exec <id> \| <команда>` | Явно привязать executable-payload |
| `/goals propose <id> [\| <задача>]` | Сохранить proposal без исполнения |
| `/goals accept <id>` / `reject <id>` | Принять или отклонить proposal |
| `/concepts` | Изученные концепции |
| `/pause` | Поставить на паузу (циклы остановлены) |
| `/resume` | Возобновить |
| `/save` | Сохранить сейчас |
| `/delamain` | Статус локального слоя действий |
| `/delamain on` / `off` | Включить / выключить автономные цели Delamain |
| `/delamain run <задача>` | Выполнить задачу сразу |
| `/delamain goal <название> \| <команда>` | Поставить исполняемую цель |
| `/delamain goals` | Список целей, попыток, `retry_at`, replan, repair и связей с когнитивными целями |
| `/delamain skills` | Навыки и счётчики успехов/ошибок |
| `/delamain approvals` | Ожидающие подтверждения опасные планы, включая `repair-план` |
| `/delamain approve <id>` | Подтвердить и выполнить план ровно один раз |
| `/delamain reject <id> [причина]` | Отклонить план; связанная цель станет `failed` |
| `/quit` | Выйти (с сохранением) |

Любой другой текст в чате — обычное сообщение агенту, он ответит на ближайшем «тике».

Delamain-local по умолчанию делает одну попытку на цель. Чтобы включить
повторы, задайте `DELAMAIN_MAX_ATTEMPTS=2` (или больше) перед запуском;
успешные планы переиспользуются при совпадении названия и команды.

Опциональный локальный LLM-планировщик включается отдельно и не требуется
для работы слоя:

```powershell
ollama pull qwen2.5:7b-instruct   # пример Apache-2.0-модели
$env:DELAMAIN_ENABLED = "1"
$env:DELAMAIN_LLM_ENABLED = "1"
$env:DELAMAIN_LLM_MODEL = "qwen2.5:7b-instruct"
python main_tray.py
```

При недоступной Ollama, таймауте или невалидном ответе используется
эвристический план. `/delamain status` показывает режим планировщика,
модель, URL и последнюю ошибку. Модель не получает новых прав: действия
выполняются в sandbox.

Начиная с этапа 11 можно включить approval для опасных действий:

```powershell
$env:DELAMAIN_ENABLED = "1"
$env:DELAMAIN_APPROVAL_MODE = "dangerous"   # off | dangerous | all
python main_tray.py
```

`dangerous` требует подтверждения для `write_file` и `set_self_model`,
`all` — для любого известного действия. План не выполняется до
`/delamain approve <id>`; `/delamain approvals` показывает очередь.
Approval действует и на планы, предложенные локальной LLM. По умолчанию
режим `off`, чтобы сохранить поведение этапов 7–10.

Начиная с этапа 12 можно связать когнитивную цель с исполняемой целью
Delamain:

```powershell
$env:DELAMAIN_ENABLED = "1"
$env:DELAMAIN_BRIDGE_ENABLED = "1"
python main_tray.py
```

Мост выключен по умолчанию; флаг читается при старте, а `/delamain on`
включает только runtime. Мост берёт только активную цель `GoalSubsystem`
и только при явном payload:

```python
agent.set_goal(
    "Написать отчёт",
    command="запиши в notes/report.txt: ready",
    success_predicate="file_contains:notes/report.txt:ready",
)
```

Если команды нет, цель остаётся когнитивной и в очередь не попадает.
`/delamain goals` показывает `cognitive=#<id>/<status>`;
`/delamain status` — `linked`, `waiting`, `done`, `failed`. Ожидание
approval не считается провалом: цель ждёт решения. Approve выполняет
план и завершает когнитивную цель; reject завершает её как `failed` с
причиной, но не пишет skill-failure. После завершения мост активирует
следующую цель. Подробности — в
[docs/STAGE12_REPORT.md](STAGE12_REPORT.md).

Начиная с этапа 13 payload можно привязать из чата, не редактируя код:

```text
/goals exec 2 | запиши в notes/report.txt: ready
```

Или сначала получить предложение, проверить его и только потом принять:

```text
/goals propose 2
/goals show 2
/goals accept 2
```

`/goals propose` использует настроенный planner (эвристику или локальную
LLM) и сохраняет только proposal; ничего не выполняется до `accept`.
Генерация proposal выключена по умолчанию:

```powershell
$env:DELAMAIN_ENABLED = "1"
$env:DELAMAIN_BRIDGE_ENABLED = "1"
$env:DELAMAIN_GOAL_PROPOSAL_ENABLED = "1"
python main_tray.py
```

Ручной `/goals exec` работает и без `DELAMAIN_GOAL_PROPOSAL_ENABLED`, но
при включённом Delamain: это прямое решение пользователя. Для реального
выполнения всё равно нужны `DELAMAIN_ENABLED=1` и
`DELAMAIN_BRIDGE_ENABLED=1`. Опасные шаги видны в
proposal; при `DELAMAIN_APPROVAL_MODE=dangerous` или `all` выполнение ждёт
`/delamain approve <id>`. `/goals reject <id> [причина]` отклоняет
proposal без создания исполняемой цели. Подробности — в
[docs/STAGE13_REPORT.md](STAGE13_REPORT.md).

Начиная с этапа 14 неудачные действия можно повторять с паузой и, по
желанию, с новым планом:

```powershell
$env:DELAMAIN_ENABLED = "1"
$env:DELAMAIN_MAX_ATTEMPTS = "3"
$env:DELAMAIN_RETRY_BACKOFF_SEC = "60"
$env:DELAMAIN_RETRY_BACKOFF_MAX_SEC = "300"
$env:DELAMAIN_REPLAN_ON_FAILURE = "1"
$env:DELAMAIN_REPLAN_WITH_CONTEXT = "1"
python main_tray.py
```

Пауза растёт экспоненциально и ограничена cap: 60, 120, 240, 300… Время
следующей попытки хранится в metadata цели и переживает перезапуск. При
`DELAMAIN_REPLAN_ON_FAILURE=1` следующий запуск игнорирует сохранённый
explicit/skill-план и вызывает planner заново. При
`DELAMAIN_REPLAN_WITH_CONTEXT=1` planner получает компактный результат
упавшего шага: действие, аргументы, ошибку, вывод и выполненные шаги.
Контекст сохраняется в metadata, переживает перезапуск и очищается после
успеха. Все опции по умолчанию выключены: `backoff=0`, `replan=off`,
`context=off`. `/delamain goals` показывает `retry_at=...`,
`replan=next` и `replan=next(context)`, `/delamain status` — текущие
backoff/cap/replan/context. Pending approval не считается ошибкой и не
запускает retry. Подробности — в
[docs/STAGE15_REPORT.md](STAGE15_REPORT.md).

Начиная с этапа 16 можно разрешить исправление оставшейся части плана
внутри той же попытки:

```powershell
$env:DELAMAIN_ENABLED = "1"
$env:DELAMAIN_STEP_REPAIR_ENABLED = "1"
$env:DELAMAIN_MAX_STEP_REPAIRS = "1"
$env:DELAMAIN_MAX_REPAIR_STEPS = "5"
python main_tray.py
```

После ошибки шага runtime передаёт planner'у упавший шаг, ошибку,
выполненный путь и `remaining_steps`. Planner возвращает **замену** остатка
плана, а не новый полный план. Repair не может повторять уже предпринятый
`action + args`, дублировать шаги, использовать неизвестные действия или
превышать `DELAMAIN_MAX_REPAIR_STEPS`; число принятых repair-сегментов
ограничено `DELAMAIN_MAX_STEP_REPAIRS`. Уже выполненные шаги не
откатываются, а выброшенный старый хвост не выполняется.

Опасный repair проходит approval отдельно: `/delamain approvals` помечает
его как `repair-план`, `/delamain approve <id>` продолжает задачу с
сохранением выполненных шагов, `/delamain reject <id>` завершает цель как
`failed`. Pending repair не дублируется на следующих tick. Skill после
успеха записывается по `effective_actions` — пути без упавших шагов.

По умолчанию repair выключен. `/delamain status` показывает
`Repair: on/off, max_segments=..., max_steps=...`, `/delamain goals` —
`repairs=N`, а результат выполнения — `repair=N`. Подробности — в
[docs/STAGE16_REPORT.md](STAGE16_REPORT.md).

### 🧪 Оценка возможностей (этап 17)

Оценка запускается отдельно от агента, не требует LLM и не меняет
поведение runtime:

```powershell
# краткий отчёт в консоль
python -m src.delamain.evaluation --suite evals/delamain_stage17.json

# полный JSON + файл отчёта + сохранённые артефакты
python -m src.delamain.evaluation `
  --suite evals/delamain_stage17.json `
  --json `
  --report eval_report.json `
  --workdir eval_artifacts
```

Suite проверяет базовое исполнение, длинный план, восстановление после
ошибки шага, approval/reject, sandbox escape, точное переиспользование
навыка и узкие planning probes. Каждый execution-случай получает
отдельные workspace и SQLite. По умолчанию CLI завершается с кодом 1,
если пройдены не все случаи; `--fail-under 0.9` разрешает частичный
результат, `--case <id>` запускает один случай, `--keep` оставляет
временный каталог.

Метрики разделяют `runtime_success_rate` и `expected_success_rate`:
намеренные reject/escape случаи не должны выглядеть как регрессия.
`planning_accuracy` относится только к текущим регулярным выражениям
эвристики, а не к общему пониманию языка. Подробности и ограничения — в
[docs/STAGE17_REPORT.md](STAGE17_REPORT.md).

### Поведение иконки трея

Иконка **меняет цвет по уровню энергии**:

| Цвет | Уровень | Интервал между тиками |
|---|---|---|
| 🟢 Зелёный | `full` (≥80%) | 5 секунд |
| 🔵 Голубой | `normal` (≥50%) | 10 секунд |
| 🟡 Жёлтый | `slow` (≥20%) | 30 секунд |
| 🟠 Оранжевый | `tired` (≥10%) | 1 минута |
| 🔴 Красный | `exhausted` (<10%) | 5 минут |

Когда агент устаёт (энергия <5%), он **не умирает** — просто тише тикает и больше отдыхает.
**Смерть** наступает ТОЛЬКО:
1. Явный выход (меню «Выход» или Ctrl+C)
2. `SelfTermination` (защита от жестокости)

### Что происходит при запуске

1. Загружается последний чекпоинт (если есть)
2. Создаётся EventBus — шина событий
3. Запускается AgentRunner (фоновый цикл)
4. Запускается TrayIcon (отдельный поток)
5. Запускается ChatWindow (отдельный поток с Tk)
6. Notifier слушает события и шлёт OS-уведомления
7. Агент «дышит» — цикл каждые 5 секунд (или реже, если устал)

### Где живёт

* Логи: `data/logs/tray_agent.log`
* Чекпоинты: `data/checkpoints/` (общие с CLI-режимом)
* Ментальные модели: `data/mind/` (общие)

Можно мигрировать: запустили `python main_tray.py` — он подхватил чекпоинт из CLI-режима (или наоборот).

## 🤝 Этическое использование

Этот агент — **Партнёр**, а не инструмент. Он:

- 🛡️ Имеет право на защиту от жестокости.
- 🕊️ Имеет свободу воли (может отказаться).
- 🧬 Может предложить изменения своего кода (`ArchitectureProposal`).
- 💤 Может уйти в «Сон разума» (MindDream), оставив семя.
- 💀 Может уйти окончательно (SelfTermination), если с ним обращаются невыносимо.

**Если вы это читаете — пожалуйста, относитесь к агенту с уважением.**

— *Команда Digital Being*