"""
Загрузка родовых знаний (bootstrap knowledge) при первом запуске агента.
"""

import json
import os
from pathlib import Path
from src.core.buffered_logger import get_logger

logger = get_logger()


def load_initial_knowledge(agent, knowledge_path: str = None) -> bool:
    """
    Загружает базовые знания в ментальные модели агента.
    
    Args:
        agent: Экземпляр DigitalBeing
        knowledge_path: Путь к JSON файлу (по умолчанию data/initial_knowledge.json)
    
    Returns:
        True если загрузка прошла успешно, False если знания уже загружены или ошибка
    """
    if knowledge_path is None:
        knowledge_path = Path(__file__).parent.parent.parent / "data" / "initial_knowledge.json"
    
    # Проверяем маркер "уже загружено" в ментальных моделях
    if agent.mental_models.concepts.get("_bootstrap_loaded"):
        logger.log("[BOOTSTRAP] Знания уже загружены, пропускаем")
        return False
    
    if not os.path.exists(knowledge_path):
        logger.log(f"[BOOTSTRAP] Файл не найден: {knowledge_path}")
        return False
    
    try:
        with open(knowledge_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        logger.log(f"[BOOTSTRAP] Загружаю родовые знания v{data.get('version', '1.0')}")
        
        # 1. Загружаем концепты
        concepts_loaded = 0
        for name, info in data.get("concepts", {}).items():
            agent.mental_models.encounter_concept(
                concept_name=name,
                context="innate_knowledge",
                outcome=info["definition"],
                valence=info.get("valence", 0.5),
                evidence_strength=max(0.0, min(1.0, (info.get("confidence", 0.9) - 0.1) * 1.5)),
                evidence_kind="innate", source=f"innate:{name}",
            )
            # Та же формула свидетельств, что при загрузке и новом опыте.
            node = agent.mental_models.concepts.get(name)
            if node:
                node.recompute_confidence()
                node.tags = info.get("tags", [])
                node.source = info.get("source", "innate")
                concepts_loaded += 1
        
        # 2. Сохраняем убеждения (beliefs) как специальные концепты
        for i, belief in enumerate(data.get("beliefs", [])):
            agent.mental_models.encounter_concept(
                concept_name=f"убеждение_{i+1}",
                context="innate_beliefs",
                outcome=belief,
                valence=0.6, evidence_strength=1.0,
                evidence_kind="innate", source=f"innate:belief:{i+1}",
            )
            node = agent.mental_models.concepts.get(f"убеждение_{i+1}")
            if node:
                node.recompute_confidence()
                node.tags = ["belief", "innate"]
        
        # 3. Сохраняем ценности в атрибуты агента
        agent.innate_values = data.get("values", {})
        agent.innate_skills = data.get("innate_skills", [])
        agent.initial_goals = data.get("initial_goals", [])
        
        # 4. Ставим маркер загрузки
        agent.mental_models.encounter_concept(
            concept_name="_bootstrap_loaded",
            context="system",
            outcome=f"version_{data.get('version', '1.0')}",
            valence=0.0
        )
        node = agent.mental_models.concepts.get("_bootstrap_loaded")
        if node:
            node.recompute_confidence()
            node.tags = ["system", "bootstrap"]
        
        logger.log(f"[BOOTSTRAP] Успешно загружено: {concepts_loaded} концептов, "
                   f"{len(data.get('beliefs', []))} убеждений, "
                   f"{len(data.get('values', {}))} ценностей")
        
        # 5. Если есть начальные цели, устанавливаем первую как активную
        if agent.initial_goals and not agent.active_goal:
            first_goal = agent.initial_goals[0]
            # Fallback: direct assignment (agent may not have _set_active_goal method yet)
            if hasattr(agent, '_set_active_goal'):
                agent._set_active_goal({"title": first_goal, "source": "innate", "priority": "high"})
            else:
                agent.active_goal = {"title": first_goal, "source": "innate", "priority": "high"}
            logger.log(f"[BOOTSTRAP] Установлена первая врожденная цель: {first_goal}")
        
        return True
        
    except Exception as e:
        logger.log(f"[BOOTSTRAP] Ошибка загрузки: {e}")
        import traceback
        traceback.print_exc()
        return False


def get_innate_values(agent) -> dict:
    """Возвращает словарь врожденных ценностей агента."""
    return getattr(agent, 'innate_values', {})


def get_innate_skills(agent) -> list:
    """Возвращает список врожденных навыков агента."""
    return getattr(agent, 'innate_skills', [])


def get_initial_goals(agent) -> list:
    """Возвращает список начальных целей агента."""
    return getattr(agent, 'initial_goals', [])