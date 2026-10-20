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


class SoulController:
    """Контроллер души — оркестратор всех экзистенциальных подсистем."""

    def __init__(self, agent_name: str = "agent"):
        self.agent_name = agent_name
        self._systems: Dict[str, object] = {}
        self._available: Dict[str, bool] = {}

        # Ленивая загрузка каждой системы
        self._try_import(
            "dialogue", "src.consciousness.internal_dialogue", "InternalDialogueEngine"
        )
        self._try_import(
            "ethics", "src.emotion.ethical_core", "EthicalCoreSystem"
        )
        self._try_import(
            "self", "src.core.self_identity_module", "CoreSelfModule"
        )
        self._try_import(
            "meaning", "src.motivation.intrinsic_meaning_finder", "IntrinsicMeaningFinder"
        )
        self._try_import(
            "immune", "src.emotion.immuno_system", "ImmuneSystem"
        )
        self._try_import(
            "survival", "src.emotion.survival_instincts", "SurvivalInstincts"
        )

        self.current_quest: Optional[str] = None
        self.tick_count = 0

    def _try_import(self, key: str, module_path: str, class_name: str) -> None:
        """Пытается импортировать модуль и создать экземпляр класса.

        Использует importlib.util.spec_from_file_location чтобы обойти
        __init__.py пакета src.emotion (там не-ASCII символы в комментариях).
        """
        import importlib.util
        import os
        # Преобразуем 'src.emotion.ethical_core' → путь к файлу
        parts = module_path.split('.')
        file_path = os.path.join(*parts) + '.py'
        if not os.path.exists(file_path):
            self._systems[key] = None
            self._available[key] = False
            return
        try:
            spec = importlib.util.spec_from_file_location(
                f"soul_{key}", file_path
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            cls = getattr(module, class_name)
            self._systems[key] = cls()
            self._available[key] = True
        except Exception:
            self._systems[key] = None
            self._available[key] = False

    # ============================================================
    # Главный цикл
    # ============================================================
    def tick(self, cycle_count: int, agent=None) -> Dict:
        """Один цикл души — обновляет все системы.

        Возвращает сводный отчёт.
        """
        self.tick_count += 1
        report: Dict = {"cycle": cycle_count, "systems": {}}

        # 1. Внутренний диалог — откликается на текущий момент
        if self._available.get("dialogue") and self.tick_count % 5 == 0:
            try:
                topic = f"цикл {cycle_count}: что я делаю и зачем"
                dialogue = self._systems["dialogue"].initiate_dialogue(topic)
                report["systems"]["dialogue"] = {
                    "dominant_voice": dialogue.get("dominant_voice"),
                    "harmony": dialogue.get("harmony", 0.5),
                }
            except Exception:
                pass

        # 2. Иммунная система — периодическое сканирование
        if self._available.get("immune") and self.tick_count % 20 == 0:
            try:
                self._systems["immune"].scan_for_infections()
                health = self._systems["immune"].get_health_report()
                report["systems"]["immune"] = health
            except Exception:
                pass

        # 3. Survival — проверка гомеостаза
        if self._available.get("survival") and self.tick_count % 10 == 0:
            try:
                homeo = self._systems["survival"].check_homeostasis()
                report["systems"]["survival"] = homeo
            except Exception:
                pass

        # 4. Intrinsic Meaning — обновляем квест, если пора
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
            except Exception:
                pass

        # 5. Self — синтез идентичности (если был конфликт в диалоге)
        if self._available.get("self") and self.tick_count % 7 == 0:
            try:
                core = self._systems["self"]
                dominant = report["systems"].get(
                    "dialogue", {}
                ).get("dominant_voice", "Наблюдатель")
                new_identity = core.synthesize({
                    "dominant_voice": dominant,
                    "voices": [dominant],
                    "reason": f"cycle_{cycle_count}",
                })
                report["systems"]["self"] = {
                    "stability": round(core.identity_stability_score, 3),
                    "identity_preview": new_identity[:80],
                    "integrity": core.check_integrity(),
                }
            except Exception:
                pass

        return report

    # ============================================================
    # Доступ к отдельным системам (для DecisionArbitrator)
    # ============================================================
    def get(self, key: str):
        return self._systems.get(key)

    def is_available(self, key: str) -> bool:
        return self._available.get(key, False)

    def get_all_systems_state(self) -> Dict:
        """Возвращает текущее состояние всех систем."""
        state = {"available": [k for k, v in self._available.items() if v]}
        for key, sys in self._systems.items():
            if sys is None:
                continue
            try:
                if hasattr(sys, "get_micrbiome_state"):
                    state[key] = sys.get_micrbiome_state()
                elif hasattr(sys, "get_health_report"):
                    state[key] = sys.get_health_report()
                elif hasattr(sys, "get_status_report"):
                    state[key] = sys.get_status_report()
                elif hasattr(sys, "get_current_quest"):
                    state[key] = {"quest": sys.get_current_quest()}
            except Exception:
                pass
        return state

    def get_current_quest(self) -> Optional[str]:
        return self.current_quest