"""Central action dispatcher extracted from ``agent.py``.

``DigitalBeing`` and ``record_denied_outcome`` are keyword-only injections so
class-qualified lookup and the core monkeypatch surface remain unchanged.
Handlers and autonomous-tick methods stay behind the facade.
"""

import gc

from config.simulation_config import LR_CONFIG, SIM_CONFIG
from src.core.agent_body import ESSENTIAL_ACTIONS, RECOVERY_ACTIONS, step_body
from src.core.buffered_logger import get_logger
from src.core.world_delta import capture


def _wire_action_outcome_emotion(agent, action_type: str, outcome) -> None:
    """«Эмоции-1» (k16-03): окрашивать исход исполненного действия.

        success (эффект есть) — joy, промах после исполнения — sadness.
        Вызывается только для исполненных действий: отказы (denied)
        выходят из act() раньше и не переживаются — эмоция окрашивает
        факт, а не намерение. Guard обязателен: act() работает и в
        лёгких объектах без emotional_state.
        """
    emotional_state = getattr(agent, "emotional_state", None)
    if emotional_state is None or outcome is None:
        return
    if outcome.had_effect:
        emotional_state.handle_event(
            "intention_completed", cycle=agent.cycle_count,
            cause=action_type,
        )
    else:
        emotional_state.handle_event(
            "intention_failed", cycle=agent.cycle_count,
            cause=action_type,
        )


def _wire_execution_exception_emotion(agent, action) -> None:
    """«Эмоции-1» (k16-03): падение исполнения — тоже промах.

        Событие то же, что у исполненного-впустую действия (k15: ветка
        исключений не имела проводки). Guard обязателен.
        """
    emotional_state = getattr(agent, "emotional_state", None)
    if emotional_state is None:
        return
    emotional_state.handle_event(
        "intention_failed", cycle=agent.cycle_count,
        cause=str(action),
    )


def act_impl(self, decision: str, *, intention=None, DigitalBeing, record_denied_outcome) -> str:
    """Действие на основе мышления с учетом разных затрат энергии.

        Args:
            decision: описание действия (результат think()).

        Returns:
            Отформатированная строка действия ("Ответ: ...").

        Побочный эффект: снимает подпись мира до и после действия и
        регистрирует исход в ``self.loop_closer``. Благодаря этому
        появляется ответ на вопрос «действие что-то изменило?», без
        которого цели не могут двигаться, а бесполезные действия
        повторяются бесконечно.
        """
    from src.cognition.intention_payload import intention_target

    selected_target = intention_target(intention)
    creative_choice = None
    if DigitalBeing.ACTION_ALIASES.get(str(decision).strip().lower()) == "create_draft":
        from src.cognition.creative_catalog import creative_request

        creative_choice = creative_request(intention)
    world_before = capture(self)
    action = f"Ответ: {decision}"
    topic = ""

    # === Определяем тип действия и его стоимость ===
    decision_str = str(decision).lower()

    if "гипотеза" in decision_str:
        action_type = "hypothesis"
    elif "декомпозиц" in decision_str:
        action_type = "decomposition"
    elif ("не нашел" in decision_str
          or "не нашёл" in decision_str
          or "не найдено" in decision_str):
        # «Сироты-1» (k16-10): отрицательные формулировки проверяются
        # РАНЬШЕ «нашёл ответ». Раньше подстрока «нашёл» матчила внутри
        # «не нашёл», и промах классифицировался как know_answer —
        # успех молча и неверно.
        action_type = "search_miss"
    elif ("ментальная модель" in decision_str
          or "знаю ответ" in decision_str
          or "нашел ответ" in decision_str
          or "нашёл ответ" in decision_str):
        action_type = "know_answer"
    elif "пользователь ответил" in decision_str:
        action_type = "user_answer"
    elif "repair" in decision_str or "ремонт" in decision_str:
        action_type = "repair"
    elif "deep_rest" in decision_str or "глубокий отдых" in decision_str:
        action_type = "deep_rest"
    elif "checkpoint" in decision_str:
        action_type = "checkpoint_now"
    elif decision_str.strip() in self.ACTION_ALIASES:
        # Действия от Active Inference / арбитра: «explore», «rest»,
        # «think_decompose», «synthesize», «ask_user».
        action_type = self.ACTION_ALIASES[decision_str.strip()]
    else:
        action_type = "default"

    self._action_type_counts[action_type] = (
        self._action_type_counts.get(action_type, 0) + 1
    )
    # Тип действия — в логе, иначе метрика «смысла» не восстанавливается
    # из истории после перезапуска.
    get_logger().log(f"Выполняет [{action_type}]: {action}")

    base_cost = self._get_adaptive_cost(action_type)

    # === Интероцепция: модулируем стоимость и проверяем возможность ===
    # Восстановительные и служебные действия (отдых, ремонт, чекпоинт)
    # не проверяются на усталость: запрещать отдых уставшему — значит
    # запирать его в истощении навсегда. Замер до правки: 243 отказа
    # «too_tired» на 400 попыток, включая сами попытки отдохнуть.
    if action_type in ESSENTIAL_ACTIONS:
        cost = 0.0 if action_type in RECOVERY_ACTIONS else base_cost
    elif hasattr(self, 'interoception') and self.interoception:
        cost = self.interoception.get_action_cost(base_cost)
        if not self.interoception.can_perform_action(base_cost, self.energy):
            get_logger().log(f"[INTEROCEPTION] Too exhausted for {action_type} (cost={cost:.1f}, energy={self.energy})")
            # Отказ — тоже исход: мир не изменился. Без записи
            # действие не гаснет и выбирается снова и снова.
            step_body(self, action_type, performed=False)
            record_denied_outcome(self, action_type, world_before, "too_tired")
            return f"Ответ: Слишком устала для {action_type}"
    else:
        cost = base_cost

    # === Stage 19: одно бюджетное решение на действие ===
    # Бюджет читает и пишет ту же энергию агента. При выключенном флаге
    # он лишь повторяет прежнее ``self.energy -= cost``.
    budget = getattr(self, "action_budget", None)
    if budget is not None:
        decision = budget.charge(
            action_type=action_type,
            cost=cost,
            source="core_act",
        )
        if not decision.allowed:
            get_logger().log(
                f"[BUDGET] denied {action_type}: {decision.reason} "
                f"(cost={decision.cost:.1f}, energy={decision.energy_before:.1f})"
            )
            step_body(self, action_type, performed=False)
            record_denied_outcome(self, action_type, world_before, "budget")
            return (
                f"Ответ: Бюджет не разрешает {action_type}: "
                f"{decision.reason}"
            )
        # Стоимость реально списана — запоминаем для права на ошибку.
        self._last_action_cost = float(decision.cost)
    else:
        self.energy -= cost
        self._last_action_cost = float(cost)

    expectation_trial = None
    expectations = None
    # Узкое доказательство результата для действий, чей полезный эффект
    # не выражается в общей подписи знаний. Заполняет только обработчик
    # после фактического изменения; сам вызов действия успехом не считается.
    confirmed_result = False
    result_description = ""
    if action_type in ("rest", "deep_rest") and getattr(self, "mental_models", None) is not None:
        from src.cognition.action_expectations import ActionExpectations

        expectations = getattr(self, "action_expectations", None)
        if expectations is None:
            expectations = self.action_expectations = ActionExpectations()
        expectation_trial = expectations.begin(
            self.mental_models, action_type, float(self.energy),
            float(getattr(LR_CONFIG, "ENERGY_MAX", 200)),
            fatigue=getattr(getattr(getattr(self, "interoception", None), "state", None), "fatigue", None),
        )

    # === Death Risk actions: выполняем реальную логику восстановления ===
    if action_type == "repair":
        if hasattr(self, 'death_risk') and self.death_risk:
            changes = self.death_risk.integrity.manual_repair(intensity=2.0)
            get_logger().flush_immediate(f"[DEATH_RISK] Manual repair: {changes}")
    elif action_type == "deep_rest":
        # Тело «живёт» этот такт централизованно, в конце act():
        # см. step_body(action_type). Здесь только восстановление
        # энергии агента и работа сна.
        recover = getattr(self, "_recover_energy", None)
        recovered = recover(deep=True) if recover else 0.0
        consolidate = getattr(self, "_accumulate_sleep", None)
        consolidated = consolidate(1.0) if consolidate else {}
        parts = []
        if recovered:
            confirmed_result = True
            result_description = f"энергия восстановлена на {recovered:.0f}"
            parts.append(
                f"восстановила {recovered:.0f} энергии (теперь {self.energy:.0f})"
            )
        if consolidated:
            parts.append(
                f"осмыслила накопленное: связей {consolidated.get('links', 0)}, "
                f"формулировок {consolidated.get('definitions', 0)}"
            )
        if parts:
            action = "Ответ: " + "; ".join(parts)
    elif action_type == "checkpoint_now":
        if hasattr(self, 'death_risk') and self.death_risk:
            self.death_risk.force_checkpoint()
            get_logger().flush_immediate("[DEATH_RISK] Manual checkpoint created")
    # Обработчики действий вызываются через getattr: act() работает и в
    # лёгких объектах (тесты бюджета, заглушки), где их нет. Отсутствие
    # обработчика — не ошибка: действие остаётся без эффекта.
    elif action_type == "let_go":
        from src.cognition.intention_waiting import resolve_wait

        params = intention or {}
        values = params.get("params", {})
        decision = resolve_wait(self, values.get("action", "explore"), values.get("topic", ""),
                                kind="forgotten", reason=values.get("reason", "сама решила отпустить"))
        action = f"Ответ: отпустила намерение '{values.get('topic', '')}' ({decision['status']})"
    elif action_type == "create_draft":
        from src.cognition.creative_catalog import perform_creative

        mode, identifier, reason = creative_choice
        draft = perform_creative(self, mode, identifier, reason)
        verb = "оставила" if mode == "leave" else "создала" if mode == "new" else "продолжила"
        action = f"Ответ: {verb} черновик «{draft['theme']}», версия {draft['revision']}"
    elif action_type == "play":
        from src.cognition.local_play import (
            guess_turn,
            new_game,
            new_guess_game,
            play_turn,
        )

        # Две игры. Выбор — та, где сыграно меньше партий: опыт
        # распределяется ровно, а не залипает на первой игре.
        ttt = getattr(self, "_local_play", None)
        guess = getattr(self, "_local_guess", None)
        ttt_rounds = (ttt or {}).get("round", 0)
        guess_rounds = (guess or {}).get("round", 0)
        if guess_rounds < ttt_rounds:
            if guess is None:
                guess = self._local_guess = new_guess_game()
            turn = guess_turn(guess)
            self._last_play_result = turn
            action = (
                f"Ответ: угадываю число — назвала {turn['guess']} "
                f"({turn['hint']}), попытка {turn['attempts']}"
            )
            if turn["result"] is not None:
                action += (
                    f"; партия {turn['round']} выиграна "
                    f"за {turn['attempts']} попыток"
                )
        else:
            state = ttt
            if state is None:
                state = self._local_play = new_game()
            turn = play_turn(state)
            self._last_play_result = turn
            action = f"Ответ: сыграла ход {turn['chosen_cell'] + 1}; поле {''.join(turn['board'])}"
            if turn["result"] is not None:
                action += f"; партия завершена: {turn['result']}"
        # Вернувшийся ход уже изменил состояние выбранной игры. Исход
        # партии не требуется: проигрыш и ничья — тоже результат хода.
        confirmed_result = True
        result_description = f"выполнен игровой ход в партии {turn['round']}"
    elif action_type == "explore":
        # Раньше «explore» ничего не делал: тип «default», энергия
        # списывалась, мир не менялся. Теперь это настоящая работа —
        # выбрать слабое место в знаниях и поработать над ним.
        handler = getattr(self, "_act_explore", None)
        target = selected_target
        exploration = (handler(target=target) if target else handler()) if handler else None
        topic = (exploration or {}).get("target") or ""
        action = (exploration or {}).get("text") or action
    elif action_type == "rest":
        recover = getattr(self, "_recover_energy", None)
        recovered = recover(deep=False) if recover else 0.0
        consolidate = getattr(self, "_accumulate_sleep", None)
        consolidated = consolidate(0.5) if consolidate else {}
        parts = []
        if recovered:
            parts.append(
                f"восстановила {recovered:.0f} энергии (теперь {self.energy:.0f})"
            )
        if consolidated:
            parts.append(
                f"осмыслила накопленное: связей {consolidated.get('links', 0)}, "
                f"формулировок {consolidated.get('definitions', 0)}"
            )
        if parts:
            action = "Ответ: " + "; ".join(parts)
    elif action_type == "synthesis":
        handler = getattr(self, "_act_synthesize", None)
        synthesis = (handler(target=selected_target) if selected_target else handler()) if handler else None
        topic = (synthesis or {}).get("target") or ""
        action = (synthesis or {}).get("text") or action
    elif action_type == "decomposition":
        handler = getattr(self, "_act_decompose", None)
        target = selected_target
        decomposition = (handler(target=target) if target else handler()) if handler else None
        topic = (decomposition or {}).get("target") or ""
        action = (decomposition or {}).get("text") or action
    elif action_type == "reflection":
        handler = getattr(self, "_act_reflect", None)
        reflection = handler() if handler else None
        action = (reflection or {}).get("text") or action
    elif action_type == "ask_user":
        handler = getattr(self, "_act_ask_user", None)
        asked = (handler(target=selected_target) if selected_target else handler()) if handler else None
        topic = (asked or {}).get("target") or ""
        action = (asked or {}).get("text") or action
    elif action_type == "communicate":
        handler = getattr(self, "_act_communicate", None)
        told = handler() if handler else None
        action = (told or {}).get("text") or action
    elif action_type == "web_search":
        handler = getattr(self, "_act_web_search", None)
        found = (handler(target=selected_target) if selected_target else handler()) if handler else None
        topic = (found or {}).get("target") or ""
        action = (found or {}).get("text") or action
    elif action_type == "read_news":
        handler = getattr(self, "_act_read_news", None)
        news = handler() if handler else None
        topic = (news or {}).get("target") or ""
        action = (news or {}).get("text") or action
    elif action_type == "browse_web":
        handler = getattr(self, "_act_browse_web", None)
        browsed = handler() if handler else None
        topic = (browsed or {}).get("target") or ""
        action = (browsed or {}).get("text") or action
    elif action_type == "draw":
        handler = getattr(self, "_act_draw", None)
        drawn = handler() if handler else None
        topic = (drawn or {}).get("target") or ""
        action = (drawn or {}).get("text") or action
    elif action_type == "compose_music":
        handler = getattr(self, "_act_compose_music", None)
        composed = handler() if handler else None
        topic = (composed or {}).get("target") or ""
        action = (composed or {}).get("text") or action
    elif action_type == "hypothesis":
        handler = getattr(self, "_act_hypothesis", None)
        guess = handler() if handler else None
        topic = (guess or {}).get("target") or ""
        action = (guess or {}).get("text") or action
    elif action_type == "set_own_goal":
        handler = getattr(self, "_act_set_own_goal", None)
        own = handler() if handler else None
        topic = (own or {}).get("target") or ""
        action = (own or {}).get("text") or action

    # === Замыкание петли: что изменилось в мире? ===
    # Не обязательно: act() используется и в лёгких тестовых объектах.
    loop_closer = getattr(self, "loop_closer", None)
    outcome = None
    if loop_closer is not None:
        outcome = loop_closer.observe_agent_action(
            self,
            action_type,
            world_before,
            topic=topic,
            confirmed_result=confirmed_result,
            result_description=result_description,
        )
        self._last_action_outcome = outcome

    # === «Эмоции-1» (k16-03): исход исполнения окрашивает состояние ===
    # Интенсивности задаёт таблица EVENT_EMOTIONS (emotional_state.py);
    # scale не передаём — исход либо был, либо нет. Путь исключений
    # окрашивается в autonomous_tick (_wire_execution_exception_emotion).
    _wire_action_outcome_emotion(self, action_type, outcome)

    if outcome is not None and outcome.had_effect:
        get_logger().log(
            f"[LOOP] {action_type} дал результат: {outcome.summary}"
        )
        # Прогресс цели засчитывается по доказанному результату, а не
        # по факту «пошевелился». Тема — то, над чем шла работа.
        if topic:
            credit = self._check_goal_progress(
                topic, answered=True, evidence=outcome.delta
            )
            outcome_credit = credit.get("pct", 0)
            if outcome_credit:
                get_logger().log(
                    f"[LOOP] Цель: {outcome_credit}% после '{topic}'"
                )
    else:
        streak = (
            loop_closer.no_effect_streak(action_type)
            if loop_closer is not None
            else 0
        )
        if streak >= 2:
            get_logger().log(
                f"[LOOP] {action_type} без результата "
                f"({streak} раз подряд)"
            )

    # === Тело: прожить такт ===
    # Ровно один раз за действие, после того как оно выполнено.
    # Нагрузка зависит от типа: тяжёлая работа утомляет, отдых
    # восстанавливает. Отказы обрабатываются отдельно, до обработчика.
    # Модульная функция, а не метод: act() работает и в лёгких
    # объектах без тела (тесты бюджета, заглушки).
    step_body(self, action_type, performed=True)
    if expectations is not None:
        observation = expectations.finish(
            self.mental_models, expectation_trial, float(self.energy),
            fatigue_after=getattr(getattr(getattr(self, "interoception", None), "state", None), "fatigue", None),
        )
        if observation is not None:
            get_logger().log(
                f"[EXPECTATION] {action_type}: delta={observation['delta']:.3f}, "
                f"matched={observation['prediction_matched']}"
            )

    # === Мотивация: результат действия (P1.2 Valence Feedback) ===
    if hasattr(self, 'motivation_system'):
        # Успех — это факт исполнения, а не остаток энергии. Раньше
        # здесь стояло `self.energy > 10`: усталый агент не мог
        # удовлетворить ни одну потребность, любое действие считалось
        # неуспешным, и голод только рос — отсюда бесконечные вопросы.
        # Отказы (усталость, бюджет) выходят из act() раньше и сюда не
        # доходят. Качество исхода передаётся отдельно, в valence.
        success = action_type not in ("default", "wait")
        # Compute actual valence from result
        valence_context = {"energy": self.energy, "max_energy": getattr(self, "_legacy_energy", 150)}
        actual_valence = self.motivation_system.compute_actual_valence(
            action_type, action, success, valence_context
        )
        # Учебное действие, которое ничего не изменило в мире, не
        # должно удовлетворять любопытство. Раньше «изучил, но не
        # нашёл» получало положительную валентность (в тексте нет
        # слова error), и потребность закрывалась впустую — агент
        # «учился» вечно и никогда не шёл спрашивать.
        if (
            loop_closer is not None
            and outcome is not None
            and loop_closer.is_productive(action_type)
            and not outcome.had_effect
        ):
            actual_valence = min(actual_valence, -0.2)
        if action_type == "create_draft" and creative_choice[0] == "leave":
            actual_valence = 0.0
        self.motivation_system.on_action_result(action_type, success, actual_valence)
        get_logger().log(f"[ACT VALENCE] {action_type}: success={success}, valence={actual_valence:.3f}")
    elif hasattr(self, 'internal_motivation'):
        # Fallback to legacy internal_motivation
        success = self.energy > 10
        valence = 0.3 if success else -0.2
        self.internal_motivation.on_action_result(action_type, success, valence)

    # === Отслеживание использования концепций (для забывания) ===
    if decision and isinstance(decision, str):
        self._concept_usage_count[decision] = self._concept_usage_count.get(decision, 0) + 1

    # gc.collect() периодически для контроля памяти
    if self.cycle_count % SIM_CONFIG.GC_INTERVAL == 0:
        gc.collect()

    return action
