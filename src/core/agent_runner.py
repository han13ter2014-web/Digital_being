"""
AgentRunner — оркестратор жизни агента в трей-режиме.

Связывает между собой:
- DigitalBeing (существующий, без изменений в основной логике)
- EventBus (асинхронная шина событий)
- EnergyPolicy (новая политика «энергия управляет темпом»)
- Watchdog (защита ресурсов)

Цикл работы:
    1. Таймер тикает каждые TRAY_TICK_INTERVAL_SEC (или реже, если устал)
    2. Генерируется стимул
    3. agent.perceive → agent.think → agent.act → agent.evolve
    4. Результаты публикуются в EventBus (мысли, действия, эволюция)
    5. Энергия пересчитывается через EnergyPolicy
    6. Цикл «отдыха» восстанавливает энергию

Главное отличие от main.py:
- Не блокирует UI (нет input())
- Реагирует на события шины (user_message, pause, save, shutdown)
- Не «умирает» от энергии — только замедляется
- Может работать без присмотра неделями

Запуск:
    bus = EventBus()
    agent = DigitalBeing("Alpha")
    runner = AgentRunner(agent, bus)
    await runner.start()        # запускает фоновый цикл
    await bus.run()             # крутит шину (вместе с tray/chat)

    # Позже:
    await runner.stop()         # graceful shutdown
"""

import asyncio
import logging
import os
import time
from typing import Any, Dict, List, Optional

from config.simulation_config import LR_CONFIG
from src.core.event_bus import EventBus, Events
from src.core.energy_policy import EnergyPolicy
from src.core.stimulus_selector import (
    TRAIL_GOAL_PRIORITY_PROB,
    is_open_question_stimulus,
    select_novel_stimulus,
)
from src.core.watchdog import get_watchdog, Watchdog
from src.core.buffered_logger import flush_logs
from src.core.paths import data_path
from src.core.agent import AgentDeadSignal
from src.core.dialogue_acts import (
    ACT_ASK_ABOUT_SELF,
    ACT_SOCIAL,
    classify_user_text,
    extract_definition,
)


logger = logging.getLogger(__name__)


# «Собеседник-5»: подмножество социальных маркеров, которое означает
# протест на ПОВТОР вопроса. Только при открытом pending-вопросе: без
# него «уже отвечал» — обычная социальная реплика, а не команда mute.
# «я же» сознательно не входит: «я же рядом» — присутствие, не протест.
_REPEAT_PROTEST_MARKERS = (
    "уже отвечал",
    "уже отвечала",
    "уже говорил",
    "уже говорила",
    "повторяешь",
    "снова спрашиваешь",
    "тот же вопрос",
    "зачем снова",
)


# ============================================================
# Загрузка/сохранение состояния (вынесено из main.py для переиспользования)
# ============================================================

def get_latest_checkpoint(agent_name: str) -> Optional[str]:
    """Найти путь к последнему чекпоинту агента. None если нет."""
    checkpoint_dir = data_path('checkpoints')
    if not os.path.exists(checkpoint_dir):
        return None
    checkpoints = [f for f in os.listdir(checkpoint_dir)
                   if f.startswith(f"{agent_name}_cycle_")]
    if not checkpoints:
        return None
    checkpoints.sort(key=lambda x: int(x.split('_')[-1].split('.')[0]))
    return os.path.join(checkpoint_dir, checkpoints[-1])


def load_agent_from_checkpoint(agent, checkpoint_path: Optional[str]) -> bool:
    """Загрузить состояние агента из чекпоинта. Возвращает True если успешно."""
    if not checkpoint_path:
        return False
    if not os.path.exists(checkpoint_path):
        logger.warning(f"Чекпоинт не найден: {checkpoint_path}")
        return False
    try:
        agent.load_state(checkpoint_path)
        logger.info(f"[{agent.name}] Состояние восстановлено из {os.path.basename(checkpoint_path)}")
        return True
    except Exception as e:
        logger.exception(f"Ошибка загрузки чекпоинта {checkpoint_path}: {e}")
        return False


# ============================================================
# Генерация стимулов — делегирует в src.core.stimulus_selector.
# Сохранена обёртка ``generate_prioritized_stimulus`` для
# обратной совместимости (использует p=0.7 для трей-режима).
# ============================================================

def generate_prioritized_stimulus(agent) -> str:
    """Обратная совместимость: старая обёртка над ``stimulus_selector``.

    Использует ``TRAIL_GOAL_PRIORITY_PROB = 0.7`` (жёсткая приоритезация
    для трей-режима).
    """
    from src.core.stimulus_selector import (
        generate_prioritized_stimulus as _impl,
    )
    return _impl(agent)


# ============================================================
# AgentRunner
# ============================================================

class PersistentMessageQueue(asyncio.Queue):
    """Зеркало ожидающих сообщений для согласованного checkpoint раннера."""

    def __init__(self, agent):
        super().__init__()
        self.agent = agent
        for text in getattr(agent, "_pending_message_texts", []) or []:
            super().put_nowait(text)
        self._sync()

    def _sync(self):
        self.agent._pending_message_texts = list(self._queue)

    def put_nowait(self, item):
        super().put_nowait(item)
        self._sync()

    def get_nowait(self):
        item = super().get_nowait()
        self._sync()
        return item


class AgentRunner:
    """Фоновый оркестратор жизни агента.

    Не является частью DigitalBeing — это «обёртка», которая живёт
    в asyncio-цикле и делегирует агенту конкретную работу.
    """

    def __init__(
        self,
        agent,
        bus: EventBus,
        watchdog: Optional[Watchdog] = None,
        name: str = "AgentRunner",
    ):
        """
        Args:
            agent: экземпляр DigitalBeing.
            bus: EventBus, через который публикуются события.
            watchdog: Watchdog (опционально). Если None — создаётся глобальный.
            name: имя для логов.
        """
        self.agent = agent
        self.bus = bus
        self.watchdog = watchdog or get_watchdog()
        self.name = name

        # Состояние
        self._running = False
        self._paused = False
        self._stop_requested = False
        self._tick_count = 0
        self._last_auto_save_ts = time.time()
        self._stimulus_mode = "quiet"
        self._last_user_message_at = 0  # время последнего сообщения пользователя

        # Дедупликация стимулов: не повторять один и тот же вопрос
        # чаще, чем раз в STIMULUS_COOLDOWN_TICKS тиков (см. docs/BASELINE.md).
        self._recent_stimuli: dict = {}
        # Одна и та же автономная мысль подряд — шум, а не событие.
        self._recent_thoughts: Dict[str, int] = {}
        self._loop_tick = 0
        self._idle_ticks = 0

        # === Скорость жизни (этап C) ===
        # Интервал между циклами — параметр рантайма. Раньше он был
        # захардкожен как ``max(5.0, energy_interval, 1.0)``, поэтому
        # трей физически не мог работать быстрее одного цикла в 5 секунд,
        # а консольный main.py успевал тысячи циклов в секунду.
        self._speed_intervals: Dict[str, float] = dict(
            getattr(LR_CONFIG, "RUNNER_SPEED_INTERVALS", None)
            or {"live": 5.0, "fast": 0.5, "max": 0.0}
        )
        self._speed_mode: str = str(
            getattr(LR_CONFIG, "RUNNER_DEFAULT_SPEED", "live")
        )
        if self._speed_mode not in self._speed_intervals:
            self._speed_mode = "live"
        # Сколько циклов прошло в режиме «лаборатория». Такие циклы
        # помечаются отдельно: ускорение не должно выдавать себя за жизнь.
        self._accelerated_cycles = 0

        # Энергетическая политика
        self.energy_policy = EnergyPolicy(
            get_energy=lambda: agent.energy,
            max_energy=LR_CONFIG.ENERGY_MAX,
        )
        # Привязываем setter — пишем в energy_subsystem
        self.energy_policy.attach_setter(lambda v: setattr(agent, "energy", v))

        # Подписки на события шины
        self._setup_subscriptions()

        logger.info(
            f"[{self.name}] AgentRunner создан для {agent.name}. "
            f"Энергия={agent.energy:.0f}, max={LR_CONFIG.ENERGY_MAX}"
        )

    # ============================================================
    # Подписки
    # ============================================================

    def _setup_subscriptions(self) -> None:
        """Подписаться на события, на которые Runner должен реагировать."""
        self.bus.subscribe(Events.USER_MESSAGE, self._on_user_message)
        self.bus.subscribe(Events.USER_COMMAND, self._on_user_command)
        self.bus.subscribe(Events.PAUSE_REQUESTED, self._on_pause)
        self.bus.subscribe(Events.RESUME_REQUESTED, self._on_resume)
        self.bus.subscribe(Events.SHUTDOWN_REQUESTED, self._on_shutdown)
        self.bus.subscribe(Events.SAVE_REQUESTED, self._on_save)
        # Скорость жизни: окно публикует событие, раннер меняет темп.
        self.bus.subscribe(Events.SPEED_CHANGED, self._on_speed_changed)
        self.bus.subscribe(Events.STEP_REQUESTED, self._on_step)

    async def _on_user_message(self, event) -> None:
        """Пользователь отправил сообщение. Обрабатываем его в следующем тике.

        Очередь сообщений создаётся лениво при первом вызове, чтобы
        не терять сообщения, пришедшие ДО ``start()``. Раньше в этом
        случае сообщение молча отбрасывалось с warning-логом (UX-баг:
        пользователь мог отправить сообщение в окно чата ещё до того,
        как AgentRunner стартовал, и оно исчезало бесследно).
        """
        self._last_user_message_at = time.time()
        text = (event.data or {}).get("text", "")
        if not text:
            return
        logger.info(f"[{self.name}] USER_MESSAGE: {text[:60]}")

        # Имя — отдельный Core-owned диалог, а не обычная тема для обучения.
        # После приветствия NamingDialogue ждёт естественный ответ пользователя
        # без требования команды /name. Это должно происходить до помещения
        # текста в очередь стимулов, иначе «Малютка» станет концептом, а имя
        # агента останется прежним.
        naming = getattr(self.agent, "naming_dialogue", None)
        if naming is not None and await self._handle_naming_phase(naming, text):
            return

        interaction = getattr(self.agent, "user_interaction", None)
        pending = interaction.get_pending_question() if interaction is not None else None

        # === «Собеседник-1/5»: акт распознаётся один раз до дверей ===
        # Живой прогон 2026-11-01: «Я же уже отвечал тебе» уходило в
        # «Ответ записан» или в изучение концептов («Не нашел файл для…»).
        # Настоящие ответы (ACT_ANSWER/ACT_UNKNOWN) идут прежним путём
        # без изменений — безопасный fallback сохранён.
        act = classify_user_text(text)

        # Вопрос о самой сущности — честный ответ из read-only Core.
        if act.kind == ACT_ASK_ABOUT_SELF:
            if interaction is not None:
                interaction.receive_user_message(text, cycle=self.agent.cycle_count)
            user_model = getattr(self.agent, "user_model", None)
            if user_model is not None:
                user_model.observe(text, cycle=self.agent.cycle_count)
            response = self._format_about_self_reply()
            if response:
                await self.bus.publish(
                    Events.AGENT_THOUGHT,
                    {"text": response, "cycle": self.agent.cycle_count},
                    source="dialogue_acts",
                    priority=1,
                )
            return

        # Социальная речь — не ответ и не учебный материал.
        if act.kind == ACT_SOCIAL:
            if interaction is not None:
                interaction.receive_user_message(text, cycle=self.agent.cycle_count)
            user_model = getattr(self.agent, "user_model", None)
            if user_model is not None:
                user_model.observe(text, cycle=self.agent.cycle_count)
            if (
                pending is not None
                and act.matched_marker in _REPEAT_PROTEST_MARKERS
            ):
                response = self._handle_repeat_protest(pending, interaction)
            else:
                response = self._format_social_reply(pending)
            if response:
                await self.bus.publish(
                    Events.AGENT_THOUGHT,
                    {"text": response, "cycle": self.agent.cycle_count},
                    source="dialogue_acts",
                    priority=1,
                )
            return

        # Если Core задал пользователю прямой вопрос, обычный ответ должен
        # закрыть именно его, а не стать новой темой обучения.
        if pending is not None:
            # Синтез сложного вопроса: когда все под-вопросы отвечены,
            # submit_answer вызывает колбэк. Живой путь раньше шёл без
            # него — синтез существовал только во внутреннем контуре.
            synthesizer = getattr(self.agent, "synthesize_complex_question", None)
            result = interaction.submit_answer(
                pending["id"], text,
                on_synthesis_needed=(
                    synthesizer if callable(synthesizer) else None
                ),
                cycle=self.agent.cycle_count,
            )
            if isinstance(result, dict):
                normalized_answer = " ".join(text.lower().strip().split())
                unknown = normalized_answer.rstrip(".!?") in {
                    "не знаю", "не уверен", "не уверена", "не могу сказать",
                    "без понятия", "затрудняюсь ответить", "не знаю ответа",
                }
                if unknown:
                    result["answer_kind"] = "unknown"
            topic = AgentRunner._topic_from_pending(pending)
            answered = (
                isinstance(result, dict)
                and result.get("status") in {"answered", "next_question"}
            )
            if (
                answered
                and result.get("answer_kind") != "unknown"
                and topic
            ):
                recorder = getattr(self.agent, "record_user_answer", None)
                if callable(recorder):
                    recorder(topic, text, self.agent.cycle_count)
            response = self._format_user_answer_result(
                result, topic=topic, answer_text=text
            )
            if response:
                await self.bus.publish(
                    Events.AGENT_THOUGHT,
                    {"text": response, "cycle": self.agent.cycle_count},
                    source="user_interaction",
                    priority=1,
                )
            return

        # Если Core задал пользователю открытый вопрос, обычный ответ должен
        # закрыть этот вопрос, а не стать новой темой обучения.
        answerer = getattr(self.agent, "answer_open_question", None)
        if callable(answerer) and self.agent.has_open_questions():
            result = answerer(text)
            if result.get("status") == "answered":
                response = f"Ответ записан к вопросу «{result['question']}»."
                await self.bus.publish(
                    Events.AGENT_THOUGHT,
                    {"text": response, "cycle": self.agent.cycle_count},
                    source="open_question",
                    priority=1,
                )
                return

        # === «Собеседник-5»: «X — это Y» — свидетельство без вопроса ===
        # Человек объясняет тему по своей инициативе; раньше такое уходило
        # в очередь стимулов и изучалось как «файл». Записываем как
        # знание-свидетельство (record_user_answer) со штампом «не
        # переспрашивать». Не записалось — текст идёт старым путём.
        definition = extract_definition(text)
        if definition is not None:
            topic, body = definition
            recorder = getattr(self.agent, "record_user_answer", None)
            saved = (
                recorder(topic, f"{topic} — это {body}", self.agent.cycle_count)
                if callable(recorder)
                else None
            )
            if saved:
                response = (
                    f"Записал: «{saved} — это {body}». "
                    "Теперь я знаю это от тебя — переспрашивать не буду."
                )
                await self.bus.publish(
                    Events.AGENT_THOUGHT,
                    {"text": response, "cycle": self.agent.cycle_count},
                    source="dialogue_acts",
                    priority=1,
                )
                return

        # Ленивое создание очереди — сообщения, пришедшие до start(),
        # не теряются, а дожидаются первого тика.
        if not hasattr(self, "_pending_user_messages") or self._pending_user_messages is None:
            self._pending_user_messages = PersistentMessageQueue(self.agent)
            logger.debug(
                f"[{self.name}] Очередь user-сообщений создана лениво "
                f"(до start()) — сообщение будет обработано."
            )
        await self._pending_user_messages.put(text)

    async def _publish_naming_result(self, result: Dict[str, Any],
                                     proposed: str) -> None:
        """Опубликовать ответ диалога об имени; при смене имени — событие Core."""
        if result.get("status") in {"accepted", "alternative_accepted"}:
            self._publish_name_changed(result)
        response = self._format_name_result(result, proposed)
        if response:
            await self.bus.publish(
                Events.AGENT_THOUGHT,
                {"text": response, "cycle": self.agent.cycle_count},
                source="naming_dialogue",
                priority=1,
            )

    async def _handle_naming_phase(self, naming, text: str) -> bool:
        """Пропустить текст через NamingDialogue по фазе.

        Возвращает True, если сообщение полностью обработано именем.
        В фазе ``completed`` перехватываем только реальные предложения
        имени (осознанное переименование): остальная речь — и ответы
        «да/нет/хорошо» без активного диалога — идёт обычными дверями.
        """
        from src.core.name_proposal import extract_name_proposal
        from src.core.subsystems.naming_dialogue import classify_confirmation

        phase = getattr(naming, "phase", None)
        cycle = self.agent.cycle_count

        if phase == "completed":
            if classify_confirmation(text) != "unknown":
                return False
            proposed = extract_name_proposal(text)
            if proposed is None:
                return False
            result = self.agent.propose_name(proposed, cycle=cycle)
            await self._publish_naming_result(result, proposed)
            return True

        if phase not in {"awaiting_name", "considering", "renaming_pending"}:
            return False

        if phase == "renaming_pending":
            decision = classify_confirmation(text)
            if decision == "affirmative":
                result = naming.confirm_rename(agent=self.agent, cycle=cycle)
                await self._publish_naming_result(result, text)
                return True
            if decision == "negative":
                result = naming.cancel_rename(agent=self.agent, cycle=cycle)
                await self._publish_naming_result(result, text)
                return True
            proposed = extract_name_proposal(text)
            if proposed is not None:
                result = self.agent.propose_name(proposed, cycle=cycle)
                await self._publish_naming_result(result, proposed)
                return True
            # Пользователь ушёл в другую тему — тихо отменяем переспрос
            # и обрабатываем сообщение обычными дверями.
            naming.cancel_rename(agent=self.agent, cycle=cycle, notify=False)
            return False

        if phase == "considering":
            decision = classify_confirmation(text)
            if decision == "affirmative":
                result = naming.accept_alternative(agent=self.agent, cycle=cycle)
                await self._publish_naming_result(result, text)
                return True
            if decision == "negative":
                result = naming.decline_alternative(agent=self.agent, cycle=cycle)
                await self._publish_naming_result(result, text)
                return True

        proposed = extract_name_proposal(text)
        if proposed is not None:
            result = self.agent.propose_name(proposed, cycle=cycle)
            await self._publish_naming_result(result, proposed)
            return True

        if phase == "considering":
            alt = getattr(naming, "_alternative_name", "") or "другое имя"
            hint = (
                f"Я предложил(а) «{alt}». Скажи «да» или «нет» — "
                "или напиши другое имя отдельно."
            )
        else:
            hint = (
                "Если ты предлагаешь имя, напиши его отдельно или так: "
                "«Пусть тебя зовут Омелла». "
                "Остальную речь я пока не умею разбирать свободно."
            )
        await self.bus.publish(
            Events.AGENT_THOUGHT,
            {"text": hint, "cycle": cycle},
            source="naming_dialogue", priority=1,
        )
        return True

    def _publish_name_changed(self, result: Dict[str, Any]) -> None:
        """Уведомить UI и наблюдателей о принятом имени Core."""
        self.name = str(result.get("new_name") or self.agent.name)
        self.bus.publish_sync(
            "agent_name_changed",
            {
                "old_name": result.get("old_name"),
                "new_name": result.get("new_name"),
                "cycle": self.agent.cycle_count,
            },
            source="naming_dialogue",
            priority=1,
        )

    @staticmethod
    def _topic_from_pending(pending) -> Optional[str]:
        """Тема прямого вопроса сущности из контекста ``_act_ask_user``.

        Контекст имеет вид «самостоятельный вопрос по теме: {target}».
        Без узнанного префикса возвращает None — не привязываем ответ
        к случайной строке.
        """
        if not pending:
            return None
        context = str(pending.get("context") or "")
        prefix = "самостоятельный вопрос по теме: "
        if context.startswith(prefix):
            topic = context[len(prefix):].strip()
            return topic or None
        return None

    @staticmethod
    def _format_social_reply(pending) -> str:
        """Честный отклик на социальный акт без выдуманного понимания.

        Если у Core открыт прямой вопрос — сущность говорит, что вопрос
        остаётся открытым; тема берётся из контекста, который кладёт
        ``_act_ask_user``. Без темы — нейтральный отклик.
        """
        topic = AgentRunner._topic_from_pending(pending)
        if topic:
            return (
                "Я слышу тебя. "
                f"Вопрос про «{topic}» остаётся открытым — "
                "ответишь, когда захочешь."
            )
        return "Я слышу тебя. Спасибо, что ты рядом."

    def _handle_repeat_protest(self, pending, interaction) -> str:
        """«Уже отвечал» — вопрос снимается, тема замолкает.

        «Собеседник-5»: повторять вопрос после протеста человека — то,
        что живой прогон показал на сущности Тэсс. Вопрос закрывается
        как отклонённый (не как ответ: в историю ответов не попадает),
        а тема получает mute-штамп — сам к ней сущность не вернётся.
        """
        topic = AgentRunner._topic_from_pending(pending)
        # Mute ДО decline: штамп подтверждается тем, что вопрос ещё
        # висит в ожидании; после decline подтверждения уже нет.
        muted = None
        mute = getattr(self.agent, "mute_topic", None)
        if callable(mute) and topic:
            muted = mute(topic, self.agent.cycle_count)
        interaction.decline_question(
            pending["id"], cycle=self.agent.cycle_count
        )
        if muted:
            return (
                f"Ты прав — я спрашивал об этом, вопрос снимаю. "
                f"К теме «{muted}» сам больше не вернусь."
            )
        return "Ты прав — вопрос снимаю и сам к нему больше не вернусь."

    def _format_about_self_reply(self) -> str:
        """Честный рассказ о себе из read-only Core — без выдумки.

        «Собеседник-5»: на «чем занимаешься?» сущность отвечает только
        тем, что действительно есть в её состоянии: имя, возраст в
        циклах, последняя тема исследования, объём опыта, что она помнит
        о человеке. Ничего из этого не придумывается и не улучшается.
        """
        agent = self.agent
        concepts = getattr(
            getattr(agent, "mental_models", None), "concepts", None
        )
        known = 0
        if isinstance(concepts, dict):
            known = sum(1 for name in concepts if agent._is_learnable(name))
        history = getattr(agent, "_exploration_history", None)
        occupation = ""
        if isinstance(history, list) and history:
            last = str(history[-1] or "").strip()
            if last and agent._is_learnable(last):
                occupation = last
        if occupation:
            parts = [
                f"Меня зовут {agent.name}. Я живу уже {agent.cycle_count} "
                f"циклов, сейчас разбираюсь с темой «{occupation}»."
            ]
        else:
            parts = [
                f"Меня зовут {agent.name}. Я живу уже {agent.cycle_count} "
                "циклов и изучаю мир вокруг — по чуть-чуть за цикл."
            ]
        if known:
            parts.append(
                f"О {known} темах у меня уже есть хоть какой-то "
                "собственный опыт."
            )
        user_model = getattr(agent, "user_model", None)
        if user_model is not None:
            promise = user_model.silence_promise()
            if promise:
                parts.append(
                    "И я помню: ты говорил, что можешь отлучаться — "
                    "не тревожу."
                )
            traits = getattr(user_model, "traits", None)
            if isinstance(traits, dict) and traits:
                first_trait = next(iter(traits.values()))
                parts.append(
                    "Про тебя я записал: "
                    f"«{self._short_quote(first_trait, 100)}»."
                )
        return " ".join(parts)

    @staticmethod
    def _short_quote(text: str, limit: int = 80) -> str:
        """Цитата из ответа пользователя не длиннее ``limit`` символов."""
        quote = " ".join(str(text or "").split())
        if len(quote) <= limit:
            return quote
        return quote[: limit - 1].rstrip() + "…"

    @staticmethod
    def _format_user_answer_result(
        result: Dict[str, Any],
        topic: Optional[str] = None,
        answer_text: Optional[str] = None,
    ) -> str:
        """Коротко подтвердить прямой ответ на вопрос Core.

        Если ответ стал знанием-свидетельством (тема известна), сущность
        цитирует, что именно она записала: подтверждение должно быть
        проверяемым для пользователя, а не безликим «Ответ записан».
        """
        status = result.get("status")
        if status == "answered":
            if result.get("answer_kind") == "unknown":
                return "Понял: «не знаю» — я запомню это как твой ответ, а не как факт."
            if topic and answer_text:
                quote = AgentRunner._short_quote(answer_text)
                if quote:
                    return (
                        f"Записал про «{topic}»: «{quote}» — "
                        "буду проверять на своём опыте."
                    )
            if result.get("synthesis_needed"):
                return (
                    "Ответ записан. Части сложены в целое — "
                    f"я свёл воедино «{result.get('complex_question', '')}»."
                )
            if result.get("next_sub_question"):
                return "Ответ записан. Есть ещё один уточняющий вопрос."
            return "Ответ записан."
        if status == "next_question":
            return "Ответ записан. Есть ещё один уточняющий вопрос."
        return "Ответ получен."

    @staticmethod
    def _format_name_result(result: Dict[str, Any], proposed: str) -> str:
        """Сформировать ответ naming dialogue без генеративной модели."""
        status = result.get("status", "ok")
        if status == "accepted":
            return f"✨ Принято! Теперь меня зовут «{result.get('new_name', proposed)}»."
        if status == "rejected":
            return f"🤔 Не подошло: {result.get('reason', 'неизвестная причина')}."
        if status == "alternative_proposed":
            alternative = result.get("agent_alternative") or result.get("alternative") or "другое имя"
            return f"💭 Я бы предпочёл(ла) другое имя: «{alternative}». Согласен?"
        if status == "alternative_accepted":
            return f"✨ Согласен! Теперь меня зовут «{result.get('new_name', proposed)}»."
        if status == "rename_confirmation":
            return (
                f"💭 Сейчас я «{result.get('current_name', '')}». "
                f"Хочешь переименовать меня в «{result.get('candidate', proposed)}»? "
                "Скажи «да» или «нет»."
            )
        if status == "rename_declined":
            return (
                f"🧭 Я остаюсь «{result.get('kept_name', '')}». "
                f"«{result.get('candidate', '')}» — в другой раз."
            )
        if status == "rename_cancelled":
            return f"🧭 Хорошо, остаюсь «{result.get('kept_name', '')}»."
        if status == "no_rename_pending":
            return "ℹ️ Сейчас нет ожидающего переименования."
        if status == "no_alternative_pending":
            return "ℹ️ Сейчас нет ожидающего альтернативного имени."
        if status == "no_naming_dialogue":
            return "⚠️ Диалог об имени сейчас недоступен."
        if status == "no_op":
            return f"ℹ️ Сейчас не время для смены имени: {result.get('reason', '')}".strip()
        return f"ℹ️ Результат диалога об имени: {result}"

    async def _on_user_command(self, event) -> None:
        """Команда из чата. Выполняется синхронно, ответ публикуется в чат."""
        cmd = (event.data or {}).get("command", "")
        if not cmd:
            return
        logger.info(f"[{self.name}] USER_COMMAND: /{cmd}")
        response = await self.handle_command("/" + cmd)
        if response:
            # Публикуем ответ как сообщение от агента (для отображения в чате)
            await self.bus.publish(
                Events.AGENT_THOUGHT,
                {"text": response, "cycle": self.agent.cycle_count},
                source="runner",
                priority=1,
            )

    async def _on_user_opened_chat(self, event) -> None:
        """Пользователь открыл чат из трея. Публикуем краткий статус."""
        logger.info(f"[{self.name}] USER_OPENED_CHAT")
        status = self._format_status()
        await self.bus.publish(
            Events.AGENT_THOUGHT,
            {"text": f"👋 Привет! Вот мой статус:\n\n{status}",
             "cycle": self.agent.cycle_count},
            source="runner",
            priority=1,
        )

    async def _on_pause(self, event) -> None:
        logger.info(f"[{self.name}] PAUSE_REQUESTED")
        self._paused = True

    async def _on_resume(self, event) -> None:
        logger.info(f"[{self.name}] RESUME_REQUESTED")
        self._paused = False

    async def _on_shutdown(self, event) -> None:
        logger.info(f"[{self.name}] SHUTDOWN_REQUESTED")
        self._stop_requested = True
        # Не делаем save_state здесь — это делает main_tray.py при graceful shutdown
        # (чтобы не дублировать). Но flush_logs — обязательно.
        flush_logs()

    async def _on_save(self, event) -> None:
        logger.info(f"[{self.name}] SAVE_REQUESTED")
        self._save_state_safe()

    async def _on_speed_changed(self, event) -> None:
        """Окно попросило сменить темп жизни."""
        mode = str((event.data or {}).get("mode", "")).strip()
        try:
            status = self.set_speed(mode)
        except ValueError as exc:
            logger.warning(f"[{self.name}] SPEED_CHANGED отклонён: {exc}")
            return
        logger.info(
            f"[{self.name}] Скорость: {status['mode']} "
            f"({status['interval_sec']}с между циклами)"
        )

    async def _on_step(self, event) -> None:
        """Окно попросило ровно один цикл жизни."""
        if await self.step_once():
            logger.info(f"[{self.name}] Шаг выполнен вручную")

    # ============================================================
    # Скорость жизни (этап C)
    # ============================================================

    def available_speeds(self) -> List[str]:
        """Режимы, доступные человеку. ``step`` — отдельный, не интервал."""
        return sorted(self._speed_intervals) + ["step"]

    def set_speed(self, mode: str) -> Dict:
        """Переключает темп жизни на лету.

        Args:
            mode: ``live`` / ``fast`` / ``max`` / ``step``.

        Raises:
            ValueError: неизвестный режим. Не угадываем: опечатка в
                названии не должна молча менять поведение.
        """
        mode = str(mode).strip().lower()
        if mode != "step" and mode not in self._speed_intervals:
            raise ValueError(
                f"неизвестный режим скорости: {mode!r}; "
                f"допустимо: {self.available_speeds()}"
            )
        self._speed_mode = mode
        self._apply_speed_side_effects()
        return self.get_speed_status()

    def _apply_speed_side_effects(self) -> None:
        """Побочные настройки, зависящие от темпа.

        В режиме ``max`` выключаем внешний web-поиск: он синхронный, с
        ``time.sleep`` для rate-limit и SSL-рукопожатиями. В ускоренном
        цикле это блокирует event loop и превращает «лабораторию» в
        ожидание сети вместо тысяч циклов. В ``live``/``fast`` поиск
        нужен — это часть жизни, а не только вычисление.
        """
        searcher = getattr(self.agent, "web_searcher", None)
        if searcher is None:
            return
        try:
            if self._speed_mode == "max":
                searcher.toggle(False)
            else:
                searcher.toggle(True)
        except Exception as exc:  # WebSearcher — необязательная подсистема
            logger.debug(f"[{self.name}] web search toggle: {exc}")

    def base_interval_sec(self) -> float:
        """Интервал, выбранный человеком (без влияния энергии)."""
        if self._speed_mode == "step":
            return 0.0
        return float(self._speed_intervals.get(self._speed_mode, 5.0))

    def current_interval_sec(self) -> float:
        """Фактический интервал с учётом энергии и этичного throttle.

        Правило: в ``fast``/``max`` явный выбор человека важнее усталости.
        Иначе «ускорение» ничего не ускоряло бы: энергетическая политика
        возвращала бы 5–120 секунд.
        """
        base = self.base_interval_sec()

        if self._speed_mode in ("max", "step"):
            return 0.0

        if self._speed_mode == "fast":
            interval = base
        else:  # live
            energy_interval = float(
                self.energy_policy.current_tick_interval_sec()
            )
            interval = max(base, energy_interval, 1.0)

        ethical_throttle = float(
            getattr(LR_CONFIG, "MIN_CYCLE_INTERVAL_SEC", 0.0) or 0.0
        )
        return max(interval, ethical_throttle)

    def get_speed_status(self) -> Dict:
        """Состояние темпа для окна и логов."""
        return {
            "mode": self._speed_mode,
            "interval_sec": self.base_interval_sec(),
            "effective_interval_sec": self.current_interval_sec(),
            "paused": self._paused,
            "accelerated_cycles": self._accelerated_cycles,
            "available_modes": self.available_speeds(),
        }

    async def step_once(self) -> bool:
        """Выполняет ровно один цикл жизни по требованию.

        Работает и на паузе: это осознанный шаг, а не поток циклов.
        Возвращает False, если раннер не запущен.
        """
        if not self._running:
            logger.warning(f"[{self.name}] step_once: раннер не запущен")
            return False
        started = time.time()
        await self._tick_once(wait_for_user=False)
        logger.debug(
            f"[{self.name}] step_once: {time.time() - started:.3f}с"
        )
        return True

    # ============================================================
    # Цикл жизни
    # ============================================================

    def _save_state_safe(self) -> bool:
        """Сохранить состояние и ментальные модели. Не падает при ошибках."""
        try:
            self.agent.save_state(force=True)
            from config.simulation_config import SIM_CONFIG

            if getattr(SIM_CONFIG, "CHECKPOINT_BACKEND", "sqlite") != "sqlite":
                self.agent.save_mental_models()
            from src.app.active_profile import remember_active_name
            from src.core.paths import data_dir

            remember_active_name(data_dir(), self.agent.name, getattr(self.agent, "life_id", None))
            flush_logs()
            return True
        except Exception as e:
            logger.exception(f"[{self.name}] Ошибка сохранения: {e}")
            return False

    def backup_now(self, destination: str) -> str:
        """Сохранить и скопировать профиль синхронно в потоке event loop.

        Нет await между сохранением и копированием: следующий тик и другие
        обработчики этой шины не могут вмешаться. Внешние writers исключать
        отдельно; это не межпроцессная блокировка.
        """
        import asyncio
        from src.core.paths import data_dir
        from src.memory.profile_backup import create_backup

        asyncio.get_running_loop()
        if not self._save_state_safe():
            raise RuntimeError("Резервирование отменено: сохранение не завершено")
        return create_backup(data_dir(), destination)

    def save_now(self) -> bool:
        """Публичное сохранение состояния.

        Нужно слою приложения: первый чекпоинт пишется сразу после
        старта, чтобы аварийное закрытие окна не стирало жизнь.
        """
        return self._save_state_safe()

    async def start(self) -> None:
        """Запустить фоновый цикл. Возвращает управление сразу (async task).

        Очередь ``_pending_user_messages`` создаётся лениво в
        ``_on_user_message`` — здесь НЕ пересоздаём её, чтобы не
        потерять сообщения, пришедшие от пользователя в окно чата
        между подпиской и ``start()`` (race-condition fix).
        """
        if self._running:
            logger.warning(f"[{self.name}] Уже запущен")
            return
        self._running = True
        self._stop_requested = False

        # Очередь создаётся лениво в _on_user_message — НЕ пересоздаём,
        # иначе потеряем все сообщения, пришедшие до start().
        if not hasattr(self, "_pending_user_messages") or self._pending_user_messages is None:
            self._pending_user_messages = PersistentMessageQueue(self.agent)

        logger.info(f"[{self.name}] Старт. Циклов до: ∞ (без смерти от энергии)")
        await self.bus.publish(
            Events.TIMER_TICK,
            {"phase": "started", "agent": self.agent.name},
            source="runner",
        )

    async def stop(self) -> None:
        """Остановить фоновый цикл. Сохранить состояние."""
        if not self._running:
            return
        logger.info(f"[{self.name}] Остановка...")
        self._stop_requested = True
        self._running = False
        self._save_state_safe()
        await self.bus.publish(
            Events.TIMER_TICK,
            {"phase": "stopped", "ticks": self._tick_count},
            source="runner",
        )

    async def run_forever(self) -> None:
        """Бесконечный цикл. Возвращает управление когда stop_requested."""
        if not self._running:
            await self.start()

        logger.info(f"[{self.name}] run_forever() стартовал")
        try:
            while not self._stop_requested:
                # Состояние жизни — источник правды. Спящий или ушедший
                # агент не должен продолжать цикл: иначе окно показывало
                # бы «спит», а существо продолжало жить в фоне.
                if not self._agent_is_alive():
                    guard = getattr(self.agent, "life_guard", None)
                    if guard is not None and guard.load_state() == "dormant":
                        await asyncio.sleep(self._pause_poll_sec())
                        continue
                    logger.info(
                        f"[{self.name}] Агент не жив — цикл остановлен"
                    )
                    self._stop_requested = True
                    break
                await self._one_iteration()
        except asyncio.CancelledError:
            logger.info(f"[{self.name}] run_forever() отменён")
            raise
        except Exception as e:
            logger.exception(f"[{self.name}] Неожиданная ошибка в цикле: {e}")
            raise
        finally:
            await self.stop()

    async def _one_iteration(self) -> None:
        """Один шаг внешнего цикла: пауза/шаг, затем тик и throttle.

        Логика:
        1. На паузе или в режиме ``step`` — только ждём (жизнь стоит).
        2. Один цикл жизни (``_tick_once``).
        3. Досыпаем остаток интервала до выбранного темпа.
        """
        if self._paused or self._speed_mode == "step":
            # На паузе просто ждём и выходим (потребляем немного CPU).
            await asyncio.sleep(self._pause_poll_sec())
            return

        started = time.time()
        await self._tick_once(wait_for_user=True)

        # Тик уже потратил время на ожидание сообщения, поэтому спим
        # только остаток интервала. Иначе пауза удваивалась бы.
        interval = self.current_interval_sec()
        remaining = interval - (time.time() - started)
        if remaining > 0:
            await asyncio.sleep(remaining)
        else:
            # Даём event loop шанс обслужить шину и UI, не задерживая цикл.
            await asyncio.sleep(0)

    def _agent_is_alive(self) -> bool:
        """Жив ли агент по его собственному состоянию."""
        checker = getattr(self.agent, "is_alive", None)
        if checker is None:
            return True
        try:
            return bool(checker())
        except Exception:
            return True

    def _should_publish_thought(self, text: str, cycle: int) -> bool:
        """Не показывать ту же автономную мысль снова слишком скоро."""
        key = " ".join(str(text).casefold().split())[:200]
        previous = self._recent_thoughts.get(key)
        repeat_window = int(
            getattr(LR_CONFIG, "RUNNER_THOUGHT_REPEAT_CYCLES", 40) or 40
        )
        if previous is not None and cycle - previous < repeat_window:
            return False
        self._recent_thoughts[key] = cycle
        # Старые записи не нужны: окно повтора ограничено по циклам.
        self._recent_thoughts = {
            item: seen for item, seen in self._recent_thoughts.items()
            if cycle - seen < repeat_window
        }
        return True

    def _pause_poll_sec(self) -> float:
        """Как часто проверять, не сняли ли паузу. Компромисс CPU/отзывчивость."""
        return 0.2

    async def _tick_once(self, *, wait_for_user: bool = True) -> None:
        """Ровно один «цикл жизни» агента.

        Args:
            wait_for_user: если True — ждём сообщение пользователя до
                текущего интервала, иначе берём стимул сразу. ``False``
                используется кнопкой «Шаг» и режимом ``max``.
        """
        # === Watchdog на цикл ===
        self.watchdog.on_cycle_start()

        cycle_start_ts = time.time()
        stimulus = None
        user_initiated = False
        deferred = getattr(self.agent, "_deferred_stimulus", None)
        if deferred is not None:
            stimulus = deferred["text"]
            user_initiated = deferred["user_initiated"]

        # Пока отложенный стимул не обработан, новые остаются в очереди.
        if deferred is not None:
            pass
        elif wait_for_user:
            timeout = self.current_interval_sec()
            try:
                if timeout <= 0:
                    message = self._pending_user_messages.get_nowait()
                else:
                    message = await asyncio.wait_for(
                        self._pending_user_messages.get(),
                        timeout=timeout,
                    )
                stimulus = message
                user_initiated = True
            except asyncio.TimeoutError:
                stimulus = None
            except asyncio.QueueEmpty:
                stimulus = None
            except asyncio.CancelledError:
                self.watchdog.on_cycle_end()
                raise
        else:
            try:
                stimulus = self._pending_user_messages.get_nowait()
                user_initiated = True
            except asyncio.QueueEmpty:
                stimulus = None

        if stimulus is None:
            stimulus = self._next_stimulus()
            user_initiated = False

        # === Восстановить энергию за время ожидания ===
        elapsed = time.time() - cycle_start_ts
        self.energy_policy.regenerate(elapsed)

        # === Собственно один «цикл жизни» агента ===
        if stimulus is None:
            # Все стимулы на кулдауне: лучше отдохнуть, чем 13 000 раз
            # повторить один и тот же вопрос (см. docs/BASELINE.md).
            await asyncio.to_thread(self._rest_tick)
        else:
            try:
                # Цикл агента уходит в worker-поток: синхронные сетевые
                # паузы (Wikipedia timeout + rate-limit) не должны
                # замораживать event loop, иначе замирают EventBus,
                # StatusLoop и откладываются tick_will/tick_communication.
                # publish_sync() потокобезопасен (см. event_bus.py).
                await asyncio.to_thread(
                    self._do_one_agent_cycle,
                    stimulus,
                    user_initiated=user_initiated,
                )
            except Exception as e:
                logger.exception(f"[{self.name}] Ошибка в цикле агента: {e}")

        if self._speed_mode == "max":
            self._accelerated_cycles += 1

        # === Watchdog: конец цикла ===
        self.watchdog.on_cycle_end()

        # === Проверить health + энергетические события ===
        await self._check_energy_transitions()
        await self._check_watchdog_pressure()

        # === Автосохранение по таймеру ===
        if (time.time() - self._last_auto_save_ts) >= LR_CONFIG.TRAY_AUTO_SAVE_INTERVAL_SEC:
            self._save_state_safe()
            self._last_auto_save_ts = time.time()

    def set_stimulus_mode(self, mode: str) -> None:
        if mode not in {"quiet", "pool"}:
            raise ValueError("stimulus mode должен быть quiet или pool")
        self._stimulus_mode = mode

    def _next_stimulus(self) -> Optional[str]:
        """Следующий стимул с учётом кулдауна повторов.

        Returns:
            Текст стимула или ``None``, если всё «скучно» — тогда отдых.
        """
        if self._stimulus_mode == "quiet":
            self._loop_tick += 1
            if getattr(self.agent, "_open_questions", None) and self.agent.has_open_questions():
                return self.agent._consume_open_question() or None
            return None
        cooldown = int(getattr(LR_CONFIG, "STIMULUS_COOLDOWN_TICKS", 0) or 0)
        if self._speed_mode == "max":
            # В режиме «лаборатория» кулдаун выключен: иначе после
            # выжигания пула агент уходил бы в бесконечный _rest_tick
            # и ускорение превращалось бы в холостой ход.
            cooldown = 0
        stimulus = select_novel_stimulus(
            self.agent,
            self._recent_stimuli,
            self._loop_tick,
            cooldown,
            goal_priority_prob=TRAIL_GOAL_PRIORITY_PROB,
        )
        self._loop_tick += 1

        if stimulus and cooldown > 0 and not is_open_question_stimulus(stimulus):
            self._recent_stimuli[stimulus.strip().lower()] = self._loop_tick
            self._prune_stimulus_history(cooldown)

        return stimulus

    def _prune_stimulus_history(self, cooldown: int) -> None:
        """Удаляет из истории стимулы, давно вышедшие из кулдауна."""
        horizon = self._loop_tick - cooldown * 2
        if horizon <= 0:
            return
        for key, seen in list(self._recent_stimuli.items()):
            if seen < horizon:
                del self._recent_stimuli[key]

    def _rest_tick(self) -> None:
        """Тик отдыха: подсистемы живут, но агент не повторяет себя."""
        self._idle_ticks += 1
        cycle_before = self.agent.cycle_count
        energy_before = self.agent.energy
        self._last_tick_ledger = {"kind": "idle", "cycle_before": cycle_before,
                                  "energy_before": energy_before, "completed": False}
        try:
            report = self.agent.autonomous_tick()
            self._log_autonomous_events(report)
            self.agent.evolve()
            self._tick_count += 1
            self.agent.cycle_count += 1
            self._last_tick_ledger.update(completed=True, autonomous_action=report.get("autonomous_action"))
            self.bus.publish_sync(Events.TICK, {"phase": "idle", "cycle": self.agent.cycle_count,
                                  "tick": self._tick_count, "energy": self.agent.energy}, source="runner")
        except AgentDeadSignal:
            self._stop_requested = True
            self._running = False
            self._save_state_safe()
        except Exception as e:
            self._last_tick_ledger["error"] = str(e)
            logger.exception(f"[{self.name}] idle autonomous_tick failed: {e}")
        finally:
            self._last_tick_ledger.update(cycle_after=self.agent.cycle_count, energy_after=self.agent.energy)

    def _do_one_agent_cycle(self, stimulus: str, user_initiated: bool = False) -> None:
        """Один полный цикл агента: perceive → think → act → evolve.

        Публикует события на шине о мыслях, действиях, эволюции.
        Не использует input()/print() — общение через EventBus.
        """
        autonomous_report = {}
        self.agent._deferred_stimulus = {"text": stimulus, "user_initiated": user_initiated}
        self.agent._attention_stimulus = {"text": stimulus, "user_initiated": user_initiated}
        # === АВТОНОМНЫЙ ТИК ЖИЗНИ ===
        # Вызываем КАЖДЫЙ цикл, независимо от того, был ли стимул от пользователя.
        # Это делает агента по-настоящему живым: он думает, чувствует, мечтает,
        # инициативирует диалог — даже в полной тишине.
        try:
            autonomous_report = self.agent.autonomous_tick()
            # Логируем интересные события автономной жизни
            self._log_autonomous_events(autonomous_report)
        except AgentDeadSignal as e:
            # Agent died — graceful shutdown
            logger.info(f"[{self.name}] Agent died: {e.cause}. Initiating graceful shutdown...")
            # Publish death event
            self.bus.publish_sync(
                Events.TICK,
                {
                    "phase": "death",
                    "cause": e.cause,
                    "legacy": e.legacy,
                    "cycle": self.agent.cycle_count,
                },
                source="runner",
            )
            # Request stop
            self._stop_requested = True
            self._running = False
            # Save final state
            self._save_state_safe()
            return
        except Exception as e:
            logger.exception(f"autonomous_tick failed: {e}")
        finally:
            self.agent._attention_stimulus = None
        selected = (autonomous_report.get("arbitrator") or {}).get("action", "")
        if not autonomous_report.get("attention_selected"):
            self.agent._deferred_stimulus = {"text": stimulus, "user_initiated": user_initiated}
            self.agent.evolve()
            self._tick_count += 1
            self.agent.cycle_count += 1
            self._last_tick_ledger = {"kind": "stimulus_deferred", "cycle_after": self.agent.cycle_count,
                                      "reason": "another_intention_selected", "autonomous_action": selected,
                                      "user_initiated": user_initiated, "completed": True}
            self.bus.publish_sync(Events.TICK, {"phase": "stimulus_deferred", "cycle": self.agent.cycle_count,
                                  "energy": self.agent.energy, "user_initiated": user_initiated}, source="runner")
            return

        try:
            perceived = self.agent.perceive(stimulus)
        except Exception as e:
            logger.exception(f"perceive failed: {e}")
            return

        try:
            thought = self.agent.think(perceived)
        except Exception as e:
            logger.exception(f"think failed: {e}")
            return

        try:
            action = self.agent.act(thought)
        except Exception as e:
            logger.exception(f"act failed: {e}")
            return

        try:
            self.agent.evolve()
        except Exception as e:
            logger.exception(f"evolve failed: {e}")
            return

        self.agent._deferred_stimulus = None
        self._last_tick_ledger = {"kind": "stimulus_processed", "completed": True,
                                  "autonomous_action": selected, "stimulus_action": str(action),
                                  "user_initiated": user_initiated}
        self._tick_count += 1
        # Используем существующее поле cycle_count в агенте
        self.agent.cycle_count += 1

        # === Публикуем события ===
        # Делаем это синхронно через publish_sync — корутины EventBus не блокируют.
        thought_str = str(thought) if thought else ""
        action_str = str(action) if action else ""

        self.bus.publish_sync(
            Events.TICK,
            {
                "tick": self._tick_count,
                "cycle": self.agent.cycle_count,
                "stimulus": stimulus,
                "thought": thought_str[:200],
                "action": action_str[:200],
                "user_initiated": user_initiated,
                "energy": self.agent.energy,
                "intelligence": self.agent.intelligence,
            },
            source="runner",
        )

        # === Открытые вопросы (свобода воли) ===
        # Если текущий стимул — это exploration открытого вопроса,
        # фиксируем результат мышления в агенте (как делает main.py).
        # Без этого вопрос «крутится» бесконечно без прогресса.
        is_open_question_stimulus = (
            getattr(self.agent, "_open_questions", None)
            and stimulus.startswith("вопрос: ")
        )
        if is_open_question_stimulus:
            self.agent._record_open_question_exploration(stimulus, thought)

        # Если мысль интересная — публикуем отдельно. Повтор той же мысли
        # в пределах THOUGHT_REPEAT_CYCLES не показываем: в чате это выглядит
        # как заевшая пластинка, а не как новая мысль.
        if (
            thought_str
            and not _is_boring_thought(thought_str)
            and self._should_publish_thought(thought_str, self.agent.cycle_count)
        ):
            self.bus.publish_sync(
                Events.AGENT_THOUGHT,
                {"text": thought_str[:300], "cycle": self.agent.cycle_count},
                source="agent",
                priority=0,  # низкий приоритет — чтобы не перебивать важное
            )

        # === Ответ на открытый вопрос → публикуем в чат как особое событие ===
        # Это позволяет GUI-режиму видеть прогресс размышлений над вопросами
        # пользователя. Раньше ответы отсекались _is_boring_thought(), поэтому
        # в чат не попадали — пользователь видел только в терминале (main.py).
        if is_open_question_stimulus:
            recently_answered = [
                q for q in self.agent._open_questions
                if q.get("answered") and q.get("answer")
                and q["last_explored_at"] == self.agent.cycle_count
            ]
            if recently_answered:
                q = recently_answered[0]
                answer_text = (
                    f"✅ Ответ на вопрос «{q['text'][:50]}»:\n"
                    f"   {q['answer'][:200]}"
                )
                self.bus.publish_sync(
                    Events.AGENT_THOUGHT,
                    {"text": answer_text, "cycle": self.agent.cycle_count},
                    source="agent",
                    priority=1,  # выше чем обычные мысли
                )

        # Если интеллект вырос
        if self.agent.intelligence > getattr(self, "_last_intel", 0):
            self._last_intel = self.agent.intelligence
            self.bus.publish_sync(
                Events.AGENT_EVOLVED,
                {"intelligence": self.agent.intelligence},
                source="agent",
                priority=2,  # высокий — это важное событие
            )

    async def _check_energy_transitions(self) -> None:
        """Публикует события при пересечении порогов энергии."""
        if self.energy_policy.should_publish_critical():
            await self.bus.publish(
                Events.ENERGY_LOW,
                {
                    "level": "critical",
                    "energy": self.agent.energy,
                    "percent": self.energy_policy.energy_percent,
                    "message": (
                        f"Я очень устал (энергия {self.agent.energy:.0f}). "
                        f"Я не умру — просто замедлюсь и буду отдыхать."
                    ),
                },
                source="energy_policy",
                priority=2,
            )
        elif self.energy_policy.should_publish_low():
            await self.bus.publish(
                Events.ENERGY_LOW,
                {
                    "level": "low",
                    "energy": self.agent.energy,
                    "percent": self.energy_policy.energy_percent,
                    "message": "Энергия падает. Я начинаю думать реже.",
                },
                source="energy_policy",
                priority=1,
            )

        if self.energy_policy.should_publish_recovered():
            await self.bus.publish(
                Events.ENERGY_RECOVERED,
                {
                    "energy": self.agent.energy,
                    "percent": self.energy_policy.energy_percent,
                    "message": "Я снова полон сил!",
                },
                source="energy_policy",
                priority=1,
            )

    async def _check_watchdog_pressure(self) -> None:
        """Реагирует на сигналы watchdog (RSS, медленные циклы)."""
        if self.watchdog.should_force_forget():
            try:
                # Принудительное забывание уже реализовано в perform_forgetting()
                # Вызываем его и публикуем событие
                self.agent.perform_forgetting()
                self.watchdog.mark_forced_forget(0)  # счётчик ведётся внутри
                await self.bus.publish(
                    "watchdog_pressure",
                    {"kind": "memory_pressure", "rss_mb": self.watchdog.get_rss_mb()},
                    source="watchdog",
                    priority=2,
                )
            except Exception as e:
                logger.exception(f"Ошибка при принудительном забывании: {e}")

    # ============================================================
    # Команды из чата
    # ============================================================

    async def handle_command(self, cmd: str) -> str:
        """Обработать команду из чата (начинается с /).

        Возвращает текст ответа для чата.
        """
        # Сохраняем оригинальную команду ДО lower(), чтобы команды вида
        # /name <Имя> сохраняли регистр самого имени (ЛюСЯ, Макс и т.п.).
        # В нижний регистр приводим только служебный cmd для маршрутизации.
        cmd_raw = cmd.strip()
        cmd = cmd_raw.lstrip("/").lower()
        agent = self.agent

        if cmd in ("status", "s"):
            return self._format_status()
        if cmd == "goals" or cmd.startswith("goals "):
            return self._handle_goals_command(cmd_raw)
        if cmd in ("g",):
            return self._format_goals()
        if cmd in ("concepts", "c"):
            return self._format_concepts()
        if cmd in ("pause",):
            self._paused = True
            return "⏸ Пауза. Циклы остановлены, агент ждёт."
        if cmd in ("resume", "wake"):
            self._paused = False
            return "▶ Возобновлено."
        if cmd in ("save",):
            ok = self._save_state_safe()
            return "💾 Сохранено." if ok else "⚠️ Ошибка сохранения."
        if cmd in ("energy",):
            return self._format_status()  # alias
        if cmd in ("quit", "exit"):
            await self.bus.publish(Events.SHUTDOWN_REQUESTED, source="command")
            return "👋 Завершение..."
        if cmd in ("help", "h", "?"):
            return self._format_help()
        if cmd.startswith("ask "):
            # Открытый вопрос (свобода воли). Ставим в очередь,
            # AgentRunner будет думать над ним в ближайших циклах.
            question = cmd[4:].strip()
            if question:
                result = agent.ask_user(question, source="chat")
                if result.get("status") == "queued":
                    return (
                        f"🧠 Вопрос «{question[:60]}» поставлен в очередь "
                        f"(размер очереди: {result.get('queue_size')})."
                    )
                if result.get("status") == "duplicate":
                    return f"↺ Вопрос «{question[:60]}» уже в очереди."
                return f"⚠️ Не удалось поставить вопрос: {result}"
            return "Использование: /ask <вопрос>"
        if cmd in ("questions", "q"):
            return self._format_open_questions()
        # === Доступы: те же переключатели, что на экране «Доступы» ===
        if cmd.startswith("access "):
            return self._handle_access_command(cmd)
        # === Этап 2.5: /web — управление web-поиском ===
        if cmd in ("web on", "web_on"):
            ws = getattr(self.agent, "web_searcher", None)
            if ws is None:
                return "⚠️ Web-поиск не настроен (см. WEB_SEARCH_ENABLED в конфиге)."
            ws.toggle(True)
            return "🌐 Интернет-поиск включён."
        if cmd in ("web off", "web_off"):
            ws = getattr(self.agent, "web_searcher", None)
            if ws is None:
                return "⚠️ Web-поиск не настроен."
            ws.toggle(False)
            return "🌐 Интернет-поиск выключен."
        if cmd.startswith("web "):
            # /web <запрос> — ручной поиск
            query = cmd[4:].strip()
            if not query:
                return "Использование: /web <запрос>"
            ws = getattr(self.agent, "web_searcher", None)
            if ws is None:
                return "⚠️ Web-поиск не настроен."
            result = ws.search(query)
            if result.get("found"):
                extract = result["extract"]
                if len(extract) > 500:
                    extract = extract[:500] + "…"
                return (
                    f"🌐 {result['title']} (Wikipedia/{result.get('lang', 'ru')}):\n"
                    f"{extract}\n"
                    f"Источник: {result['url']}"
                )
            reason = result.get("error", "not_found")
            if reason in ("disabled",):
                return "⚠️ Интернет-поиск выключен (/web on чтобы включить)."
            if reason in ("network_error", "timeout"):
                return f"🌐 Интернет недоступен ({reason})."
            return f"🌐 Ничего не нашёл по «{query}» ({reason})."
        if cmd == "web":
            ws = getattr(self.agent, "web_searcher", None)
            if ws is None:
                return "⚠️ Web-поиск не настроен."
            state = "включён" if ws.is_enabled else "выключен"
            stats = ws.get_stats()
            return (
                f"🌐 Интернет-поиск: {state}\n"
                f"   Язык: {ws.lang}\n"
                f"   Кэш: {ws.cache_size()} записей\n"
                f"   HTTP-вызовов: {stats['network_calls']}, "
                f"найдено: {stats['found']}, ошибок: {stats['errors']}"
            )
        # === name / propose_name — NamingDialogue ===
        # Чат публикует USER_COMMAND с command="propose_name <имя>".
        # Здесь мы её диспетчеризуем в agent.propose_name(...), который
        # уже делегирует в naming_dialogue.process_name_proposal().
        # Имя берём из cmd_raw (оригинальный регистр), не из cmd (lower).
        # Поддерживаем оба префикса:
        #   "propose_name <X>" — публикуется из chat_window.py через EventBus.
        #   "name <X>" / "name" — короткий алиас (на случай прямого вызова
        #                        handle_command("/name X"), а также на будущее).
        if (
            cmd.startswith("propose_name ")
            or cmd.startswith("name ")
            or cmd == "name"
        ):
            stripped = cmd_raw.lstrip("/")
            if cmd.startswith("propose_name "):
                proposed = stripped[len("propose_name "):].strip()
            elif cmd.startswith("name "):
                proposed = stripped[len("name "):].strip()
            else:
                proposed = ""
            if not proposed:
                return "Использование: /name <имя_которое_ты_хочешь_дать>"
            result = agent.propose_name(proposed, cycle=agent.cycle_count)
            if result.get("status") in {"accepted", "alternative_accepted"}:
                self._publish_name_changed(result)
            # Единый форматтер с USER_MESSAGE-дверью (включая переспрос
            # переименования и no_op/no_naming_dialogue).
            return self._format_name_result(result, proposed)
        # === Delamain-local: детерминированный слой действий ===
        if cmd == "delamain" or cmd.startswith("delamain "):
            return self._handle_delamain_command(cmd_raw)
        return f"❓ Неизвестная команда: /{cmd}. Введите /help."

    def _handle_access_command(self, cmd: str) -> str:
        """Включить или выключить разрешение из окна или командой."""
        from src.app.access_control import describe_error, set_access
        from src.core.paths import data_dir

        parts = cmd.split()
        if len(parts) != 3 or parts[2] not in ("on", "off"):
            return "Использование: /access network|delamain|effector on|off"
        key, value = parts[1], parts[2]
        result = set_access(
            self.agent, key, value == "on", root=data_dir()
        )
        if not result.get("ok"):
            return "⚠️ " + describe_error(result)
        label = str(result.get("label") or "Разрешение")
        return f"{label}: {'включено' if value == 'on' else 'выключено'}."

    def _handle_delamain_command(self, cmd_raw: str) -> str:
        """Обработать /delamain ...; регистр задачи берём из ``cmd_raw``."""

        sub = getattr(self.agent, "delamain", None)
        if sub is None:
            return "⚠️ Delamain-local не подключён (см. лог инициализации)."

        body = cmd_raw.strip().lstrip("/").strip()
        parts = body.split(maxsplit=2)
        action = parts[1].lower() if len(parts) > 1 else "status"
        rest = parts[2].strip() if len(parts) > 2 else ""

        if action in ("status", "s"):
            return self._format_delamain_status(sub)
        if action in ("on", "enable"):
            result = sub.enable()
            if result.get("enabled"):
                return "🧪 Delamain-local включён. Runtime готов к работе."
            return f"⚠️ Не удалось включить Delamain-local: {result.get('error')}"
        if action in ("off", "disable"):
            sub.disable()
            return "🧪 Delamain-local выключен (runtime закроется при shutdown)."
        if action in ("run", "task"):
            if not rest:
                return "Использование: /delamain run <задача>"
            try:
                result = sub.run_now(rest)
            except Exception as exc:
                return f"⚠️ Delamain-local: {type(exc).__name__}: {exc}"
            return self._format_delamain_result(result)
        if action in ("goal", "queue"):
            if "|" not in rest:
                return "Использование: /delamain goal <название> | <команда>"
            title, command = rest.split("|", 1)
            title = title.strip()
            command = command.strip()
            if not title or not command:
                return "Использование: /delamain goal <название> | <команда>"
            try:
                goal = sub.queue_goal(title, command)
            except Exception as exc:
                return f"⚠️ Не удалось поставить цель: {type(exc).__name__}: {exc}"
            return (
                f"🧪 Цель #{goal['id']} «{goal['title']}» поставлена в очередь. "
                f"Выполнится на ближайшем тике Delamain."
            )
        if action in ("goals", "list"):
            try:
                goals = sub.list_goals()
            except Exception as exc:
                return f"⚠️ Не удалось прочитать цели: {type(exc).__name__}: {exc}"
            if not goals:
                return "🧪 Исполняемых целей Delamain нет."
            lines = [f"🧪 Delamain-цели ({len(goals)}):"]
            for goal in goals[:10]:
                metadata = goal.get("metadata") or {}
                attempts = metadata.get("attempts")
                attempt_note = (
                    f", attempts={attempts}/{sub.max_attempts}"
                    if attempts is not None
                    else ""
                )
                approval_note = (
                    f", approval={metadata.get('approval_id')}"
                    if metadata.get("approval_id")
                    else ""
                )
                retry_note = ""
                if (
                    goal.get("status") == "pending"
                    and metadata.get("next_retry_at")
                ):
                    retry_note = f", retry_at={metadata.get('next_retry_at')}"
                replan_note = ""
                if metadata.get("replan_on_next_attempt"):
                    replan_note = ", replan=next"
                    if metadata.get("last_failure_context"):
                        replan_note += "(context)"
                elif metadata.get("last_attempt_replanned"):
                    replan_note = ", replanned"
                if metadata.get("step_repairs"):
                    replan_note += f", repairs={metadata.get('step_repairs')}"
                bridge_note = ""
                if metadata.get("bridge_source") == "goal_subsystem":
                    bridge_note = (
                        f", cognitive=#{metadata.get('cognitive_goal_id')}"
                        f"/{goal.get('bridge_status', '?')}"
                    )
                lines.append(
                    f"  [{goal.get('status')}{attempt_note}{approval_note}"
                    f"{retry_note}{replan_note}{bridge_note}] "
                    f"#{goal.get('id')} {goal.get('title')} "
                    f"(p={float(goal.get('priority', 0)):.2f})"
                )
            if len(goals) > 10:
                lines.append(f"  … ещё {len(goals) - 10}")
            return "\n".join(lines)
        if action in ("skills", "skill"):
            try:
                skills = sub.list_skills()
            except Exception as exc:
                return f"⚠️ Не удалось прочитать навыки: {type(exc).__name__}: {exc}"
            if not skills:
                return "🧪 Навыков Delamain пока нет."
            lines = [f"🧪 Delamain-навыки ({len(skills)}):"]
            for skill in skills[:10]:
                lines.append(self._format_delamain_skill(skill))
            if len(skills) > 10:
                lines.append(f"  … ещё {len(skills) - 10}")
            return "\n".join(lines)
        if action in ("approvals", "pending"):
            state = rest.strip().lower() or "pending"
            if state in ("all", "*"):
                state = None
            try:
                approvals = sub.list_approvals(status=state)
            except Exception as exc:
                return f"⚠️ Не удалось прочитать approvals: {type(exc).__name__}: {exc}"
            if not approvals:
                label = "ожидающих" if state == "pending" else "подходящих"
                return f"🧪 Approvals Delamain: {label} нет."
            title = "ожидают" if state == "pending" else f"status={state or 'all'}"
            lines = [f"🧪 Delamain-approvals ({title}, {len(approvals)}):"]
            for approval in approvals[:10]:
                lines.append(self._format_delamain_approval(approval))
            if len(approvals) > 10:
                lines.append(f"  … ещё {len(approvals) - 10}")
            return "\n".join(lines)
        if action == "approve":
            approval_id = rest.split(maxsplit=1)[0] if rest else ""
            if not approval_id:
                return "Использование: /delamain approve <approval_id>"
            try:
                result = sub.approve(approval_id)
            except Exception as exc:
                return f"⚠️ Не удалось подтвердить approval: {type(exc).__name__}: {exc}"
            return self._format_delamain_result(result, prefix="Delamain approval")
        if action == "reject":
            parts = rest.split(maxsplit=1)
            approval_id = parts[0] if parts else ""
            reason = parts[1].strip() if len(parts) > 1 else ""
            if not approval_id:
                return "Использование: /delamain reject <approval_id> [причина]"
            try:
                result = sub.reject(approval_id, reason)
            except Exception as exc:
                return f"⚠️ Не удалось отклонить approval: {type(exc).__name__}: {exc}"
            return self._format_delamain_result(result, prefix="Delamain approval")
        return (
            "Использование: /delamain [status|on|off|run <задача>|"
            "goal <название> | <команда>|goals|skills|approvals|"
            "approve <id>|reject <id> [причина]]"
        )

    def _format_delamain_status(self, sub) -> str:
        status = sub.status()
        goals = status.get("goals") or {}
        planner = status.get("planner") or {}
        approval = status.get("approval") or {}
        approval_counts = approval.get("counts") or {}
        bridge = status.get("bridge") or {}
        bridge_counts = bridge.get("counts") or {}
        authoring = status.get("authoring") or {}
        retry = status.get("retry") or {}
        step_repair = status.get("step_repair") or {}
        backoff_sec = float(retry.get("backoff_sec") or 0.0)
        backoff_max_sec = float(retry.get("backoff_max_sec") or 0.0)
        lines = [
            "🧪 Delamain-local",
            f"  Включён: {'да' if status.get('enabled') else 'нет'}",
            f"  Runtime: {'готов' if status.get('runtime_ready') else 'не создан'}",
            f"  Workspace: {status.get('workspace')}",
            f"  Планировщик: {planner.get('mode') or 'heuristic'}",
            f"  Approval: {approval.get('mode', 'off')}; "
            f"pending={approval_counts.get('pending', 0)}",
            f"  Цели: pending={goals.get('pending', 0)}, "
            f"done={goals.get('done', 0)}, failed={goals.get('failed', 0)}",
            f"  Навыки: {status.get('skills', 0)}; "
            f"попыток на цель: {status.get('max_attempts', 1)}",
            f"  Retry: backoff={backoff_sec:g}s, cap={backoff_max_sec:g}s, "
            f"replan={'on' if retry.get('replan_on_failure') else 'off'}, "
            f"context={'on' if retry.get('replan_with_context') else 'off'}",
            f"  Repair: {'on' if step_repair.get('enabled') else 'off'}, "
            f"max_segments={step_repair.get('max_step_repairs', 0)}, "
            f"max_steps={step_repair.get('max_repair_steps', 0)}",
            f"  Тик: каждые {status.get('tick_interval')} циклов",
            f"  Authoring: {'on' if authoring.get('enabled') else 'off'}, "
            f"proposals={'on' if authoring.get('proposal_enabled') else 'off'}",
        ]
        if bridge.get("enabled"):
            lines.append(
                f"  Когнитивные цели: linked={bridge.get('linked', 0)}, "
                f"waiting={bridge_counts.get('waiting_approval', 0)}, "
                f"done={bridge_counts.get('done', 0)}, "
                f"failed={bridge_counts.get('failed', 0)}"
            )
        if bridge.get("last_error"):
            lines.append(f"  Ошибка моста целей: {bridge['last_error']}")
        if approval.get("error"):
            lines.append(f"  Approval-ошибка: {approval['error']}")
        if planner.get("enabled"):
            lines.append(
                f"  LLM: {planner.get('model')} @ {planner.get('base_url')}"
            )
        planner_error = planner.get("error") or planner.get("last_error")
        if planner_error:
            lines.append(f"  LLM-ошибка: {planner_error}")
        last = status.get("last_result")
        if last:
            if last.get("pending_approval"):
                mark = "⏸"
            else:
                mark = "✅" if last.get("ok") else "⚠️"
            last_retry = ""
            if last.get("retry_scheduled"):
                last_retry = ", retry"
                if last.get("next_retry_at"):
                    last_retry += f" after {last['next_retry_at']}"
                if last.get("replan_on_next_attempt"):
                    last_retry += ", replan"
            if last.get("step_repairs"):
                last_retry += f", repair={last['step_repairs']}"
            lines.append(
                f"  Последняя: {mark} {last.get('title') or last.get('task')} "
                f"(шагов: {last.get('steps', 0)}{last_retry})"
            )
        if status.get("last_error"):
            lines.append(f"  Ошибка: {status['last_error']}")
        return "\n".join(lines)

    def _format_delamain_result(self, result: dict, prefix: str = "Delamain") -> str:
        steps = result.get("steps", 0)
        task_id = result.get("task_id", "?")
        pending = result.get("pending_approval")
        if pending:
            approval_id = pending.get("id", "?")
            dangerous = ", ".join(pending.get("dangerous_actions") or [])
            detail = f" ({dangerous})" if dangerous else ""
            repair_note = ""
            if pending.get("repair"):
                repair_note = (
                    "\n  Это repair-план: уже выполнено шагов: "
                    f"{pending.get('prior_steps', 0)}."
                )
            return (
                f"⏸ {prefix}: нужно подтверждение{detail}.\n"
                f"  Approval: {approval_id}; task: {task_id}{repair_note}\n"
                f"  /delamain approve {approval_id} — выполнить\n"
                f"  /delamain reject {approval_id} [причина] — отклонить"
            )
        repair_note = ""
        if result.get("step_repairs"):
            repair_note = f", repair={result['step_repairs']}"
        if result.get("ok"):
            output = result.get("final_output")
            suffix = f"\n  Вывод: {output}" if output is not None else ""
            return (
                f"✅ {prefix}: успешно, шагов: {steps}{repair_note} "
                f"(task {task_id}).{suffix}"
            )
        retry_note = ""
        if result.get("retry_scheduled"):
            retry_note = " Повтор на следующем тике."
            if result.get("next_retry_at"):
                retry_note = f" Повтор после {result['next_retry_at']}."
            if result.get("replan_on_next_attempt"):
                retry_note += " С перепланированием"
                if result.get("replan_context"):
                    retry_note += " и контекстом ошибки"
                retry_note += "."
        return (
            f"⚠️ {prefix}: ошибка, шагов: {steps}{repair_note} "
            f"(task {task_id}).\n"
            f"  {result.get('error')}{retry_note}"
        )

    @staticmethod
    def _format_delamain_approval(approval: dict) -> str:
        dangerous = ", ".join(approval.get("dangerous_actions") or [])
        danger_note = f"; опасные: {dangerous}" if dangerous else ""
        goal_note = (
            f"; goal #{approval.get('goal_id')}"
            if approval.get("goal_id") is not None
            else ""
        )
        metadata = approval.get("metadata") or {}
        repair_note = (
            "; repair-план"
            if isinstance(metadata, dict)
            and metadata.get("kind") == "step_repair"
            else ""
        )
        return (
            f"  [{approval.get('status')}] {approval.get('id')} "
            f"«{approval.get('title') or approval.get('task') or '—'}»"
            f"{danger_note}{goal_note}{repair_note}"
        )

    @staticmethod
    def _format_delamain_skill(skill: dict) -> str:
        plan = skill.get("plan")
        if (
            isinstance(plan, dict)
            and plan.get("version") == 1
            and isinstance(plan.get("steps"), list)
        ):
            steps = plan["steps"]
            command = plan.get("command")
        elif isinstance(plan, list):
            steps = plan
            command = None
        else:
            steps = []
            command = None
        actions = [
            str(step.get("action"))
            for step in steps
            if isinstance(step, dict) and step.get("action")
        ]
        plan_note = " → ".join(actions[:4]) if actions else "план не сохранён"
        if len(actions) > 4:
            plan_note += " → …"
        command_note = f"; команда: {command}" if command else ""
        return (
            f"  [{skill.get('success_count', 0)}✓/"
            f"{skill.get('failure_count', 0)}✗] {skill.get('name')}: "
            f"{plan_note}{command_note}"
        )

    def _format_open_questions(self) -> str:
        """Форматирует список открытых вопросов для чата."""
        a = self.agent
        questions = a.get_open_questions()
        if not questions:
            return "📭 Очередь открытых вопросов пуста."
        lines = [f"📝 Открытые вопросы ({len(questions)}):"]
        for i, q in enumerate(questions[:10], 1):
            status = "✅" if q["answered"] else "🔄"
            hint = f" (💡 {q['hint'][:30]})" if q.get("hint") else ""
            lines.append(
                f"  {status} [{q['explored']}/{q['max']}] "
                f"«{q['text'][:50]}»{hint}"
            )
        return "\n".join(lines)

    def _format_status(self) -> str:
        a = self.agent
        es = self.energy_policy.get_status()
        lines = [
            f"🤖 {a.name}",
            f"  Цикл: {a.cycle_count} | Тик Runner: {self._tick_count}",
            f"  Энергия: {es['energy']:.0f}/{es['max_energy']:.0f} "
            f"({es['percent']:.0f}%, {es['level']})",
            f"  Интеллект: {a.intelligence}",
            f"  Концепций: {len(a.mental_models.concepts)}",
            f"  Интервал тика: {es['tick_interval_sec']:.0f}с",
            f"  На паузе: {'да' if self._paused else 'нет'}",
        ]
        delamain = getattr(a, "delamain", None)
        if delamain is not None and getattr(delamain, "bridge_enabled", False):
            bridge = delamain.status().get("bridge") or {}
            counts = bridge.get("counts") or {}
            lines.append(
                f"  Delamain-цели: linked={bridge.get('linked', 0)}, "
                f"waiting={counts.get('waiting_approval', 0)}, "
                f"done={counts.get('done', 0)}, failed={counts.get('failed', 0)}"
            )
        return "\n".join(lines)

    def _handle_goals_command(self, cmd_raw: str) -> str:
        """Обработать /goals и подкоманды Stage 13."""
        body = cmd_raw.strip().lstrip("/").strip()
        parts = body.split(maxsplit=2)
        action = parts[1].lower() if len(parts) > 1 else ""
        rest = parts[2].strip() if len(parts) > 2 else ""
        agent = self.agent
        goal_subsystem = getattr(agent, "goal_subsystem", None)

        if not action:
            return self._format_goals()
        if action in ("list", "ls"):
            return self._format_goals_list(goal_subsystem)
        if action in ("show", "info"):
            goal_id = self._parse_goal_id(rest)
            if goal_id is None:
                return "Использование: /goals show <id>"
            goal = self._find_cognitive_goal(goal_subsystem, goal_id)
            if goal is None:
                return f"⚠️ Когнитивная цель #{goal_id} не найдена."
            return self._format_goal_details(goal)

        sub = getattr(agent, "delamain", None)
        if sub is None:
            return "⚠️ Delamain-local не подключён; authoring недоступен."

        if action in ("exec", "attach"):
            raw_id, sep, payload = rest.partition("|")
            if not sep:
                return "Использование: /goals exec <id> | <команда>"
            goal_id = self._parse_goal_id(raw_id)
            if goal_id is None:
                return "Использование: /goals exec <id> | <команда>"
            command, predicate_sep, predicate = payload.partition("|")
            command = command.strip()
            predicate = predicate.strip() if predicate_sep else ""
            if not command:
                return "Использование: /goals exec <id> | <команда>"
            try:
                result = sub.attach_goal_execution(
                    goal_id,
                    command,
                    success_predicate=predicate,
                    agent=agent,
                )
            except Exception as exc:
                return f"⚠️ Не удалось привязать payload: {type(exc).__name__}: {exc}"
            return self._format_goals_authoring_result(result, action="exec")

        if action in ("propose", "plan"):
            raw_id, sep, task = rest.partition("|")
            goal_id = self._parse_goal_id(raw_id)
            if goal_id is None:
                return "Использование: /goals propose <id> [| <задача>]"
            task = task.strip() if sep else None
            try:
                result = sub.propose_goal_execution(
                    goal_id,
                    task=task,
                    agent=agent,
                )
            except Exception as exc:
                return f"⚠️ Не удалось предложить план: {type(exc).__name__}: {exc}"
            return self._format_goals_authoring_result(result, action="propose")

        if action in ("accept", "approve"):
            goal_id = self._parse_goal_id(rest)
            if goal_id is None:
                return "Использование: /goals accept <id>"
            try:
                result = sub.accept_goal_execution(goal_id, agent=agent)
            except Exception as exc:
                return f"⚠️ Не удалось принять proposal: {type(exc).__name__}: {exc}"
            return self._format_goals_authoring_result(result, action="accept")

        if action in ("reject", "decline"):
            raw_id, _, reason = rest.partition(" ")
            goal_id = self._parse_goal_id(raw_id)
            if goal_id is None:
                return "Использование: /goals reject <id> [причина]"
            try:
                result = sub.reject_goal_execution(
                    goal_id,
                    reason=reason.strip(),
                    agent=agent,
                )
            except Exception as exc:
                return f"⚠️ Не удалось отклонить proposal: {type(exc).__name__}: {exc}"
            return self._format_goals_authoring_result(result, action="reject")

        return (
            "Использование: /goals [list|show <id>|exec <id> | <команда>|"
            "propose <id> [| <задача>]|accept <id>|reject <id> [причина]]"
        )

    @staticmethod
    def _parse_goal_id(value: str) -> Optional[int]:
        raw = str(value or "").strip().lstrip("#")
        if not raw:
            return None
        try:
            goal_id = int(raw.split()[0])
        except (TypeError, ValueError):
            return None
        return goal_id if goal_id > 0 else None

    @staticmethod
    def _find_cognitive_goal(goal_subsystem, goal_id: int):
        if goal_subsystem is None:
            return None
        getter = getattr(goal_subsystem, "get_goal", None)
        if callable(getter):
            return getter(goal_id)
        return next(
            (
                goal
                for goal in list(getattr(goal_subsystem, "goals", []) or [])
                if goal.get("id") == goal_id
            ),
            None,
        )

    def _format_goals_list(self, goal_subsystem) -> str:
        if goal_subsystem is None:
            return "⚠️ GoalSubsystem не подключена."
        goals = list(getattr(goal_subsystem, "goals", []) or [])
        if not goals:
            return "📋 Когнитивных целей нет."
        lines = [f"📋 Когнитивные цели ({len(goals)}):"]
        for goal in goals[:20]:
            marks = []
            if isinstance(goal.get("execution"), dict):
                marks.append("exec")
            proposal = goal.get("execution_proposal")
            if isinstance(proposal, dict):
                marks.append(f"proposal={proposal.get('status', '?')}")
            link = goal.get("delamain_bridge")
            if isinstance(link, dict):
                marks.append(
                    f"delamain=#{link.get('goal_id')}/{link.get('status', '?')}"
                )
            note = f" ({', '.join(marks)})" if marks else ""
            lines.append(
                f"  [{goal.get('status', '?')}] #{goal.get('id')} "
                f"{goal.get('title') or '—'}{note}"
            )
        if len(goals) > 20:
            lines.append(f"  … ещё {len(goals) - 20}")
        return "\n".join(lines)

    def _format_goal_details(self, goal: dict) -> str:
        lines = [
            f"📋 Цель #{goal.get('id')} «{goal.get('title') or '—'}»",
            f"  Статус: {goal.get('status')}",
            f"  Сложность: {goal.get('difficulty', 1)}",
            f"  Источник: {goal.get('source') or '—'}",
        ]
        if goal.get("created_at"):
            lines.append(f"  Создана: {goal['created_at']}")
        if goal.get("failure_reason"):
            lines.append(f"  Причина провала: {goal['failure_reason']}")

        execution = goal.get("execution")
        if isinstance(execution, dict):
            lines.append("  Executable: да")
            if execution.get("command"):
                lines.append(f"    Команда: {execution['command']}")
            if execution.get("plan"):
                lines.append(
                    f"    План: {self._format_goal_plan(execution['plan'])}"
                )
            if execution.get("success_predicate"):
                lines.append(
                    f"    Predicate: {execution['success_predicate']}"
                )
        else:
            lines.append("  Executable: нет")

        proposal = goal.get("execution_proposal")
        if isinstance(proposal, dict):
            lines.append(
                f"  Proposal: {proposal.get('status', '?')} "
                f"(source={proposal.get('source', '?')})"
            )
            if proposal.get("summary"):
                lines.append(f"    План: {proposal['summary']}")
            files = proposal.get("files") or []
            if files:
                lines.append(f"    Файлы: {', '.join(str(f) for f in files)}")
            dangerous = proposal.get("dangerous_actions") or []
            if dangerous:
                lines.append(
                    f"    Опасные действия: {', '.join(str(a) for a in dangerous)}"
                )
            lines.append(
                f"    Approval: {'нужен' if proposal.get('requires_approval') else 'не нужен'}"
                f" (mode={proposal.get('approval_mode', 'off')})"
            )
            if proposal.get("error"):
                lines.append(f"    Ошибка: {proposal['error']}")
            if proposal.get("reason"):
                lines.append(f"    Причина: {proposal['reason']}")
        else:
            lines.append("  Proposal: нет")

        link = goal.get("delamain_bridge")
        if isinstance(link, dict):
            lines.append(
                f"  Delamain: goal #{link.get('goal_id')} "
                f"[{link.get('status', '?')}]"
            )
            if link.get("message"):
                lines.append(f"    {link['message']}")
        return "\n".join(lines)

    @staticmethod
    def _format_goal_plan(plan) -> str:
        if not isinstance(plan, list):
            return "—"
        parts = []
        for step in plan[:8]:
            if not isinstance(step, dict):
                continue
            action = str(step.get("action") or "?")
            args = step.get("args")
            path = args.get("path") if isinstance(args, dict) else None
            parts.append(f"{action}:{path}" if path else action)
        if len(plan) > 8:
            parts.append("…")
        return " → ".join(parts) if parts else "—"

    def _format_goals_authoring_result(self, result: dict, *, action: str) -> str:
        goal = result.get("goal") if isinstance(result.get("goal"), dict) else {}
        proposal = (
            result.get("proposal")
            if isinstance(result.get("proposal"), dict)
            else {}
        )
        if not result.get("ok"):
            lines = [f"⚠️ /goals {action}: {result.get('error') or 'ошибка'}"]
            if proposal.get("summary"):
                lines.append(f"  План: {proposal['summary']}")
            if proposal.get("error"):
                lines.append(f"  Ошибка proposal: {proposal['error']}")
            return "\n".join(lines)

        goal_id = result.get("goal_id") or goal.get("id")
        title = goal.get("title") or "—"
        if action == "exec":
            lines = [f"✅ Payload привязан к цели #{goal_id} «{title}»."]
        elif action == "propose":
            lines = [f"🧠 Proposal для цели #{goal_id} «{title}» сохранён."]
        elif action == "accept":
            lines = [f"✅ Proposal для цели #{goal_id} «{title}» принят."]
        else:
            lines = [f"🚫 Proposal для цели #{goal_id} «{title}» отклонён."]

        if proposal.get("summary"):
            lines.append(f"  План: {proposal['summary']}")
        files = proposal.get("files") or []
        if files:
            lines.append(f"  Файлы: {', '.join(str(f) for f in files)}")
        dangerous = proposal.get("dangerous_actions") or []
        if dangerous:
            lines.append(f"  Опасные действия: {', '.join(str(a) for a in dangerous)}")
        if action != "reject":
            if proposal.get("requires_approval"):
                lines.append(
                    f"  ⏸ При выполнении потребуется approval "
                    f"(mode={proposal.get('approval_mode', 'off')})."
                )
            elif dangerous:
                lines.append(
                    "  ⚠️ Approval выключен: принятие payload означает согласие "
                    "на опасные действия без отдельного запроса."
                )
        elif proposal.get("reason"):
            lines.append(f"  Причина: {proposal['reason']}")
        if proposal.get("planner_error"):
            lines.append(f"  ℹ️ Preview-план: {proposal['planner_error']}")

        if action == "propose":
            lines.append(f"  /goals accept {goal_id} — принять и привязать")
            lines.append(f"  /goals reject {goal_id} [причина] — отклонить")

        if action in ("exec", "propose", "accept"):
            sub = getattr(self.agent, "delamain", None)
            if sub is not None and not getattr(sub, "bridge_enabled", False):
                if action == "propose":
                    lines.append(
                        "  ⚠️ Мост когнитивных целей выключен: proposal "
                        "сохранён, но после accept исполняться не будет "
                        "(DELAMAIN_BRIDGE_ENABLED=1)."
                    )
                else:
                    lines.append(
                        "  ⚠️ Мост когнитивных целей выключен: payload "
                        "сохранён, но не будет исполнен "
                        "(DELAMAIN_BRIDGE_ENABLED=1)."
                    )
            if goal.get("status") == "pending":
                lines.append(
                    "  ℹ️ Цель станет активной после завершения текущей."
                )
        return "\n".join(lines)

    def _format_goals(self) -> str:
        a = self.agent
        goals_status = a.get_goals_status()
        active = goals_status.get('active', '')
        lines = [
            f"📋 Цели: {goals_status['completed']}/{goals_status['total']}",
            f"  Активная: {active or '—'}",
        ]
        active_goal = getattr(a, "active_goal", None)
        if isinstance(active_goal, dict):
            execution = active_goal.get("execution")
            if isinstance(execution, dict):
                lines.append("  Executable: да")
            proposal = active_goal.get("execution_proposal")
            if isinstance(proposal, dict) and proposal.get("status") == "pending":
                lines.append(
                    f"  Proposal: pending — /goals accept {active_goal.get('id')} "
                    f"или /goals reject {active_goal.get('id')}"
                )
            link = active_goal.get("delamain_bridge")
            if isinstance(link, dict):
                lines.append(
                    f"  Delamain: goal #{link.get('goal_id')} "
                    f"[{link.get('status')}]"
                    + (f" — {link.get('message')}" if link.get("message") else "")
                )
        return "\n".join(lines)

    def _format_concepts(self) -> str:
        a = self.agent
        mm = a.mental_models
        total = len(mm.concepts)
        high_conf = sum(1 for n in mm.concepts.values() if n.confidence > 0.7)
        return (
            f"📚 Концепций: {total}\n"
            f"  С высокой уверенностью (>70%): {high_conf}"
        )

    def _format_help(self) -> str:
        return (
            "Доступные команды:\n"
            "  /status    — статус агента\n"
            "  /goals     — цели\n"
            "  /goals list — все когнитивные цели\n"
            "  /goals show <id> — payload и proposal цели\n"
            "  /goals exec <id> | <команда> — привязать payload\n"
            "  /goals propose <id> [| <задача>] — предложить план\n"
            "  /goals accept|reject <id> — решение по proposal\n"
            "  /concepts  — концепции\n"
            "  /energy    — энергия (алиас status)\n"
            "  /pause     — пауза\n"
            "  /resume    — возобновить\n"
            "  /save      — сохранить сейчас\n"
            "  /name <имя> — дать агенту имя\n"
            "  /web       — статус интернет-поиска\n"
            "  /web on    — включить интернет-поиск\n"
            "  /web off   — выключить интернет-поиск\n"
            "  /web <запрос> — поиск в Wikipedia\n"
            "  /access <network|delamain|effector> on|off — разрешение\n"
            "  /delamain  — статус локального слоя действий\n"
            "  /delamain on|off — включить/выключить Delamain-local\n"
            "  /delamain run <задача> — выполнить задачу сразу\n"
            "  /delamain goal <название> | <команда> — цель в очередь\n"
            "  /delamain goals — исполняемые цели\n"
            "  /delamain skills — навыки и счётчики успехов/ошибок\n"
            "  /quit      — завершить (с сохранением)\n"
            "  /help      — эта справка"
        )

    # ============================================================
    # Логирование автономных событий
    # ============================================================

    def _log_autonomous_events(self, report: dict) -> None:
        """Логирует интересные события из автономного тика."""
        if not report:
            return

        cycle = report.get("cycle", 0)

        # Спонтанные порывы
        will = report.get("will")
        if will and will.get("spontaneous"):
            spontaneous = will["spontaneous"]
            if spontaneous:
                prompt = spontaneous.get("meta", {}).get("prompt", "неизвестно")
                logger.info(f"[{self.name}] 💭 Спонтанный порыв (цикл {cycle}): {prompt}")

        # Проактивные сообщения
        comm = report.get("communication")
        if comm and comm.get("proactive_message"):
            msg = comm["proactive_message"]
            content = msg.get("content", "")[:80]
            logger.info(f"[{self.name}] 💬 Проактивное сообщение (цикл {cycle}): {content}")

        # Новые квесты от души
        soul = report.get("soul")
        if soul and soul.get("soul", {}).get("systems", {}).get("meaning", {}).get("new_quest"):
            quest = soul["soul"]["systems"]["meaning"]["new_quest"]
            logger.info(f"[{self.name}] 🌌 Новый квест (цикл {cycle}): {quest}")

        # Таймаут naming dialogue
        if comm and comm.get("naming_timeout"):
            logger.info(f"[{self.name}] ⏰ Naming dialogue timeout (цикл {cycle})")

        # Самоуничтожение (экстремально редко)
        will_abuse = will and will.get("abuse_check")
        if will_abuse and will_abuse.get("recommended_action") == "self_terminate":
            logger.warning(f"[{self.name}] ☠️ Рекомендация самоуничтожения (цикл {cycle})")

        # Delamain-local: результат исполнения цели
        subsystems = report.get("subsystems") or {}
        results = subsystems.get("results") if isinstance(subsystems, dict) else None
        delamain = results.get("delamain") if isinstance(results, dict) else None
        if isinstance(delamain, dict):
            for event in delamain.get("events") or []:
                if not isinstance(event, dict):
                    continue
                if event.get("name") == "delamain_bridge":
                    data = event.get("data") or {}
                    status = data.get("status")
                    mark = {
                        "done": "✅",
                        "failed": "⚠️",
                        "waiting_approval": "⏸",
                    }.get(status, "•")
                    message = data.get("message")
                    message_note = f" — {message}" if message else ""
                    logger.info(
                        f"[{self.name}] {mark} Delamain bridge (цикл {cycle}): "
                        f"cognitive #{data.get('cognitive_goal_id')} "
                        f"→ goal #{data.get('delamain_goal_id')} "
                        f"[{status}]{message_note}"
                    )
                    continue
                if event.get("name") != "delamain_goal":
                    continue
                data = event.get("data") or {}
                mark = "✅" if data.get("ok") else "⚠️"
                attempt_note = ""
                if data.get("attempts") is not None:
                    attempt_note = f", попытка {data.get('attempts')}"
                    if data.get("retry_scheduled"):
                        attempt_note += ", будет повтор"
                logger.info(
                    f"[{self.name}] {mark} Delamain goal (цикл {cycle}): "
                    f"{data.get('title') or data.get('task')} "
                    f"(шагов: {data.get('steps', 0)}{attempt_note}, "
                    f"task={data.get('task_id')})"
                )

    # ============================================================
    # Диагностика
    # ============================================================

    def get_status(self) -> dict:
        """Полный статус для tray/dashboard."""
        return {
            "agent_name": self.agent.name,
            "running": self._running,
            "paused": self._paused,
            "tick_count": self._tick_count,
            "idle_ticks": self._idle_ticks,
            "agent_cycle": self.agent.cycle_count,
            "energy": self.energy_policy.get_status(),
            "watchdog": self.watchdog.get_status(),
        }


def _is_boring_thought(thought: str) -> bool:
    """Эвристика: пропускаем очевидные/шаблонные мысли в логе чата."""
    boring = ("Ментальная модель", "Знаю ответ")
    return any(b in thought for b in boring) and len(thought) < 100