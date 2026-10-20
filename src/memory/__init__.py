"""Инициализация пакета memory.

Центральный экспорт LongTermMemory (раньше legacy-классы Memory,
KnowledgeAssociationEngine, MentalModelsPreferences жили здесь,
но они удалены из кодовой базы в рамках Шага 6 оптимизации).

Эта версия __init__.py нормально экспортирует LongTermMemory,
чтобы можно было писать `from src.memory import LongTermMemory`
без хаков с importlib.
"""

from src.memory.long_term_memory import LongTermMemory

__all__ = ["LongTermMemory"]