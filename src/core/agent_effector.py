"""Terminal effector-result bridge from ``agent.py``.

All intention, life-episode and goal calls remain on the facade object so
instance/class monkeypatches keep their previous behavior.
"""

from src.core.buffered_logger import get_logger


def _record_core_life_episode_impl(self, entry):
    memory = getattr(getattr(self, "delamain", None), "runtime", None)
    memory = getattr(memory, "memory", None)
    if memory is None:
        # «Сироты-1» (k16-10): молча проглатывать потерю эпизода
        # нельзя — биография сущности не должна исчезать бесследно.
        # Ошибка не пробрасывается (живой цикл важнее одной записи),
        # но факт потери остаётся в логе.
        get_logger().log(
            "[LIFE_EPISODE] память недоступна: эпизод "
            f"{entry.get('action')} не записан"
        )
        return None
    try:
        return memory.record_life_episode(
            life_id=self.life_id, intention_id=entry["id"], action=entry["action"],
            target=entry.get("target") or "", status=entry.get("status", "unobserved"),
            outcome=entry.get("outcome"),
        )
    except Exception as exc:
        get_logger().log(f"[LIFE_EPISODE] не записан: {exc}")
        return None


def _complete_effector_intention_impl(self, payload):
    """Замкнуть явно связанное intention после terminal Effector result.

        Связь допустима только через сохранённый ``intention_id``. UI и
        технический результат без этой связи не создают жизненный эпизод.
        Повтор результата безопасен: завершённая запись не завершается и не
        записывается в память второй раз.
        """
    metadata = dict((payload.get("detail") or {}).get("metadata") or {})
    intention_id = metadata.get("intention_id")
    if not isinstance(intention_id, str) or not intention_id:
        return
    history = getattr(self, "_intention_history", None)
    if not isinstance(history, list):
        return
    entry = next((item for item in history if isinstance(item, dict)
                  and item.get("id") == intention_id), None)
    if entry is None or entry.get("status") != "started":
        return

    from types import SimpleNamespace
    from src.cognition.intention_history import finish_intention

    status = payload.get("status")
    outcome = {
        "action": entry.get("action"),
        "had_effect": bool(payload.get("ok")),
        "effector_request_id": payload.get("request_id"),
        "result_status": status,
    }
    if status == "succeeded":
        finish_intention(entry, outcome=SimpleNamespace(
            reason="", as_dict=lambda: dict(outcome)
        ))
        # «Эмоции-1»: завершённое дело — реальная причина счастья.
        emotional_state = getattr(self, "emotional_state", None)
        if emotional_state is not None:
            emotional_state.handle_event(
                "intention_completed", cycle=self.cycle_count,
                cause=str(entry.get("action") or ""),
            )
    elif status == "failed":
        finish_intention(entry, error=RuntimeError(
            str(payload.get("error") or "effector action failed")
        ))
        # «Эмоции-1»: неудача — реальная причина грусти.
        emotional_state = getattr(self, "emotional_state", None)
        if emotional_state is not None:
            emotional_state.handle_event(
                "intention_failed", cycle=self.cycle_count,
                cause=str(entry.get("action") or ""),
            )
    elif status == "rejected":
        finish_intention(entry, outcome=SimpleNamespace(
            reason=f"denied: {payload.get('error') or 'effector rejected'}",
            as_dict=lambda: dict(outcome),
        ))
    else:
        return
    self._record_core_life_episode(entry)


def _on_effector_result_impl(self, result):
    """Применить результат эффектора только после terminal status."""
    payload = (result or {}).get("result") if isinstance(result, dict) else None
    if payload is None and isinstance(result, dict) and result.get("status"):
        payload = result
    if not payload:
        return
    if payload.get("status") not in {"succeeded", "failed", "rejected"}:
        return
    self._complete_effector_intention(payload)
    detail = payload.get("detail") or {}
    activity = detail.get("activity")
    if activity != "creative":
        return
    metadata = detail.get("metadata") or {}
    goal_id = metadata.get("activity_goal_id")
    if payload.get("status") == "succeeded" and goal_id is not None:
        goal = next((item for item in self.goals if item.get("id") == goal_id), None)
        if goal is not None and goal.get("activity", {}).get("criterion") == "draft_revision":
            self.complete_goal(goal_id)
    from src.cognition.method_preferences import observe

    observe(self, "create_draft", outcome="performed" if payload.get("status") == "succeeded" else "error",
            had_effect=bool(payload.get("ok")), emotional_valence=0.0)
    if payload.get("status") == "succeeded":
        self._last_effector_activity_result = payload
