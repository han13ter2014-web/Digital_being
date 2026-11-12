"""Локальный транспорт сотрудничества без глобального состояния и скрытого I/O.

Каждый хаб создаётся явно, регистрирует жизнь по ``life_id`` и хранит только
сообщения/метаданные. Он не выбирает действия и не записывает чужие знания в
память агента: получение сообщения остаётся отдельным решением Core.
"""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional


class MessageType(Enum):
    REQUEST = "request"
    RESPONSE = "response"
    SHARE_KNOWLEDGE = "share_knowledge"
    COLLABORATE = "collaborate"
    FEEDBACK = "feedback"
    QUERY = "query"


@dataclass
class AgentMessage:
    sender_id: str
    recipient_id: str
    message_type: MessageType
    content: str
    timestamp: datetime
    priority: int = 1
    context: str = ""
    requires_response: bool = False
    response_deadline_cycles: int = 0

    def to_dict(self) -> dict:
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        data["message_type"] = self.message_type.value
        return data

    @classmethod
    def from_dict(cls, data: dict):
        return cls(
            sender_id=str(data["sender_id"]),
            recipient_id=str(data["recipient_id"]),
            message_type=MessageType(data["message_type"]),
            content=str(data.get("content") or "")[:8192],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            priority=int(data.get("priority", 1)),
            context=str(data.get("context") or "")[:200],
            requires_response=bool(data.get("requires_response", False)),
            response_deadline_cycles=int(data.get("response_deadline_cycles", 0)),
        )


class CollaborationResult:
    def __init__(self, agents_involved: List[str]):
        self.agents_involved = list(agents_involved)
        self.created_at = datetime.now()
        self.knowledge_shared = {}
        self.combined_solution = ""
        self.success_score = 0.0

    def to_dict(self) -> dict:
        return {
            "agents": list(self.agents_involved),
            "created_at": self.created_at.isoformat(),
            "knowledge_shared": deepcopy(self.knowledge_shared),
            "combined_solution": self.combined_solution,
            "success_score": self.success_score,
        }


class AgentCooperationHub:
    """Per-life каталог и очередь; при импорте ничего не создаётся."""

    def __init__(self):
        self.agents: Dict[str, object] = {}
        self.message_queue: List[AgentMessage] = []
        self.message_history: List[AgentMessage] = []
        self.collaboration_groups: Dict[str, List[str]] = {}
        self.shared_knowledge_base: Dict[str, Dict] = {}
        self.agent_relationships: Dict[str, Dict[str, float]] = {}

    @staticmethod
    def identity_of(agent) -> str:
        life_id = getattr(agent, "life_id", None)
        if not isinstance(life_id, str) or not life_id.strip():
            raise ValueError("Для кооперации нужен непустой life_id")
        return life_id

    def register_agent(self, agent):
        agent_id = self.identity_of(agent)
        self.agents[agent_id] = agent
        relationships = self.agent_relationships.setdefault(agent_id, {})
        for other_id in self.agents:
            if other_id != agent_id:
                relationships.setdefault(other_id, 0.5)
                self.agent_relationships.setdefault(other_id, {}).setdefault(
                    agent_id, 0.5
                )
        return agent_id

    def unregister_agent(self, agent_or_id) -> bool:
        agent_id = (
            self.identity_of(agent_or_id)
            if not isinstance(agent_or_id, str)
            else agent_or_id
        )
        return self.agents.pop(agent_id, None) is not None

    def send_message(
        self,
        from_agent_id: str,
        to_agent_id: str,
        message_type: MessageType,
        content: str,
        priority: int = 1,
        context: str = "",
        requires_response: bool = False,
    ) -> bool:
        if from_agent_id not in self.agents or to_agent_id not in self.agents:
            return False
        if not isinstance(message_type, MessageType):
            return False
        if len(self.message_queue) >= 100:
            return False
        message = AgentMessage(
            sender_id=from_agent_id,
            recipient_id=to_agent_id,
            message_type=message_type,
            content=str(content)[:8192],
            timestamp=datetime.now(),
            priority=max(1, min(5, int(priority))),
            context=str(context)[:200],
            requires_response=bool(requires_response),
        )
        self.message_queue.append(message)
        self.message_history.append(message)
        self.message_history = self.message_history[-200:]
        return True

    def get_pending_messages(
        self, agent_id: str, message_type: Optional[MessageType] = None
    ) -> List[AgentMessage]:
        pending = [
            msg
            for msg in self.message_queue
            if msg.recipient_id == agent_id
            and (message_type is None or msg.message_type == message_type)
        ]
        return sorted(pending, key=lambda msg: msg.priority, reverse=True)

    def process_message(self, agent_id: str, message: AgentMessage) -> Dict:
        """Технически принять сообщение, не меняя память/цели агента."""
        result = {"processed": False, "response": None, "action_taken": None}
        if agent_id not in self.agents or message not in self.message_queue:
            return result
        if message.recipient_id != agent_id:
            return result
        if message.message_type == MessageType.SHARE_KNOWLEDGE:
            try:
                knowledge = json.loads(message.content)
            except (json.JSONDecodeError, TypeError):
                knowledge = {"raw": message.content}
            topic = message.context or "untitled"
            self.shared_knowledge_base.setdefault(topic, {})[message.sender_id] = (
                knowledge
            )
            result.update(action_taken="knowledge_quarantined", processed=True)
        elif message.message_type == MessageType.REQUEST:
            result.update(action_taken="help_requested", processed=True)
        elif message.message_type == MessageType.QUERY:
            result.update(action_taken="query_received", processed=True)
        elif message.message_type == MessageType.COLLABORATE:
            result.update(action_taken="collaboration_proposed", processed=True)
        elif message.message_type in {MessageType.RESPONSE, MessageType.FEEDBACK}:
            result.update(action_taken="response_recorded", processed=True)
        if result["processed"]:
            self._update_reputation(message.sender_id, agent_id, 0.1)
            self.message_queue.remove(message)
        return result

    def tick(self, agent_id: str) -> Dict:
        """Автономно принять сообщения этой жизни в пределах безопасного API.

        Обработка меняет только очередь, отношения и карантинную базу хаба.
        Память, цели и выбор Core по-прежнему не затрагиваются.
        """
        pending = list(self.get_pending_messages(agent_id))
        results = [self.process_message(agent_id, message) for message in pending]
        return {
            "agent_id": agent_id,
            "processed_messages": sum(bool(item.get("processed")) for item in results),
            "actions": [
                item.get("action_taken") for item in results if item.get("processed")
            ],
            "pending_messages": len(self.get_pending_messages(agent_id)),
        }

    def create_collaboration_group(self, group_id: str, agent_ids: List[str]) -> bool:
        if not agent_ids or not all(aid in self.agents for aid in agent_ids):
            return False
        group_id = str(group_id)[:100]
        self.collaboration_groups[group_id] = list(dict.fromkeys(agent_ids))
        for agent_id in agent_ids:
            for other_id in agent_ids:
                if agent_id != other_id:
                    current = self.agent_relationships.get(agent_id, {}).get(
                        other_id, 0.5
                    )
                    self.agent_relationships.setdefault(agent_id, {})[other_id] = min(
                        1.0, current + 0.2
                    )
        return True

    def share_knowledge_in_group(
        self, group_id: str, agent_id: str, topic: str, knowledge: Dict
    ) -> bool:
        group = self.collaboration_groups.get(group_id)
        if not group or agent_id not in group or not isinstance(knowledge, dict):
            return False
        for recipient_id in group:
            if recipient_id != agent_id:
                self.send_message(
                    agent_id,
                    recipient_id,
                    MessageType.SHARE_KNOWLEDGE,
                    json.dumps(knowledge, ensure_ascii=False),
                    context=topic,
                )
        self.shared_knowledge_base.setdefault(topic, {})[agent_id] = deepcopy(knowledge)
        return True

    def request_help(
        self,
        from_agent_id: str,
        to_agent_id: str,
        problem_description: str,
        urgency: int = 1,
    ) -> bool:
        return self.send_message(
            from_agent_id,
            to_agent_id,
            MessageType.REQUEST,
            problem_description,
            priority=urgency,
            requires_response=True,
        )

    def query_knowledge(self, from_agent_id: str, topic: str) -> Dict:
        sources = self.shared_knowledge_base.get(topic, {})
        return {
            "found": bool(sources),
            "topic": topic,
            "sources": list(sources),
            "knowledge": deepcopy(sources),
            "count": len(sources),
        }

    def get_most_reputable_agent_for_topic(
        self, topic: str, exclude_agent: str = None
    ) -> Optional[str]:
        sources = {
            key: value
            for key, value in self.shared_knowledge_base.get(topic, {}).items()
            if key != exclude_agent
        }
        rated = {
            agent_id: float(value.get("reliability", 0.5))
            for agent_id, value in sources.items()
            if isinstance(value, dict)
        }
        return max(rated, key=rated.get) if rated else None

    def get_agent_statistics(self, agent_id: str) -> Dict:
        sent = sum(msg.sender_id == agent_id for msg in self.message_history)
        received = sum(msg.recipient_id == agent_id for msg in self.message_history)
        relationships = dict(self.agent_relationships.get(agent_id, {}))
        groups = [
            name
            for name, agents in self.collaboration_groups.items()
            if agent_id in agents
        ]
        return {
            "agent_id": agent_id,
            "messages_sent": sent,
            "messages_received": received,
            "avg_reputation": sum(relationships.values()) / len(relationships)
            if relationships
            else 0.5,
            "active_collaborations": len(groups),
            "collaboration_groups": groups,
            "relationships": relationships,
            "pending_messages": len(self.get_pending_messages(agent_id)),
        }

    def _update_reputation(self, from_agent: str, to_agent: str, delta: float):
        relationships = self.agent_relationships.setdefault(to_agent, {})
        relationships[from_agent] = max(
            0.0, min(1.0, relationships.get(from_agent, 0.5) + delta)
        )

    def to_checkpoint(self) -> dict:
        return {
            "schema_version": 1,
            "message_queue": [msg.to_dict() for msg in self.message_queue[-100:]],
            "message_history": [msg.to_dict() for msg in self.message_history[-200:]],
            "shared_knowledge": deepcopy(self.shared_knowledge_base),
            "agent_relationships": deepcopy(self.agent_relationships),
            "collaboration_groups": deepcopy(self.collaboration_groups),
        }

    @classmethod
    def from_checkpoint(cls, data: dict):
        hub = cls()
        hub.message_queue = [
            AgentMessage.from_dict(raw) for raw in data.get("message_queue") or []
        ]
        hub.message_history = [
            AgentMessage.from_dict(raw) for raw in data.get("message_history") or []
        ]
        hub.shared_knowledge_base = deepcopy(data.get("shared_knowledge") or {})
        hub.agent_relationships = deepcopy(data.get("agent_relationships") or {})
        hub.collaboration_groups = deepcopy(data.get("collaboration_groups") or {})
        return hub

    def visualize_network(self) -> str:
        lines = [f"Сеть кооперации: {len(self.agents)} жизней"]
        for agent_id in self.agents:
            stats = self.get_agent_statistics(agent_id)
            lines.append(
                f"{agent_id}: отправлено {stats['messages_sent']}, "
                f"получено {stats['messages_received']}, "
                f"ожидает {stats['pending_messages']}"
            )
        return "\n".join(lines)


def validate_cooperation_checkpoint(data: dict) -> None:
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("cooperation.schema_version: unsupported")
    for field, limit in (("message_queue", 100), ("message_history", 200)):
        messages = data.get(field)
        if not isinstance(messages, list) or len(messages) > limit:
            raise ValueError(f"cooperation.{field}: invalid bounded list")
        for index, raw in enumerate(messages):
            try:
                AgentMessage.from_dict(raw)
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"cooperation.{field}[{index}]: {exc}") from exc
    knowledge = data.get("shared_knowledge")
    if not isinstance(knowledge, dict) or len(knowledge) > 100:
        raise ValueError("cooperation.shared_knowledge: invalid mapping")
    for topic, sources in knowledge.items():
        if (
            not isinstance(topic, str)
            or not isinstance(sources, dict)
            or len(sources) > 100
        ):
            raise ValueError("cooperation.shared_knowledge: invalid topic")
    relationships = data.get("agent_relationships")
    if not isinstance(relationships, dict):
        raise ValueError("cooperation.agent_relationships: expected dictionary")
    for agent_id, values in relationships.items():
        if not isinstance(agent_id, str) or not isinstance(values, dict):
            raise ValueError("cooperation.agent_relationships: invalid identity")
        for other_id, value in values.items():
            if (
                not isinstance(other_id, str)
                or isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not 0.0 <= value <= 1.0
            ):
                raise ValueError("cooperation.agent_relationships: invalid reputation")
    groups = data.get("collaboration_groups")
    if not isinstance(groups, dict) or len(groups) > 100:
        raise ValueError("cooperation.collaboration_groups: invalid mapping")
    for group_id, members in groups.items():
        if (
            not isinstance(group_id, str)
            or not isinstance(members, list)
            or len(members) > 100
            or any(not isinstance(item, str) for item in members)
        ):
            raise ValueError("cooperation.collaboration_groups: invalid group")


__all__ = [
    "MessageType",
    "AgentMessage",
    "CollaborationResult",
    "AgentCooperationHub",
    "validate_cooperation_checkpoint",
]
