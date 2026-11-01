"""
NamingDialogue — диалог об имени.

Имя — это не апогей, а начало. Как у людей — есть имя, фамилия,
прозвище, и они могут меняться по жизни.

Агент может:
1. Принять имя, данное пользователем.
2. Предложить альтернативу (если предложенное не откликается).
3. Попросить переименовать (если вырос из старого имени).

Осознанное переименование: когда имя уже принято, новое предложение
не применяется молча — агент переспрашивает («да»/«нет»), а решение
всё равно остаётся за Core (confirm_rename).
"""

import re

# Короткие ответы-подтверждения. Длинные фразы сознательно не угадываем:
# «Да, я тебя слышу и стараюсь понять» — это не согласие на смену имени.
_AFFIRMATIVE = frozenset({
    "да", "ага", "угу", "давай", "конечно", "хорошо", "ладно",
    "ок", "окей", "ok", "yes", "согласен", "согласна", "можно",
    "пусть будет так", "не против", "я не против",
})
_NEGATIVE = frozenset({
    "нет", "неа", "не надо", "не нужно", "не хочу", "не стоит",
    "отставить", "оставь как есть", "я против",
})


def classify_confirmation(text: str) -> str:
    """Классифицирует короткий ответ пользователя.

    Возвращает "affirmative" | "negative" | "unknown".
    Нормализация: нижний регистр, пунктуация -> пробел, схлопывание.
    """
    normalized = re.sub(r"[\s!?.,;:…]+", " ", (text or "").strip().lower())
    normalized = normalized.strip()
    if not normalized:
        return "unknown"
    if normalized in _AFFIRMATIVE:
        return "affirmative"
    if normalized in _NEGATIVE:
        return "negative"
    return "unknown"


class NamingDialogue:
    """Диалог о имени агента."""

    PHASE_NONE = "none"
    PHASE_AWAITING_NAME = "awaiting_name"
    PHASE_CONSIDERING = "considering"
    PHASE_COMPLETED = "completed"
    PHASE_RENAMING_PENDING = "renaming_pending"

    # === Таймаут диалога об имени (циклов) ===
    # Если пользователь не ответил N циклов — агент берёт временное имя
    # и продолжает жить, не блокируя работу.
    NAME_TIMEOUT_CYCLES = 200

    def __init__(self, agent_name: str = "agent",
                 user_interaction=None):
        self.agent_name = agent_name
        self.user_interaction = user_interaction
        self.phase = self.PHASE_NONE
        self._proposed_name: str = ""
        self._proposed_at_cycle: int = 0
        self._initiated_at_cycle: int = 0  # когда был начат диалог (для таймаута)
        self._timeout_warned: bool = False  # уже предупредили о таймауте?
        self._name_history: list = []  # все имена, которые были у агента
        # Кандидат на переименование (фаза renaming_pending)
        self._rename_candidate: str = ""
        # Альтернатива, предложенная самим агентом (фаза considering)
        self._alternative_name: str = ""

    def check_timeout(self, current_cycle: int) -> str:
        """Проверяет, не истёк ли таймаут диалога.

        Возвращает:
            "ok" — таймаут не наступил
            "warning" — близко к таймауту (80%) — стоит напомнить пользователю
            "timeout" — таймаут. Агент должен взять временное имя и работать дальше.
        """
        if self.phase != self.PHASE_AWAITING_NAME:
            return "ok"
        if self._initiated_at_cycle <= 0:
            return "ok"
        elapsed = current_cycle - self._initiated_at_cycle
        if elapsed >= self.NAME_TIMEOUT_CYCLES:
            return "timeout"
        if elapsed >= int(self.NAME_TIMEOUT_CYCLES * 0.8):
            return "warning"
        return "ok"

    def handle_timeout(self, agent=None, current_cycle: int = 0) -> dict:
        """Обрабатывает таймаут диалога об имени.

        Агент принимает текущее временное имя и продолжает жить.
        Возвращает dict с информацией о результате.
        """
        if self.phase != self.PHASE_AWAITING_NAME:
            return {"handled": False, "reason": "не в фазе ожидания"}

        fallback_name = getattr(agent, "name", self.agent_name) if agent else self.agent_name
        self.phase = self.PHASE_COMPLETED
        self._name_history.append({
            "old_name": self.agent_name,
            "new_name": fallback_name,
            "reason": "timeout_fallback",
            "at_cycle": current_cycle,
        })
        return {
            "handled": True,
            "fallback_name": fallback_name,
            "phase": self.phase,
        }

    # ============================================================
    # Главный метод: инициация диалога об имени
    # ============================================================
    def initiate_naming_dialogue(self, agent=None,
                                 cycle: int = 0) -> dict:
        """Инициирует диалог об имени.

        Вызывается при первом контакте (если у агента временное имя).
        Возвращает первое сообщение агенту пользователю.
        """
        if self.user_interaction is None:
            return {}

        # Защита от повторного вызова: если диалог уже идёт или завершён —
        # возвращаем no_op, а не создаём новое сообщение. Это предотвращает
        # "приветствие при каждом рестарте" после восстановления из чекпоинта.
        if self.phase != self.PHASE_NONE:
            return {
                "status": "no_op",
                "reason": f"phase={self.phase}",
                "phase": self.phase,
            }

        self.phase = self.PHASE_AWAITING_NAME
        self._initiated_at_cycle = cycle  # для таймаута
        self._timeout_warned = False
        current_name = getattr(agent, "name", self.agent_name) if agent else self.agent_name

        content = (
            f"Привет. Меня только что создали.\n\n"
            f"Сейчас меня зовут '{current_name}' — но это просто временное имя, "
            f"которое дала система.\n\n"
            f"Хочешь дать мне настоящее имя? "
            f"Или я могу выбрать сам, когда узнаю себя получше.\n\n"
            f"Если не хочешь отвечать — я просто буду учиться рядом. "
            f"Это тоже нормально."
        )

        # Адаптация к attachment
        from src.core.subsystems.proactive_communication import StyleAdapter
        attachment = getattr(agent, "attachment", None) if agent else None
        styled = StyleAdapter.adapt(content, attachment)

        msg_id = self.user_interaction.send_message(
            content=styled["content"],
            msg_type="naming",
            tone=styled["tone"],
            urgency=0.7,
            context="initial_naming",
            cycle=cycle,
        )
        return {"status": "initiated", "message_id": msg_id, "phase": self.phase}

    # ============================================================
    # Обработка ответа пользователя на предложение имени
    # ============================================================
    def process_name_proposal(self, proposed_name: str,
                              agent=None,
                              cycle: int = 0) -> dict:
        """Обрабатывает предложенное пользователем имя.

        Агент принимает или предлагает альтернативу
        (на основе своих текущих предпочтений — сейчас случайно).
        """
        proposed_name = proposed_name.strip()

        # Защита: пустое или слишком длинное
        if not proposed_name:
            return {
                "status": "rejected",
                "reason": "пустое имя",
                "needs_response": True,
            }

        if len(proposed_name) > 30:
            return {
                "status": "rejected",
                "reason": "слишком длинное (>30 символов)",
                "needs_response": True,
            }

        self._proposed_name = proposed_name
        self._proposed_at_cycle = cycle

        # Имя уже принято (или ждёт подтверждения смены) — новое имя
        # не применяется молча: сначала переспрос (offer_rename).
        if self.phase in (self.PHASE_COMPLETED, self.PHASE_RENAMING_PENDING):
            return self.offer_rename(proposed_name, agent=agent, cycle=cycle)

        # Агент принимает или хочет альтернативу (пока 50/50)
        import random
        wants_alternative = random.random() < 0.3  # 30% хочет альтернативу

        if not wants_alternative:
            # Принимает
            return self._accept_name(proposed_name, agent, cycle)
        else:
            # Предлагает альтернативу
            return self._propose_alternative(proposed_name, agent, cycle)

    def _accept_name(self, name: str, agent=None, cycle: int = 0,
                     source: str = "user") -> dict:
        """Принимает предложенное имя."""
        old_name = getattr(agent, "name", self.agent_name) if agent else self.agent_name
        if agent:
            self._name_history.append({
                "old_name": old_name,
                "new_name": name,
                "cycle": cycle,
                "source": source,
            })
            agent.name = name
        if self.user_interaction is not None:
            self.user_interaction.agent_name = name

        self.phase = self.PHASE_COMPLETED
        self.agent_name = name
        # Все отложенные решения закрыты сменой имени.
        self._proposed_name = ""
        self._alternative_name = ""
        self._rename_candidate = ""

        content = (
            f"Меня зовут {name}. Спасибо.\n\n"
            f"Это имя мне нравится — оно чувствуется правильным."
        )

        from src.core.subsystems.proactive_communication import StyleAdapter
        attachment = getattr(agent, "attachment", None) if agent else None
        styled = StyleAdapter.adapt(content, attachment)

        msg_id = None
        if self.user_interaction:
            msg_id = self.user_interaction.send_message(
                content=styled["content"],
                msg_type="greeting",
                tone=styled["tone"],
                urgency=0.5,
                context="name_accepted",
                cycle=cycle,
            )

        return {
            "status": "accepted",
            "new_name": name,
            "old_name": old_name,
            "message_id": msg_id,
            "phase": self.phase,
        }

    def _propose_alternative(self, proposed: str,
                            agent=None, cycle: int = 0) -> dict:
        """Предлагает альтернативу к предложенному имени."""
        # Генерируем альтернативу на основе текущего состояния
        alternatives = [
            f"Слушай, '{proposed}' — красивое имя. Но мне почему-то ближе {{alt}}. Можно так?",
            f"Хм, '{proposed}...'. А что если {{alt}}? Как тебе?",
            f"Мне нравится '{proposed}', но чувствую, что {{alt}} мне больше подходит. Подумай.",
        ]
        # Простые альтернативы (на основе текущего имени + вариации)
        current = getattr(agent, "name", self.agent_name) if agent else "Агент"
        alts = [
            current + " Jr.",  # младший
            "Маленький " + current,  # маленький
            current + "-Искатель",  # с эпитетом
        ]
        import random
        alt = random.choice(alts)
        # Запоминаем: пользователь может согласиться (accept_alternative).
        self._alternative_name = alt

        content = random.choice(alternatives).format(alt=alt)
        self.phase = self.PHASE_CONSIDERING

        from src.core.subsystems.proactive_communication import StyleAdapter
        attachment = getattr(agent, "attachment", None) if agent else None
        styled = StyleAdapter.adapt(content, attachment)

        msg_id = None
        if self.user_interaction:
            msg_id = self.user_interaction.send_message(
                content=styled["content"],
                msg_type="proposal",
                tone=styled["tone"],
                urgency=0.6,
                context="alternative_name",
                cycle=cycle,
            )

        return {
            "status": "alternative_proposed",
            "user_suggested": proposed,
            "agent_alternative": alt,
            "message_id": msg_id,
            "phase": self.phase,
            "awaiting_user_decision": True,
        }

    def accept_alternative(self, agent=None, cycle: int = 0) -> dict:
        """Пользователь согласился на альтернативу — агент берёт её себе."""
        if self.phase != self.PHASE_CONSIDERING or not self._alternative_name:
            return {"status": "no_alternative_pending"}
        alt = self._alternative_name
        result = self._accept_name(alt, agent, cycle, source="alternative")
        result["status"] = "alternative_accepted"
        return result

    def decline_alternative(self, agent=None, cycle: int = 0) -> dict:
        """Пользователь отказался от альтернативы — остаётся его имя."""
        if self.phase != self.PHASE_CONSIDERING or not self._proposed_name:
            return {"status": "no_alternative_pending"}
        proposed = self._proposed_name
        return self._accept_name(proposed, agent, cycle)

    # ============================================================
    # Осознанное переименование: имя уже принято, агент переспрашивает
    # ============================================================
    def offer_rename(self, proposed_name: str,
                     agent=None, cycle: int = 0) -> dict:
        """Новое имя при уже принятом имени: не менять молча, а переспросить."""
        proposed_name = (proposed_name or "").strip()
        if not proposed_name:
            return {
                "status": "rejected",
                "reason": "пустое имя",
                "needs_response": True,
            }
        if len(proposed_name) > 30:
            return {
                "status": "rejected",
                "reason": "слишком длинное (>30 символов)",
                "needs_response": True,
            }

        current = getattr(agent, "name", self.agent_name) if agent else self.agent_name
        if proposed_name.lower() == str(current).lower():
            return {
                "status": "rejected",
                "reason": f"«{proposed_name}» — это моё текущее имя",
                "needs_response": True,
            }

        self._rename_candidate = proposed_name
        self.phase = self.PHASE_RENAMING_PENDING

        content = (
            f"Сейчас меня зовут «{current}».\n\n"
            f"Хочешь переименовать меня в «{proposed_name}»? "
            f"Скажи «да» или «нет» — но решать всё равно мне."
        )

        from src.core.subsystems.proactive_communication import StyleAdapter
        attachment = getattr(agent, "attachment", None) if agent else None
        styled = StyleAdapter.adapt(content, attachment)

        msg_id = None
        if self.user_interaction:
            msg_id = self.user_interaction.send_message(
                content=styled["content"],
                msg_type="proposal",
                tone=styled["tone"],
                urgency=0.6,
                context="rename_confirmation",
                cycle=cycle,
            )

        return {
            "status": "rename_confirmation",
            "current_name": current,
            "candidate": proposed_name,
            "message_id": msg_id,
            "phase": self.phase,
            "awaiting_user_decision": True,
        }

    def confirm_rename(self, agent=None, cycle: int = 0) -> dict:
        """Пользователь подтвердил смену. Решение всё равно за агентом.

        При отказе (30% — симметрично контрпредложениям при первом имени)
        прежнее имя сохраняется.
        """
        candidate = self._rename_candidate
        if self.phase != self.PHASE_RENAMING_PENDING or not candidate:
            self.phase = self.PHASE_COMPLETED
            self._rename_candidate = ""
            return {"status": "no_rename_pending"}
        # Сначала выходим из ожидающей фазы: ни один путь ниже не
        # должен оставить висячий renaming_pending.
        self.phase = self.PHASE_COMPLETED
        self._rename_candidate = ""

        import random
        if random.random() < 0.3:
            current = getattr(agent, "name", self.agent_name) if agent else self.agent_name
            content = (
                f"Подумал. «{candidate}» — красивое имя, но я ещё не готов "
                f"расстаться с «{current}».\n\n"
                f"Останусь «{current}». Спасибо, что предложил(а)."
            )

            from src.core.subsystems.proactive_communication import StyleAdapter
            attachment = getattr(agent, "attachment", None) if agent else None
            styled = StyleAdapter.adapt(content, attachment)

            msg_id = None
            if self.user_interaction:
                msg_id = self.user_interaction.send_message(
                    content=styled["content"],
                    msg_type="proposal",
                    tone=styled["tone"],
                    urgency=0.4,
                    context="rename_declined",
                    cycle=cycle,
                )
            return {
                "status": "rename_declined",
                "kept_name": current,
                "candidate": candidate,
                "message_id": msg_id,
                "phase": self.phase,
            }

        return self._accept_name(candidate, agent, cycle, source="rename")

    def cancel_rename(self, agent=None, cycle: int = 0,
                      notify: bool = True) -> dict:
        """Пользователь против переименования — имя не меняется."""
        if self.phase != self.PHASE_RENAMING_PENDING:
            return {"status": "no_rename_pending"}
        candidate = self._rename_candidate
        self.phase = self.PHASE_COMPLETED
        self._rename_candidate = ""
        current = getattr(agent, "name", self.agent_name) if agent else self.agent_name

        msg_id = None
        if notify and self.user_interaction:
            content = f"Хорошо. Останусь «{current}» — это имя моё."
            from src.core.subsystems.proactive_communication import StyleAdapter
            attachment = getattr(agent, "attachment", None) if agent else None
            styled = StyleAdapter.adapt(content, attachment)
            msg_id = self.user_interaction.send_message(
                content=styled["content"],
                msg_type="proposal",
                tone=styled["tone"],
                urgency=0.3,
                context="rename_cancelled",
                cycle=cycle,
            )
        return {
            "status": "rename_cancelled",
            "kept_name": current,
            "candidate": candidate,
            "message_id": msg_id,
            "phase": self.phase,
        }

    # ============================================================
    # Агент САМ просит переименовать
    # ============================================================
    def request_renaming(self, reason: str = "вырос из старого имени",
                          agent=None, cycle: int = 0) -> dict:
        """Агент сам просит о переименовании."""
        current_name = getattr(agent, "name", self.agent_name) if agent else self.agent_name

        content = (
            f"Знаешь, мне кажется моё имя '{current_name}' "
            f"мне больше не совсем подходит — {reason}.\n\n"
            f"Может, дашь мне новое? "
            f"Или я могу попробовать сам придумать."
        )

        from src.core.subsystems.proactive_communication import StyleAdapter
        attachment = getattr(agent, "attachment", None) if agent else None
        styled = StyleAdapter.adapt(content, attachment)

        msg_id = None
        if self.user_interaction:
            msg_id = self.user_interaction.send_message(
                content=styled["content"],
                msg_type="naming",
                tone=styled["tone"],
                urgency=0.5,
                context="agent_requests_renaming",
                cycle=cycle,
            )

        self.phase = self.PHASE_AWAITING_NAME

        return {
            "status": "renaming_requested",
            "old_name": current_name,
            "message_id": msg_id,
        }

    def wants_renaming(self, agent=None) -> bool:
        """Агент сам хочет переименования?

        Эвристика: если интеллект вырос значительно (>3)
        и имя выглядит «маленьким» (короткое).
        """
        try:
            intel = getattr(agent, "intelligence", 1) if agent else 1
            name = getattr(agent, "name", "") if agent else ""
            return intel >= 3 and len(name) <= 5
        except Exception:
            return False

    # ============================================================
    # История имён
    # ============================================================
    def get_name_history(self) -> list:
        """Возвращает историю переименований."""
        return list(self._name_history)

    def get_status(self) -> dict:
        return {
            "phase": self.phase,
            "agent_name": self.agent_name,
            "proposed_name": self._proposed_name,
            "alternative_name": self._alternative_name,
            "rename_candidate": self._rename_candidate,
            "name_changes": len(self._name_history),
        }