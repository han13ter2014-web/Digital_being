"""Communication facade implementations extracted from ``agent.py``.

The open-questions property intentionally remains in the core class. Cross-
contour learning calls stay on ``self`` so existing monkeypatches keep working.
"""

from typing import Dict, List, Optional

from src.core.buffered_logger import get_logger


def tick_communication_impl(self, cycle_count: int) -> Dict:
    """Единый цикл коммуникации — проверяет инициативу агента.

    Вызывается каждый цикл (можно из main.py или из tick_will).
    Возвращает отчёт о проактивных сообщениях.
    """
    if getattr(self, "_last_communication_tick_cycle", None) == cycle_count:
        return {"cycle": cycle_count, "skipped": "duplicate_cycle"}
    self._last_communication_tick_cycle = cycle_count

    # «Эмоции-1»: затухание эмоций каждый цикл жизни — эмоция тает,
    # покой возвращается. Без тика контур застыл бы на последнем
    # всплеске навсегда.
    emotional_state = getattr(self, "emotional_state", None)
    if emotional_state is not None:
        emotional_state.tick(cycle_count)

    result = {
        "cycle": cycle_count,
        "proactive_message": None,
        "naming_phase": None,
    }

    # 1. NamingDialogue — если в фазе AWAITING_NAME, ничего не делаем.
    #    Пользователь должен сам предложить имя.
    #    Но если таймаут истёк — берём временное имя и продолжаем жить.
    if hasattr(self, "naming_dialogue"):
        result["naming_phase"] = self.naming_dialogue.phase
        timeout_state = self.naming_dialogue.check_timeout(cycle_count)
        if timeout_state == "timeout":
            handled = self.naming_dialogue.handle_timeout(
                agent=self, current_cycle=cycle_count
            )
            result["naming_timeout"] = handled
        elif timeout_state == "warning":
            result["naming_warning"] = (
                f"Диалог об имени скоро истечёт "
                f"({self.naming_dialogue.NAME_TIMEOUT_CYCLES} циклов)"
            )

    # 2. ProactiveCommunication — проверить инициативу
    if hasattr(self, "proactive_communication"):
        msg = self.proactive_communication.maybe_initiate(agent=self, cycle=cycle_count)
        if msg is not None:
            # Отправляем через UserInteraction (новый метод send_message)
            if hasattr(self, "user_interaction"):
                self.user_interaction.send_message(
                    content=msg["content"],
                    msg_type=msg["msg_type"],
                    tone=msg["tone"],
                    urgency=msg.get("urgency", 0.5),
                    context=msg.get("context"),
                    cycle=cycle_count,
                )
            result["proactive_message"] = msg

    return result


def start_naming_dialogue_impl(self, cycle: int = 0) -> Dict:
    """Инициирует диалог об имени (при первом контакте)."""
    if not hasattr(self, "naming_dialogue"):
        return {"status": "no_naming_dialogue"}
    return self.naming_dialogue.initiate_naming_dialogue(
        agent=self,
        cycle=cycle,
    )


def ask_user_impl(
    self, text: str, source: str = "user", max_explorations: Optional[int] = None
) -> Dict:
    """Фасад: поставить открытый вопрос в очередь (логика в OpenQuestionsManager)."""
    if not hasattr(self, "_open_questions_manager"):
        return {"status": "rejected", "reason": "manager не инициализирован"}
    return self._open_questions_manager.ask(
        text, source=source, max_explorations=max_explorations
    )


def hint_to_open_question_impl(self, text: str, hint: str) -> Dict:
    """Фасад: добавить подсказку к существующему вопросу."""
    if not hasattr(self, "_open_questions_manager"):
        return {"status": "rejected", "reason": "manager не инициализирован"}
    return self._open_questions_manager.hint(text, hint)


def drop_open_question_impl(self, text: str) -> Dict:
    """Фасад: удалить открытый вопрос из очереди."""
    if not hasattr(self, "_open_questions_manager"):
        return {"status": "rejected", "reason": "manager не инициализирован"}
    return self._open_questions_manager.drop(text)


def get_open_questions_impl(self) -> List[Dict]:
    """Фасад: получить публичный список открытых вопросов."""
    if not hasattr(self, "_open_questions_manager"):
        return []
    return self._open_questions_manager.list_public()


def has_open_questions_impl(self) -> bool:
    """Фасад: есть ли неотвеченные вопросы?"""
    if not hasattr(self, "_open_questions_manager"):
        return False
    return self._open_questions_manager.has_unanswered()


def answer_open_question_impl(self, text: str) -> Dict:
    """Фасад: принять обычный ответ пользователя на открытый вопрос."""
    if not hasattr(self, "_open_questions_manager"):
        return {"status": "not_found"}
    return self._open_questions_manager.answer(text)


def _on_user_answered_open_question_impl(
    self, question_text: str, answer_text: str
) -> None:
    """Мост «Собеседник-3»: ответ на открытый вопрос → знание о теме.

    Ошибки моста не должны ломать приём ответа: свидетельство —
    обогащение, а не условие работы очереди.
    """
    from src.core.open_questions import _topic_from_question

    topic = _topic_from_question(question_text)
    if not topic:
        return
    try:
        self.record_user_answer(topic, answer_text, self.cycle_count)
    except Exception as exc:
        get_logger().log(f"[KNOWLEDGE] свидетельство не записано: {exc}")


def record_user_answer_impl(
    self, topic: str, answer: str, cycle: int = 0
) -> Optional[str]:
    """Записать объяснение пользователя как знание-свидетельство.

    Ответ человека на вопрос сущности становится опытом концепта
    (kind=testimony, source="user", сила 0.4: доверие взрослому
    собеседнику, но не собственное наблюдение) — и штампом цикла,
    чтобы тема не переспрашивалась (USER_EXPLAINED_COOLDOWN_CYCLES).

    Граница субъектности: слова человека не становятся ценностями
    или мотивацией — только факт «человек так это объяснил».

    Returns:
        Нормализованная тема или None, если записывать нечего.
    """
    normalized = " ".join(str(topic or "").split())
    if not normalized or not self._is_learnable(normalized):
        return None
    answer_text = " ".join(str(answer or "").split())
    if not answer_text:
        return None

    stamps = self._user_explained_topics
    stamps[normalized] = int(cycle)
    if len(stamps) > 50:
        for old_topic, _stamp in sorted(stamps.items(), key=lambda item: item[1])[
            : len(stamps) - 50
        ]:
            stamps.pop(old_topic, None)

    if hasattr(self, "mental_models"):
        self.mental_models.encounter_concept(
            normalized,
            context=f"объяснение пользователя (цикл {int(cycle)})",
            outcome=answer_text[:300],
            evidence_strength=0.4,
            evidence_kind="testimony",
            source="user",
        )
        get_logger().log(
            f"[KNOWLEDGE] свидетельство пользователя о «{normalized}»: "
            f"{answer_text[:60]}"
        )
    return normalized


def mute_topic_impl(self, topic: str, cycle: int = 0) -> Optional[str]:
    """Человек попросил не возвращаться к теме («ты повторяешься»).

    «Собеседник-5»: только штамп цикла в ``_user_explained_topics`` —
    БЕЗ записи концепта и без свидетельства: объяснения не было,
    было требование тишины. Граница: замолкает лишь тема, которую
    сущность действительно спрашивала (в истории вопросов или
    сейчас в ожидании); случайная строка из протеста не мьютится.

    Returns:
        Нормализованная тема или None, если мьютить нечего.
    """
    normalized = " ".join(str(topic or "").split())
    if not normalized or not self._is_learnable(normalized):
        return None
    lower = normalized.lower()
    interaction = getattr(self, "user_interaction", None)
    asked_before = False
    if interaction is not None:
        for entry in getattr(interaction, "question_history", []) or []:
            question = " ".join(str(entry.get("question") or "").lower().split())
            if lower in question:
                asked_before = True
                break
        if not asked_before:
            for pending in getattr(interaction, "pending_questions", []) or []:
                question = " ".join(str(pending.get("question") or "").lower().split())
                if lower in question:
                    asked_before = True
                    break
    if not asked_before:
        return None
    self._user_explained_topics[normalized] = int(cycle)
    get_logger().log(f"[MUTE] человек попросил не возвращаться к «{normalized}»")
    return normalized


def _consume_open_question_impl(self) -> Optional[str]:
    """Фасад: взять следующий стимул для размышления над вопросом."""
    if not hasattr(self, "_open_questions_manager"):
        return None
    return self._open_questions_manager.consume()


def _record_open_question_exploration_impl(
    self, stimulus: str, thought: str, strategy: Optional[str] = None
) -> None:
    """Фасад: записать результат размышления."""
    if not hasattr(self, "_open_questions_manager"):
        return
    self._open_questions_manager.record_exploration(stimulus, thought, strategy)


def propose_name_impl(self, name: str, cycle: int = 0) -> Dict:
    """Пользователь предлагает имя агенту."""
    if not hasattr(self, "naming_dialogue"):
        return {"status": "no_naming_dialogue"}
    return self.naming_dialogue.process_name_proposal(
        name,
        agent=self,
        cycle=cycle,
    )


def request_renaming_impl(
    self, reason: str = "вырос из старого имени", cycle: int = 0
) -> Dict:
    """Агент сам просит переименовать."""
    if not hasattr(self, "naming_dialogue"):
        return {"status": "no_naming_dialogue"}
    return self.naming_dialogue.request_renaming(
        reason,
        agent=self,
        cycle=cycle,
    )


def add_quiet_app_impl(self, app_name: str) -> None:
    """Добавляет приложение в quiet hours (не беспокоить)."""
    if hasattr(self, "proactive_communication"):
        self.proactive_communication.add_quiet_app(app_name)
    if hasattr(self, "user_interaction"):
        self.user_interaction.add_quiet_app(app_name)
    if hasattr(self, "user_quiet_hours"):
        self.user_quiet_hours[app_name] = True


def remove_quiet_app_impl(self, app_name: str) -> None:
    """Убирает приложение из quiet hours."""
    if hasattr(self, "proactive_communication"):
        self.proactive_communication.remove_quiet_app(app_name)
    if hasattr(self, "user_interaction"):
        self.user_interaction.remove_quiet_app(app_name)
    if hasattr(self, "user_quiet_hours"):
        self.user_quiet_hours[app_name] = False


def get_communication_stats_impl(self) -> Dict:
    """Возвращает статистику проактивной коммуникации."""
    if not hasattr(self, "proactive_communication"):
        return {}
    return self.proactive_communication.get_stats()
