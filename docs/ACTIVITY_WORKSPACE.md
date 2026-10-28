# Этап 4: единая граница рабочей области занятия

Добавлен `ActivityWorkspace`: узкий адаптер над существующим Delamain Sandbox.
Корень фиксирован как `<profile>/delamain/workspace/creative`; абсолютные
пути/`..`/symlink escape отклоняются, текст UTF-8 и размер ограничены 8192
байтами, запись атомарна, обратное чтение проверяется в creative_draft.

Добавлен безопасный EffectorRequest-конструктор `creative_write_request` и
registry-action `write_creative_draft`: request содержит явный plan,
metadata activity=creative и postcondition file_exists; action ограничен
относительным `.txt` и отдельным creative sandbox. Registry/план проверены
адресными тестами (31 вместе с sandbox/effector/creative).

Конструктор теперь можно явно отправить в DelamainEffectorAdapter:
не включённый адаптер отклоняет request, включённый создаёт ровно одну
idempotent goal по request_id. Тесты submit/registry/workspace проверяют
план и дубликат; submit не запускает исполнение сам. Approval/core-driven
режим остаются владельцами фактического запуска. Прямой creative_draft путь
пока существует для локальной активности; два пути не объявлены единым
автоматическим исполнителем до отдельной интеграции/выбора авторитетной
очереди. В core-driven режиме approval теперь только фиксирует approved: выполнение
отложено до следующего EffectorAdapter.step(cycle), так что approval не
создаёт второй источник часов и не исполняет план напрямую. Обновлён тест
restart approval: после approve статус queued, после step — succeeded.
`DigitalBeing._on_effector_result` теперь обновляет creative method preference
только для terminal succeeded/failed/rejected и только при detail.activity=
creative. waiting_approval/queued не меняют историю; non-creative планы
игнорируются. На succeeded сохраняется результат запроса. Профильный
activity-result/approval/submit/workspace/draft набор: 13 passed.
Metadata `activity_goal_id` теперь может передаваться в explicit request;
на terminal succeeded matching `draft_revision` завершает activity goal через
обычный GoalSubsystem, failed/rejected/queued не завершают. Метод preference
обновляется terminal status. Это не переносит весь creative_draft local state
в Delamain и не завершает цель по одному status без metadata/postcondition.
Добавлен core_effector_result.interpret_result: terminal EffectorResult
становится Core payload с intention_id/target/core_cycle/activity, а не
Delamain memory event. Agent принимает driver report (result wrapper) и
legacy direct result; queued/waiting не обновляют preference/goal.
Core-led success с activity_goal_id завершает только matching activity goal.
Профильный core-result/activity-result/goal/approval/submit/workspace/draft:
12 passed; полный прежний профильный набор остаётся ниже.

Сквозной test_activity_effector_roundtrip.py: submit явного творческого
request → waiting_approval → approve (execution deferred) → core step →
проверенный creative/draft.txt → succeeded; повтор request не создаёт goal.
Reject даёт terminal rejected и файл не появляется. Профильный
roundtrip/result/approval/submit/workspace/draft набор: 27 passed.
Общий прогон перед этим участком: 1281 passed, 2 skipped. Адресный
EffectorResult/life episode/bridge набор: 12 passed. Операционный effector
результат пока намеренно не записывается в autobiographical life episodes:
нет core intention_id и authoritative event. Полный общий
прогон после теста ещё не запускался. Операционный effector результат
остаётся техническим; Core не дублирует его в autobiographical life episodes.
Этот append-only мост отложен до этапа 6, где будет выбран authoritative
событие и точно определена связь intention_id.

 Игра
хранит состояние в checkpoint, творческий текст — в этой папке, а каталоги
старых работ входят в профильную резервную копию. Прямой local_play не
пишет файлы; creative_draft использует ActivityWorkspace. Произвольные
workspace actions, сеть, shell, code execution и публикация не добавлены.

Профильный набор workspace/draft/play/sandbox: 22 passed. Проверены
roundtrip, escape и размер. Это адресная граница, не проверка реальной
долгой жизни или многопроцессной записи.

Оставшиеся этапы интеграции:
- подключить выбранный workspace-план к единому effector queue;
- сделать UI каталога и явное отображение доступа;
- добавить quota всего каталога и lifecycle/backup manifest;
- исправить ручные обходы Delamain/прямого Sandbox до расширения прав.
