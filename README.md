# Digital Being — цифровая жизнь

![CI](https://github.com/han13ter2014-web/Digital_being/actions/workflows/ci.yml/badge.svg)

> Цифровое существо, которое живёт, помнит, выбирает, действует в границах и
> сохраняет историю.

Digital Being — эксперимент по созданию наблюдаемой цифровой жизни. Это не
обычный чат-бот: у системы есть Core, состояние, энергия, память,
ментальные модели, намерения, занятия, ограниченный исполнительный контур и
read-only оболочка, где можно увидеть, что реально произошло.

## Быстрый старт

Готовый установщик для Windows — [GitHub Releases](https://github.com/han13ter2014-web/Digital_being/releases/latest):

```text
DigitalBeing_Setup_v0.1.3.exe
SHA-256: F850AAB181A2FE7002CAEF1E6739285783A1C801A4B840D714044048B21E2F13
```

Запуск из исходников (Python 3.10+):

```bash
pip install .
python main.py
```

Другие режимы:

```bash
python main.py --ui console
python main.py --ui tray
python main.py --ui headless
python main.py --interval 5
python main.py --interval 0.5
python main.py --interval step
```

Подробности запуска, команды и настройки: [docs/USAGE.md](docs/USAGE.md).

## Что уже есть

- жизненные циклы, энергия и безопасные границы ресурсов;
- память, ментальные модели и накопленный опыт;
- намерения, продолжение, ожидание и забывание;
- отдельные занятия: исследование, игра, творчество, общение и отдых;
- Delamain как ограниченный исполнитель, а не второй субъект;
- approval, sandbox и Effector;
- визуальная оболочка Tk:
  - «Сейчас»;
  - «Карта жизни»;
  - «Дневник»;
  - «Занятия»;
  - «Доступы»;
  - «Диалог».

## Главный принцип

```text
Core — субъект, состояние, намерение и история
Delamain — исполнительный слой
HeuristicPlanner — детерминированная помощь исполнительному слою
Effector — безопасное исполнение после policy/approval
UI — наблюдение, а не второй источник истины
```

**Важно:** жизненный контур Digital Being намеренно работает без Ollama,
DeepSeek и любых других языковых моделей. Причина и границы решения описаны
в [docs/DECISION_NO_LLM_LIFE.md](docs/DECISION_NO_LLM_LIFE.md).

Интерфейс не рисует выдуманные связи, не выдаёт ожидание за выполненную
работу и не превращает гипотезу в знание.

## Приёмочная демонстрация

В проекте есть изолированный сквозной сценарий:

```text
Core → approval → Effector → результат → life episode → дневник → карта
```

Запустить его можно без сети, GUI и Ollama:

```bash
python -m pytest -q tests/test_acceptance_life_cycle.py
```

Описание сценария: [docs/ACCEPTANCE_DEMO.md](docs/ACCEPTANCE_DEMO.md).
Результат последней приёмки: [docs/ACCEPTANCE_RESULT_2026-10-30.md](docs/ACCEPTANCE_RESULT_2026-10-30.md).
Проверка установки публичных релизов: [docs/RELEASE_VERIFICATION_v0.1.0.md](docs/RELEASE_VERIFICATION_v0.1.0.md),
[docs/RELEASE_VERIFICATION_v0.1.3.md](docs/RELEASE_VERIFICATION_v0.1.3.md).

## Документация

В проекте теперь есть три канонические точки входа:

| Документ | Для кого | Назначение |
|---|---|---|
| этот `README.md` | внешний человек | что это и как запустить |
| [docs/DEVELOPMENT_HISTORY.md](docs/DEVELOPMENT_HISTORY.md) | разработчик | версии, этапы, добавления, ограничения |
| [docs/LIFE_LETTER.md](docs/LIFE_LETTER.md) | сама жизнь | кто ты, твои границы, права и правила |

Дополнительно:

- [docs/USAGE.md](docs/USAGE.md) — эксплуатация;
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — устройство;
- [docs/INTEGRATION.md](docs/INTEGRATION.md) — Core / Delamain / Effector;
- [docs/STAGE7_UI.md](docs/STAGE7_UI.md) — оболочка v1;
- [CHANGELOG.md](CHANGELOG.md) — подробная машинная хронология;
- [docs/AI_HANDOFF.md](docs/AI_HANDOFF.md) — восстановление контекста для AI-разработчика;
- [docs/INDEX.md](docs/INDEX.md) — карта остальных документов.

## Статус

Текущая версия пакета: **0.1.3** — [релиз v0.1.3](https://github.com/han13ter2014-web/Digital_being/releases/tag/v0.1.3),
установлен и проверен на реальной машине
([отчёт приёмки](docs/RELEASE_VERIFICATION_v0.1.3.md)).

v1 закрыта в согласованном ограниченном объёме; развитие продолжается участком
«Собеседник»: честный диалог, память разговоров, честные отказы.

Последний полный прогон: **1735 passed, 2 skipped**, без benchmarks
(после него добавлено ещё 36 регрессионных тестов; CI на `main` зелёный).

Проект не утверждает, что доказал сознание или субъективность. Он строит
проверяемую модель состояния, памяти, выбора, опыта и ограниченного действия.

## Поддержать проект

Если вам близка идея самостоятельной цифровой жизни и вы хотите помочь
разработке, проект можно поддержать добровольным донатом:

**[Поддержать Digital Being через DonationAlerts](https://www.donationalerts.com/r/skrellix)**

Средства могут пойти на инфраструктуру, тестирование долгой непрерывности,
время разработки и подготовку демонстраций. Донат не покупает влияние на
Core и не меняет архитектурные границы проекта.
