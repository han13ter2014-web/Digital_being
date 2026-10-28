"""Явный EffectorRequest для безопасного творческого артефакта."""

from uuid import uuid4

from src.core.effector_port import EffectorRequest


def creative_write_request(path, content, *, reason="творческое занятие", request_id=None, activity_goal_id=None, intention_id=None, target="", core_cycle=None):
    if not isinstance(path, str) or not path.endswith(".txt") or path.startswith("/") or ".." in path.split("/"):
        raise ValueError("Творческий путь должен быть относительным .txt")
    if not isinstance(content, str) or not content or len(content.encode("utf-8")) > 8192:
        raise ValueError("Творческий текст пуст или слишком велик")
    return EffectorRequest(
        request_id=request_id or f"creative-{uuid4().hex}",
        goal="Сохранить творческий текстовый артефакт",
        plan=[{"action": "write_creative_draft", "args": {"path": path, "content": content, "overwrite": True}}],
        success_predicate=f"file_exists:{path}",
        priority=0.4,
        metadata={"activity": "creative", "reason": reason,
                 **({"activity_goal_id": activity_goal_id} if activity_goal_id is not None else {}),
                 **({"intention_id": intention_id} if intention_id is not None else {}),
                 **({"target": target} if target else {}),
                 **({"core_cycle": core_cycle} if core_cycle is not None else {})},
    )
