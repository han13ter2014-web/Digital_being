# RE-CS-V — synthetic clean-segment contract

Дата: 2026-11-22.

Статус: **CS-V завершён в test-only песочнице: 12/12 проверок прошли**.
Production implementation, активация нового сегмента, обучение, commit и push не
выполнялись и требуют отдельных решений.

Основание и границы: `RESPONSE_EXPERIENCE_CLEAN_SEGMENT_PLAN.md`.

## 1. Реализованный объём

Только ignored harness:

- `tmp/response_experience_clean_segment/harness/cs_v.py`;
- `tmp/response_experience_clean_segment/cs-v.json`.

Используется test-only наследник настоящего `ResponseExperienceJournal`. Версия схемы и
writer contract переопределяются только внутри процесса песочницы; production-файлы не
изменяются. Все SQLite создаются под `tmp/response_experience_clean_segment/`.

Проверены:

- hash-chain граница сегмента и immutable `segment_exclusion` события;
- исключение pre-segment outcome/expiry/pruning без ложных delivery и gaps;
- обязательный gap для настоящего orphan;
- repeat origin в pre-segment ответ без выдачи его за in-segment доставку;
- новые фактические delivery/outcome и их samples;
- clean restart с сохранением exclusions;
- unclean restart, core restore divergence и corruption detection;
- изоляция второй жизни;
- сохранение и исключение исторических аннотаций без перезаписи hashes;
- temporal cutoffs для исходов и поздних annotation revisions;
- видимость исключённых gaps и cross-interval событий;
- одинаковый `ResponseExperience` с writer disabled/enabled;
- SQLite integrity, отсутствие writer leases/WAL после shutdown и отсутствие raw-text
  маркеров.

Итог: **12/12 synthetic checks passed**. Это не production AgentRunner/UI и не запуск
естественной жизни.

## 2. Исправления по результатам adversarial-проверок

Первый запуск дал 9/12, затем 11/12. Исправления относились к harness:

- hash mismatch больше не ожидается как валидный sample: правильный результат —
  отсутствие sample и явный `annotation_provenance` gap;
- случайные profile IDs нормализуются только при differential-сравнении, а не в
  поведении агента;
- degraded head для restart-сценария моделируется явно;
- добавлен случай terminal/pruning события в чистом интервале, когда исходная delivery
  находится в исключённом интервале. Такое событие исключается как
  `cross_interval_excluded_events` и не остаётся ложным orphan в dataset.

После последнего изменения весь harness повторно прошёл 12/12.

## 3. Read-only projection существующей sandbox-копии v7

Использовались только существующие файлы
`tmp/response_annotation_review_v7/ee9d16cb-1e37-44dc-8c8e-91d437513e12/`, открытые в
read-only режиме. Живой `data/` и работающая Тэсс не читались и не изменялись этим
запуском. SQLite integrity, sequences и hash-chains обоих журналов проверены.

Правила projection:

- интервал без штатного `journal_stopped` исключается;
- operational gap исключает весь текущий интервал;
- startup `previous_shutdown_unclean` / `previous_writer_degraded` остаётся видимым и
  относится к границе, а не доказывает или отменяет чистоту последующего интервала;
- outcome/expiry/pruning исключается, если его delivery не входит в допущенные
  интервалы;
- аннотации исключённых deliveries не подменяются и не переносятся;
- неизвестная или hash-mismatched аннотация остаётся в projection и создаёт видимый
  provenance gap, а не исчезает ради метрики.

Фактический результат:

| Показатель | Значение |
|---|---:|
| Допущенные / исключённые интервалы | 10 / 4 |
| Допущенные deliveries | 137 |
| Аннотированные deliveries в projection | 82 |
| Resolved intent labels | 76 |
| Resolved semantic plans | 38 |
| Intent abstentions | 6 |
| Annotation provenance gaps | 0 |
| Исключённые annotation revisions | 37 |
| Исключённые cross-interval events | 18 |

Исключённые gaps остаются видимыми: 3 `previous_shutdown_unclean`, 12
`previous_writer_degraded`, 1 `event_id_conflict`, 1 `orphan_outcome`.

После projection `journal_integrity` больше не входит в missing **только для
допущенного набора событий**. Это не очищает исходный журнал и не отменяет его историю.

Оставшиеся blockers:

- `semantic_plan_labels`: 38 при общем минимуме 50 — не хватает 12;
- `outcome_class_coverage`: в train по-прежнему нет `answer`, `follow_up`,
  `explicit_support`, `explicit_opposition`; `unclassified_reply=27`,
  `ordinary_reply=19`.

Итог остаётся `insufficient_data`, `training_allowed=False`. Projection не обучает
модель и не разрешает следующий gate автоматически. Дополнительные метки и события
должны пройти временные и классовые gates после split; простого добавления 12
произвольных записей недостаточно для гарантии готовности.

## 4. Проверки

Выполнено из корня проекта:

```text
.venv/Scripts/python.exe -m ruff check tmp/response_experience_clean_segment/harness/cs_v.py
.venv/Scripts/python.exe -m ruff format --check tmp/response_experience_clean_segment/harness/cs_v.py
.venv/Scripts/python.exe tmp/response_experience_clean_segment/harness/cs_v.py --output tmp/response_experience_clean_segment/cs-v.json
.venv/Scripts/python.exe -m pytest tests/test_response_experience_journal.py tests/test_neural_speech_r2_prep.py tests/test_neural_speech_r1.py -q
```

Результаты:

- CS-01…CS-12: **12/12 passed**;
- существующие journal/R1/R2 contracts: **87 passed**;
- Ruff check: passed;
- Ruff format: `1 file already formatted`.

Полный regression этой документно/test-only фазы не запускался: production-код не
менялся. Он обязателен для CS-I вместе с mypy, Bandit, compileall и полным CI Ruff.

## 5. Следующая граница

CS-V достаточен как synthetic proof сегментной границы и historical projection. Он не
разрешает архивировать текущий живой журнал, создавать новый сегмент или собирать новые
метки автоматически.

Следующий возможный этап — **CS-I**: минимальный production contract, default-off,
обратная совместимость read-only v1, production regressions и все статические gates.
Требуется новое отдельное разрешение владельца.
