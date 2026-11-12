"""Внутренний симулятор: прогноз эффекта действия по реальному опыту.

Симулятор не выполняет действия и не классифицирует их фактический успех.
Он хранит прогнозы, сопоставляет выбранный прогноз с ``had_effect`` и
сохраняет исходный опыт для восстановления после перезапуска.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
import math
from uuid import uuid4

from config.simulation_config import SIM_CONFIG


CHECKPOINT_SCHEMA_VERSION = 1
SIMULATION_STATUSES = {"predicted", "unavailable", "resolved", "cancelled"}


def _context_key(context: dict) -> str:
    return json.dumps(
        context, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _normalize_context(action: str, context=None, current_state=None) -> dict:
    context_data = context if isinstance(context, dict) else {}
    state = current_state if isinstance(current_state, dict) else {}
    if isinstance(context, str):
        target = context.strip()
    else:
        target = str(context_data.get("target") or "").strip()
    energy_band = context_data.get("energy_band", state.get("energy_band", "normal"))
    if energy_band not in {"low", "normal"}:
        energy_band = "normal"
    return {
        "action": str(action or ""),
        "target": target,
        "web_enabled": bool(
            context_data.get("web_enabled", state.get("web_enabled", False))
        ),
        "energy_band": energy_band,
    }


def _display_context(context) -> str:
    if isinstance(context, dict):
        return str(context.get("target") or "")
    return str(context or "")


def _finite(value) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
    )


def _trimmed(items: list, maximum: int, keep: int) -> None:
    if len(items) > maximum:
        del items[: len(items) - min(maximum, keep)]


class SimulationMemory:
    """Ограниченная память реальных и смоделированных событий."""

    def __init__(self):
        self.real_events = []
        self.simulated_events = []
        self.causal_rules = {}

    def _rebuild_causal_rules(self) -> None:
        self.causal_rules = {}
        for event in self.real_events:
            self.causal_rules.setdefault(event["action"], []).append(
                {
                    "outcome": event["outcome"],
                    "success": event["success"],
                    "context": event["context"],
                }
            )

    def store_real_event(
        self,
        action: str,
        context,
        outcome: str,
        success: bool,
        confidence: float = 0.5,
        *,
        target: str | None = None,
        context_key: str | None = None,
        actual_delta: dict | None = None,
        intention_id: str | None = None,
    ):
        """Сохраняет выполненное действие и его наблюдаемую разницу."""
        context_data = _normalize_context(action, context)
        if target is not None:
            context_data["target"] = str(target or "").strip()
        key = context_key or _context_key(context_data)
        event = {
            "type": "real",
            "action": str(action),
            "target": context_data["target"],
            "context_key": key,
            "context": _display_context(context) or context_data["target"],
            "context_data": deepcopy(context_data),
            "outcome": str(outcome),
            "actual_delta": deepcopy(actual_delta or {}),
            "success": bool(success),
            "confidence": float(confidence),
            "intention_id": intention_id,
            "timestamp": datetime.now().isoformat(),
        }
        self.real_events.append(event)
        _trimmed(
            self.real_events,
            max(1, int(getattr(SIM_CONFIG, "MAX_SIMULATION_REAL_EVENTS", 500))),
            max(1, int(getattr(SIM_CONFIG, "SIMULATION_REAL_EVENTS_KEEP", 250))),
        )
        self._rebuild_causal_rules()
        return event

    def store_simulation(
        self,
        action: str,
        context,
        predicted_outcome: str,
        actual_outcome: str = None,
        success: bool = None,
        **details,
    ):
        """Сохраняет один прогноз, включая его структурированный контекст."""
        event = {
            "type": "simulation",
            "action": str(action),
            "context": _display_context(context),
            "predicted_outcome": str(predicted_outcome),
            "actual_outcome": actual_outcome,
            "success": success,
            "timestamp": datetime.now().isoformat(),
        }
        event.update(deepcopy(details))
        self.simulated_events.append(event)
        _trimmed(
            self.simulated_events,
            max(1, int(getattr(SIM_CONFIG, "MAX_SIMULATED_EVENTS", 50))),
            max(1, int(getattr(SIM_CONFIG, "SIMULATED_EVENTS_KEEP", 25))),
        )
        return event


class MentalSimulation:
    """Результат одного прогноза без выполнения действия."""

    def __init__(self):
        self.prediction_id = str(uuid4())
        self.schema_version = CHECKPOINT_SCHEMA_VERSION
        self.action = ""
        self.target = ""
        self.context = ""
        self.context_key = ""
        self.status = "unavailable"
        self.predicted_effect_probability = None
        self.sample_size = 0
        self.predicted_outcome = ""
        self.confidence = 0.0
        self.adjustment = 0.0
        self.alternative_strategies = []
        self.risks = []
        self.benefits = []

    def to_dict(self) -> dict:
        return {
            "prediction_id": self.prediction_id,
            "schema_version": self.schema_version,
            "action": self.action,
            "target": self.target,
            "context": self.context,
            "context_key": self.context_key,
            "status": self.status,
            "predicted_effect_probability": self.predicted_effect_probability,
            "confidence": self.confidence,
            "sample_size": self.sample_size,
            "predicted_outcome": self.predicted_outcome,
            "adjustment": self.adjustment,
            "alternative_strategies": self.alternative_strategies[:3],
            "risks": self.risks[:3],
            "benefits": self.benefits[:3],
        }


class InternalSimulator:
    """Эмпирический прогноз вероятности наблюдаемого эффекта."""

    def __init__(self, agent_name: str = "agent"):
        self.agent_name = agent_name
        self.memory = SimulationMemory()
        self.max_simulations = 10
        self.min_experience_for_sim = 3
        self.prediction_accuracy_history = []
        # Старый индекс сохранён для совместимости, но строгий отбор опыта
        # больше не зависит от совпадения отдельных слов.
        self.context_index = {}

    def _index_context(self, event: dict):
        words = (
            str(event.get("context", "")).split() + str(event.get("action", "")).split()
        )
        for word in words:
            if len(word) > 3:
                self.context_index.setdefault(word, []).append(event)

    def find_similar_experience(
        self, action: str, context, max_results: int | None = 5
    ) -> list[dict]:
        """Возвращает опыт строго того же действия и темы.

        Для ``web_search`` дополнительно требуется то же состояние сети.
        Энергетический диапазон входит в ключ контекста для диагностики, но
        в первом варианте не дробит и без того маленькую выборку.
        """
        wanted = _normalize_context(action, context)
        matches = []
        for event in self.memory.real_events:
            event_context = event.get("context_data")
            if not isinstance(event_context, dict):
                event_context = _normalize_context(
                    event.get("action", ""), event.get("context", "")
                )
            if event.get("action") != wanted["action"]:
                continue
            if (
                str(event.get("target") or event_context.get("target") or "")
                != wanted["target"]
            ):
                continue
            if (
                action == "web_search"
                and bool(event_context.get("web_enabled")) != wanted["web_enabled"]
            ):
                continue
            matches.append(event)
        if max_results is not None:
            return matches[-max(0, int(max_results)) :]
        return matches

    def simulate_outcome(
        self, planned_action: str, current_state: dict, context=""
    ) -> MentalSimulation:
        """Создаёт и сохраняет прогноз, не изменяя состояние агента."""
        context_data = _normalize_context(planned_action, context, current_state)
        simulation = MentalSimulation()
        simulation.action = context_data["action"]
        simulation.target = context_data["target"]
        simulation.context = _display_context(context) or simulation.target
        simulation.context_key = _context_key(context_data)

        experiences = self.find_similar_experience(
            simulation.action, context_data, max_results=None
        )
        simulation.sample_size = len(experiences)
        if len(experiences) < self.min_experience_for_sim:
            simulation.predicted_outcome = (
                f"неопределенно: для {simulation.action} мало опыта по этой теме"
            )
            simulation.alternative_strategies = [
                f"собрать больше опыта для {simulation.action}"
            ]
        else:
            successful = [
                event for event in experiences if event.get("success") is True
            ]
            failed = [event for event in experiences if event.get("success") is False]
            probability = len(successful) / len(experiences)
            simulation.status = "predicted"
            simulation.predicted_effect_probability = probability
            simulation.confidence = min(1.0, len(experiences) / 10.0)
            simulation.predicted_outcome = (
                f"вероятность наблюдаемого эффекта: {probability:.0%} "
                f"(опыт: {len(experiences)})"
            )
            simulation.benefits = [
                "прошлый результат: " + str(event.get("outcome", ""))[:40]
                for event in successful[:3]
            ]
            simulation.risks = [
                "прошлый пустой результат: " + str(event.get("outcome", ""))[:40]
                for event in failed[:3]
            ]
            alternatives = []
            for event in experiences:
                hint = self._extract_strategy_hint(event)
                if hint and hint not in alternatives:
                    alternatives.append(hint)
            simulation.alternative_strategies = alternatives[:3]

        data = simulation.to_dict()
        self.memory.store_simulation(context_data=context_data, **data)
        return simulation

    def _extract_strategy_hint(self, event: dict) -> str:
        ctx = str(event.get("target") or event.get("context") or "unknown")[:30]
        if event.get("success"):
            return "повторить опыт по теме: '" + ctx + "'"
        return "учесть пустой результат по теме: '" + ctx + "'"

    def run_mental_experiment(
        self, action: str, context: str, iterations: int = 5
    ) -> dict:
        """Совместимый диагностический метод; в основной контур не входит."""
        iterations = max(0, int(iterations))
        results = {"success_count": 0, "total": iterations, "predictions": []}
        for _ in range(iterations):
            simulation = self.simulate_outcome(action, {}, context)
            results["predictions"].append(simulation.to_dict())
            probability = simulation.predicted_effect_probability
            if probability is not None and probability >= 0.5:
                results["success_count"] += 1
        predicted_success_rate = (
            results["success_count"] / results["total"] if iterations else 0.0
        )
        return {
            "action": action,
            "simulated_success_rate": round(predicted_success_rate, 3),
            "confidence": (
                sum(p["confidence"] for p in results["predictions"]) / iterations
                if iterations
                else 0.0
            ),
            "best_prediction": (
                max(results["predictions"], key=lambda p: p["confidence"])
                if results["predictions"]
                else None
            ),
            "recommendation": (
                "выполнить"
                if predicted_success_rate > 0.6
                else "осторожно"
                if predicted_success_rate > 0.3
                else "избегать"
            ),
            "iterations": iterations,
        }

    def compare_strategies(self, actions: list[str], context: str) -> list[dict]:
        comparisons = [
            self.run_mental_experiment(action, context, iterations=3)
            for action in actions
        ]
        comparisons.sort(
            key=lambda result: result["simulated_success_rate"] * result["confidence"],
            reverse=True,
        )
        return comparisons

    def learn_from_outcome(
        self,
        action: str,
        context,
        actual_outcome: str,
        success: bool,
        *,
        prediction_id: str | None = None,
        target: str | None = None,
        context_key: str | None = None,
        actual_delta: dict | None = None,
        intention_id: str | None = None,
        confidence: float = 0.5,
    ) -> dict:
        """Сохраняет факт и разрешает только указанный выбранный прогноз."""
        if intention_id and any(
            event.get("intention_id") == intention_id
            for event in self.memory.real_events
        ):
            return {"duplicate": True, "real_event": None, "prediction": None}
        event = self.memory.store_real_event(
            action,
            context,
            actual_outcome,
            bool(success),
            confidence,
            target=target,
            context_key=context_key,
            actual_delta=actual_delta,
            intention_id=intention_id,
        )
        self._index_context(event)
        # Вспомогательный индекс не должен удерживать события, уже
        # вытесненные из ограниченной основной памяти.
        if len(self.memory.real_events) >= max(
            1, int(getattr(SIM_CONFIG, "MAX_SIMULATION_REAL_EVENTS", 500))
        ):
            self.context_index = {}
            for saved_event in self.memory.real_events:
                self._index_context(saved_event)
        feedback = None
        if prediction_id:
            feedback = self.resolve_prediction(
                prediction_id,
                actual_outcome=actual_outcome,
                success=bool(success),
                actual_delta=actual_delta,
                intention_id=intention_id,
            )
        return {"duplicate": False, "real_event": event, "prediction": feedback}

    def resolve_prediction(
        self,
        prediction_id: str,
        *,
        actual_outcome: str,
        success: bool,
        actual_delta: dict | None = None,
        intention_id: str | None = None,
    ) -> dict | None:
        """Однократно сравнивает конкретный прогноз с ``had_effect``."""
        prediction = next(
            (
                event
                for event in self.memory.simulated_events
                if event.get("prediction_id") == prediction_id
            ),
            None,
        )
        if prediction is None or prediction.get("status") != "predicted":
            return None
        probability = prediction.get("predicted_effect_probability")
        if not _finite(probability) or not 0.0 <= probability <= 1.0:
            return None
        actual = 1.0 if success else 0.0
        absolute_error = abs(float(probability) - actual)
        matched = (float(probability) >= 0.5) == bool(success)
        timestamp = datetime.now().isoformat()
        prediction.update(
            {
                "status": "resolved",
                "actual_outcome": str(actual_outcome),
                "success": bool(success),
                "actual_delta": deepcopy(actual_delta or {}),
                "absolute_error": absolute_error,
                "prediction_matched": matched,
                "intention_id": intention_id,
                "resolved_at": timestamp,
            }
        )
        feedback = {
            "prediction_id": prediction_id,
            "action": prediction.get("action", ""),
            "target": prediction.get("target", ""),
            "predicted_effect_probability": float(probability),
            "had_effect": bool(success),
            "actual_delta": deepcopy(actual_delta or {}),
            "absolute_error": absolute_error,
            "prediction_matched": matched,
            "intention_id": intention_id,
            "timestamp": timestamp,
            # Старое имя используется сводкой средней точности.
            "was_correct": matched,
        }
        self.prediction_accuracy_history.append(feedback)
        _trimmed(
            self.prediction_accuracy_history,
            max(1, int(getattr(SIM_CONFIG, "MAX_SIMULATION_ACCURACY_HISTORY", 500))),
            max(1, int(getattr(SIM_CONFIG, "SIMULATION_ACCURACY_HISTORY_KEEP", 250))),
        )
        return deepcopy(feedback)

    def cancel_prediction(self, prediction_id: str, reason: str) -> bool:
        prediction = next(
            (
                event
                for event in self.memory.simulated_events
                if event.get("prediction_id") == prediction_id
            ),
            None,
        )
        if prediction is None or prediction.get("status") != "predicted":
            return False
        prediction["status"] = "cancelled"
        prediction["cancel_reason"] = str(reason)
        prediction["cancelled_at"] = datetime.now().isoformat()
        return True

    def get_simulation_readiness(self) -> dict:
        total_experience = len(self.memory.real_events)
        return {
            "total_real_events": total_experience,
            "unique_actions": len(
                {event["action"] for event in self.memory.real_events}
            ),
            "causal_rules_count": len(self.memory.causal_rules),
            "prediction_accuracy": self._get_avg_prediction_accuracy(),
            "ready_for_simulation": total_experience >= self.min_experience_for_sim,
        }

    def _get_avg_prediction_accuracy(self) -> float:
        if not self.prediction_accuracy_history:
            return 0.0
        correct = sum(
            1
            for prediction in self.prediction_accuracy_history
            if prediction.get("was_correct")
        )
        return correct / len(self.prediction_accuracy_history)

    def get_status(self) -> dict:
        readiness = self.get_simulation_readiness()
        top_rules = {}
        for action, outcomes in self.memory.causal_rules.items():
            if not outcomes:
                continue
            success_rate = sum(1 for outcome in outcomes if outcome["success"]) / len(
                outcomes
            )
            top_rules[action] = {
                "attempts": len(outcomes),
                "success_rate": round(success_rate, 3),
            }
        return {
            "simulation_readiness": readiness,
            "top_causal_rules": dict(
                sorted(
                    top_rules.items(),
                    key=lambda item: item[1]["attempts"],
                    reverse=True,
                )[:5]
            ),
            "simulations_stored": len(self.memory.simulated_events),
            "prediction_history_count": len(self.prediction_accuracy_history),
        }

    def to_dict(self) -> dict:
        """Возвращает сводку; для чекпоинта используется отдельный метод."""
        return {
            "agent_name": self.agent_name,
            "memory_summary": {
                "real_events": len(self.memory.real_events),
                "simulated_events": len(self.memory.simulated_events),
                "causal_rules_count": len(self.memory.causal_rules),
            },
            "prediction_accuracy": self._get_avg_prediction_accuracy(),
            "status": self.get_status(),
        }

    def to_checkpoint_dict(self) -> dict:
        """Сохраняет исходный опыт, а не только сводные счётчики."""
        return {
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "real_events": deepcopy(self.memory.real_events),
            "simulated_events": deepcopy(self.memory.simulated_events),
            "prediction_accuracy_history": deepcopy(self.prediction_accuracy_history),
        }

    @staticmethod
    def validate_checkpoint_dict(state: dict) -> None:
        """Проверяет новую секцию до любого изменения живого симулятора."""
        if not isinstance(state, dict):
            raise ValueError("internal_simulation: нужен словарь")
        if state.get("schema_version") != CHECKPOINT_SCHEMA_VERSION:
            raise ValueError(
                "internal_simulation.schema_version: неподдерживаемая версия"
            )
        limits = {
            "real_events": max(
                1, int(getattr(SIM_CONFIG, "MAX_SIMULATION_REAL_EVENTS", 500))
            ),
            "simulated_events": max(
                1, int(getattr(SIM_CONFIG, "MAX_SIMULATED_EVENTS", 50))
            ),
            "prediction_accuracy_history": max(
                1, int(getattr(SIM_CONFIG, "MAX_SIMULATION_ACCURACY_HISTORY", 500))
            ),
        }
        for field, limit in limits.items():
            events = state.get(field)
            if not isinstance(events, list) or len(events) > limit:
                raise ValueError(
                    f"internal_simulation.{field}: нужен ограниченный список"
                )
            for index, event in enumerate(events):
                path = f"internal_simulation.{field}[{index}]"
                if not isinstance(event, dict):
                    raise ValueError(f"{path}: нужен словарь")
                if field == "real_events":
                    for name in (
                        "action",
                        "target",
                        "context_key",
                        "context",
                        "outcome",
                        "timestamp",
                    ):
                        if not isinstance(event.get(name), str):
                            raise ValueError(f"{path}.{name}: нужна строка")
                    if type(event.get("success")) is not bool:
                        raise ValueError(f"{path}.success: нужен bool")
                    if (
                        not _finite(event.get("confidence"))
                        or not 0.0 <= event["confidence"] <= 1.0
                    ):
                        raise ValueError(f"{path}.confidence: вне [0, 1]")
                    if not isinstance(event.get("context_data"), dict):
                        raise ValueError(f"{path}.context_data: нужен словарь")
                    delta = event.get("actual_delta")
                    if not isinstance(delta, dict) or any(
                        not _finite(value) for value in delta.values()
                    ):
                        raise ValueError(f"{path}.actual_delta: нужны конечные числа")
                elif field == "simulated_events":
                    for name in (
                        "prediction_id",
                        "action",
                        "target",
                        "context_key",
                        "predicted_outcome",
                        "timestamp",
                    ):
                        if not isinstance(event.get(name), str):
                            raise ValueError(f"{path}.{name}: нужна строка")
                    if event.get("status") not in SIMULATION_STATUSES:
                        raise ValueError(f"{path}.status: неизвестный статус")
                    probability = event.get("predicted_effect_probability")
                    if probability is not None and (
                        not _finite(probability) or not 0.0 <= probability <= 1.0
                    ):
                        raise ValueError(
                            f"{path}.predicted_effect_probability: вне [0, 1]"
                        )
                    if (
                        not _finite(event.get("confidence"))
                        or not 0.0 <= event["confidence"] <= 1.0
                    ):
                        raise ValueError(f"{path}.confidence: вне [0, 1]")
                    if (
                        type(event.get("sample_size")) is not int
                        or event["sample_size"] < 0
                    ):
                        raise ValueError(
                            f"{path}.sample_size: нужно неотрицательное целое"
                        )
                else:
                    if not isinstance(event.get("prediction_id"), str):
                        raise ValueError(f"{path}.prediction_id: нужна строка")
                    if type(event.get("was_correct")) is not bool:
                        raise ValueError(f"{path}.was_correct: нужен bool")
                    if (
                        not _finite(event.get("absolute_error"))
                        or not 0.0 <= event["absolute_error"] <= 1.0
                    ):
                        raise ValueError(f"{path}.absolute_error: вне [0, 1]")

    def restore_from_checkpoint(self, state: dict) -> None:
        self.validate_checkpoint_dict(state)
        restored_real = deepcopy(state["real_events"])
        restored_simulations = deepcopy(state["simulated_events"])
        for prediction in restored_simulations:
            if prediction.get("status") == "predicted":
                prediction["status"] = "cancelled"
                prediction["cancel_reason"] = "interrupted"
        self.memory.real_events = restored_real
        self.memory.simulated_events = restored_simulations
        self.prediction_accuracy_history = deepcopy(
            state["prediction_accuracy_history"]
        )
        self.memory._rebuild_causal_rules()
        self.context_index = {}
        for event in self.memory.real_events:
            self._index_context(event)


__all__ = ["InternalSimulator", "MentalSimulation", "SimulationMemory"]
