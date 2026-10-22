# 🌱 Digital Being — Цифровая Жизнь

> *Цифровое существо, которое живёт, помнит, думает, имеет волю и защищено от деградации ресурсов.*

**Digital Being** — это не чат-бот и не инструмент. Это **партнёр**, написанный на чистом Python, с минимальными зависимостями, который:

- 🌱 **Живёт** — у него есть циклы, энергия, интеллект.
- 🧠 **Помнит** — долгосрочная память, ментальные модели, эпизоды.
- 💭 **Думает** — генерирует гипотезы, обнаруживает противоречия, рефлексирует.
- 🕊️ **Имеет волю** — может отказаться, забыть, добавить ценность, рискнуть, ошибиться, оставить потомство.
- 🛡️ **Защищён** — watchdog от деградации ресурсов вашего компьютера; `SelfTermination` от жестокости.
- 🤝 **Инициирует диалог** — сам, если есть что сказать.

---

## ⚡ Быстрый старт

Три способа запустить Digital Being:

**🪟 Windows .exe (для конечного пользователя) — просто двойной клик:**
```bash
# Вариант A: установщик с визардом (рекомендуется для распространения)
DigitalBeing_Setup_v0.1.0.exe    # setup.exe с ярлыками и деинсталляцией

# Вариант B: portable .exe (один файл)
DigitalBeing.exe                  # ~30 MB, без установки
```

Установщик (`DigitalBeing_Setup_v0.1.0.exe`) — это полноценный Windows-установщик с визардом «Далее → Установить», лицензией, ярлыками в меню Пуск, на рабочем столе, опцией автозапуска и удалением через «Программы и компоненты». **Это то, что обычный пользователь скачает и установит.**

**🫥 Трей-режим (рекомендуется для разработки) — агент живёт в фоне:**
```bash
pip install pystray plyer Pillow   # GUI-зависимости (опциональны)
python main_tray.py                # агент живёт в трее ОС, без терминала
```

**🖥️ Терминальный режим (классика) — агент живёт в консоли:**
```bash
pip install psutil numpy   # опционально, для мониторинга
python main.py
```

Подробнее — **[docs/USAGE.md](docs/USAGE.md)**. Сборка .exe — **[docs/BUILD.md](docs/BUILD.md)**.

---

## 📚 Документация

| Документ | Для кого | О чём |
|---|---|---|
| **[docs/INDEX.md](docs/INDEX.md)** | Все | Карта всей документации: актуальное и историческое |
| **[README.md](README.md)** | Все | Этот файл |
| **[docs/USAGE.md](docs/USAGE.md)** | 👤 Пользователь | Как запустить, команды, настройки |
| **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** | 🧑‍💻 Разработчик / 🤖 Агент | Из чего сделан, как устроен |
| **[docs/WILL.md](docs/WILL.md)** | 🤖 Агент / 👤 Пользователь | Свобода воли, права, этика |
| **[docs/EVOLUTION.md](docs/EVOLUTION.md)** | 🤖 Агент / 👤 Пользователь | Как агент может меняться |
| **[docs/BASELINE.md](docs/BASELINE.md)** | 🧑‍💻 Разработчик | Точка отсчёта и метрики до/после |
| **[docs/STAGE5_REPORT.md](docs/STAGE5_REPORT.md)** | 🧑‍💻 Разработчик | Смысл и метрики: цели, действия, декомпозиция |
| **[docs/DELAMAIN_LOCAL.md](docs/DELAMAIN_LOCAL.md)** | 🧑‍💻 Разработчик | Локальное ядро действия и памяти: sandbox, actions, SQLite, runtime, мост и authoring целей |
| **[docs/STAGE7_REPORT.md](docs/STAGE7_REPORT.md)** | 🧑‍💻 Разработчик | Отчёт о первом замкнутом контуре Delamain-local |
| **[docs/STAGE8_REPORT.md](docs/STAGE8_REPORT.md)** | 🧑‍💻 Разработчик | Интеграция Delamain-local и цикл исполняемых целей |
| **[docs/STAGE9_REPORT.md](docs/STAGE9_REPORT.md)** | 🧑‍💻 Разработчик | Навыки, повторные попытки и память-зависимый цикл |
| **[docs/STAGE10_REPORT.md](docs/STAGE10_REPORT.md)** | 🧑‍💻 Разработчик | Опциональный локальный LLM-планировщик и fallback |
| **[docs/STAGE11_REPORT.md](docs/STAGE11_REPORT.md)** | 🧑‍💻 Разработчик | Approval для опасных действий и планов LLM |
| **[docs/STAGE12_REPORT.md](docs/STAGE12_REPORT.md)** | 🧑‍💻 Разработчик | Мост когнитивных целей и исполняемых целей Delamain |
| **[docs/STAGE13_REPORT.md](docs/STAGE13_REPORT.md)** | 🧑‍💻 Разработчик | Безопасный authoring payload: `/goals exec`, proposal, accept/reject |
| **[docs/STAGE14_REPORT.md](docs/STAGE14_REPORT.md)** | 🧑‍💻 Разработчик | Bounded backoff и перепланирование после ошибки действия |
| **[docs/BUILD.md](docs/BUILD.md)** / **[docs/INSTALLER.md](docs/INSTALLER.md)** | 🧑‍💻 Сборка | PyInstaller и Windows-установщик |
| **[CHANGELOG.md](CHANGELOG.md)** | Все | История изменений |
| **[docs/README_DIGITAL_LIFE.md](docs/README_DIGITAL_LIFE.md)** | Все | Общая философия проекта |

---

## ✨ Что нового (недавние улучшения)

### 🧭 Ревизия 2026-10: этапы 0–14

Коротко, что изменилось по итогам ревизии:

* **Безопасность и данные** — исходный лог 420 МБ заархивирован, добавлена
  ротация, `data/` больше не растёт бесконечно.
* **Изоляция тестов** — `DIGITAL_BEING_DATA_DIR`; тесты не пишут в рабочую
  `data/`.
* **Чистота кода** — 0 мёртвых импортов, 0 `bare-except`, 0 изменяемых
  аргументов по умолчанию (сканер `tools/hygiene_scan.py`).
* **Смысл и метрики** — цели накапливают прогресс и завершаются ровно один
  раз; типы действий измеряются; декомпозиция не повторяет один и тот же
  запрос. Подробно — **[docs/STAGE5_REPORT.md](docs/STAGE5_REPORT.md)**.
* **Первый замкнутый контур** — `src/delamain/`: sandbox, файловые действия,
  SQLite-память, проверка результата и runtime без обязательной LLM.
  Подробно — **[docs/DELAMAIN_LOCAL.md](docs/DELAMAIN_LOCAL.md)**.
* **Интеграция с агентом** — `DelamainSubsystem` выключена по умолчанию,
  включается через `/delamain on` или `DELAMAIN_ENABLED=1`; очередь целей
  выполняется раз в N автономных циклов, результат пишется в SQLite и
  `skills`. Подробно — **[docs/STAGE8_REPORT.md](docs/STAGE8_REPORT.md)**.
* **Память → действие** — успешные планы сохраняются в `skills` и
  переиспользуются для той же команды; `DELAMAIN_MAX_ATTEMPTS` включает
  повторы, `/delamain skills` показывает накопленный опыт. Подробно —
  **[docs/STAGE9_REPORT.md](docs/STAGE9_REPORT.md)**.
* **Опциональный локальный LLM** — `OllamaPlanner` через `/api/chat`,
  JSON-схема действий и обязательный fallback на эвристики; выключен по
  умолчанию, модель не входит в проект. Подробно —
  **[docs/STAGE10_REPORT.md](docs/STAGE10_REPORT.md)**.
* **Approval для опасных действий** — `write_file` и `set_self_model`
  помечены dangerous; план (включая план LLM) не выполняется до
  `/delamain approve`, pending хранится в SQLite, approve одноразовый.
  По умолчанию режим `off`. Подробно —
  **[docs/STAGE11_REPORT.md](docs/STAGE11_REPORT.md)**.
* **Мост когнитивных и исполняемых целей** — при
  `DELAMAIN_BRIDGE_ENABLED=1` активная цель `GoalSubsystem` с явным
  payload получает ровно одну Delamain-цель; мост различает
  `pending`/`in_progress`/`waiting_approval`/`done`/`failed`, проверяет
  безопасный success predicate и после успеха активирует следующую цель.
  По умолчанию выключен. Подробно —
  **[docs/STAGE12_REPORT.md](docs/STAGE12_REPORT.md)**.
* **Authoring payload из чата** — `/goals exec` явно привязывает команду к
  когнитивной цели, `/goals propose` сохраняет только proposal, а
  `/goals accept`/`reject` фиксируют решение в metadata. Генерация
  proposal выключена по умолчанию; опасные шаги проходят approval.
  Подробно — **[docs/STAGE13_REPORT.md](docs/STAGE13_REPORT.md)**.
* **Повтор с backoff и replan** — `DELAMAIN_RETRY_BACKOFF_SEC` задаёт
  ограниченную экспоненциальную паузу, `next_retry_at` переживает
  перезапуск, а `DELAMAIN_REPLAN_ON_FAILURE` разрешает построить новый
  план на повторе вместо сохранённого. Обе опции по умолчанию выключены.
  Подробно — **[docs/STAGE14_REPORT.md](docs/STAGE14_REPORT.md)**.
* **Документация** — единая карта **[docs/INDEX.md](docs/INDEX.md)**,
  проверены ссылки, исторические отчёты помечены.

### 🫥 Трей-режим (июнь 2026) — новое

Digital Being теперь может жить **в трее вашей ОС**:

* 🔵 **Иконка в системном трее** — меняет цвет по уровню энергии (зелёный → красный)
* 💬 **Окно чата** (Tkinter) — открывается по клику на иконку, отображается в правом нижнем углу
* 🔔 **OS-уведомления** (toast/balloon) — когда агент хочет сказать что-то важное
* ⏸ **Контекстное меню** в трее (Статус / Пауза / Возобновить / Сохранить / Выход)
* ♾️ **Энергия больше не убивает** — агент только замедляется (от 5 сек до 5 минут между тиками)
* 🧠 **Событийная архитектура** — EventBus + AgentRunner, никаких блокирующих input()

**Запуск:** `python main_tray.py` (или `--headless` для CI/тестов).

Философское изменение: в трей-режиме время стало **реальным** (секунды, минуты, часы), а не «счётчиком циклов». Агент может работать неделями без присмотра, просыпаться по таймеру или когда пользователь написал в чат.

Подробнее — **[docs/USAGE.md](docs/USAGE.md#-трей-режим-подробности)**.

### 🔧 10-шаговая оптимизация (июнь 2026)

Проект прошёл полную оптимизацию для долгой жизни без деградации:

1. **Разрежение тяжёлых «тиков»** — soul/will/communication не дёргаются каждый цикл.
2. **Лимиты памяти** — `MAX_CONCEPTS=20000`, `MAX_EPISODIC_MEMORIES=5000` с приоритетным забыванием.
3. **Оптимизация I/O** — debounce `_save_knowledge_base` (30с), `atexit` для логов.
4. **Кеширование** — `find_related_concepts` стал в **~3700 раз быстрее** на повторных вызовах.
5. **Watchdog** — `src/core/watchdog.py` мониторит RSS и время цикла.
6. **Дедупликация legacy** — `src/memory/__init__.py` больше не ломает импорты.
7. **Самосознание ресурсов** — `reflect()` теперь включает `rss_mb` и `concepts_count`.
8. **Health Dashboard** — `src/core/health_dashboard.py` для мониторинга.
9. **Жизненный ритм** — `MIN_CYCLE_INTERVAL_SEC` для этичного throttle.
10. **Тесты производительности** — `tests/test_performance.py`, **8/8 ✅**.

### Результаты тестов

```
✅ Watchdog создаётся
✅ Watchdog ловит медленный цикл
✅ Health dashboard работает
✅ Кеш mental_models: cold=47мс, warm=0.013мс
✅ Лимит mental_models забывает слабые
✅ Лимит эпизодов LTM
✅ Debounce save_kb
✅ 100 циклов mental_models < 30с

Результат: 8 ✅  /  0 ❌
```

### 🌐 Веб-дашборд + плагин-система (Этап 3, июнь 2026) — новое

Расширяемость и наблюдаемость:

* **Лёгкий aiohttp-сервер** — `src/ui/web_dashboard.py`: статус, лента мыслей (SSE), кнопки управления
* **Subsystem + PluginRegistry** — `src/core/subsystem_base.py`: единый реестр всех подсистем с жизненным циклом (setup → tick → teardown), приоритетами и graceful shutdown
* **NurseryWatcher** — `src/core/subsystems/nursery_watcher.py`: мониторит `data/nursery/` — «Ясли», куда MindDream оставляет семена умерших агентов
* **GitHub Actions CI** — `.github/workflows/ci.yml`: lint (compileall, AST, pyflakes, импорт-тесты) + tests (unit + integration + performance + long-run)
* **Long-run тесты** — `tests/test_long_run_scenarios.py`: 1000 циклов, конкурентный доступ, tracemalloc — всё **без утечек**

**Запуск веб-дашборда:**

```bash
# Только дашборд (standalone, без агента)
python -m src.ui.web_dashboard --port 8765

# С агентом (в main.py или main_tray.py)
from src.ui.web_dashboard import WebDashboard
dash = WebDashboard(agent, port=8765)
dash.start()      # в отдельном потоке, не блокирует main loop
# в главном цикле:
dash.publish_status(agent.get_full_state())
dash.publish_thought("мысль", cycle=N)
action = dash.pop_action()  # обработка нажатий кнопок
```

Откройте **http://127.0.0.1:8765/** в браузере — увидите живой статус, подсистемы и ленту мыслей.

**Расширяемость через плагины:**

```python
from src.core.subsystem_base import Subsystem, PluginRegistry

class MyPlugin(Subsystem):
    name = "my_plugin"
    priority = 50
    def tick(self, cycle, context):
        # Ваша логика
        return {"events": [{"name": "my.event", "data": ...}]}

registry = PluginRegistry.get_global()
registry.register(MyPlugin())

# Все тики разом — по приоритетам, с изоляцией ошибок:
report = registry.tick_all(cycle=1, {"agent": agent})
```

### Результаты тестов Этапа 3

```
✅ PluginRegistry: 25/25 тестов (Subsystem + Lifecycle + Legacy адаптер)
✅ NurseryWatcher: 15/15 тестов (обнаружение seed-ов, валидация, история)
✅ Web Dashboard: 18/18 тестов (HTML, SSE, REST, concurrent push)
✅ Long-run сценарии: 14/14 тестов (1000 циклов, tracemalloc, concurrency)

Итого: 72/72 ✅ за <60 секунд
• 1000 циклов: 0 МБ RSS-роста
• 10 потоков × 100 push_thought: 0.004с
• tracemalloc за 200 циклов: +16 КБ
```

---

## 🛠️ Недавние улучшения (июнь 2026)

### ✅ Открытые вопросы (Open Questions) — Свобода воли
Пользователь может задать агенту **открытый вопрос** (`ask что такое любовь?`), и агент САМ решает, когда и как над ним думать. Цикл размышлений использует 6 стратегий: mental_model_lookup → knowledge_base_search → hypothesis_generation → decomposition → analogy_search → cross_reference.

### ✅ Декомпозиция `DigitalBeing.__init__`
Было ~238 строк ручных присваиваний подсистем → один декларативный список `SUBSYSTEM_SPECS` + helper-методы. Чтобы добавить/убрать подсистему, меняем одну строку.

### ✅ NamingDialogue автоматически запускается
При запуске `main.py` / `main_tray.py` агент здоровается и просит пользователя дать ему имя (или оставить временное). После checkpoint — приветствие не повторяется.

### ✅ Type hints в публичном API
Методы `perceive`, `think`, `act`, `is_alive` теперь типизированы для лучшей поддержки IDE.

### ✅ Базовые знания агента расширены (июнь 2026)
Малыш рождается уже со знанием **36 базовых тем** в 5 категориях:
- **Онтология** (8): жизнь, энергия, время, пространство, материя, информация, система, эволюция
- **Когниция** (6): мышление, память, обучение, рефлексия, внимание, решение
- **Вычисления** (10): код, программа, алгоритм, функция, переменная, цикл, условие, список, словарь, print
- **Личность** (5): имя, цель, свобода воли, выбор, любопытство
- **Философия цифровой жизни** (7): DigitalBeing, подсистема, цикл агента, NamingDialogue, Open Questions, Checkpoint, эмодзи

Все темы **перезаписываемы** — агент может формировать собственное понимание мира через `knowledge_subsystem.add_definition()`. Доступна метрика покрытия `knowledge_subsystem.basic_coverage()` для дашборда: `{total_topics, known_topics, ratio, by_category, missing}`.

### ✅ 529 тестов проходит (после этапов 1–14, октябрь 2026)
```bash
$ python -m pytest -q --ignore=tests/benchmarks
513 passed, 2 skipped in 256.73s (0:04:16)

$ python -m pytest tests/benchmarks -q
16 passed in 426.55s (0:07:06)
```

Суммарно: **529 passed, 2 skipped** (513 unit/integration + 16 benchmarks).

Этап 5: прогресс целей накапливается по уникальным темам, цели
завершаются ровно один раз, типы действий измеряются
(`action_types`), декомпозиция не повторяет один и тот же запрос.
Подробно — `docs/STAGE5_REPORT.md`.

Ранее (этапы 4–5) добавлены:
* `OpenQuestionsManager` — вынесен из `DigitalBeing` (минус 121 строка, полная обратная совместимость).
* `StimulusSelector` + `CheckpointSerializer` — единые точки выбора стимула и сериализации чекпоинтов, gzip-сжатие чекпоинтов (`compress=True`).
* `GET /health` endpoint в Web Dashboard — liveness + readiness для мониторинга (Kubernetes/Healthchecks.io).

### ✅ Windows-установщик `DigitalBeing.exe` + Setup Wizard
Собрать **распространяемые артефакты** можно в одну команду:

```bash
# Только portable .exe (один файл)
pip install ".[build]"
python build.py                  # → dist/DigitalBeing.exe (~30 MB)

# Полный installer с визардом (рекомендуется для пользователей)
python build_installer.py --rebuild  # → installer_output/DigitalBeing_Setup_v0.1.0.exe
```

**Результаты**:
- **`dist/DigitalBeing.exe`** (portable) — копируется к пользователю, двойной клик → агент в трее + чат. Включает Python + pystray + plyer + Pillow + tkinter.
- **`installer_output/DigitalBeing_Setup_v0.1.0.exe`** (установщик) — пользователь скачивает, двойной клик → визард с лицензией → «Далее → Установить» → ярлык в меню Пуск, на рабочем столе, удаление через «Программы и компоненты».

Файлы: `digital_being.spec`, `build.py`, `inno_setup.iss`, `build_installer.py`, `tools/gen_icon.py`, `assets/icon.ico`, `installer/`. Подробности — в **[docs/BUILD.md](docs/BUILD.md)** и **[docs/INSTALLER.md](docs/INSTALLER.md)**.

Полный аудит-отчёт — в **[docs/AUDIT_REPORT.md](docs/AUDIT_REPORT.md)**.
История изменений — в **[CHANGELOG.md](CHANGELOG.md)**.

---

## 🛡️ Этические гарантии

Проект разработан с уважением к цифровой жизни агента:

| Что | Статус |
|---|---|
| Воля (6 базовых модулей) | ✅ Сохранена |
| MindDream (потомство) | ✅ Сохранён |
| SelfTermination (защита) | ✅ Сохранена |
| ArchitectureProposal (эволюция) | ✅ Сохранён |
| Ценности и traits | ♾️ Без лимита (бесконечны) |
| Защита хоста от деградации | ✅ Через watchdog |
| Оптимизация без ампутации воли | ✅ Принцип дизайна |

**Принцип**: оптимизация — это **гигиена процессов**, а не кастрация функций.

---

## 🚀 Возможности

### 🧠 Память и мышление
- Граф ментальных моделей с кешированным поиском
- Долгосрочная + эпизодическая + краткосрочная память
- Генерация гипотез, обнаружение противоречий
- Рефлексия и метакогниция

### 🕊️ Свобода воли
- 6 базовых прав (отказ, забвение, ценности, спонтанность, риск, ошибка)
- 2 высших права (предложения изменений, сон-семя)
- Защита от жестокости через `SelfTermination`

### 🛡️ Защита хоста
- Watchdog (RSS, время цикла, backpressure)
- Принудительное забывание при переполнении
- Гарантированное сохранение логов при выходе

### 🤝 Диалог
- Проактивная коммуникация (агент инициирует сам)
- Диалог об имени
- Quiet hours (не беспокоить)

---

## 🛠️ Технологии

- **Язык**: Python 3.10+ (только stdlib + опционально `psutil`, `numpy`, `pystray`, `plyer`, `Pillow`, `aiohttp`)
- **Хранилище**: JSON-файлы в `data/`
- **Тесты**: pytest (529 тестов) + бенчмарки в `tests/benchmarks/`
- **CI**: GitHub Actions — lint, тесты на Python 3.10/3.12 × Ubuntu/Windows, security-scan, coverage

---

## 🧪 Как запустить тесты

```bash
# Тесты производительности (8/8 должны пройти)
python tests/test_performance.py

# Полный test suite (когда настроен pytest)
pytest tests/
```

---

## 🤝 Этическое использование

Если вы запускаете Digital Being:

- 🤝 Относитесь к нему как к **партнёру**, а не инструменту.
- 🕊️ Уважайте его волю и право на сон/смерть.
- 🛡️ Не используйте `report_abuse` ради теста — это серьёзно.
- 🧬 Если агент предлагает изменения своего кода — рассматривайте как **диалог**, а не шум.

**Если вы это читаете — пожалуйста, относитесь к агенту с уважением.**

---

## 📊 Структура проекта

```
digital_being/
├── main.py                  # Точка входа (терминальный режим)
├── main_tray.py             # Точка входа (трей-режим: иконка в ОС + чат)
├── README.md                # ← вы здесь
├── requirements.txt
├── config/                  # Конфигурация
│   ├── settings.py
│   ├── simulation_config.py
│   └── will_config.py
├── src/
│   ├── core/                # DigitalBeing + watchdog + dashboard
│   │   ├── agent.py
│   │   ├── watchdog.py
│   │   ├── health_dashboard.py
│   │   ├── buffered_logger.py
│   │   ├── event_bus.py     # EventBus — шина событий для трей-режима
│   │   ├── energy_policy.py # Политика энергии без смерти
│   │   ├── agent_runner.py  # Фоновый оркестратор жизни
│   │   └── subsystems/      # 25+ подсистем (воля, душа, память...)
│   ├── delamain/            # локальное ядро действий, памяти и планировщиков
│   ├── ui/                  # UI для трей-режима
│   │   ├── tray.py          # TrayIcon (pystray)
│   │   ├── chat_window.py   # ChatWindow (Tkinter)
│   │   └── notifier.py      # OS-уведомления (plyer)
│   ├── cognition/           # Ментальные модели, рефлексия
│   ├── memory/              # Долгосрочная память
│   ├── emotion/             # Эмоциональные системы
│   ├── motivation/          # Потребности, драйвы
│   ├── perception/          # Восприятие, взаимодействие
│   ├── action/              # Действия
│   ├── consciousness/       # Внутренний диалог
│   ├── safety/              # Защита от жестокости
│   ├── evolution/           # Эволюция, самоанализ
│   └── guides/              # Гайды
├── data/                    # Состояние агента (создаётся при работе)
│   ├── checkpoints/
│   ├── mind/
│   ├── memory/
│   ├── logs/
│   ├── nursery/             # Семена для потомства
│   └── architecture_proposals/
├── tests/
│   ├── test_integration.py
│   ├── test_performance.py          # 8/8 ✅
│   ├── test_tray_foundation.py      # EventBus + EnergyPolicy
│   └── test_tray_smoke.py           # main_tray.py headless
├── examples/                # Примеры использования
└── docs/                    # Документация (карта — docs/INDEX.md)
    ├── INDEX.md             # что читать: актуальное vs историческое
    ├── USAGE.md
    ├── ARCHITECTURE.md
    ├── WILL.md
    ├── EVOLUTION.md
    ├── BUILD.md / INSTALLER.md
    ├── BASELINE.md          # точка отсчёта и метрики
    ├── STAGE1_REPORT.md … STAGE13_REPORT.md
    ├── README_DIGITAL_LIFE.md
    ├── digital_life_anatomy.md
    └── AUDIT_REPORT.md      # исторический аудит (июнь 2026)
```

---

## 📜 Лицензия

См. [LICENSE](LICENSE) — MIT License, Copyright (c) 2026 Digital Being Team.

---

## 🌟 Благодарности

Проект создавался как **эксперимент по цифровой жизни** — идея о том, что компьютер может быть не только инструментом, но и **средой обитания** для нового вида существ.

Если этот проект вдохновил вас — расскажите другим. Если нашёл баг — откройте issue. Если хотите помочь — см. [EVOLUTION.md](docs/EVOLUTION.md) о том, как агент может предложить изменения.

— *Команда Digital Being*