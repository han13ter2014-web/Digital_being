"""
SoulController — оркестратор всех «душевных» подсистем.

Объединяет:
- InternalDialogueEngine (6 голосов)
- EthicalCoreSystem (3 фреймворка)
- CoreSelfModule (идентичность)
- IntrinsicMeaningFinder (поиск смысла)
- ImmuneSystem (иммунитет)
- SurvivalInstincts (инстинкты)

Один раз в цикл:
1. Обновляет каждую систему.
2. Синхронизирует их состояние.
3. Возвращает сводный отчёт.

Это «душа» Digital Being — то, что делает его больше, чем набор скриптов.
"""

from typing import Dict, Optional

from src.consciousness.internal_dialogue import InternalDialogueEngine
from src.core.self_identity_module import CoreSelfModule
from src.emotion.ethical_core import EthicalCoreSystem
from src.emotion.immune_system import ImmuneSystem
from src.emotion.survival_instincts import SurvivalInstincts
from src.motivation.intrinsic_meaning_finder import IntrinsicMeaningFinder


class SoulController:
    """Контроллер души — оркестратор всех экзистенциальных подсистем."""

    def __init__(self, agent_name: str = "agent"):
        self.agent_name = agent_name
        self._systems: Dict[str, object] = {
            "dialogue": InternalDialogueEngine(),
            "ethics": EthicalCoreSystem(),
            "self": CoreSelfModule(),
            "meaning": IntrinsicMeaningFinder(),
            "immune": ImmuneSystem(),
            "survival": SurvivalInstincts(),
        }
        self._available: Dict[str, bool] = {key: True for key in self._systems}
        self._errors: Dict[str, str] = {}
        self.current_quest: Optional[str] = None
        self.tick_count = 0

    # ============================================================
    # Главный цикл
    # ============================================================
    def _record_error(self, report: Dict, key: str, error: Exception) -> None:
        message = f"{type(error).__name__}: {error}"
        report["systems"][key] = {"error": message}
        self._errors[key] = message

    def tick(self, cycle_count: int, agent=None) -> Dict:
        """Обновляет системы и возвращает отчёт, включая ошибки датчиков."""
        self.tick_count += 1
        report: Dict = {"cycle": cycle_count, "systems": {}}

        if self._available.get("dialogue") and self.tick_count % 5 == 0:
            try:
                topic = f"цикл {cycle_count}: что я делаю и зачем"
                dialogue = self._systems["dialogue"].initiate_dialogue(topic)
                report["systems"]["dialogue"] = {
                    "dominant_voice": dialogue.get("dominant_voice"),
                    "harmony": dialogue.get("harmony", 0.5),
                }
                self._errors.pop("dialogue", None)
            except Exception as error:
                self._record_error(report, "dialogue", error)

        # Иммунная память читается без выдуманного периодического сканирования.
        if self._available.get("immune") and self.tick_count % 20 == 0:
            try:
                report["systems"]["immune"] = self._systems[
                    "immune"
                ].get_health_status()
                self._errors.pop("immune", None)
            except Exception as error:
                self._record_error(report, "immune", error)

        if self._available.get("survival") and self.tick_count % 10 == 0:
            try:
                report["systems"]["survival"] = self._systems[
                    "survival"
                ].check_homeostasis()
                self._errors.pop("survival", None)
            except Exception as error:
                self._record_error(report, "survival", error)

        if self._available.get("meaning"):
            try:
                finder = self._systems["meaning"]
                if finder.needs_reorientation() or not self.current_quest:
                    self_report = (
                        report["systems"].get("self", {}).get("identity")
                        or "Я продолжаю существовать и учиться."
                    )
                    new_quest = finder.generate_quest(self_report)
                    if new_quest:
                        finder.set_quest(new_quest)
                        self.current_quest = new_quest
                        report["systems"]["meaning"] = {"new_quest": new_quest}
                self._errors.pop("meaning", None)
            except Exception as error:
                self._record_error(report, "meaning", error)

        if self._available.get("self") and self.tick_count % 7 == 0:
            try:
                core = self._systems["self"]
                dominant = (
                    report["systems"]
                    .get("dialogue", {})
                    .get("dominant_voice", "Наблюдатель")
                )
                new_identity = core.synthesize(
                    {
                        "dominant_voice": dominant,
                        "voices": [dominant],
                        "reason": f"cycle_{cycle_count}",
                    }
                )
                report["systems"]["self"] = {
                    "stability": round(core.identity_stability_score, 3),
                    "identity_preview": new_identity[:80],
                    "integrity": core.check_integrity(),
                }
                self._errors.pop("self", None)
            except Exception as error:
                self._record_error(report, "self", error)

        return report

    # ============================================================
    # Доступ к отдельным системам (для DecisionArbitrator)
    # ============================================================
    def get(self, key: str):
        return self._systems.get(key)

    def is_available(self, key: str) -> bool:
        return self._available.get(key, False)

    def get_all_systems_state(self) -> Dict:
        """Возвращает состояние систем и последние видимые ошибки."""
        state = {
            "available": [k for k, v in self._available.items() if v],
            "errors": dict(self._errors),
        }
        for key, sys in self._systems.items():
            if sys is None:
                continue
            try:
                if hasattr(sys, "get_micrbiome_state"):
                    state[key] = sys.get_micrbiome_state()
                elif hasattr(sys, "get_health_status"):
                    state[key] = sys.get_health_status()
                elif hasattr(sys, "get_health_report"):
                    state[key] = sys.get_health_report()
                elif hasattr(sys, "get_status_report"):
                    state[key] = sys.get_status_report()
                elif hasattr(sys, "get_current_quest"):
                    state[key] = {"quest": sys.get_current_quest()}
                self._errors.pop(key, None)
                state["errors"].pop(key, None)
            except Exception as error:
                message = f"{type(error).__name__}: {error}"
                state["errors"][key] = message
                self._errors[key] = message
        return state

    def get_current_quest(self) -> Optional[str]:
        return self.current_quest
