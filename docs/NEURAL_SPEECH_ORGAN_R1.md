# R1: контракты речевого органа и измерение данных

Дата: 2026-11-22.

Статус: **контракты и controlled observation реализованы; решение — `insufficient_data`**.
R2, обучение нейросети, Neural Composer, advisor и активный shadow-writer не запускались.
Активные ответы и маршруты `AgentRunner` не изменялись.

## 1. Реализованный объём

- `src/core/semantic_response_plan.py` — frozen DTO `SemanticResponsePlan` версии 1,
  вложенные факты занятия/завершённого действия, evidence refs, allowed claims и builders
  для `ASK_SELF_ACTIVITY` и `ASK_SELF_STATE`.
- `src/core/shadow_prediction.py` — frozen read-only DTO `ShadowPrediction` и
  `PredictionProvenance`: шесть нормированных вероятностей либо явный `abstain_reason`,
  версии feature/architecture/weights/training contract, идентификаторы и provenance.
- `src/core/response_shadow_inventory.py` — чистые функции инвентаризации событий
  существующего `ResponseExperienceJournal`, адаптация samples к B0/B1/B2,
  хронологическое разбиение целых эпизодов и readiness-отчёт.
- `tests/observations/neural_speech_r1.py` — воспроизводимый controlled observation
  через настоящий production SQLite writer в `tmp/` и реальные переходы
  `ResponseExperience`.
- `tests/test_neural_speech_r1.py` — 31 unit/adversarial regression-тест контрактов.

Новых зависимостей, сети, внешней LLM, обучения на живом профиле и записи предсказаний
в жизненный контур нет. Существующий production response-journal остаётся выключенным
по умолчанию; observation открывает его только в собственной песочнице.

## 2. SemanticResponsePlan

План содержит копии значений, а не ссылки на изменяемую историю Core:

- `schema_version`, `response_id`, `cycle`, `language`, `intent`;
- `activity`: `current|none`, kind, проверенный `work_id|null`, `started_cycle`, target;
- отдельный `last_completed_action`;
- `energy` только для state-плана, без вывода усталости, грусти или другого переживания;
- `evidence_refs`, `allowed_claims` и уже построенный `baseline_text`.

Правила builders:

1. Текущее действие берётся только из `started`, завершённое — только из `performed`.
2. `interrupted` не считается ни текущим, ни завершённым действием.
3. При текущем действии прошлое не добавляется в activity-план как лишний факт.
4. При отсутствии текущего действия используется явный `status=none`; последняя тема
   исследования не подменяет занятие.
5. `work_id` проходит только при наличии работы в соответствующем реальном каталоге
   `_art_catalog`, `_music_catalog` или `_creative_catalog`; новая работа и forged ID
   получают `work_id=None`.
6. Изменение исходной `_intention_history` после построения не меняет DTO.
7. Сериализация строгая: неизвестные поля и противоречивые activity-факты отклоняются.

DTO ещё не подключён к доставке. Это контракт для последующего детерминированного
контура, а не разрешение генеративной модели создавать факты.

## 3. ShadowPrediction

Запись содержит только pre-outcome предсказание и происхождение обучающей истории:

- life/profile/response/episode IDs, delivery и prediction sequences;
- feature/architecture/weights/training contract versions;
- шесть вероятностей исходов с суммой 1 либо причину abstention;
- SHA-256 исходного delivery event;
- training response IDs, cutoff sequence, sample count и необязательный training life ID.

Отклоняются: одновременные probabilities и abstention, отсутствие обоих, неверная сумма
или число вероятностей, cross-life provenance, cutoff после delivery, self-training,
неизвестные поля `outcome`, `raw_text`, `baseline_text` и другие поля вне схемы.

Writer для этих предсказаний не создавался. DTO не содержит исход наблюдения и не может
служить скрытым каналом утечки будущего в признаки.

## 4. Доступные примеры и исходы

### 4.1. Что реально доступно по существующему контракту

`ResponseExperienceJournal` связывает фактическую доставку с последующим исходом по
`response_id`, `episode_id` и event sequences. Он различает шесть наблюдаемых классов:
`answer`, `follow_up`, `unclassified_reply`, `ordinary_reply`, `explicit_support`,
`explicit_opposition`. `no_observed_reaction` остаётся expiry/censoring, а не успехом.

Этот контракт **не содержит** подтверждённых человеком меток перефразировок
`ASK_SELF_STATE` / `ASK_SELF_ACTIVITY` / `UNKNOWN_OR_OTHER` и размеченных
`SemanticResponsePlan` для composer. Поэтому исходы ответов нельзя выдать за метки
интентов или обучающие смысловые планы.

### 4.2. Controlled production-SQLite observation

Использованы реальные `prepare_plan`, `register_delivery`, `observe_reply`,
`observe_feedback`, `expire` и настоящий `ResponseExperienceJournal`. Тексты и расписание
controlled, поэтому это проверка инструмента, а не естественная биография Тэсс.

| Показатель | Значение |
|---|---:|
| Доставки | 32 |
| Наблюдаемые исходы | 30 |
| Expired | 1 |
| Pending | 1 |
| `answer` | 9 |
| `follow_up` | 6 |
| `unclassified_reply` | 3 |
| `ordinary_reply` | 6 |
| `explicit_support` | 3 |
| `explicit_opposition` | 3 |
| Missing episode/outcome cycle | 0 / 0 |
| Provenance gaps / invalid ordering / journal gaps | 0 / 0 / 0 |

Содержимое живого `data/` не читалось. Реальная биография не инвентаризировалась;
количество её естественных примеров этот отчёт не утверждает. Metadata manifest до/после
observation совпал.

## 5. Временное разбиение и baseline

Целые эпизоды упорядочены по первой доставке и разделены 60/20/20 без shuffle.
Для train исход доступен только при `outcome_sequence < validation_start`; поздний отзыв
исключается. Held-out начинается после более ранних эпизодов. Вторая жизнь не наследует
выборку, статистику или веса.

| Срез | Эпизоды | Наблюдаемые исходы |
|---|---:|---:|
| Train | 19 | 19 eligible |
| Validation | 6 | 6 |
| Held-out | 7 | 5 |

В train после cut: `answer=6`, `follow_up=3`, `unclassified_reply=2`,
`ordinary_reply=4`, `explicit_support=2`, `explicit_opposition=2`.
Late outcomes в этом controlled расписании: 0; отдельный adversarial-тест подтверждает
исключение позднего исхода.

Использованы уже существующие реализации B0/B1/B2 из RE-S1, без дублирования алгоритмов
в production. Метрики: log loss, Brier, ECE на 10 bins, coverage, per-class support/recall
и срезы по context/expectation/language/borrowed. Срезы с `examples < 5` дополнительно
помечаются `data_status=insufficient_data`.

### Held-out, n=5

| Baseline | Log loss | Brier | ECE | Coverage |
|---|---:|---:|---:|---:|
| B0 | 1.688937 | 0.803200 | 0.080000 | 1.0 |
| B1 | 1.273233 | 0.632937 | 0.267255 | 1.0 |
| B2 | 1.530022 | 0.726531 | 0.314286 | 1.0 |

B1 лучше по log loss/Brier на этом controlled held-out, но выборка слишком мала, ECE не
улучшается, а данные не являются естественными перефразировками. Это не основание для
обучения или продвижения кандидата.

## 6. Замороженные readiness и ресурсные бюджеты

Минимальный measurement gate для outcome baseline:

- train observed ≥ 30, validation ≥ 10, held-out ≥ 10;
- не менее 2 train-примеров каждого observed class;
- отсутствие journal/provenance/ordering gaps;
- срез менее 5 примеров считается `insufficient_data`.

Для перехода к R2 дополнительно требуются независимые подтверждённые метки: не менее 50
intent labels и не менее 50 semantic plans как стартовый порог полноты контракта. Сам по
себе порог не разрешает обучение: нужны временное разбиение меток, классовое покрытие,
baseline comparison и отдельное решение владельца.

Ресурсные бюджеты относятся к measurement, не к качеству модели:

| Измерение | Результат | Бюджет | Итог |
|---|---:|---:|---|
| Write pair p95 | 2.998 ms | < 250 ms | passed |
| Write pair max | 3.570 ms | < 1000 ms | passed |
| Максимальный SQLite artifact | 118 784 bytes | < 4 MiB | passed |
| Tracemalloc peak | 950 764 bytes | < 16 MiB | passed |

Два controlled observation заняли 0.238 s. SQLite integrity после закрытия: `ok` для обоих
журналов. Повтор дал идентичные delivery/outcome projection, inventory и held-out metrics;
случайные journal envelope IDs и hash-chain не сравнивались как содержательный результат.

## 7. Adversarial-набор и stop conditions

Проверены:

- current activity без kind/cycle и `none` с заполненными полями;
- forged и новый `work_id`;
- `interrupted` как запрещённый источник current/completed;
- mutation исходной history после копирования;
- неверная сумма/размер probabilities, probabilities вместе с abstention и отсутствие обоих;
- cross-life provenance, future cutoff, self-training;
- запрещённые outcome/raw-text/baseline-text поля предсказания;
- missing episode/provenance, malformed payload и invalid ordering;
- late outcome после training cutoff;
- неизменяемость входных событий и DTO;
- пустая вторая жизнь и uniform B0 без унаследованной статистики.

Эксперимент останавливается с сохранением baseline при недостатке независимых меток или
исходов, отсутствии превосходства над baseline, нарушении смысла, утечке будущего,
cross-life переносе, изменении активного поведения, превышении ресурсов либо потребности
во внешней LLM/сети. Неудачный кандидат не является причиной ослабить gate.

## 8. Решение

Итог R1: **`insufficient_data`; обучение не разрешено и не запускалось**.

Причины:

1. Controlled outcome baseline измерим как инструмент, но train/validation/held-out не
   проходят замороженные численные пороги.
2. Существующий response-journal не предоставляет human-confirmed intent labels.
3. Существующий response-journal не предоставляет human-confirmed semantic plans.
4. Controlled выигрыш B1 на пяти held-out исходах не доказывает пользу нейросети.

Следующий самостоятельно полезный этап по общему плану — R3: подключить смысловой
планировщик и валидатор к реальным фактам, не обучая нейросеть. Подготовка разрешённой
разметки для R2 требует отдельного согласования; автоматический переход не выполняется.

## 9. Воспроизведение и проверки

```powershell
.venv/Scripts/python.exe tests/observations/neural_speech_r1.py --label controlled-final --output tmp/neural_speech_r1/report.json
.venv/Scripts/python.exe -m pytest tests/test_neural_speech_r1.py tests/test_response_experience_shadow_baseline.py tests/test_response_experience_journal.py tests/test_response_experience.py tests/test_user_message_routing.py tests/test_dialogue_working_memory.py -q
```

Результаты:

- новые контрактные тесты: **31 passed**;
- профильный regression: **159 passed**;
- полный regression: **4208 passed, 2 skipped за 572.85 s**;
- Ruff check: passed;
- Ruff format: 593 файла уже отформатированы;
- compileall: passed;
- mypy: no issues in 2 source files;
- Bandit: passed; только существующие informational `nosec` warnings;
- live GUI/диалог и естественная биография не проверялись;
- commit и push не выполнялись.
