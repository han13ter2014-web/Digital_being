# Инвентарная матрица верификаторов K14 (verify_*.py)

Статус: 2026-11-08, тикет T2 спринта вне декомпозиции (k15_backlog_2026-11-08).
Назначение: зафиксировать класс каждого верификатора и подтверждение его зелёного статуса на момент шага. Исторические верификаторы — **завершённые одноразовые инструменты**, их «ложные» падения на текущем дереве — не провал, а признак выполненности шага.

## Правило классификации (tests/test_verifier_selfcheck.py)

- В исходнике есть литерал `HEAD:` (якорь `git show HEAD:<файл>`) → **historical / one-shot**: верификатор сравнивает состояние «до шага» (HEAD на момент шага) с деревом «после шага» и по построению выполняется один раз — до коммита шага. После коммита шага HEAD содержит тонкие фасады, и честный прогон ложно падает.
- Литераl `HEAD:` отсутствует → **eternal**: верификатор не зависит от подвижного HEAD, честно проходит на любом дереве и подлежит постоянной самопроверке (honest + corruption-кейсы) в `tests/test_verifier_selfcheck.py`.

## Таблица

| Верификатор | Шаг K14 | Якорь «до шага» (родитель коммита шага) | Класс | Зелёный в момент шага |
|---|---|---|---|---|
| verify_reflection_move.py | 1 reflection | `5fd4604` | historical | протокол шага: коммит `e00151b` только после ok |
| verify_goals_move.py | 2 goals | `e00151b` | historical | stage2_report.md:51 (зафиксировано) |
| verify_body_move.py | 3 body | `e17170c` | historical | протокол шага: коммит `d5b53d3` только после ok |
| verify_persistence_move.py | 4 persistence | `d5b53d3` | historical | протокол шага: коммит `3903e92` только после ok |
| verify_persistence_paths.py | 4 persistence (runtime-проба) | — (без HEAD-якоря) | **eternal** | честный прогон 2026-11-08: exit=0; самопроверка в гейте |
| verify_effector_move.py | 5 effector | `3903e92` | historical | протокол шага: коммит `c39c4da` только после ok |
| verify_selection_move.py | 6 selection | `c39c4da` | historical | протокол шага: коммит `3cc8ba1` только после ok |
| verify_communication_move.py | 7 communication | `3cc8ba1` | historical | протокол шага: коммит `16bd920` только после ok |
| verify_handlers_move.py | 8 handlers | `16bd920` | historical | stage9_report.md:19 (перенос зафиксирован) |
| verify_creative_exploration_move.py | 9 creative+exploration | `497109d` | historical | stage8_report.md:59 (уточнение probe-правила, повторная проверка ok) |
| verify_emotional_move.py | 10 emotional | `87d4e2a` | historical | протокол шага: коммит `de79580` только после ok |
| verify_evolution_move.py | 11 evolution (статика) | `de79580` | historical | протокол шага: коммит `e7eaf31` только после ok |
| verify_evolution_runtime.py | 11 evolution (рантайм) | `de79580` | historical | протокол шага: коммит `e7eaf31` только после ok |
| verify_properties_move.py | 12 properties | `e7eaf31` | historical | протокол шага: коммит `b9241a2` только после ok |
| verify_act_move.py | 13 act | `b9241a2` | historical | протокол шага: коммит `2d53629` только после ok |
| verify_autonomous_tick_move.py | 14 autonomous tick | `2d53629` | historical | протокол шага: коммит `54ec3f5` только после ok |
| verify_creation_move.py | 15 creation | `54ec3f5` | historical | протокол шага: коммит `d6a3c3e` только после ok |

Коммиты шагов: `e00151b`→`e17170c`→`d5b53d3`→`3903e92`→`c39c4da`→`3cc8ba1`→`16bd920`→`497109d`→`87d4e2a`→`de79580`→`e7eaf31`→`b9241a2`→`2d53629`→`54ec3f5`→`d6a3c3e` (git log, ветка main).

## Самопроверка (eternal)

`tests/test_verifier_selfcheck.py` (тикет T2, 2026-11-08): авто-обнаружение `k*_decomposition_*/verify_*.py`, классификация по правилу выше, для eternal — честный прогон и четыре corruption-кейса (подменённое тело / убранный импорт / лишний импорт / перестановка функций) в изолированном git-worktree на HEAD; живое дерево и живой `data/` не затрагиваются.

Вердикты для verify_persistence_paths.py (поверхность: `src/core/agent.py`, `src/core/checkpoint_serializer.py`, `src/core/paths.py`):

| Кейс | Результат |
|---|---|
| подменённое тело | поймал (src/core/checkpoint_serializer.py → exit=1) |
| убранный импорт | поймал (src/core/agent.py → ImportError → exit=1) |
| лишний импорт | не пойман (поведение сохраняется, exit=0 на всех файлах поверхности) |
| перестановка функций | не пойман (поведение сохраняется, exit=0 на всех файлах поверхности) |

Не-ловля косметических кейсов — ожидаемое свойство runtime-пробы: она охраняет семантику (пути данных внутри песочницы, атомарность tempfile+os.replace), а не структуру AST.

## Замечания

- Исторические верификаторы не удаляются и не правятся (тикет T2, решение владельца: вариант C). Их возможная ревизия (пин якорей родительских коммитов шагов) — отдельное задание.
- Честные прогоны 2026-11-08 всех 17 верификаторов (16 ожидаемых ложных падений historical + 1 зелёный eternal) зафиксированы как evidence инвентаря: папка спринта `k15_backlog_2026-11-08/t2_honest_reports/`, сводка `k15_backlog_2026-11-08/t2_inventory.md` (локальные evidence-папки спринта не трекаются).
