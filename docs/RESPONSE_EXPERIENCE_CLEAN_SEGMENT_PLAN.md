# RE-CS — чистый сегмент prospective response-journal

Дата подготовки: 2026-11-22.

Статус: **CS-V, CS-I и CS-A завершены локально; один сегмент запущен для выбранной
жизни, естественный сбор и итоговый CS-R ещё не выполнены**. Отчёты —
`RESPONSE_EXPERIENCE_CLEAN_SEGMENT_CS_V.md`,
`RESPONSE_EXPERIENCE_CLEAN_SEGMENT_CS_I.md` и
`RESPONSE_EXPERIENCE_CLEAN_SEGMENT_CS_A.md`.

Связанные контракты: `RESPONSE_EXPERIENCE_PROSPECTIVE_JOURNAL_TICKET.md`,
`NEURAL_SPEECH_ORGAN_R1.md`, `NEURAL_SPEECH_ORGAN_R2_PREP.md` и раздел «Собственная
пластичная кора» в `body_plan.md`.

## 1. Фактическая проблема

Последняя read-only оценка sandbox `response_annotation_review_v7` показала:

- 174 доставки, 127 observed outcomes, 40 expired и 7 pending;
- 114 человеческих аннотаций: 102 resolved intent labels и 51 resolved semantic plan;
- нулевые annotation provenance gaps;
- достаточные temporal counts: train 60, validation 32, held-out 35;
- только `ordinary_reply` и `unclassified_reply` в наблюдаемых исходах;
- нулевое train-покрытие `answer`, `follow_up`, `explicit_support` и
  `explicit_opposition`;
- 17 journal gaps, включая прежние unclean shutdown, `event_id_conflict` и один
  `orphan_outcome`.

Поэтому текущий результат остаётся `insufficient_data`, `training_allowed=False`.
Количественные пороги разметки уже пройдены, но `outcome_class_coverage` и
`journal_integrity` блокируют дальнейший gate.

Простое создание пустого SQLite не решает проблему. Core восстанавливает retained
`ResponseExperience`, включая старые pending-ответы. Их последующие outcome, expiry и
pruning не имеют delivery в новом журнале. Поддельные delivery создавать нельзя, а
очистка памяти меняла бы жизнь и запрещена этим планом.

Дополнительное ограничение: человеческие метки связаны с исходными delivery через
`response_id`, `episode_id`, `delivery_sequence` и `source_delivery_event_hash`.
Переносить их на новые ответы или автоматически объявлять пригодными в новом сегменте
нельзя.

## 2. Выбранное решение

Использовать два независимых, но совместимых механизма:

1. **Новый явный сегмент сбора** для будущих естественных событий, с hash-chain
   границей и исключением pre-segment `ResponseExperience` из области writer.
2. **Read-only сегментную инвентаризацию старого журнала**, которая определит, какие
   старые доставки и человеческие метки находятся в доказуемо чистых интервалах.
   Ничего не переписывать и не переносить автоматически.

Это не сброс памяти и не скрытое ослабление gates. Старые gaps остаются видимыми в
архиве и отчётах. В строгий dataset попадают только события с доказанной целостностью.

## 3. Граница нового сегмента

### 3.1. Хранение и идентичность

- Текущий журнал сначала штатно закрывается и сохраняется вместе с manifest и хешами.
- Новый сегмент получает отдельный технический `segment_id`; жизнь и `life_id` не
  меняются. Вторая жизнь ничего не наследует.
- Первое lifecycle-событие содержит `segment_id`, схему сегмента, граничный cycle,
  причину `owner_approved_clean_collection` и ссылку на архивный manifest hash.
- Старый журнал остаётся read-only. Новый файл не создаётся поверх него без сохранённой
  копии и проверки хешей.
- Формат journal schema повышается из-за новых event kinds; старый формат остаётся
  доступным только для read-only inventory. Существующие feature fields не меняются
  без отдельной необходимости.

### 3.2. Pre-segment exclusions

На границе writer получает только технические `(profile_id, response_id)` уже
существующих записей `ResponseExperience`.

Для каждой такой записи добавляется immutable `segment_exclusion` событие:

- `reason="pre_segment_response"`;
- технические profile/response IDs, без текста и плана;
- никаких delivery, outcome, episode или выдуманных cycles;
- событие входит в общий hash-chain.

Правила writer:

- outcome/expiry/pruning исключённого ID без delivery в сегменте игнорируются как
  заведомо вне области сбора, а не становятся `orphan_outcome` или
  `origin_unavailable`;
- любой другой переход без delivery по-прежнему создаёт явный gap;
- новая фактическая доставка записывается только через существующий подтверждённый
  AgentRunner-путь;
- exclusion не удаляет и не изменяет запись в памяти Тэсс;
- настоящий repeat в pre-segment реализацию не выдаётся за первый в жизни. Origin link
  должен разрешаться к exclusion и не считаться in-segment доставкой или эпизодом.

### 3.3. Restart и чистота

- Штатный restart продолжает тот же сегмент и проверяет sequence/hash перед append.
- Unclean shutdown, core restore divergence, conflict, orphan, corruption и writer error
  делают сегмент непригодным для строгого gate; автоматического «очищения» нет.
- Новый сегмент после такого события возможен только по отдельному разрешению, без
  удаления прежнего.
- Перед read-only оценкой Тэсс останавливается штатно, writer leases равны нулю,
  последнее событие — `journal_stopped`, SQLite integrity и hash-chain проверены.

## 4. Сохранение старой разметки

Старые annotation SQLite и response SQLite не изменяются.

Отдельная read-only функция должна:

1. восстановить lifecycle/gap интервалы старого журнала;
2. консервативно исключить unclean, degraded, conflict, orphan, restore-divergence и
   любые интервалы, для которых полнота не доказуема;
3. сохранить исходные event sequences и hashes у допустимых событий;
4. принимать старую метку только при полном совпадении join keys и delivery hash;
5. требовать, чтобы delivery и используемый outcome относились к допустимому интервалу;
6. показывать отдельно сохранённые и исключённые deliveries, intent labels, semantic
   plans и outcome classes с причинами исключения.

`previous_writer_degraded` нельзя трактовать как доказательство чистоты последующих
событий: исторический writer сохраняет degraded status. Поэтому ретроспективное
восстановление разрешено только по заранее замороженным правилам интервалов. Если
доказательной границы нет, интервал исключается, а не «спасается» ради метрик.

Итог этой инвентаризации заранее не обещается. Если сохранённых resolved labels
недостаточно, потребуется разметка новых естественных доставок. Старые 114 аннотаций
остаются ценным архивом даже если часть нельзя допустить в строгий dataset.

## 5. Segment-aware projection и readiness

Новая projection-версия должна сохранять существующие ограничения:

- единица split — целый episode, без разрыва delivery/outcome;
- сегменты упорядочиваются по явной границе, события внутри — по исходной sequence;
- shuffle запрещён; исходы и поздние annotation revisions доступны только после своих
  фактических cutoffs;
- sequences response-journal и annotation-journal не сравниваются напрямую;
- exclusion events не становятся samples и не создают episodes;
- исключённые исторические интервалы видны в coverage и не маскируются;
- cross-life, duplicate/conflicting delivery и hash mismatch остаются provenance gaps;
- raw text и запрещённые dynamic поля не добавляются.

`training_allowed=True` возможно только при одновременном выполнении всех существующих
условий: temporal coverage, все шесть outcome classes в train, отсутствие gaps в
используемых событиях, не менее 50 resolved intent labels и 50 semantic plans,
отсутствие annotation provenance gaps и отдельное решение владельца.

Для недостающих исходов по-прежнему требуется минимум по два train-примера
`answer`, `follow_up`, `explicit_support` и `explicit_opposition` после split. Новые
естественные диалоги не раздуваются искусственно; обычные реплики не переименовываются
в поддержку или несогласие.

## 6. Обязательные adversarial tests

До production-изменений в sandbox проверяются:

1. pre-segment pending получает outcome, expiry и pruning без ложного gap и без записи
   в dataset;
2. неизвестный orphan по-прежнему создаёт gap;
3. pre-segment repeat origin не выдаётся за in-segment delivery или первый в жизни;
4. новая доставка имеет новый response/episode ID и проходит обычный outcome join;
5. restart после clean shutdown продолжает сегмент без потери exclusions;
6. unclean restart, conflict, corruption и core restore закрывают strict readiness;
7. вторая жизнь начинается без сегментов, exclusions и меток первой;
8. старые annotation hashes не переписываются и не привязываются к новым delivery;
9. поздние outcomes и corrections не протекают в прошлый train;
10. gaps вне допущенных интервалов остаются видимыми в отчёте;
11. disabled/enabled writer не меняет текст, выбор, память, награды, цели и жизненный
    цикл;
12. SQLite integrity, hash-chain, shutdown/WAL, writer leases, storage/latency budgets и
    privacy whitelist проходят существующие gates.

## 7. Фазы и независимые разрешения

### CS-T — текущий план

Только этот документ. Production-код, живые данные, активная Тэсс и текущие незакоммиченные
исправления речи не меняются. Полный regression для документа не требуется.

### CS-V — test-only сегментный контракт

Отдельное разрешение. Реализация projection и segment writer только с временными
песочницами; adversarial tests и демонстрация сохранения/исключения старых меток без
изменения оригиналов.

### CS-I — production implementation, default-off

Отдельное разрешение. Минимальный код, обратная совместимость read-only v1, профильные и
полные проверки по `AGENTS.md`. Активация и живая запись не входят.

### CS-A — запуск одного нового сегмента

Отдельное разрешение после отчёта CS-I. Штатная остановка выбранной жизни, архив и
проверка хешей, создание сегмента, проверка первых событий и естественное продолжение
жизни. Никаких искусственных диалогов ради ускорения dataset.

### CS-R — read-only оценка

Отдельное разрешение. Повторная инвентаризация и readiness после достаточного объёма
естественных событий. Этот этап не запускает обучение автоматически.

## 8. Критерии остановки

Работа останавливается, если для чистого сегмента требуется:

- удалить или переписать память, старые events либо annotation revisions;
- создать фиктивную delivery/outcome или скрыть gap;
- перенести метку на другой response/hash;
- ослабить temporal, class, integrity или privacy gates;
- изменить речь, стратегии, награды, цели или жизненный цикл ради сбора;
- запустить обучение без итогового `ready_for_r2_review` и отдельного разрешения.

Commit и push на каждом этапе выполняются только по явному разрешению владельца.
