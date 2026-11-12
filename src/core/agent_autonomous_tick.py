"""Autonomous life tick extracted from ``agent.py``.

``AgentDeadSignal`` is a keyword-only injection so the death signal class
stays owned by the core without a reverse import. All periodic subsystem
calls keep their original place and firing condition.
"""

from copy import deepcopy
from typing import Dict, List

from config.simulation_config import LR_CONFIG, SIM_CONFIG
from src.cognition.active_inference import encode_observations
from src.core.agent_body import HEAVY_ACTIONS
from src.core.buffered_logger import get_logger


def _record_active_inference_experience_impl(
    self, action: str, obs_before: Dict, valence: float
) -> None:
    """Outcome loop: стимул -> действие -> наблюдаемый результат -> валентность -> опыт.

    Записывает опыт в буфер Active Inference и, при достижении batch_size,
    запускает обучение (обновление переходных вероятностей модели).
    """
    if not hasattr(self, "active_inference"):
        return
    try:
        obs_after = encode_observations(self)
        self.active_inference.record_experience(
            action=action,
            obs_before=obs_before or {},
            obs_after=obs_after,
            reward=float(valence or 0.0),
        )
        buffer = getattr(self.active_inference, "experience_buffer", None) or []
        batch_size = getattr(self.active_inference, "batch_size", None) or 32
        if len(buffer) >= batch_size:
            self.active_inference.learn_from_experience(batch_size=batch_size)
    except Exception as e:
        get_logger().log(f"[ACTIVE_INFERENCE] Experience recording error: {e}")


def _ingest_motivation_goals_impl(self, new_goals: List[dict]) -> None:
    """Этап 5: цели, сгенерированные мотивацией, → поток целей агента.

    Цели без executable-payload остаются когнитивными (честно); исполняемые
    цели проверяются через success predicate мостом Delamain.
    """
    if not new_goals:
        return
    from src.cognition.activity_goals import attach_activity, goal_work_key

    existing_titles = {
        str(g.get("title")).casefold() for g in self.goals if g.get("title")
    }
    existing_work = {goal_work_key(g) for g in self.goals}
    for g in new_goals:
        title = str(g.get("title") or "").strip()
        work_key = goal_work_key(g)
        if (
            not title
            or title.casefold() in existing_titles
            or work_key in existing_work
        ):
            continue
        try:
            gid = self.set_goal(
                title,
                difficulty=int(g.get("difficulty") or 1),
                success_predicate=str(g.get("success_predicate") or ""),
            )
            attach_activity(self, gid, g)
            existing_titles.add(title.casefold())
            existing_work.add(work_key)
            get_logger().log(f"[MOTIVATION] Goal ingested: {title} (id={gid})")
        except Exception as e:
            get_logger().log(f"[MOTIVATION] Goal ingestion failed: {e}")


def autonomous_tick_impl(self, *, AgentDeadSignal) -> Dict:
    """Автономный тик жизни — вызывается каждый цикл независимо от стимулов.

    Это «сердцебиение» агента: спонтанность, сны, проактивность, телесность,
    осознание смертности, привязанности — всё, что делает его живым
    даже когда никто не пишет в чат.
    """
    cycle = self.cycle_count
    result = {
        "cycle": cycle,
        "subsystems": None,
        "will": None,
        "communication": None,
        "soul": None,
        "active_inference": None,
        "arbitrator": None,
        "continuous_time": None,
        "meta_learning": None,
        "integrated_experience": None,
        "auxiliary_adapters": None,
    }

    # Эти системы уже принадлежат Core, но раньше только создавались.
    # Время получает один логический такт; MetaLearner работает в shadow:
    # fitness сохраняется, автономная мутация активных параметров запрещена.
    from src.core.life_systems_bridge import (
        step_meta_learning,
        tick_continuous_time,
    )

    result["continuous_time"] = tick_continuous_time(self, cycle)
    result["meta_learning"] = step_meta_learning(self)
    from src.cognition.integrated_experience import tick_integrated_experience
    from src.core.auxiliary_adapters import tick_auxiliary_adapters

    result["integrated_experience"] = tick_integrated_experience(self, cycle)
    result["auxiliary_adapters"] = tick_auxiliary_adapters(self, cycle)

    use_arbitrator = getattr(SIM_CONFIG, "USE_ARBITRATOR", True)
    candidates = []
    arbiter_context = {
        "energy": self.energy,
        "cycle": cycle,
        "intelligence": self.intelligence,
        "simulation_mode": getattr(SIM_CONFIG, "INTERNAL_SIMULATION_MODE", "shadow"),
        "simulation_max_adjustment": getattr(
            SIM_CONFIG, "INTERNAL_SIMULATION_MAX_ADJUSTMENT", 0.1
        ),
    }
    ai_intention = None
    obs_before: Dict = {}
    if hasattr(self, "active_inference"):
        try:
            observations = encode_observations(self)
            obs_before = dict(observations)
            action_name, ai_info = self.active_inference.step(observations)
            self._active_inference_intention = action_name
            self._active_inference_info = ai_info
            result["active_inference"] = {
                "intention": action_name,
                "free_energy": ai_info.get("free_energy"),
                "beliefs": ai_info.get("beliefs"),
                "G_values": ai_info.get("G_values"),
            }
            get_logger().log(
                f"[ACTIVE_INFERENCE] Cycle {cycle}: intention={action_name}, F={ai_info.get('free_energy', 0):.3f}"
            )
            ai_intention = action_name
            if action_name and action_name != "think_known":
                fe = ai_info.get("free_energy", 1.0)
                strength = max(0.1, min(1.0, 1.0 - fe / 5.0))
                candidates.append(
                    {
                        "source": "active_inference",
                        "action": action_name,
                        "strength": strength,
                        "params": {},
                        "free_energy": fe,
                    }
                )
        except Exception as e:
            get_logger().log(f"[ACTIVE_INFERENCE] Error in autonomous_tick: {e}")

    from src.cognition.method_preferences import apply as apply_method_preferences
    from src.core.agent_act import _wire_execution_exception_emotion

    candidates = apply_method_preferences(self, candidates)

    from src.cognition.activity_goals import active_goal_candidate, activity_candidate

    own_activity = activity_candidate(self)
    if own_activity is not None:
        candidates.append(own_activity)
    own_goal = active_goal_candidate(self)
    if own_goal is not None:
        candidates.append(own_goal)

    pending_stimulus = getattr(self, "_attention_stimulus", None)
    if pending_stimulus is not None:
        candidates.append(
            {
                "source": "external_attention",
                "action": "process_stimulus",
                "strength": 0.85 if pending_stimulus["user_initiated"] else 0.3,
                "params": {"user_initiated": pending_stimulus["user_initiated"]},
            }
        )

    # 1. Motivation candidates
    if hasattr(self, "motivation_system"):
        try:
            motivation_candidates = self.motivation_system.get_action_candidates(
                arbiter_context
            )
            candidates.extend(motivation_candidates)
        except Exception as e:
            get_logger().log(f"[MOTIVATION_CANDIDATES] Error: {e}")

    # 2. Embodiment candidates
    # Раньше здесь читался ``self._interoception_status``, который
    # никто никогда не выставлял: ветка была мёртвой, и тело не
    # предлагало отдых даже при полном истощении. Теперь состояние
    # берётся напрямую у интероцепции, а «eat» (не существующее
    # действие) заменён на отдых.
    #
    # Отдых включается по усталости и выключается только после
    # восстановления (гистерезис): иначе агент возвращался к работе
    # на самом пороге и не успевал восполнить АТФ.
    resting = self._update_rest_mode()
    if hasattr(self, "interoception") and self.interoception is not None:
        try:
            intero_status = self.interoception.get_status()
            fatigue = float(intero_status.get("fatigue", 0.0) or 0.0)
            energy_ratio = float(self.energy) / float(LR_CONFIG.ENERGY_MAX or 1.0)
            rest_threshold = float(getattr(LR_CONFIG, "REST_FATIGUE_THRESHOLD", 0.6))
            low_ratio = float(getattr(LR_CONFIG, "LOW_ENERGY_RATIO", 0.25))
            if resting or fatigue >= rest_threshold or energy_ratio <= low_ratio:
                candidates.append(
                    {
                        "source": "embodiment",
                        "action": "deep_rest",
                        # Пока тело отдыхает — это главное дело. На входе
                        # в отдых сила растёт быстрее усталости (0.6 → 0.75),
                        # иначе отдых проигрывал обучению.
                        "strength": 1.0
                        if resting
                        else min(
                            1.0,
                            max(fatigue, 1.0 - energy_ratio) * 1.25,
                        ),
                        "params": {
                            "reason": "resting"
                            if resting
                            else (
                                "tired" if fatigue >= rest_threshold else "low_energy"
                            ),
                            "fatigue": round(fatigue, 3),
                            "energy_ratio": round(energy_ratio, 3),
                        },
                    }
                )
        except Exception as e:
            get_logger().log(f"[EMBODIMENT_CANDIDATES] Error: {e}")

    # 3. Social candidates: потребность в контакте и незакрытые вопросы.
    # Раньше здесь стоял `pass`: секция существовала, но ничего не
    # добавляла, поэтому общение никогда не попадало в выбор.
    try:
        candidates.extend(self._social_candidates(cycle))
    except Exception as e:
        get_logger().log(f"[SOCIAL_CANDIDATES] Error: {e}")

    # Собственная проверка — кандидат, а не приказ и не новая цель.
    from src.cognition.experiment_proposals import propose_experiment

    experimental = propose_experiment(
        self.mental_models,
        energy=float(self.energy),
        energy_max=float(LR_CONFIG.ENERGY_MAX),
        fatigue=getattr(
            getattr(getattr(self, "interoception", None), "state", None),
            "fatigue",
            None,
        ),
        cycle=cycle,
        last_cycle=getattr(self, "_last_experiment_cycle", None),
    )
    if experimental is not None:
        candidates.append(experimental)
        result["experiment_proposal"] = experimental

    from src.cognition.intention_continuation import continuation_candidate

    continuation = continuation_candidate(self)
    if continuation is not None:
        candidates.append(continuation)
        result["continuation_proposal"] = continuation

    from src.cognition.intention_fading import fading_assessment
    from src.cognition.intention_waiting import waiting_key

    for waiting in getattr(self, "_waiting_intentions", {}).values():
        assessment = fading_assessment(self, waiting)
        if assessment.get("eligible"):
            candidates.append(
                {
                    "source": "self_fading",
                    "action": "let_go",
                    "strength": 0.4,
                    "params": {
                        "action": waiting["action"],
                        "topic": waiting["target"],
                        "reason": "повторные попытки без новых свидетельств",
                        "waiting_key": waiting_key(
                            waiting["action"], waiting["target"]
                        ),
                    },
                }
            )
            result.setdefault("fading_proposals", []).append(waiting["target"])
            break

    # === УСТАЛОСТЬ: тяжёлая работа хуже даётся ===
    # ``cognitive_throughput`` падает с усталостью (1 - 0.7*fatigue).
    # Раньше величина только считалась и сохранялась в чекпоинт —
    # на выбор она не влияла. Теперь она снижает тягу к тяжёлым
    # действиям: уставший агент сам выбирает отдых или лёгкое дело,
    # а не потому, что ему запретили работать.
    try:
        intero = getattr(self, "interoception", None)
        throughput = (
            float(intero.state.cognitive_throughput) if intero is not None else 1.0
        )
        if resting:
            # Пока тело отдыхает, тяжёлая работа не тянет: это не
            # запрет, а отсутствие желания работать через силу.
            throughput = min(throughput, 0.15)
        if throughput < 0.99:
            for candidate in candidates:
                action_type = self._normalize_action(candidate.get("action"))
                if action_type in HEAVY_ACTIONS:
                    candidate["strength"] = float(candidate.get("strength", 0.5)) * max(
                        0.2, throughput
                    )
    except Exception as e:
        get_logger().log(f"[BODY] throughput damping error: {e}")

    from src.cognition.creative_choices import creative_choices

    expanded_candidates = []
    for candidate in candidates:
        if self._normalize_action(candidate.get("action")) == "create_draft":
            expanded_candidates.extend(creative_choices(self, candidate))
        else:
            expanded_candidates.append(candidate)
    candidates = expanded_candidates

    # === ФИЛЬТР ДОСТУПНОСТИ ===
    # Не предлагаем арбитру то, что сейчас физически нельзя выполнить:
    # вопрос при кулдауне, поиск при выключенной сети, действие при
    # нехватке энергии. Иначе действие выигрывает выбор, упирается в
    # отказ и сжигает цикл.
    #
    # Гасить силу уже выбранных действий пробовали — это приводило к
    # метанию между бесплодными вариантами. Дешевле не предлагать
    # невозможное вовсе.
    #
    # Отказы, ставшие неправдой (энергия вернулась), снимаются здесь же:
    # иначе отдых не возвращал бы агента к работе — действие навсегда
    # осталось бы помеченным как тупиковое.
    self._release_recovered_denials()
    candidates = [
        candidate for candidate in candidates if self._is_candidate_available(candidate)
    ]

    # Тело не может ничего из предложенного — но отдых доступен всегда.
    # Без этого арбитр получал пустой список и выбирал «wait», то есть
    # агент в истощении не отдыхал, а просто стоял.
    if not candidates and (self._body_needs_rest() or self._is_resting()):
        candidates = [
            {
                "source": "embodiment",
                "action": "deep_rest",
                "strength": 1.0,
                "params": {"reason": "nothing_affordable"},
            }
        ]

    from src.cognition.method_feedback import prepare_candidates

    candidates, feedback = prepare_candidates(self, candidates)
    result["method_feedback"] = feedback
    if not candidates:
        if self._body_needs_rest() or self._is_resting():
            fallback = "deep_rest"
            reason = "body_needs_rest"
        else:
            fallback = "wait"
            reason = "no_working_method"
        candidates = [
            {
                "action": fallback,
                "source": "deliberate_pause",
                "strength": 0.1,
                "params": {"reason": reason},
            }
        ]

    # === ЭМОЦИОНАЛЬНЫЙ ОТТЕНОК ВЫБОРА (Эмоции-2) ===
    # Пережитое смещает тягу к занятиям: страх тянет к безопасному,
    # счастье — к творческому, грусть — к тихому. Это вес, не
    # команда: список кандидатов не меняется, цели и ценности не
    # трогаются, решает по-прежнему арбитр.
    try:
        emotional_bias = self._apply_emotional_bias(candidates)
        if emotional_bias:
            result["emotional_bias"] = emotional_bias
    except Exception as e:
        get_logger().log(f"[EMOTIONAL_BIAS] Error: {e}")

    # Прогноз создаётся после фильтров доступности, но до арбитража.
    # В shadow он сохраняет опыт и диагностику, не меняя прежние score.
    from src.cognition.simulation_bridge import predict_candidates

    candidates, simulation_diagnostics = predict_candidates(
        self, candidates, mode=arbiter_context["simulation_mode"]
    )
    result["simulation"] = simulation_diagnostics

    # === ARBITRATION ===
    chosen_action = None
    arbitrator_result = None
    if use_arbitrator and hasattr(self, "decision_arbitrator"):
        try:
            arbitrator_result = self.decision_arbitrator.choose_action(
                candidates, arbiter_context
            )
            chosen_action = arbitrator_result.get("action")
            result["arbitrator"] = arbitrator_result
            get_logger().log(
                f"[ARBITRATOR] {arbitrator_result.get('reasoning', 'No reasoning')}"
            )
        except Exception as e:
            get_logger().log(f"[ARBITRATOR] Error: {e}")
            if candidates:
                fallback_candidate = candidates[0]
                chosen_action = fallback_candidate.get("action")
                result["arbitrator"] = {
                    "action": chosen_action,
                    "source": "fallback_first_candidate",
                    "params": dict(fallback_candidate.get("params") or {}),
                    "simulation": deepcopy(fallback_candidate.get("simulation")),
                    "verdict": "proceed",
                    "reasoning": f"Arbitrator error: {e}",
                }
    else:
        chosen_action = ai_intention
        selected_candidate = next(
            (
                candidate
                for candidate in candidates
                if candidate.get("action") == chosen_action
            ),
            {},
        )
        result["arbitrator"] = {
            "action": chosen_action,
            "source": "legacy_active_inference",
            "params": dict(selected_candidate.get("params") or {}),
            "simulation": deepcopy(selected_candidate.get("simulation")),
            "verdict": "proceed" if chosen_action else "stop",
            "reasoning": "USE_ARBITRATOR=False or no arbitrator available",
        }

    # === ВЫХОД ИЗ ТУПИКА ===
    # Если выбранное действие уже несколько раз подряд не давало
    # наблюдаемого результата, повторять его бессмысленно. Раньше агент
    # так и делал: бесконечно выбирал explore, потому что ничто не
    # мешало. Теперь берём первого кандидата, который не в тупике.
    #
    # Имя нормализуем: мотивация зовёт действие «exploration», а
    # арбитр — «explore». Без нормализации проверка тупика смотрела бы
    # на другое имя и никогда не срабатывала.
    result["initial_arbitration"] = dict(result.get("arbitrator") or {})
    arbitrator_data = result.get("arbitrator") or {}
    if arbitrator_data.get("verdict") == "stop":
        # Воля вместо молчания: либо осознанный риск ради значимой
        # цели, либо собственный отказ с записью в журнал воли.
        # Legacy-путь («нет арбитра») — состояние системы, а не воля,
        # поэтому он не порождает волевых актов.
        risk_entry = None
        will_applies = bool(chosen_action) and (
            arbitrator_data.get("source") != "legacy_active_inference"
        )
        if will_applies:
            risk_entry = self._consider_will_risk(
                chosen_action,
                str(arbitrator_data.get("reasoning", "stop")),
            )
        if risk_entry is not None:
            result["will_risk_taken"] = risk_entry
        else:
            result["action_refused"] = {
                "action": chosen_action,
                "reason": arbitrator_data.get("reasoning", "stop"),
            }
            if will_applies:
                result["will_refusal"] = self.defend_refusal(
                    topic=str(chosen_action),
                    reason=str(arbitrator_data.get("reasoning", "stop")),
                )
            chosen_action = "wait"
    if chosen_action == "let_go":
        selected_intention = result.get("arbitrator") or {}
        result["autonomous_action"] = {
            "action": chosen_action,
            "result": self.act(chosen_action, intention=selected_intention),
        }
        return result
    chosen_type = self._normalize_action(chosen_action)
    if chosen_action and self.loop_closer.is_stuck(chosen_type):
        stopped_types = {
            self._normalize_action(entry.get("action"))
            for entry in result.get("arbitrator", {}).get("all_evaluations", [])
            if entry.get("verdict") == "stop"
        }
        ranked = sorted(
            [
                candidate
                for candidate in candidates
                if self._normalize_action(candidate.get("action")) not in stopped_types
            ],
            key=lambda c: float(c.get("strength", 0.0)),
            reverse=True,
        )
        # Запасной вариант тоже должен быть выполнимым и результативным:
        # если тело истощено, «think_decompose» — это ещё один отказ, а
        # если очередь вопросов полна — пустой ход.
        fallback = self._stuck_fallback()
        if self._normalize_action(fallback) in stopped_types:
            fallback = "wait"
        alternative = self.loop_closer.choose(
            ranked,
            fallback=fallback,
            normalize=self._normalize_action,
        )
        if alternative.get("action") != chosen_action:
            result["loop_escape"] = {
                "from": chosen_action,
                "to": alternative.get("action"),
                "reason": "no observable effect",
                "streak": self.loop_closer.no_effect_streak(chosen_type),
                "denied_streak": self.loop_closer.denied_streak(chosen_type),
                "had_effect_before": self.loop_closer.has_effect_history(chosen_type),
                "fallback": alternative.get("reason") == "all_stuck",
                "candidate_diagnostics": self.loop_closer.describe_candidates(
                    ranked, normalize=self._normalize_action
                ),
            }
            get_logger().log(
                f"[LOOP] '{chosen_action}' не даёт результата "
                f"({result['loop_escape']['streak']} раз) — "
                f"переключаюсь на '{alternative.get('action')}'"
            )
            chosen_action = alternative.get("action")
            if arbitrator_result is not None:
                arbitrator_result = dict(arbitrator_result)
                arbitrator_result["action"] = chosen_action
                arbitrator_result["source"] = "loop_closer"
                arbitrator_result["params"] = dict(alternative.get("params") or {})
                # Прогноз обязан принадлежать финальному действию, а не
                # кандидату, которого LoopCloser только что заменил.
                arbitrator_result["simulation"] = deepcopy(
                    alternative.get("simulation")
                )
                result["arbitrator"] = arbitrator_result

    # === EXECUTE ===
    # Для диагностики: что именно выбрал арбитр в этом цикле.
    self._last_arbitration = result.get("arbitrator")
    # P1.2: Valence Feedback Loop - predict valence before action
    valence_context = {
        "energy": self.energy,
        "max_energy": getattr(self, "_legacy_energy", 150),
        "cycle": cycle,
    }
    predicted_valence = 0.0
    if hasattr(self, "motivation_system") and chosen_action:
        try:
            predicted_valence = self.motivation_system.predict_valence(
                chosen_action, valence_context
            )
            result["predicted_valence"] = predicted_valence
            get_logger().log(
                f"[VALENCE] Predicted for {chosen_action}: {predicted_valence:.3f}"
            )
        except Exception as e:
            get_logger().log(f"[VALENCE] Prediction error: {e}")

    if chosen_action == "process_stimulus":
        result["attention_selected"] = True
    if chosen_action and chosen_action not in (
        "think_known",
        "wait",
        "none",
        "process_stimulus",
    ):
        from src.cognition.intention_history import begin_intention, finish_intention

        history_selection = dict(result.get("arbitrator") or {})
        history_selection["action"] = chosen_action
        intention_entry = begin_intention(self, history_selection)
        from src.core.life_systems_bridge import record_action_intention

        record_action_intention(self, history_selection, intention_entry)
        from src.cognition.experience_observers import observe_action_intention

        observe_action_intention(self, history_selection, intention_entry)
        self._last_action_outcome = None
        # Прошлая стоимость не должна простить чужую ошибку: если
        # исключение случится до списания, прощать будет нечего.
        self._last_action_cost = 0.0
        try:
            experiment_selected = (
                result.get("arbitrator", {}).get("source") == "self_experiment"
                and experimental is not None
                and chosen_action == experimental["action"]
            )
            selected_intention = result.get("arbitrator") or {}

            activity_attrs = {
                "play": "_local_play",
                "create_draft": "_creative_draft",
                "draw": "_art_work",
                "compose_music": "_music_work",
            }
            activity_before = deepcopy(
                getattr(
                    self, activity_attrs.get(chosen_action, "_creative_draft"), None
                )
            )
            if self._normalize_action(chosen_action) in {
                "explore",
                "decomposition",
                "synthesis",
                "ask_user",
                "web_search",
                "create_draft",
            } and selected_intention.get("params"):
                action_result = self.act(chosen_action, intention=selected_intention)
            else:
                action_result = self.act(chosen_action)
            from src.cognition.method_preferences import observe as observe_method

            last = getattr(self, "_last_action_outcome", None)
            normalized_action = self._normalize_action(chosen_action)
            if normalized_action not in {
                "rest",
                "deep_rest",
                "wait",
                "checkpoint_now",
                "repair",
                "play",
                "create_draft",
                "draw",
                "compose_music",
            }:
                generic_outcome = "performed"
                if last is not None and last.reason.startswith("denied:"):
                    generic_outcome = "denied"
                observe_method(
                    self,
                    normalized_action,
                    outcome=generic_outcome,
                    had_effect=bool(last and last.had_effect),
                    emotional_valence=result.get("actual_valence", 0.0),
                )
            if normalized_action in {"play", "create_draft", "draw", "compose_music"}:
                activity_state = getattr(self, activity_attrs[normalized_action], None)
                activity_outcome = (
                    "left"
                    if activity_state and activity_state.get("status") == "left"
                    else "performed"
                )
                if last is not None and last.reason.startswith("denied:"):
                    activity_outcome = "denied"
                observe_method(
                    self,
                    chosen_action,
                    outcome=activity_outcome,
                    had_effect=bool(last and last.had_effect),
                    emotional_valence=result.get("actual_valence", 0.0),
                )
            if normalized_action in {"play", "create_draft", "draw", "compose_music"}:
                from src.cognition.activity_goals import record_activity_step

                activity_type = self._normalize_action(chosen_action)
                activity_after = getattr(self, activity_attrs[activity_type], None)
                record_activity_step(
                    self,
                    selected_intention,
                    activity_type,
                    activity_before,
                    activity_after,
                )
            from src.cognition.simulation_bridge import (
                cancel_selected_prediction,
                learn_from_selected_action,
            )

            if last is not None:
                simulation_feedback = learn_from_selected_action(
                    self, selected_intention, intention_entry, last
                )
                if simulation_feedback is not None:
                    result["simulation_feedback"] = simulation_feedback
            else:
                cancel_selected_prediction(self, intention_entry, "unobserved")
            from src.core.life_systems_bridge import record_action_outcome

            record_action_outcome(self, intention_entry, last)
            from src.cognition.experience_observers import observe_action_outcome

            observe_action_outcome(self, intention_entry, last)
            from src.cognition.integrated_experience import observe_integrated_action

            observe_integrated_action(self, intention_entry, last)
            finish_intention(intention_entry, last)
            self._record_core_life_episode(intention_entry)
            from src.cognition.intention_evidence import finish_evidence_goal

            finish_evidence_goal(self, intention_entry)
            result["intention_id"] = intention_entry["id"]
            result["executed_intention"] = {
                "action": chosen_action,
                "source": selected_intention.get("source"),
                "params": dict(selected_intention.get("params") or {}),
            }
            if experiment_selected:
                self._last_experiment_cycle = cycle
                observed = getattr(
                    getattr(self, "action_expectations", None), "last_trial", None
                )
                result["experiment_result"] = {
                    "claim_id": experimental["params"]["claim_id"],
                    "observation": observed,
                }
            result["autonomous_action"] = {
                "action": chosen_action,
                "result": action_result,
            }
            get_logger().log(f"[AUTONOMOUS_ACTION] {action_result}")

            # P1.2: Compute actual valence and update motivation
            success = True
            if (
                "error" in str(action_result).lower()
                or "fail" in str(action_result).lower()
            ):
                success = False
            if not success:
                # Право на ошибку: часть оплаченной стоимости — урок.
                absolution = self._absorb_action_failure(
                    chosen_action, str(action_result)[:160]
                )
                if absolution:
                    result["will_fail_absolution"] = absolution

            if hasattr(self, "motivation_system"):
                try:
                    actual_valence = self.motivation_system.compute_actual_valence(
                        chosen_action, str(action_result), success, valence_context
                    )
                    if (
                        self._normalize_action(chosen_action) == "create_draft"
                        and selected_intention.get("params", {}).get("draft_mode")
                        == "leave"
                    ):
                        actual_valence = 0.0
                    result["actual_valence"] = actual_valence
                    prediction_error = actual_valence - predicted_valence
                    result["valence_prediction_error"] = prediction_error
                    # Сам исход в потребности уже записал act(): он
                    # знает фактический тип действия. Второй вызов
                    # здесь удваивал удовлетворение (одно действие
                    # закрывало две доли дефицита), и потребности
                    # «залипали» сытыми.
                    get_logger().log(
                        f"[VALENCE] Actual for {chosen_action}: "
                        f"{actual_valence:.3f}, error: {prediction_error:.3f}"
                    )

                    # P2: Outcome loop — стимул -> действие -> результат -> валентность -> опыт
                    self._record_active_inference_experience(
                        chosen_action, obs_before, actual_valence
                    )
                except Exception as e:
                    get_logger().log(f"[VALENCE] Feedback error: {e}")

        except Exception as e:
            from src.cognition.simulation_bridge import cancel_selected_prediction

            cancel_selected_prediction(self, intention_entry, "execution_error")
            from src.core.life_systems_bridge import record_action_outcome

            record_action_outcome(self, intention_entry, error=e)
            from src.cognition.experience_observers import observe_action_outcome

            observe_action_outcome(self, intention_entry, error=e)
            from src.cognition.integrated_experience import observe_integrated_action

            observe_integrated_action(self, intention_entry, error=e)
            finish_intention(intention_entry, error=e)
            get_logger().log(f"[AUTONOMOUS_ACTION] Error: {e}")
            result["autonomous_action"] = {"action": chosen_action, "error": str(e)}
            absolution = self._absorb_action_failure(chosen_action, str(e))
            if absolution:
                result["will_fail_absolution"] = absolution

            # «Эмоции-1» (оценки исхода): падение исполнения — тоже промах.
            _wire_execution_exception_emotion(self, chosen_action)

            # P1.2: Failed action - negative valence
            if hasattr(self, "motivation_system"):
                try:
                    actual_valence = self.motivation_system.compute_actual_valence(
                        chosen_action, str(e), False, valence_context
                    )
                    result["actual_valence"] = actual_valence
                    prediction_error = actual_valence - predicted_valence
                    result["valence_prediction_error"] = prediction_error

                    self.motivation_system.on_action_result(
                        chosen_action, False, actual_valence
                    )
                    get_logger().log(
                        f"[VALENCE] Failed action {chosen_action}: {actual_valence:.3f}"
                    )
                except Exception as e:
                    get_logger().log(f"[VALENCE] Feedback error on failure: {e}")

    # === MOTIVATION SYSTEM TICK ===
    if hasattr(self, "motivation_system"):
        try:
            motivation_result = self.motivation_system.tick()
            result["motivation"] = motivation_result
            # P2: цели, сгенерированные мотивацией, в поток целей агента
            self._ingest_motivation_goals(motivation_result.get("new_goals") or [])
        except Exception as e:
            get_logger().log(f"[MOTIVATION_TICK] Error: {e}")
            result["motivation"] = {"error": str(e)}

    # 1. PluginRegistry
    # Stage 18B: если core_driven включён, tick_subsystems сам диспатчит
    # effector через EffectorDriver (не более одного шага эффектора за цикл).
    # См. DigitalBeing.tick_subsystems — там же дедуп по циклу.
    if hasattr(self, "plugin_registry"):
        result["subsystems"] = self.tick_subsystems(cycle)

    # 2. Will
    if hasattr(self, "tick_will"):
        result["will"] = self.tick_will(cycle)

    # 3. Communication
    if hasattr(self, "tick_communication"):
        result["communication"] = self.tick_communication(cycle)

    # 4. Soul
    if hasattr(self, "tick_soul"):
        result["soul"] = self.tick_soul(cycle)

    # 5. Death risk
    if hasattr(self, "death_risk"):
        death_result = self.death_risk.step(dt=1.0)
        result["death_risk"] = death_result
        if not death_result["alive"]:
            cause = death_result.get("cause") or death_result.get("death_cause")
            legacy = (
                self.death_risk.legacy_package
                if hasattr(self.death_risk, "legacy_package")
                else {}
            )
            get_logger().flush_immediate(f"[DEATH] Agent died: {cause}")
            raise AgentDeadSignal(cause, legacy)
        # «Эмоции-2»: структура ниже порога предупреждения — реальная
        # причина страха. Кулдаун внутри EmotionalState не даёт
        # переживать один и тот же сигнал каждый цикл.
        self._emotions_from_death_risk(death_result)

    # 6. Эволюция — глаз/рука/проба/голос (периодически, внутри
    # свои пороги; None вне окна анализа).
    evolution = self._evolution_tick(cycle)
    if evolution is not None:
        result["evolution"] = evolution

    return result
