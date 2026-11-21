# D2-R — Уточняющие наблюдения потребностей и мотивации

Дата прогона: 2026-11-21.

Основание: решения владельца `MOTIVATION_DECISION_GATE_D3.md`, пункты
D3-1…D3-5. Это продолжение наблюдения, а не ревизия потребностей, действий,
наград, API или арбитра.

## 1. Воспроизводимость и границы

- Полная ревизия кода: `977817f3c0961c659a0c562981b6da9dd0eeb683`.
- Seed: `20261121`.
- Test-only инструмент: `tests/observations/d2r_motivation.py`.
- Сырые данные: `tmp/motivation_d2r/results.json`.
- Команда:

  ```bash
  .venv/Scripts/python.exe tests/observations/d2r_motivation.py
  ```

- Все сценарии используют отдельные каталоги внутри `tmp/motivation_d2r/`.
  Внешние сетевые ответы не запрашиваются: положительный поиск использует
  контролируемый ответ `WebSearcher.search`, а реальные обработчик, запись знания,
  LoopCloser и мотивационная обратная связь выполняются штатно.
- Живой `data/`: 1278 файлов сопоставлены по относительному пути, размеру и
  `mtime_ns` до/после; изменений не обнаружено.
- Production-код, живой профиль, needs, drives, константы, награды, арбитр,
  checkpoint-схема и LLM не менялись.

Все запланированные пакеты R-01…R-05 получили фактические наблюдения. Ошибок
сценариев и вынужденных `not_observed` в итоговом прогоне нет. Отсутствие
world-evidence у действия записано как результат, а не заменено успехом.

## 2. R-01 — World-evidence семи контрольных связей

Каждая связь проверена через фактический `DigitalBeing.act()`. До действия
целевая потребность контрольно установлена на `0.1`, остальные — на base level.
Записаны executor, `ActionOutcome`, фактическая валентность и изменения всех needs.

| Потребность | Действие и исполнитель | Положительный сценарий | No-effect контроль | Denied контроль |
|---|---|---|---|---|
| `curiosity` | `web_search` → `_act_web_search` → запись в knowledge base | `knowledge_entries +1`; curiosity **+0.433125** | Поиск выключен, эффекта нет; curiosity **−0.060** | `denied:too_tired`; needs без изменений |
| `competence` | `synthesis` → `_act_synthesize` → `encounter_concept` | `experiences +1`; competence **+0.450**, curiosity +0.100, meaning +0.350, coherence +0.200 | Нет связанных концепций и эффекта; competence, curiosity, meaning, coherence по **−0.060** | `denied:too_tired`; needs без изменений |
| `autonomy` | `set_own_goal` → `_act_set_own_goal` → `set_goal` | Подтверждён `goal_id`; autonomy **+0.450**, meaning +0.350 | Цель не создана, эффекта нет; всё равно autonomy **+0.450**, meaning +0.350 | `denied:too_tired`; needs без изменений |
| `connection` | `user_answer` классифицируется как `communicate` → `send_message` | `messages_sent +1`; connection **+0.423**, competence +0.141 | Нечего рассказать, эффекта нет; всё равно connection **+0.423**, competence +0.141 | `denied:too_tired`; needs без изменений |
| `play` | `create_draft` → `perform_creative` | Подтверждена записанная редакция; play **+0.23625** | Существующая работа оставлена (`leave`), эффекта нет, valence=0; needs без изменений | `denied:too_tired`; needs без изменений |
| `meaning` | `reflection` → `_act_reflect` → `reflect` | Получен контрольный текст паттерна, но `ActionOutcome.had_effect=false`; meaning **+0.405**, competence +0.135, coherence +0.180 | Новых паттернов и эффекта нет; те же положительные дельты | `denied:too_tired`; needs без изменений |
| `coherence` | `repair` → `StructuralIntegrity.manual_repair` | Подтверждено восстановление целостности; coherence **+0.450** | Целостная структура, эффекта нет; всё равно coherence **+0.450** | Отказа нет: `repair` относится к essential actions и выполняется при energy=0; coherence **+0.450** |

### Что именно доказано

1. У `web_search`, `synthesis`, `set_own_goal`, `user_answer`, `create_draft` и
   `repair` существуют сценарии с наблюдаемым мировым или узким подтверждённым
   результатом. У `reflection` в текущем контуре получен только текст результата:
   ни `WorldDelta`, ни `confirmed_result` его не подтверждают.
2. Для продуктивных `web_search` и `synthesis` no-effect переводится в valence
   −0.2 и фрустрирует связанные потребности.
3. Для непродуктивных по классификации LoopCloser `set_own_goal`, `communicate`,
   `reflection` и `repair` no-effect не получает такого ограничения. Их
   положительная валентность сохраняется, поэтому насыщение возможно без
   подтверждённого результата.
4. `create_draft/leave` — отдельный корректно различимый контроль: valence=0 и
   потребности не меняются. Denied до исполнения также не меняет needs.
5. Эти факты описывают действующую семантику. Отчёт не решает, какие из них
   являются желаемыми, и не создаёт implementation-тикет.

## 3. R-02 — Pressing, urgency и потребители статуса

| Состояние | `status.most_pressing_need` | `get_most_pressing_need()` | `pressing_needs` |
|---|---|---|---|
| Нет pressing | `curiosity` | `None` | `[]` |
| Одна pressing: curiosity=0.1 | `curiosity` | `curiosity` | `[curiosity]` |
| Три pressing: curiosity/autonomy/meaning=0.1 | `curiosity` | `curiosity` | `[curiosity, autonomy, meaning]` |
| Равная urgency: competence=coherence=0 | `competence` | `competence` | `[competence, coherence]` |

При равной urgency=1.0 оба интерфейса выбирают `competence` — первую в порядке
вставки. В состоянии без pressing все urgency равны нулю; статус всё равно
возвращает первую потребность `curiosity`, тогда как метод возвращает `None`.

Точечный поиск Python-источников в `src/`, `tests/` и `tools/` нашёл:

- production-вызов `motivation_system.get_status()` — `src/core/agent.py:1176`,
  агрегация в `get_full_state()`;
- чтение `most_pressing_need` и `pressing_needs` — `src/ui/life_view.py:988,991`,
  строки наблюдаемости `influence_rows()`;
- вызовы `.get_most_pressing_need()` — только в test-only D2; production-вызовов
  в проверенном объёме не найдено.

Это статическая карта известных потребителей, а не доказательство отсутствия
внешних или динамических читателей. Названия и совместимость не менялись.

## 4. R-03 — Explore, собственная цель и внешняя инструкция

Для сопоставимости во всех выполненных сценариях `_act_explore` контрольно
возвращает отсутствие новых свидетельств; реальные `act()`, LoopCloser и
мотивационный обработчик выполняются штатно.

| Сценарий | Эффект | Valence | Δ curiosity | Δ autonomy |
|---|---|---:|---:|---:|
| Explore по собственной цели | нет | −0.2 | −0.060 | −0.060 |
| Explore без собственной цели | нет | −0.2 | −0.060 | −0.060 |
| Внешняя инструкция пользователя | нет | −0.2 | −0.060 | −0.060 |
| Нейтральный no-effect контроль | нет | −0.2 | −0.060 | −0.060 |
| Denied до исполнения | нет; `denied:too_tired` | обработчик не вызван | 0 | 0 |

Происхождение намерения и наличие собственной цели не меняют наблюдаемую
фрустрацию: текущий путь использует тип действия, эффект и валентность, но не
provenance цели. Это наблюдение не доказывает, что autonomy должна или не должна
фрустрировать во всех этих ситуациях.

## 5. R-04 — Состав до top-5, после top-5 и после арбитра

Состав до сортировки получен `sys.settrace` из фактического `locals` работающего
`get_action_candidates()` непосредственно перед `candidates.sort(...)`. Логика
кандидатов не копировалась и production-метод не менялся. Действие не исполнялось.

- До сортировки/top-5: **13 кандидатов** — 6 need-driven и 7 drive-driven.
- После top-5: **5 кандидатов**; отсеяны **8**.
- Активные drives: creativity=0.8625, exploration=0.866667.
- В итоговый список вошли `ask_question` 1.0, `set_own_goal` 0.916667,
  `play` 0.700, `decompose_concept` 0.700 и drive exploration `exploration`
  0.693333.
- Все четыре кандидата creativity остались за пределами top-5: `creative_act`,
  `play`, `draw`, `compose_music`. Также отсеяны вторые кандидаты autonomy/play
  и дополнительные кандидаты exploration.
- Арбитр выбрал `ask_question`; исполнения не было.
- При последующем `generate_goals()` creativity всё же создал цель `draw` с
  priority 0.690, а exploration — цель `explore` с priority 0.693333. Цели также
  созданы для трёх pressing needs.

Таким образом, отсеивание кандидата из top-5 не удаляет активный драйв из
генерации целей. Но сгенерированная цель — отдельное последующее наблюдение, а не
гарантия будущего выбора или исполнения.

## 6. R-05 — Точные floating-point границы

Ожидание `floor((base-threshold)/decay)+1` вычислено до прогона. Ниже записан
первый фактический pressing-тик и точное представление уровня.

| Потребность | Ожидание | Факт | Первый pressing level | `level - threshold` |
|---|---:|---:|---|---:|
| `curiosity` | 23 | 23 | 0.33999999999999964 | −0.010000000000000342 |
| `competence` | 80 | 80 | 0.2999999999999996 | −3.885780586188048e-16 |
| `autonomy` | 117 | 117 | 0.24899999999999967 | −0.001000000000000334 |
| `connection` | 41 | **40** | 0.2999999999999998 | −1.6653345369377348e-16 |
| `play` | 16 | **15** | 0.2499999999999999 | −1.1102230246251565e-16 |
| `meaning` | 50 | 50 | 0.1999999999999999 | −1.1102230246251565e-16 |
| `coherence` | 61 | **60** | 0.2999999999999997 | −2.7755575615628914e-16 |

Во всех семи случаях первый pressing имеет строго `current_level < threshold`;
ложного перехода при равенстве не наблюдалось. Раньше идеальной floor+1 формулы
оказались только `connection`, `play` и `coherence`: накопленное двоичное
представление у них оказалось чуть ниже threshold уже на предыдущем тике.
`competence` и `meaning` тоже пересекают порог в пределах floating-point ошибки,
но их номер тика совпадает с предварительной формулой.

## 7. Проверки

- Наблюдательный скрипт выполнен полностью: 7 связей R-01, 4 состояния R-02,
  5 сценариев R-03, 13→5 кандидатов R-04 и 7 границ R-05.
- `compileall tests/observations/d2r_motivation.py` — успешно.
- `ruff check tests/observations/d2r_motivation.py` — успешно.
- `ruff format --check tests/observations/d2r_motivation.py` — успешно.
- Профильные regression-тесты в `tmp/motivation_d2r_profile/`:
  `tests/test_unified_motivation.py tests/test_unpressured_activity.py` —
  **50 passed за 2.06 с**.

## 8. Итог и ограничения

D2-R завершает пять уточняющих наблюдений и не меняет поведение. Новые факты о
насыщении без world-evidence, нечувствительности explore к provenance и различии
статусных интерфейсов требуют отдельного решения, если владелец захочет ревизию;
автоматических implementation-тикетов не создано.

Основной маршрут продолжается этапом D4 — инвентарём следопыта тем / curiosity.
Ошибка `EthicalDecision` остаётся в отдельной диагностической очереди, здесь она
не воспроизводилась и не анализировалась.
