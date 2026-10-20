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

from typing import Dict, Optional, List


class DecisionArbitrator:
    """Арбитр решений — интегратор всех подсистем."""

    def __init__(self, agent_name: str = "agent"):
        # Ленивые импорты через importlib.util (обход __init__.py пакета src.emotion)
        import importlib.util
        import os
        self._systems: Dict[str, object] = {}
        self._available = {}

        def _try_load(key, module_path, class_name):
            parts = module_path.split('.')
            file_path = os.path.join(*parts) + '.py'
            if not os.path.exists(file_path):
                self._available[key] = False
                return
            try:
                spec = importlib.util.spec_from_file_location(
                    f"arbitrator_{key}", file_path
                )
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                cls = getattr(module, class_name)
                self._systems[key] = cls()
                self._available[key] = True
            except Exception:
                self._available[key] = False

        _try_load("dialogue", "src.consciousness.internal_dialogue",
                  "InternalDialogueEngine")
        _try_load("ethics", "src.emotion.ethical_core", "EthicalCoreSystem")
        _try_load("self", "src.core.self_identity_module", "CoreSelfModule")

        self.agent_name = agent_name

    # ============================================================
    # Связывание с иммунной системой (создаётся извне)
    # ============================================================
    def attach_immune_system(self, immune_system) -> None:
        self._systems["immune"] = immune_system
        self._available["immune"] = True

    def attach_meaning_finder(self, meaning_finder) -> None:
        self._systems["meaning"] = meaning_finder
        self._available["meaning"] = True

    def attach_survival_instincts(self, survival) -> None:
        self._systems["survival"] = survival
        self._available["survival"] = True

    def attach_embodiment(self, embodiment) -> None:
        self._systems["embodiment"] = embodiment
        self._available["embodiment"] = True

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
            except Exception:
                opinions["dialogue"] = {"error": True, "weight": 0}

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
            except Exception:
                opinions["ethics"] = {"weight": 0}

        # 3. Самоидентичность
        if self._available.get("self"):
            try:
                core = self._systems["self"]
                # Синтезируем с учётом текущего вердикта диалога
                dominant = opinions.get("dialogue", {}).get(
                    "dominant_voice", "Наблюдатель"
                )
                new_identity = core.synthesize({
                    "dominant_voice": dominant,
                    "voices": [dominant],
                    "reason": topic,
                })
                opinions["self"] = {
                    "stability": core.identity_stability_score,
                    "identity": new_identity[:120],
                    "weight": 0.20,
                }
            except Exception:
                opinions["self"] = {"weight": 0}

        # 4. Интуиция (гут-фелинг)
        intuition = None
        if self._available.get("dialogue"):
            try:
                intuition = self._systems["dialogue"].assess_intuition(topic)
                opinions["intuition"] = {
                    **intuition,
                    "weight": 0.10,
                }
            except Exception:
                pass

        # 5. Иммунный статус
        if self._available.get("immune"):
            try:
                health = self._systems["immune"].get_health_report()
                opinions["immune"] = {
                    "health": health.get("health_percentage", 100),
                    "active_pathogens": health.get("active_pathogens", []),
                    "weight": 0.10,
                }
            except Exception:
                opinions["immune"] = {"weight": 0}

        # 6. Выживание / гомеостаз
        if self._available.get("survival"):
            try:
                homeo = self._systems["survival"].check_homeostasis()
                opinions["survival"] = {
                    "homeostasis_maintained": homeo.get("homeostasis_maintained", True),
                    "alarms": homeo.get("alarms", []),
                    "weight": 0.05,
                }
            except Exception:
                opinions["survival"] = {"weight": 0}

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
            reasons.append(f"⚠️ Нарушен гомеостаз: {len(survival.get('alarms', []))} тревог")

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
    # Утилиты
    # ============================================================
    def get_state(self) -> Dict:
        """Возвращает текущее состояние арбитра."""
        return {
            "available_systems": [k for k, v in self._available.items() if v],
            "agent_name": self.agent_name,
        }