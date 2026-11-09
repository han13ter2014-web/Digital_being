"""Central action dispatcher extracted from ``agent.py``.

``DigitalBeing`` and ``record_denied_outcome`` are keyword-only injections so
class-qualified lookup and the core monkeypatch surface remain unchanged.
Handlers and autonomous-tick methods stay behind the facade.
"""

import gc
import re

from config.simulation_config import LR_CONFIG, SIM_CONFIG
from src.core.agent_body import ESSENTIAL_ACTIONS, RECOVERY_ACTIONS, step_body
from src.core.buffered_logger import get_logger
from src.core.world_delta import capture

# «Окно-1» (k16-07): таблица алиасов для executable_action(). Заполняется
# facade'ом при импорте (agent.py определяет класс после этого модуля) —
# поэтому читается лениво через callable, а не копией словаря.
ACTION_ALIASES_TABLE = None
_TABLE_WARNED = False


def _set_aliases_table(table) -> None:
    global ACTION_ALIASES_TABLE, _TABLE_WARNED
    ACTION_ALIASES_TABLE = table
    _TABLE_WARNED = False  # новая регистрация — предупреждение снова слышимо


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


# Подстрочные правила парсера: negatives ПЕРЕД know_answer — «не нашёл»
# содержит «нашёл», и прежний порядок классифицировал промах как успех.
# Порядок значим; пиняется тестами (test_orphans_and_parser.py).
_PARSER_RULES = [
    ("гипотеза", "hypothesis"),
    ("декомпозиц", "decomposition"),
    ("не нашел", "search_miss"),
    ("не нашёл", "search_miss"),
    ("не найдено", "search_miss"),
    ("ментальная модель", "know_answer"),
    ("знаю ответ", "know_answer"),
    ("нашел ответ", "know_answer"),
    ("нашёл ответ", "know_answer"),
    ("пользователь ответил", "user_answer"),
    ("repair", "repair"),
    ("ремонт", "repair"),
    ("deep_rest", "deep_rest"),
    ("глубокий отдых", "deep_rest"),
    ("checkpoint", "checkpoint_now"),
]


def classify_decision(decision) -> str:
    """«Единство-1» (k16-14): единственный классификатор решений act().

        Чистая функция от строки решения к типу действия: подстрочные
        правила, затем алиасы ACTION_ALIASES. Сюда смотрят парсер
        act(), фильтр кандидатов executable_action() и тесты —
        три потребителя, одна таблица, разойдись они больше не могут
        (именно расхождение породило сирот k16-09).
        """
    global _TABLE_WARNED
    decision_str = str(decision or "").strip().lower()
    table = ACTION_ALIASES_TABLE
    # «Харднинг-2» (k16-14): пустая таблица — сломанная регистрация,
    # должна быть слышимой. Лог один раз на период отсутствия таблицы:
    # каждый вызов спамил бы буфер, молчание прячет поломку навсегда.
    if table is None and decision_str and not _TABLE_WARNED:
        from src.core.buffered_logger import get_logger

        get_logger().log(
            "[CLASSIFIER] таблица алиасов не зарегистрирована: "
            "алиасные решения классифицируются только подстрочными правилами"
        )
        _TABLE_WARNED = True
    for fragment, action_type in _PARSER_RULES:
        if fragment in decision_str:
            return action_type
    if table is not None and decision_str in table:
        return table[decision_str]
    return "default"


def executable_action(action) -> bool:
    """«Окно-1» (k16-07): поймает ли контур исполнения это имя.

        Делегат к classify_decision(): исполняемо всё, что классифицируется
        не в «default». Служебные имена-не-действия («wait», «none») —
        True: это честные исходы, а не пустышки.
        """
    key = str(action or "").strip().lower()
    if not key:
        return False
    if key in ("wait", "none"):
        return True
    return classify_decision(key) != "default"


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
    # «Единство-1» (k16-14): классификация в classify_decision() —
    # та же функция, что у фильтра кандидатов и тестов.
    action_type = classify_decision(decision)

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
            # «Подтверждение-1» (k16-14): положительный вклад хотя бы
            # одного компонента — факт поднятой целостности. Словарь
            # всегда содержит ключ corruption_accumulator (может быть
            # 0.0 на целой структуре): проверка «словарь не пуст» была
            # бы ложным успехом на уже целостной структуре.
            repaired = sum(
                delta for delta in changes.values() if delta > 0
            )
            if repaired > 0:
                confirmed_result = True
                result_description = (
                    f"целостность восстановлена (+{repaired:.2f})"
                )
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
            checkpoint = self.death_risk.force_checkpoint()
            get_logger().flush_immediate("[DEATH_RISK] Manual checkpoint created")
            # «Подтверждение-1» (k16-14): create_checkpoint вернул
            # Checkpoint с шагом — факт зафиксированного состояния.
            if checkpoint is not None:
                confirmed_result = True
                result_description = f"чекпоинт создан на шаге {checkpoint.step}"
    # Обработчики действий вызываются через getattr: act() работает и в
    # лёгких объектах (тесты бюджета, заглушки), где их нет. Отсутствие
    # обработчика — не ошибка: действие остаётся без эффекта.
    elif action_type == "let_go":
        from src.cognition.intention_waiting import resolve_wait

        params = intention or {}
        values = params.get("params", {})
        wait_decision = resolve_wait(self, values.get("action", "explore"), values.get("topic", ""),
                                     kind="forgotten", reason=values.get("reason", "сама решила отпустить"))
        action = f"Ответ: отпустила намерение '{values.get('topic', '')}' ({wait_decision['status']})"
        # «Подтверждение-1» (k16-14): намерение реально помечено forgotten —
        # проверяемый факт изменения _waiting_intentions. not_found и
        # already_resolved — честные промахи (нечего было отпускать),
        # флага им не достаётся. (Переменная не «decision»: это имя уже
        # занято бюджетным решением выше, и mypy путал типы.)
        if wait_decision["status"] == "forgotten":
            confirmed_result = True
            result_description = (
                f"намерение '{values.get('topic', '')}' помечено forgotten"
            )
    elif action_type == "create_draft":
        from src.cognition.creative_catalog import perform_creative

        mode, identifier, reason = creative_choice
        draft = perform_creative(self, mode, identifier, reason)
        verb = "оставила" if mode == "leave" else "создала" if mode == "new" else "продолжила"
        action = f"Ответ: {verb} черновик «{draft['theme']}», версия {draft['revision']}"
        # «Подтверждение-1» (k16-14): perform_creative вернул состояние
        # с ревизией и валидным sha256 (обратное чтение проверено внутри)
        # — факт записанного черновика, не факт вызова обработчика.
        # mode='leave' — сознательное оставление работы: не достижение,
        # флага не получает (k16-02: и валентность для leave — ноль).
        if mode != "leave":
            confirmed_result = True
            result_description = f"черновик «{draft['theme']}» редакция {draft['revision']}"
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
            # «Подтверждение-1» (k16-14): зеркало deep_rest —
            # фактическое восстановление, не факт вызова.
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
        # «Подтверждение-1» (k16-14): goal_id в ответе обработчика —
        # факт созданной записи цели (set_goal возвращает id только при
        # успехе). Отказы «уже есть»/«не из чего»/«не смогла» id не
        # несут и флага не получают.
        text = str((own or {}).get("text") or "")
        match = re.search(r"#(\d+)", text)
        if own is not None and match:
            confirmed_result = True
            result_description = f"цель #{match.group(1)} записана"

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
