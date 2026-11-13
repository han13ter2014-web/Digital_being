"""
DecisionArbitrator — единая точка принятия решений.

Объединяет «голоса» всех систем:
- InternalDialogueEngine (6 голосов)
- EthicalCoreSystem (3 фреймворка: утилитаризм, деонтология, добродетель)
- CoreSelfModule (стабильность идентичности)
- assess_intuition() (гут-фелинг)
- ImmuneSystem (иммунный статус)

Перед каждым решением arbitrator спрашивает каждую систему
и выносит вердикт: действовать / осторожно / остановиться.

Аналогия с человеком: префронтальная кора, которая интегрирует
эмоции, память, этику и интуицию в одно решение.
"""

from typing import Dict, List, Any

from src.consciousness.internal_dialogue import InternalDialogueEngine
from src.core.self_identity_module import CoreSelfModule
from src.emotion.ethical_core import EthicalCoreSystem


class DecisionArbitrator:
    """Арбитр решений — интегратор всех подсистем."""

    def __init__(self, agent_name: str = "agent"):
        # Все модули входят в установленный пакет: обычные импорты не зависят
        # от CWD, а ошибка загрузки не маскируется под недоступную подсистему.
        self._systems: Dict[str, object] = {
            "dialogue": InternalDialogueEngine(),
            "ethics": EthicalCoreSystem(),
            "self": CoreSelfModule(),
        }
        self._available = {key: True for key in self._systems}
        self.agent_name = agent_name

    # ============================================================
    # Связывание с иммунной системой (создаётся извне)
    # ============================================================
    def attach_dialogue(self, dialogue) -> None:
        self._systems["dialogue"] = dialogue
        self._available["dialogue"] = dialogue is not None

    def attach_ethics(self, ethics) -> None:
        self._systems["ethics"] = ethics
        self._available["ethics"] = ethics is not None

    def attach_identity(self, identity) -> None:
        self._systems["self"] = identity
        self._available["self"] = identity is not None

    def attach_immune_system(self, immune_system) -> None:
        self._systems["immune"] = immune_system
        self._available["immune"] = immune_system is not None

    def attach_meaning_finder(self, meaning_finder) -> None:
        self._systems["meaning"] = meaning_finder
        self._available["meaning"] = meaning_finder is not None

    def attach_survival_instincts(self, survival) -> None:
        self._systems["survival"] = survival
        self._available["survival"] = survival is not None

    def attach_embodiment(self, embodiment) -> None:
        self._systems["embodiment"] = embodiment
        self._available["embodiment"] = embodiment is not None

    # ============================================================
    # Главный метод: арбитраж
    # ============================================================
    def arbitrate(self, topic: str, proposed_action: str = "") -> Dict:
        """Собирает мнения всех систем и выносит вердикт.

        Возвращает:
            {
                'verdict': 'proceed' | 'caution' | 'stop',
                'confidence': float,
                'voices': { system_name: opinion },
                'reasoning': str,
            }
        """
        opinions: Dict[str, Dict] = {}

        # 1. Внутренний диалог
        if self._available.get("dialogue"):
            try:
                dialogue_result = self._systems["dialogue"].initiate_dialogue(topic)
                opinions["dialogue"] = {
                    "dominant_voice": dialogue_result.get("dominant_voice"),
                    "harmony": dialogue_result.get("harmony", 0.5),
                    "weight": 0.25,
                }
            except Exception as error:
                opinions["dialogue"] = {
                    "error": f"{type(error).__name__}: {error}",
                    "weight": 0,
                }

        # 2. Этика
        if self._available.get("ethics"):
            try:
                from src.emotion.ethical_core import MoralDilemma

                dilemma = MoralDilemma(
                    scenario=topic,
                    stakes=["репутация", "время", "энергия", "знание"],
                )
                ethics_result = self._systems["ethics"].analyze_dilemma(dilemma)
                opinions["ethics"] = {
                    "verdict": ethics_result,
                    "weight": 0.30,  # Этика — самый высокий вес
                }
            except Exception as error:
                opinions["ethics"] = {
                    "error": f"{type(error).__name__}: {error}",
                    "weight": 0,
                }

        # 3. Самоидентичность
        if self._available.get("self"):
            try:
                core = self._systems["self"]
                # Оценка альтернатив читает идентичность, но не проживает
                # каждый рассмотренный вариант как изменение себя.
                new_identity = core.core_identity
                opinions["self"] = {
                    "stability": core.identity_stability_score,
                    "identity": new_identity[:120],
                    "weight": 0.20,
                }
            except Exception as error:
                opinions["self"] = {
                    "error": f"{type(error).__name__}: {error}",
                    "weight": 0,
                }

        # 4. Интуиция (гут-фелинг)
        intuition = None
        if self._available.get("dialogue"):
            try:
                intuition = self._systems["dialogue"].assess_intuition(topic)
                opinions["intuition"] = {
                    **intuition,
                    "weight": 0.10,
                }
            except Exception as error:
                opinions["intuition"] = {
                    "error": f"{type(error).__name__}: {error}",
                    "weight": 0,
                }

        # 5. Иммунный статус
        if self._available.get("immune"):
            try:
                health = self._systems["immune"].get_health_status()
                opinions["immune"] = {
                    "health": float(health.get("health_score", 1.0)) * 100,
                    "active_pathogens": list(health.get("active_pathogens", [])),
                    "known_threats": health.get("known_threats", 0),
                    "risks": list(health.get("risks", [])),
                    "weight": 0.10,
                }
            except Exception as error:
                opinions["immune"] = {
                    "error": f"{type(error).__name__}: {error}",
                    "weight": 0,
                }

        # 6. Выживание / гомеостаз
        if self._available.get("survival"):
            try:
                homeo = self._systems["survival"].check_homeostasis()
                opinions["survival"] = {
                    "homeostasis_maintained": homeo.get("homeostasis_maintained", True),
                    "alarms": homeo.get("alarms", []),
                    "weight": 0.05,
                }
            except Exception as error:
                opinions["survival"] = {
                    "error": f"{type(error).__name__}: {error}",
                    "weight": 0,
                }

        # ============================================================
        # Синтез финального вердикта
        # ============================================================
        score = 0.5  # нейтральная позиция
        reasons = []

        # Вклад этики (высокий вес)
        ethics = opinions.get("ethics", {})
        ethics_verdict = str(ethics.get("verdict", "")).lower()
        if "долг" in ethics_verdict or "принцип" in ethics_verdict:
            score += 0.15
            reasons.append("Этика: требует следовать принципу")
        elif "осторожн" in ethics_verdict:
            score -= 0.10
            reasons.append("Этика: рекомендует осторожность")
        elif "общей выгод" in ethics_verdict or "польз" in ethics_verdict:
            score += 0.05

        # Вклад идентичности
        self_op = opinions.get("self", {})
        stability = self_op.get("stability", 1.0)
        if stability < 0.6:
            score -= 0.20
            reasons.append(f"⚠️ Кризис идентичности (стабильность {stability:.2f})")
        elif stability > 0.85:
            score += 0.05

        # Вклад интуиции
        if intuition:
            int_score = intuition.get("intuition_score", 0.5)
            if int_score > 0.7:
                score += 0.10
                reasons.append("Интуиция: действовать")
            elif int_score < 0.5:
                score -= 0.10
                reasons.append("Интуиция: быть осторожным")

        # Вклад иммунитета
        immune = opinions.get("immune", {})
        health = immune.get("health", 100)
        if health < 50:
            score -= 0.20
            reasons.append(f"⚠️ Здоровье системы: {health}%")
        elif health < 80:
            score -= 0.05

        # Вклад гомеостаза
        survival = opinions.get("survival", {})
        if not survival.get("homeostasis_maintained", True):
            score -= 0.10
            reasons.append(
                f"⚠️ Нарушен гомеостаз: {len(survival.get('alarms', []))} тревог"
            )

        # Финальный вердикт
        score = max(0.0, min(1.0, score))
        if score >= 0.65:
            verdict = "proceed"
            emoji = "✅"
        elif score >= 0.40:
            verdict = "caution"
            emoji = "⚠️"
        else:
            verdict = "stop"
            emoji = "🛑"

        return {
            "verdict": verdict,
            "score": round(score, 3),
            "confidence": round(abs(score - 0.5) * 2, 3),
            "voices": opinions,
            "reasoning": " | ".join(reasons) if reasons else "Все системы согласны",
            "emoji": emoji,
        }

    # ============================================================
    # НОВЫЙ МЕТОД P1.1: Выбор действия из кандидатов
    # ============================================================
    def choose_action(
        self, candidates: List[Dict[str, Any]], context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Выбирает действие; симулятор может лишь ограниченно менять score."""
        if not candidates:
            return {
                "action": "wait",
                "source": "none",
                "verdict": "stop",
                "confidence": 0.0,
                "reasoning": "Нет доступных кандидатов",
                "voices": {},
                "all_evaluations": [],
                "simulation": None,
            }

        from copy import deepcopy

        simulation_mode = context.get("simulation_mode", "shadow")
        try:
            max_adjustment = float(context.get("simulation_max_adjustment", 0.0))
        except (TypeError, ValueError, OverflowError):
            max_adjustment = 0.0
        max_adjustment = max(0.0, min(0.1, max_adjustment))

        evaluations = []
        for cand in candidates:
            action_name = cand.get("action", "unknown")
            source = cand.get("source", "unknown")
            strength = cand.get("strength", 0.5)
            topic = f"{source}:{action_name}"
            verdict_result = self.arbitrate(topic, action_name)
            arbiter_score = verdict_result.get("score", 0.5)
            base_score = strength * 0.4 + arbiter_score * 0.6

            simulation = deepcopy(cand.get("simulation"))
            probability = None
            confidence = 0.0
            adjustment = 0.0
            if isinstance(simulation, dict):
                probability = simulation.get("predicted_effect_probability")
                confidence = simulation.get("confidence", 0.0) or 0.0
                if (
                    simulation_mode == "advisor"
                    and simulation.get("status") == "predicted"
                    and isinstance(probability, (int, float))
                    and not isinstance(probability, bool)
                ):
                    adjustment = max_adjustment * confidence * (2 * probability - 1)
                simulation["adjustment"] = adjustment
            combined_score = max(0.0, min(1.0, base_score + adjustment))
            evaluations.append(
                {
                    "candidate": cand,
                    "simulation": simulation,
                    "verdict": verdict_result,
                    "base_combined_score": base_score,
                    "combined_score": combined_score,
                    "arbiter_score": arbiter_score,
                    "simulation_adjustment": adjustment,
                }
            )

        evaluations.sort(key=lambda entry: entry["combined_score"], reverse=True)

        def public_evaluation(entry):
            simulation = entry["simulation"] or {}
            return {
                "action": entry["candidate"]["action"],
                "source": entry["candidate"]["source"],
                "base_combined_score": round(entry["base_combined_score"], 3),
                "predicted_effect_probability": simulation.get(
                    "predicted_effect_probability"
                ),
                "simulation_confidence": simulation.get("confidence", 0.0),
                "simulation_adjustment": round(entry["simulation_adjustment"], 3),
                "combined_score": round(entry["combined_score"], 3),
                "verdict": entry["verdict"]["verdict"],
            }

        allowed = [
            entry for entry in evaluations if entry["verdict"]["verdict"] != "stop"
        ]
        if not allowed:
            return {
                "action": "wait",
                "source": "arbitrator_refusal",
                "params": {},
                "verdict": "stop",
                "confidence": 1.0,
                "reasoning": "Все предложенные действия остановлены арбитром",
                "voices": {},
                "simulation": None,
                "all_evaluations": [public_evaluation(entry) for entry in evaluations],
            }
        best = allowed[0]
        best_candidate = best["candidate"]
        best_verdict = best["verdict"]
        reasoning = f"Выбрано: {best_candidate['action']} (источник: {best_candidate['source']}, score: {best['combined_score']:.2f}). {best_verdict['reasoning']}"
        return {
            "action": best_candidate["action"],
            "source": best_candidate["source"],
            "params": best_candidate.get("params", {}),
            "simulation": deepcopy(best["simulation"]),
            "verdict": best_verdict["verdict"],
            "confidence": best_verdict["confidence"],
            "reasoning": reasoning,
            "voices": best_verdict["voices"],
            "all_evaluations": [public_evaluation(entry) for entry in evaluations],
        }

    # ============================================================
    # Утилиты
    # ============================================================
    def get_state(self) -> Dict:
        """Возвращает текущее состояние арбитра."""
        return {
            "available_systems": [k for k, v in self._available.items() if v],
            "agent_name": self.agent_name,
        }
