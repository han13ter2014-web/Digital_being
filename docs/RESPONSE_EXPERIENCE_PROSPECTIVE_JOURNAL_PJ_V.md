# RE-S1-PJ-V — Synthetic prospective journal adapter

Дата: 2026-11-21.

Основание: отдельное разрешение владельца на **только PJ-V** по
`RESPONSE_EXPERIENCE_PROSPECTIVE_JOURNAL_TICKET.md`.

Статус: **synthetic adapter и приёмочная матрица PJ-01…PJ-20 выполнены**. Это не
production writer, не естественный диалог и не включение журнала в жизнь. PJ-I, PJ-A,
PJ-R, feature flag, модель, advisor, запуск сущности и запись в живой `data/` не
авторизованы.

## 1. Что реализовано

Только ignored test-only harness:

`tmp/response_experience_prospective/harness/pj_v.py`.

Он использует настоящие `ResponseExperience.prepare_plan()`, `register_delivery()`,
`observe_reply()`, `observe_feedback()`, `expire()` и `consolidate()` на синтетических
планах. Поверх них отдельный per-life SQLite adapter проверяет:

- подтверждение локальной доставки перед событием;
- `turn_id`, `episode_id`, `response_id` и монотонный `event_sequence`;
- delivery/outcome/expiry/pruning и journal lifecycle события;
- атомарный head, идемпотентный event ID и integrity hash chain;
- repeat origin links без raw text и текстовых fingerprint;
- fail-open ошибки writer с обязательным degraded/gap;
- crash/restart, corruption, restore, вторую жизнь и concurrent writers;
- disabled/enabled differential всего synthetic поведения.

Production-код этой фазой не менялся. Adapter и все SQLite-файлы находятся только в
ignored `tmp/response_experience_prospective/`. `DIGITAL_BEING_DATA_DIR` также
перенаправлен в песочницу. Harness живой `data/` не читал и не изменял; отдельное
разрешение владельца на его использование в этой фазе не потребовалось. Штатный pytest
выполняет собственную metadata-only проверку сохранности `data/`; предупреждений об
изменениях не было.

Полный regression дополнительно выявил test-only дефект изоляции: существующий
controlled observation при импорте безусловно переназначал `DIGITAL_BEING_DATA_DIR` и
тем перекрывал session-песочницу pytest. В рамках разрешённой test-only фазы присваивание
заменено на `os.environ.setdefault()` и добавлен regression-тест сохранения уже
установленного пути. Standalone-поведение observation сохранено; production writer этим
не появился.

## 2. Приёмочная матрица

Все результаты ниже относятся только к synthetic adapter.

| ID | Фактический результат |
|---|---|
| PJ-01 | Событие создаётся только после synthetic local delivery confirmation и реального `register_delivery()` |
| PJ-02 | Все шесть observed-классов получены реальными переходами; expiry остаётся censored |
| PJ-03 | Session-scoped/external и отсутствующий `message_id` не создают событий |
| PJ-04 | Outcome сохраняет исходный episode и отдельный observation turn |
| PJ-05 | Sequence монотонна; exact retry не дублирует событие; конфликт event ID отклоняется |
| PJ-06 | Поздний исход исключается cut по `outcome_sequence` |
| PJ-07 | Изменение будущего исхода не меняет delivery payload |
| PJ-08 | Raw text, dynamic значения, запрещённые ключи и текстовые fingerprint отсутствуют |
| PJ-09 | Повторы ссылаются на самый ранний origin в retained window |
| PJ-10 | Два pruning-события видны; 34 исхода остаются доступны в журнале |
| PJ-11 | Orphan получает `journal_gap/unverified` и не входит в supervised samples |
| PJ-12 | Injected writer failure и hard budget не отменяют доставку; completeness портится |
| PJ-13 | Clean restart продолжает sequence; crash оставляет видимый gap без reconstruction |
| PJ-14 | Изменённый payload обнаружен по hash chain до append; история не переписана |
| PJ-15 | Вторая жизнь не наследует deliveries, samples или origins |
| PJ-16 | Core restore не откатывает журнальный outcome; divergence отмечен gap |
| PJ-17 | Disabled/enabled synthetic behavior тождественно, включая `ResponseExperience` |
| PJ-18 | RAM, artifact size и elapsed измерены; production budget не устанавливался |
| PJ-19 | После close `integrity_check=ok`, WAL/SHM отсутствуют, фоновых writers нет |
| PJ-20 | Журнал не создаёт модель, advisor, речь или candidate gate |

Итог: **20/20 synthetic gates passed**. Естественный AgentRunner/UI путь этим не
доказан и остаётся за пределами PJ-V.

## 3. Crash и честная полнота

Отдельный child process завершён через `os._exit()` после реального
`register_delivery()`, но до journal append. После restart:

- прежний delivery в журнале сохранился;
- потерянный delivery не реконструировался;
- `journal_started` отметил unclean shutdown;
- `journal_gap` получил `completeness=unverified`;
- integrity chain продолжилась без перезаписи истории.

Exactly-once между внешней доставкой и SQLite **не заявляется**. Дополнительно injected
writer failure при штатном close создаёт gap при следующем открытии через сохранённый
degraded status.

## 4. Приватность и повторы

Whitelist сохраняет только frozen enums, boolean uncertainties, bounded confidence,
length/count buckets, normalized realization/component/borrowed признаки и provenance.
Dynamic source `pj_v_controlled` становится `other`.

Проверка рекурсивно отклоняет запрещённые payload keys. SQLite raw bytes дополнительно
проверены на отсутствие маркеров `SAME_SECRET_TEXT` и
`SYNTHETIC_RAW_INPUT_NEVER_PERSIST`. SHA-256 используется только для integrity chain
событий, не как fingerprint текста. Origin links остаются внутри журнала.

## 5. Differential

Одинаковый synthetic сценарий выполнен с writer disabled и enabled. Сравнены:

- стратегии, действия, score и тексты;
- фактические доставки и внешние synthetic effects;
- цели, награды, память, self-model, ценности и конфигурация;
- autonomous ticks;
- итоговое `ResponseExperience.to_dict()`.

Различий нет. Это доказывает изоляцию только в controlled harness, не в production
AgentRunner. Разрешённое различие — отдельный SQLite journal и diagnostic status.

## 6. Synthetic ресурсы

Финальный прогон `tmp/response_experience_prospective/pj-v.json`:

| Метрика | Значение |
|---|---:|
| Elapsed до crash-parent | 0,495915 с |
| `tracemalloc` current | 521 965 байт |
| `tracemalloc` peak | 976 735 байт |
| SQLite artifacts до crash case | 450 560 байт |
| Основная история | 18 событий |
| Repeat/prune история | 71 событие |
| Concurrent история | 11 событий |

Это диагностические измерения песочницы, не frozen production budget и не гарантия tick
latency. PJ-I обязан отдельно заморозить и проверить resource budget.

## 7. Проверки

Команды выполнялись из корня проекта в `.venv`:

```text
.venv/Scripts/python.exe tmp/response_experience_prospective/harness/pj_v.py --output tmp/response_experience_prospective/pj-v.json
.venv/Scripts/python.exe -m pytest tests/test_response_experience_shadow_baseline.py tests/test_response_experience.py tests/test_language_consolidation.py tests/test_external_response.py -q
.venv/Scripts/python.exe -m pytest tests/test_creative_draft.py tests/test_response_experience_shadow_baseline.py -q
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m ruff check tmp/response_experience_prospective/harness/pj_v.py
.venv/Scripts/python.exe -m ruff format --check tmp/response_experience_prospective/harness/pj_v.py
.venv/Scripts/python.exe -m ruff check src/ config/ tests/ main.py main_tray.py
.venv/Scripts/python.exe -m ruff format --check src/ config/ tests/ main.py main_tray.py
.venv/Scripts/python.exe -m mypy --config-file pyproject.toml --explicit-package-bases --no-site-packages --follow-imports=skip main.py main_tray.py
.venv/Scripts/python.exe -m bandit -q -r src/ config/ main.py main_tray.py -ll --skip B101,B601
.venv/Scripts/python.exe -m compileall -q src/ config/ tests/ main.py main_tray.py
```

Профильный pytest получил отдельный `DIGITAL_BEING_DATA_DIR` в песочнице. Для полного
regression используется штатная session-изоляция `tests/conftest.py`.

Фактические результаты:

- PJ-01…PJ-20: **20/20 passed**;
- профильные диалоговые тесты после добавления isolation regression: **71 passed**;
- Ruff harness: passed, `1 file already formatted`;
- Ruff production/tests: passed, **583 files already formatted**;
- mypy: `Success: no issues found in 2 source files`;
- Bandit: без failed tests, существующие nosec warnings;
- compileall: passed;
- первый полный запуск с внешне заданным общим `DIGITAL_BEING_DATA_DIR`: **13 failed,
  4068 passed, 2 skipped**. Все падения относились к заполненному общему creative
  workspace: внешняя переменная отключила создание штатной новой session-папки.
  Те же creative-сценарии отдельно дали **17 passed**;
- повтор без внешнего переопределения: **23 failed, 4058 passed, 2 skipped**. Падения
  снова относились к creative/music и повторному использованию заполненного workspace;
- узкое воспроизведение `tests/test_creative_draft.py` вместе с
  `tests/test_response_experience_shadow_baseline.py`: **4 failed, 11 passed**. При импорте
  observation безусловно заменял session `DIGITAL_BEING_DATA_DIR` на
  `tmp/response_experience_shadow/bootstrap`; в этой старой песочнице уже находились
  creative-файлы;
- после `setdefault()` и нового regression-теста тот же узкий набор: **16 passed**;
  collection завершился кодом 0 и сохранил штатный временный `DIGITAL_BEING_DATA_DIR`;
- финальный полный regression после исправления: **4082 passed, 2 skipped за 562,46 с**.

## 8. Решение и границы следующей фазы

PJ-V достаточен как synthetic proof контракта prospective журнала. Он не даёт реальных
событий и не изменяет R0: readiness остаётся `insufficient_data`, реальных записей
`ResponseExperience` в retained snapshot по-прежнему ноль.

Следующий возможный PJ-I требует нового отдельного разрешения и включает минимальный
production writer, выключенный по умолчанию, production regressions и resource gates.
Включение для жизни, естественные диалоги, модель и advisor этим отчётом не разрешены.

Commit/push не выполнялись.
