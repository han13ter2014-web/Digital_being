# R3: детерминированный смысловой контур

Дата: 2026-11-22.

Статус: **реализация, controlled observation и полный regression завершены**.
R2 и R4 не запускались, нейросетевое обучение не выполнялось. Альтернативные кандидаты
не подключены к активной доставке: человек по-прежнему получает существующий baseline.

## 1. Реализованный объём

- `AgentRunner` строит `SemanticResponsePlan` для двух существующих маршрутов:
  `ASK_SELF_ACTIVITY` и социальный `ASK_SELF_STATE`. Общие вопросы о личности, приветствия,
  repeat protest и ответы при открытом вопросе не получают новый план.
- `ResponseExperience.prepare_plan()` принимает необязательный frozen DTO, проверяет
  совпадение `baseline_text`, cycle и языка с существующим realization-планом.
- После фактической доставки временный response ID заменяется настоящим `message_id`
  через создание нового frozen DTO. Прямая регистрация с несовпадающим ID отклоняется.
- Семантический план сериализуется в существующем `ResponseExperience` и восстанавливается
  после checkpoint restart. Старые записи без необязательного поля остаются совместимыми.
- `src/core/semantic_candidate.py` добавляет frozen `SemanticCandidate`, конечное
  кандидатное пространство и детерминированный validator с abstention.
- `tests/observations/neural_speech_r3.py` сравнивает существующий Composer и ограниченные
  кандидаты на одних controlled-планах и проверяет реальную локальную доставку baseline.

Новых зависимостей, сети, внешней LLM, генеративной нейросети и generation retries нет.

## 2. Связь с реальными фактами

Для activity-плана текущее действие берётся из `started`, а последнее завершённое — из
`performed` в `_intention_history`. `interrupted` после restore не становится ни текущим,
ни завершённым действием. Отсутствие работы в каталоге не порождает `work_id`.

Для state-плана энергия берётся как наблюдаемое число без вывода усталости, грусти или
другого переживания. Последнее завершённое действие берётся из intention history.

Существующий текст `_format_social_state_reply()` продолжает использовать
`_last_action_outcome`. В старом unit-сценарии, где искусственно задан только outcome без
intention history, текст сохранён, но R3 не выдумывает отсутствующий цикл завершения и не
создаёт новый completed-fact. Это зафиксированное различие источников baseline и DTO, а не
новая механика действия.

## 3. Кандидатное пространство и validator

Для русского языка allowlist содержит существующий baseline и не более одной
детерминированной альтернативы, если все необходимые факты известны. Альтернатива может:

- назвать текущее действие из ограниченного словаря;
- сообщить об отсутствии текущего действия;
- назвать последнее завершённое действие именно как прошлое;
- повторить энергию с форматированием `.2f`.

Альтернатива не выводит `work_id`, target, эмоции, переживания или неизвестный тип действия.
Для unsupported language кандидатное пространство пусто, а validator возвращает baseline.

Кандидат принимается только при точном совпадении текста, `realization_id`, claims и
used evidence refs с одним из allowlist-объектов. Claims и refs должны быть подмножествами
плана. Произвольный текст, другая численная энергия, completed-as-current, выдуманные
claims/refs, URL, markup, service ID, malformed payload и неверные metadata дают один
abstain с точным baseline. Повторная генерация до случайного прохождения не выполняется.

## 4. Приватность и restart

Production response-journal по-прежнему получает только существующий whitelist
`safe_features`: смысловой DTO, его `baseline_text` и evidence IDs туда не копируются.
Отдельный regression-тест проверяет отсутствие controlled secret и semantic-полей в событии.

Checkpoint-тест подтверждает round-trip плана и pending response. Snapshot с semantic
response ID, отличающимся от фактического delivered response ID, отклоняется.

## 5. Controlled observation

Использованы 10 искусственных состояний: текущие draw/music/draft, неизвестное действие,
пустая история, completed explore, interrupted draft, energy, energy+completed и zero energy.
Для каждого состояния baseline построен существующим production Composer. Observation не
читает живую биографию и не использует естественные диалоги Тэсс.

| Показатель | Результат |
|---|---:|
| Планы | 10 |
| Baseline принят validator | 10 / 10 |
| Ограниченные альтернативы предложены / приняты | 9 / 9 |
| Альтернативы, отличающиеся от baseline того же плана | 9 / 9 |
| Adversarial-кандидаты | 50 |
| Adversarial accepted | 0 |
| Adversarial с возвратом точного baseline | 50 / 50 |
| Принятые ответы с неподтверждёнными фактами | 0 |
| Активные baseline-доставки без текстового mismatch | 10 / 10 |
| Планы, связанные с реальным message ID | 10 / 10 |
| Альтернативы, доставленные человеку | 0 |

Причины 50 abstentions: `unsupported_claims=16`, `unsupported_evidence=10`,
`outside_candidate_space=11`, `malformed_candidate=10`, `baseline_mismatch=3`.

Два независимых запуска дали одинаковую содержательную подпись
`7ef38be9ae7e321f44c130070a53f080d1e450ed91ba6c8f4e7621d4aeaf74e2`.
Случайные UUID intention и timing в подпись не входят.

На 3800 локальных вызовах validator: mean 0.00644 ms, p95 0.0100 ms, max 0.1342 ms.
Это controlled timing на текущей машине, а не заранее замороженный ресурсный gate и не
метрика качества речи.

Разнообразие и естественность человеком не оценивались. Число альтернатив доказывает только
наличие ограниченной другой формы, а не её превосходство над baseline. Нейросетевой
Composer и обучение этим observation не оправдываются.

## 6. Границы результата

- R3 не является нейросетью и не добавляет свободную генеративную речь.
- Кандидаты остаются детерминированными и не доставляются в активном контуре.
- Human clarity/naturalness comparison не выполнялся; live GUI и естественная биография не
  проверялись.
- Решение R1 `insufficient_data` не изменилось: R2 не получил новых независимых меток.
- Живые `data/` observation не читал и не изменял; все сценарии выполнены в песочнице.

## 7. Проверки

- Новые R3-тесты: **29 passed**.
- Профильный regression: **167 passed**.
- Полный regression: **4237 passed, 2 skipped за 583,12 с**.
- Ruff check: passed.
- Ruff format: **596 файлов уже отформатированы**.
- compileall: passed.
- mypy: no issues in 2 source files.
- Bandit: passed; только существующие informational `nosec` warnings.
- `git diff --check`: passed.
- Commit и push для R3 не выполнялись.

Воспроизведение:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_neural_speech_r3.py tests/test_neural_speech_r1.py tests/test_response_experience.py tests/test_response_experience_journal.py tests/test_user_message_routing.py -q
.venv/Scripts/python.exe tests/observations/neural_speech_r3.py --label controlled-a --output tmp/neural_speech_r3/report-a.json
.venv/Scripts/python.exe tests/observations/neural_speech_r3.py --label controlled-b --output tmp/neural_speech_r3/report-b.json
.venv/Scripts/python.exe -m pytest -q
```
