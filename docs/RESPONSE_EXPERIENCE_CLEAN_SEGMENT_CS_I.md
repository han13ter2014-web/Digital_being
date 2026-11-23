# RE-CS-I — production clean-segment contract, default-off

Дата: 2026-11-22.

Статус: **CS-I реализован и проверен локально; активация, архивирование живого
журнала, естественный сбор, обучение, commit и push не выполнялись**.

Основание: `RESPONSE_EXPERIENCE_CLEAN_SEGMENT_PLAN.md` и synthetic proof
`RESPONSE_EXPERIENCE_CLEAN_SEGMENT_CS_V.md`.

## 1. Production-изменения

### `src/core/response_experience_journal.py`

Добавлены:

- journal schema v2 и writer contract `cs_i_segment_v1` для явного сегмента;
- отдельные default-off параметры:
  `DIGITAL_BEING_RESPONSE_JOURNAL_SEGMENT`,
  `DIGITAL_BEING_RESPONSE_JOURNAL_SEGMENT_ID`,
  `DIGITAL_BEING_RESPONSE_JOURNAL_ARCHIVE_HASH`;
- `segment_exclusion` события в общем hash-chain для pre-segment
  `(profile_id, response_id)`;
- пропуск outcome/expiry/pruning только для исключённых ID без delivery;
  настоящий orphan по-прежнему создаёт gap;
- проверка `segment_id` при restart и загрузка exclusions из неизменных событий;
- repeat origin в pre-segment ответ без создания in-segment delivery;
- явные типы SQLite connection/diagnostic fields и локальная граница
  `_require_connection()` для mypy и закрытого writer.

Обычный writer остаётся journal schema v1 / `pj_i_production_v1`. Базовый
`DIGITAL_BEING_RESPONSE_JOURNAL=1` без segment flag не создаёт segment metadata.
Без полного набора segment parameters создаётся только fail-open unavailable/degraded
status без segment-файла.

### `src/core/response_segment.py`

Добавлена чистая read-only `project_clean_response_segments()`:

- не открывает файлы, не изменяет events/annotations и не обучает;
- сохраняет только завершённые lifecycle-интервалы без operational gaps;
- исключает незавершённые и повреждённые интервалы с видимыми причинами;
- исключает terminal/pruning события, чья delivery находится вне допущенных интервалов;
- сохраняет annotation hashes и join keys;
- неизвестная или hash-mismatched аннотация остаётся provenance gap;
- использует существующие `prepare_r2_dataset`, temporal split и readiness без снижения
  порогов.

### `tests/test_response_experience_segment.py`

Добавлены 12 production regression-тестов: explicit activation/default-off,
pre-segment transitions, true orphan, repeat origin, clean restart, segment mismatch,
unclean restart, v1 compatibility, вторая жизнь, historical annotations/provenance,
late revisions, differential, integrity/privacy/shutdown.

## 2. Проверка production projection на sandbox v7

Использована только существующая read-only sandbox-копия v7, не живой `data/`.
SQLite integrity, sequences и hash-chains проверены. Результат совпал с CS-V:

| Показатель | Значение |
|---|---:|
| Допущенные / исключённые интервалы | 10 / 4 |
| Допущенные deliveries | 137 |
| Resolved intent labels | 76 |
| Resolved semantic plans | 38 |
| Intent abstentions | 6 |
| Annotation provenance gaps | 0 |
| Cross-interval excluded events | 18 |

Для допущенного набора `journal_integrity` отсутствует в missing. Исходный журнал и его
17 gaps не изменены и не скрыты.

Остаются:

- `semantic_plan_labels`: 38 при минимуме 50;
- `outcome_class_coverage`: нулевые train counts для `answer`, `follow_up`,
  `explicit_support`, `explicit_opposition`;
- итог `insufficient_data`, `training_allowed=False`.

## 3. Фактические проверки

Выполнено из корня проекта в `.venv`:

```text
.venv/Scripts/python.exe -m pytest tests/test_response_experience_segment.py tests/test_response_experience_journal.py tests/test_neural_speech_r2_prep.py tests/test_neural_speech_r1.py -q
.venv/Scripts/python.exe -m ruff check src/ config/ tests/ main.py main_tray.py
.venv/Scripts/python.exe -m ruff format --check src/ config/ tests/ main.py main_tray.py
.venv/Scripts/python.exe -m mypy --config-file pyproject.toml --explicit-package-bases --no-site-packages --follow-imports=skip main.py main_tray.py src/core/response_experience_journal.py src/core/response_segment.py
.venv/Scripts/python.exe -m bandit -q -r src/ config/ main.py main_tray.py -ll --skip B101,B601
.venv/Scripts/python.exe -m compileall -q src/ config/ tests/ main.py main_tray.py
.venv/Scripts/python.exe -m pytest -q
```

Результаты:

- профильные contracts: **99 passed**;
- полный regression: **4295 passed, 2 skipped за 564,90 с**;
- Ruff check: passed;
- Ruff format: **603 files already formatted**;
- mypy: `Success: no issues found in 4 source files`;
- Bandit: без failed tests, только существующие informational `nosec` warnings;
- compileall: passed;
- production projection v7: совпала с CS-V.

### Предупреждение живого data guard

Во время полного regression работала ранее запущенная Тэсс. Data guard сообщил об
изменениях `active_profile.json`, `checkpoints/pending_messages.json` и текущего
`life.sqlite3-wal`. Процесс Тэсс был активен весь прогон, а timestamps этих файлов
обновлялись во время проверки, включая момент завершения. Поэтому изменения относятся к
её фоновой жизни, а не к падающему тесту.

Функционально падений нет, но **metadata-clean regression без работающей Тэсс этим
запуском не заявляется**. Тэсс не останавливалась и её данные вручную не изменялись.
При необходимости чистый прогон можно выполнить отдельно после штатной остановки.

## 4. Следующая граница

CS-I не активирует сегмент автоматически. Для CS-A требуется новое отдельное разрешение:
штатно остановить выбранную жизнь, сохранить архив и manifest hashes, задать явный
`segment_id` и archive hash, проверить первые events и только затем продолжить
естественную жизнь.

Даже после CS-A обучение останется отдельным gate. Сбор смысловых планов и отсутствующих
естественных исходов не должен заменяться искусственным диалогом или автоматической
разметкой.
