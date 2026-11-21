# RE-S1 — Фаза 1: controlled inventory и baselines

Дата: 2026-11-21.

Статус: **controlled inventory и B0/B1/B2 выполнены; baseline сохраняется**.
Реальная биография не использовалась, модель не создавалась, production writer не
добавлялся. Фаза 2, advisor, генеративная речь, новые зависимости и сетевые вызовы
не авторизованы.

Основание: `RESPONSE_EXPERIENCE_SHADOW_TICKET.md`, отдельное разрешение владельца
на test-only inventory и baseline от 2026-11-21.

## 1. Что реализовано

Только test-only файлы:

- `tests/observations/re_s1_response_experience.py` — prospective event-journal,
  whitelist snapshot, chronological split, B0/B1/B2, метрики и изолированный runner;
- `tests/test_response_experience_shadow_baseline.py` — 9 проверок контракта.

Production-код, конфигурация, checkpoint-схема и живой `data/` не изменялись.
Harness вызывает настоящие `ResponseExperience.prepare_plan()`,
`register_delivery()`, `observe_reply()`, `observe_feedback()` и `expire()` на
контролируемых планах. Это не естественный диалог через AgentRunner/UI и не
основание заявлять полную RE-01 end-to-end приёмку.

Журнал сохраняет раздельные delivery/outcome события, `episode_id`, циклы и
монотонный sequence. Сырые входы и реплики в features и отчёт не копируются.
Для repeat-метрики используется только fingerprint внутри песочницы.

## 2. Зафиксированные правила baseline

- шесть observed-классов; pending и expired не получают отрицательных меток;
- целые эпизоды, хронологический split 60/20/20, без shuffle;
- train-исход доступен только при `outcome_sequence < validation_first_delivery`;
- B0: additive smoothing `alpha=1` по global training history;
- B1: `(context_count + 6 × B0) / (context_total + 6)` внутри
  `(profile_id, context, response_language)`;
- B2: предыдущий исход того же личного контекста со smoothing `alpha=1`, иначе B0;
- primary metric: multiclass log loss; abstention получает same-moment B0 fallback;
- Brier, ECE с 10 bins, coverage, per-class и контекстные срезы — сопутствующие
  метрики.

Численные candidate-пороги по этому синтетическому сценарию не устанавливались.
Они не должны подгоняться под искусственно повторяющееся расписание.

## 3. Inventory и временной split

Контролируемая история содержит 30 наблюденных эпизодов и два censored-контроля:

| Показатель | Значение |
|---|---:|
| Зарегистрировано доставок | 32 |
| Observed | 30 |
| Expired / `no_observed_reaction` | 1 |
| Pending | 1 |
| Пропущенные `outcome_cycle` | 0 |
| Пропущенные `episode_id` | 0 |

Observed-классы: `answer=9`, `follow_up=6`, `unclassified_reply=3`,
`ordinary_reply=6`, `explicit_support=3`, `explicit_opposition=3`.

| Часть | Эпизоды | Observed-примеры | Назначение |
|---|---:|---:|---|
| Train | 19 | 19 | Только исходы до cut |
| Validation | 6 | 6 | Диагностика frozen baselines |
| Held-out | 7 | 5 | Пять observed + один expired + один pending |

Поздних train-исходов в основном сценарии не было. Отдельный regression-тест
создаёт такой исход после validation cut и подтверждает его исключение: из трёх
train-исходов eligible остаются два. Два censored-контроля не вошли в supervised
метрики.

## 4. Фактические результаты

### 4.1. Overall

| Split | Baseline | N | Log loss ↓ | Brier ↓ | ECE ↓ | Coverage | Accuracy, диагностика |
|---|---|---:|---:|---:|---:|---:|---:|
| Validation | B0 | 6 | 1,741937 | 0,813867 | 0,053333 | 1,0 | 0,333333 |
| Validation | B1 | 6 | 1,226872 | 0,630609 | 0,200462 | 1,0 | 0,333333 |
| Validation | B2 | 6 | 1,714861 | 0,802721 | 0,047619 | 1,0 | 0,333333 |
| Held-out | B0 | 5 | 1,688937 | 0,803200 | 0,080000 | 1,0 | 0,200000 |
| Held-out | B1 | 5 | **1,273233** | **0,632937** | 0,267255 | 1,0 | 0,600000 |
| Held-out | B2 | 5 | 1,530022 | 0,726531 | 0,314286 | 1,0 | 0,600000 |

B1 лучше B0/B2 по log loss и Brier на этом заранее повторяющемся контекстном
расписании. Одновременно его ECE хуже B0: контекстная уверенность выше, но
калибровка не улучшается. Held-out содержит только пять observed-исходов и не
покрывает все шесть классов. Это проверка инструмента, а не доказательство
превосходства на реальной жизни.

### 4.2. Контекстные срезы held-out

| Context | N | B0 log loss | B1 log loss | B2 log loss |
|---|---:|---:|---:|---:|
| `dialogue_learning` | 1 | 1,272966 | 0,600438 | 1,252763 |
| `social_reply` | 2 | 1,864851 | 1,403015 | 1,599337 |
| `unknown_reply` | 2 | 1,721010 | 1,479848 | 1,599337 |

Каждый срез слишком мал для самостоятельного вывода. EN/ZH, borrowed, другие
профили и редкие реальные режимы в основном сценарии не наблюдались; это
`insufficient_data`, а не нулевой риск.

### 4.3. Повторы и воспроизводимость

- Все 5/5 held-out реализаций встречались в train: `repeat_rate=1,0`. Это
  намеренное свойство фиксированного синтетического расписания, не обнаруженная
  патология живой сущности.
- Два независимых построения одинаковой истории дали тождественные события и
  held-out метрики.
- Вторая жизнь: 0 записей, 0 training examples, пустой `ResponseExperience`,
  равномерный пустой B0 по шести классам. Наследования весов и статистик нет.
- Abstention-тест: при отказе на всех примерах primary log loss в точности равен
  B0 fallback, coverage равен нулю; скрытого преимущества нет.

## 5. Ресурсы и границы данных

Для двух controlled baseline observations, не для модели:

- elapsed: **0,0490854 с**;
- `tracemalloc` peak: **503 405 байт**;
- журнал основной истории: **63 события**, **16 732 байта** JSON;
- полный JSON-отчёт: **84 980 байт**.

Эти числа не являются бюджетом будущей модели или гарантией tick latency.

Живой `data/`: содержимое для observation не читалось. Metadata-only сверка до
основного замера, после него и после полного regression: **1278 файлов**, одинаковый
SHA-256 от списка `(relative_path, size, mtime_ns)`:
`d4f4f66d4929d19c52a587a7f4bc5214925c6f7f08c18c69556cca3f20bc2dc3`.
Изменений файлов не обнаружено по этой метаданной проверке.

Первичный JSON: `tmp/response_experience_shadow/phase1-controlled.json`.
Он находится в изолированном `tmp/` и не является production artifact.

## 6. Проверки

Команды выполнялись из корня проекта в `.venv`:

```text
.venv/Scripts/python.exe -m pytest tests/test_response_experience_shadow_baseline.py -q
.venv/Scripts/python.exe -m pytest tests/test_response_experience_shadow_baseline.py tests/test_response_experience.py tests/test_language_consolidation.py tests/test_external_response.py -q
.venv/Scripts/python.exe tests/observations/re_s1_response_experience.py --label phase1-controlled --output tmp/response_experience_shadow/phase1-controlled.json
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m ruff check src/ config/ tests/ main.py main_tray.py
.venv/Scripts/python.exe -m ruff format --check src/ config/ tests/ main.py main_tray.py
.venv/Scripts/python.exe -m mypy --config-file pyproject.toml --explicit-package-bases --no-site-packages --follow-imports=skip main.py main_tray.py
.venv/Scripts/python.exe -m bandit -q -r src/ config/ main.py main_tray.py -ll --skip B101,B601
.venv/Scripts/python.exe -m compileall -q src/ config/ tests/ main.py main_tray.py
```

Фактические результаты:

- новые проверки: **9 passed**;
- новый + соседние диалоговые контуры: **70 passed**;
- Ruff check: passed;
- Ruff format: **583 files already formatted**;
- mypy: `Success: no issues found in 2 source files`;
- Bandit: без failed tests, существующие nosec warnings;
- compileall: passed;
- полный regression: **4081 passed, 2 skipped за 572,24 с (0:09:32)**;
- итоговая metadata-сверка живого `data/` после regression: **1278 файлов**,
  тот же metadata SHA-256, изменений не обнаружено.

## 7. Покрытие будущей приёмочной матрицы

| Область | Результат фазы 1 |
|---|---|
| RE-01 | Частично: настоящий `register_delivery`, controlled plan; natural AgentRunner/UI отложен |
| RE-02/03 | Observed/censored разделены; внешние session-scoped записи не используются |
| RE-04 | Cross-life запрещён; личные контексты разделены; initial second life пуст |
| RE-05 | Ограничение окна задокументировано; живая полнота не измерялась |
| RE-06/07 | Leakage, episode split и late outcome проверены |
| RE-08/09 | B0/B1/B2 и abstention fallback проверены |
| RE-10/11 | Кандидата нет; не оценивалось |
| RE-12 | Repeat-метрика измерена на синтетике; вывода о живой петле нет |
| RE-13/14/15/16 | Candidate differential/restart/corruption отложены; проверен только пустой second-life baseline |
| RE-17 | Измерен только test-only baseline, не модель |
| RE-18 | Граница сохранена: advisor и речь не включались |

## 8. Решение по фазе 1

1. Prospective event-journal достаточен для доказуемого split на контролируемом
   потоке; ограничение позднего checkpoint без `outcome_cycle` остаётся в силе.
2. Baselines воспроизводимы и не требуют модели, зависимостей или сети.
3. Синтетический выигрыш B1 не авторизует выбор MLP/RNN/LTC и не доказывает
   полезность обучаемого кандидата.
4. Реальных фактических исходов в этом наблюдении ноль: использованы только
   контролируемые события. Поэтому данных для decision gate модели нет.
5. **Оставляем baseline и не начинаем фазу 2.** Любой следующий шаг с реальной
   биографией, production writer или shadow-кандидатом требует нового отдельного
   разрешения владельца.

Commit/push не выполнялись.
