"""
Dashboard Actions — бизнес-логика для веб-дашборда (Этап 3.1).

Этот модуль содержит чистые функции для обработки действий дашборда,
изолированные от транспортного слоя (aiohttp, websockets, SSE).
Все функции получают агент и аргументы, возвращают структурированный результат.
"""

from typing import Dict, Any, Optional
from datetime import datetime


def pause_agent(agent: Any) -> Dict[str, Any]:
    """Ставит агента на паузу через дашборд.
    
    Args:
        agent: Экземпляр DigitalBeing
        
    Returns:
        Словарь с результатом действия
    """
    if not hasattr(agent, "_dashboard_paused"):
        agent._dashboard_paused = False
    agent._dashboard_paused = True
    return {"status": "ok", "message": "поставлен на паузу"}


def resume_agent(agent: Any) -> Dict[str, Any]:
    """Возобновляет работу агента после паузы.
    
    Args:
        agent: Экземпляр DigitalBeing
        
    Returns:
        Словарь с результатом действия
    """
    if hasattr(agent, "_dashboard_paused"):
        agent._dashboard_paused = False
    return {"status": "ok", "message": "продолжает"}


def save_agent_state(agent: Any) -> Dict[str, Any]:
    """Сохраняет состояние агента и ментальных моделей.
    
    Args:
        agent: Экземпляр DigitalBeing
        
    Returns:
        Словарь с результатом действия
    """
    result_parts = []
    
    if hasattr(agent, "save_state"):
        agent.save_state()
        result_parts.append("состояние")
    
    if hasattr(agent, "save_mental_models"):
        agent.save_mental_models()
        result_parts.append("ментальные модели")
    
    if result_parts:
        return {"status": "ok", "message": f"сохранено: {', '.join(result_parts)}"}
    return {"status": "error", "message": "методы сохранения недоступны"}


def agent_reflect(agent: Any) -> Dict[str, Any]:
    """Запускает процесс рефлексии агента.
    
    Args:
        agent: Экземпляр DigitalBeing
        
    Returns:
        Словарь с результатом действия
    """
    if hasattr(agent, "reflect"):
        agent.reflect()
        return {"status": "ok", "message": "рефлексия выполнена"}
    return {"status": "error", "message": "метод reflect недоступен"}


def get_agent_status(agent: Any) -> Dict[str, Any]:
    """Возвращает полное состояние агента.
    
    Args:
        agent: Экземпляр DigitalBeing
        
    Returns:
        Словарь с состоянием агента или ошибкой
    """
    if hasattr(agent, "get_full_state"):
        return {"status": "ok", "state": agent.get_full_state()}
    return {"status": "error", "message": "метод get_full_state недоступен"}


def get_agent_thought(agent: Any) -> Dict[str, Any]:
    """Генерирует мысль агента по запросу и выполняет соответствующее действие.
    
    Args:
        agent: Экземпляр DigitalBeing
        
    Returns:
        Словарь с мыслью или ошибкой
    """
    if hasattr(agent, "think") and hasattr(agent, "act"):
        try:
            thought = agent.think("вопрос от пользователя через дашборд")
            agent.act(thought)
            return {"status": "ok", "thought": str(thought)}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    return {"status": "error", "message": "методы think или act недоступны"}


def shutdown_agent(agent: Any) -> Dict[str, Any]:
    """Запрашивает завершение работы агента.
    
    Args:
        agent: Экземпляр DigitalBeing
        
    Returns:
        Словарь с результатом действия
    """
    agent._dashboard_shutdown_requested = True
    return {"status": "ok", "message": "запрошено завершение"}


def set_agent_goal(agent: Any, title: str, difficulty: int = 1) -> Dict[str, Any]:
    """Устанавливает новую цель для агента.
    
    Args:
        agent: Экземпляр DigitalBeing
        title: Название цели
        difficulty: Сложность цели (по умолчанию 1)
        
    Returns:
        Словарь с результатом действия
    """
    if hasattr(agent, "set_goal"):
        try:
            goal_id = agent.set_goal(title, difficulty=difficulty)
            return {"status": "ok", "goal_id": goal_id}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    return {"status": "error", "message": "метод set_goal недоступен"}


def add_agent_quiet_app(agent: Any, app_name: str) -> Dict[str, Any]:
    """Добавляет приложение в список тихих (не тревожащих) приложений.
    
    Args:
        agent: Экземпляр DigitalBeing
        app_name: Название приложения
        
    Returns:
        Словарь с результатом действия
    """
    if hasattr(agent, "add_quiet_app"):
        try:
            agent.add_quiet_app(app_name)
            return {"status": "ok", "app": app_name}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    return {"status": "error", "message": "метод add_quiet_app недоступен"}


# Словарь для быстрого доступа к функциям по имени действия
ACTION_MAP = {
    "pause": pause_agent,
    "resume": resume_agent,
    "save": save_agent_state,
    "reflect": agent_reflect,
    "status": get_agent_status,
    "thought": get_agent_thought,
    "shutdown": shutdown_agent,
    "set_goal": set_agent_goal,
    "add_quiet_app": add_agent_quiet_app,
}


def handle_dashboard_action(agent: Any, action: str, args: Optional[dict] = None) -> Dict[str, Any]:
    """Единая точка входа для обработки действий дашборда.
    
    Args:
        agent: Экземпляр DigitalBeing
        action: Название действия
        args: Аргументы действия (опционально)
        
    Returns:
        Словарь с результатом выполнения действия
    """
    if args is None:
        args = {}
    
    action_func = ACTION_MAP.get(action)
    if action_func is None:
        return {
            "status": "error", 
            "message": f"неизвестное действие: {action}. "
                      f"Доступные: {sorted(ACTION_MAP.keys())}"
        }
    
    try:
        # Вызываем соответствующую функцию с агентом и аргументами
        if action in ["set_goal", "add_quiet_app"]:
            # Эти функции требуют конкретных аргументов
            return action_func(agent, **args)
        else:
            # Остальные функции принимают только агент
            return action_func(agent)
    except Exception as e:
        return {"status": "error", "message": f"ошибка выполнения действия: {str(e)}"}