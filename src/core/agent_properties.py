"""Compatibility property implementations extracted from ``agent.py``.

The public ``property`` objects and their decorators remain on ``DigitalBeing``.
These helpers preserve subsystem/legacy fallback behavior and queue assignment
semantics; ThinkingPipeline wrappers stay in the composition core.
"""

from typing import Dict


def energy_get_impl(self) -> float:
    if hasattr(self, "energy_subsystem") and self.energy_subsystem is not None:
        return self.energy_subsystem.energy
    return getattr(self, "_legacy_energy", 0)


def energy_set_impl(self, value: float) -> None:
    if hasattr(self, "energy_subsystem") and self.energy_subsystem is not None:
        self.energy_subsystem.energy = value
    else:
        self._legacy_energy = value


def knowledge_base_get_impl(self) -> Dict[str, str]:
    if hasattr(self, "knowledge_subsystem") and self.knowledge_subsystem is not None:
        return self.knowledge_subsystem.knowledge_base
    return getattr(self, "_legacy_knowledge_base", {})


def knowledge_base_set_impl(self, value: Dict[str, str]) -> None:
    if hasattr(self, "knowledge_subsystem") and self.knowledge_subsystem is not None:
        self.knowledge_subsystem.knowledge_base = value
    else:
        self._legacy_knowledge_base = value


def open_questions_get_impl(self) -> list:
    """Backward-compat property: возвращает очередь OpenQuestionsManager.

    Позволяет существующему коду (``for q in self._open_questions:``,
    ``self._open_questions.append(...)``) работать без изменений.
    Изменения через этот property проксируются в manager.queue.
    """
    if not hasattr(self, "_open_questions_manager"):
        return []
    return self._open_questions_manager.queue


def open_questions_set_impl(self, value) -> None:
    """Backward-compat setter: заменяет очередь целиком.

    Используется в тестах для сброса (``a._open_questions = []``) и в
    legacy-коде, который не знает про OpenQuestionsManager. После
    присвоения все методы Open Questions будут работать с новой очередью.
    """
    if not hasattr(self, "_open_questions_manager"):
        return
    if value is None:
        self._open_questions_manager.queue = []
    else:
        self._open_questions_manager.queue = list(value)
