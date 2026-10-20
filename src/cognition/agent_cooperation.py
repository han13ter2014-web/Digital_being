import json
from datetime import datetime
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, asdict
from enum import Enum
import os


class MessageType(Enum):
    """Типы сообщений между агентами."""
    REQUEST = "request"              # Запрос на помощь
    RESPONSE = "response"            # Ответ
    SHARE_KNOWLEDGE = "share_knowledge"  # Поделиться знанием
    COLLABORATE = "collaborate"      # Предложение сотрудничать
    FEEDBACK = "feedback"            # Обратная связь
    QUERY = "query"                  # Запрос информации


@dataclass
class AgentMessage:
    """Сообщение между агентами."""
    sender_id: str
    recipient_id: str
    message_type: MessageType
    content: str
    timestamp: datetime
    priority: int = 1  # 1=низкий, 5=критический
    context: str = ""
    requires_response: bool = False
    response_deadline_cycles: int = 0  # 0 = без deadline

    def to_dict(self) -> dict:
        data = asdict(self)
        data['timestamp'] = data['timestamp'].isoformat()
        data['message_type'] = data['message_type'].value
        return data


class CollaborationResult:
    """Результат совместной работы нескольких агентов."""

    def __init__(self, agents_involved: List[str]):
        self.agents_involved = agents_involved
        self.created_at = datetime.now()
        self.knowledge_shared = {}  # {agent_id: knowledge}
        self.combined_solution = ""
        self.success_score = 0.0

    def to_dict(self) -> dict:
        return {
            'agents': self.agents_involved,
            'created_at': self.created_at.isoformat(),
            'knowledge_shared': self.knowledge_shared,
            'combined_solution': self.combined_solution,
            'success_score': self.success_score
        }


class AgentCooperationHub:
    """Центральная система кооперации между агентами."""

    def __init__(self):
        self.agents: Dict[str, 'DigitalBeing'] = {}  # {agent_id: agent_reference}
        self.message_queue: List[AgentMessage] = []
        self.message_history: List[AgentMessage] = []
        self.collaboration_groups: Dict[str, List[str]] = {}  # {group_id: [agent_ids]}
        self.shared_knowledge_base: Dict[str, Dict] = {}  # {topic: {agent_id: knowledge}}
        self.agent_relationships: Dict[str, Dict] = {}  # {agent_id: {other_agent_id: reputation}}
        self.hub_file = 'data/cooperation/hub_state.json'

        os.makedirs('data/cooperation', exist_ok=True)
        self._load_state()

    def register_agent(self, agent):
        """Регистрирует агента в системе."""
        agent_id = agent.name
        self.agents[agent_id] = agent
        self.agent_relationships[agent_id] = {}

        for other_id in self.agents:
            if other_id != agent_id:
                self.agent_relationships[agent_id][other_id] = 0.5  # Нейтральная репутация

    def send_message(self, from_agent_id: str, to_agent_id: str,
                    message_type: MessageType, content: str,
                    priority: int = 1, context: str = "",
                    requires_response: bool = False) -> bool:
        """Отправляет сообщение между агентами."""
        if from_agent_id not in self.agents or to_agent_id not in self.agents:
            return False

        message = AgentMessage(
            sender_id=from_agent_id,
            recipient_id=to_agent_id,
            message_type=message_type,
            content=content,
            timestamp=datetime.now(),
            priority=priority,
            context=context,
            requires_response=requires_response
        )

        self.message_queue.append(message)
        self.message_history.append(message)
        return True

    def get_pending_messages(self, agent_id: str,
                           message_type: Optional[MessageType] = None) -> List[AgentMessage]:
        """Возвращает ожидающие сообщения для агента."""
        pending = [
            msg for msg in self.message_queue
            if msg.recipient_id == agent_id
        ]

        if message_type:
            pending = [msg for msg in pending if msg.message_type == message_type]

        pending.sort(key=lambda m: m.priority, reverse=True)
        return pending

    def process_message(self, agent_id: str, message: AgentMessage) -> Dict:
        """Обрабатывает сообщение для агента."""
        result = {
            'processed': False,
            'response': None,
            'action_taken': None
        }

        agent = self.agents.get(agent_id)
        if not agent:
            return result

        if message.message_type == MessageType.SHARE_KNOWLEDGE:
            # Агент получает новое знание
            try:
                knowledge = json.loads(message.content) if isinstance(message.content, str) else message.content
            except (json.JSONDecodeError, TypeError):
                knowledge = {'raw': message.content}

            topic = message.context

            if topic not in self.shared_knowledge_base:
                self.shared_knowledge_base[topic] = {}

            self.shared_knowledge_base[topic][message.sender_id] = knowledge
            result['action_taken'] = 'knowledge_absorbed'
            result['processed'] = True

        elif message.message_type == MessageType.REQUEST:
            # Запрос на помощь
            result['action_taken'] = 'help_requested'
            result['processed'] = True

        elif message.message_type == MessageType.QUERY:
            # Запрос информации
            result['action_taken'] = 'query_received'
            result['processed'] = True

        elif message.message_type == MessageType.COLLABORATE:
            # Предложение сотрудничать
            result['action_taken'] = 'collaboration_proposed'
            result['processed'] = True

        # Обновляем репутацию
        self._update_reputation(message.sender_id, agent_id, 0.1)

        # Удаляем из очереди
        if message in self.message_queue:
            self.message_queue.remove(message)

        return result

    def create_collaboration_group(self, group_id: str, agent_ids: List[str]) -> bool:
        """Создает группу агентов для сотрудничества."""
        # Проверяем что все агенты зарегистрированы
        if not all(aid in self.agents for aid in agent_ids):
            return False

        self.collaboration_groups[group_id] = agent_ids

        # Инициируем обмен знаниями в группе
        for agent_id in agent_ids:
            for other_id in agent_ids:
                if agent_id != other_id:
                    self.agent_relationships[agent_id][other_id] = min(
                        1.0,
                        self.agent_relationships.get(agent_id, {}).get(other_id, 0.5) + 0.2
                    )

        return True

    def share_knowledge_in_group(self, group_id: str, agent_id: str,
                                topic: str, knowledge: Dict) -> bool:
        """Один агент делится знанием с группой."""
        if group_id not in self.collaboration_groups:
            return False

        group = self.collaboration_groups[group_id]
        if agent_id not in group:
            return False

        # Отправляем знание другим членам группы
        for recipient_id in group:
            if recipient_id != agent_id:
                content = json.dumps(knowledge, ensure_ascii=False)
                self.send_message(
                    from_agent_id=agent_id,
                    to_agent_id=recipient_id,
                    message_type=MessageType.SHARE_KNOWLEDGE,
                    content=content,
                    context=topic
                )

        # Также сохраняем в общую базу знаний
        if topic not in self.shared_knowledge_base:
            self.shared_knowledge_base[topic] = {}

        self.shared_knowledge_base[topic][agent_id] = knowledge

        return True

    def request_help(self, from_agent_id: str, to_agent_id: str,
                    problem_description: str, urgency: int = 1) -> bool:
        """Агент просит помощь у другого."""
        return self.send_message(
            from_agent_id=from_agent_id,
            to_agent_id=to_agent_id,
            message_type=MessageType.REQUEST,
            content=problem_description,
            priority=urgency,
            requires_response=True
        )

    def query_knowledge(self, from_agent_id: str, topic: str) -> Dict:
        """Ищет знание по теме в общей базе."""
        if topic not in self.shared_knowledge_base:
            return {'found': False, 'sources': []}

        sources = self.shared_knowledge_base[topic]
        return {
            'found': True,
            'topic': topic,
            'sources': list(sources.keys()),
            'knowledge': sources,
            'count': len(sources)
        }

    def get_most_reputable_agent_for_topic(self, topic: str, exclude_agent: str = None) -> Optional[str]:
        """Находит агента с лучшей репутацией по теме."""
        if topic not in self.shared_knowledge_base:
            return None

        sources = self.shared_knowledge_base[topic]
        sources = {k: v for k, v in sources.items() if k != exclude_agent}

        if not sources:
            return None

        # Рейтиг = репутация + количество источников
        ratings = {}
        for agent_id in sources:
            reliability = sources[agent_id].get('reliability', 0.5)
            ratings[agent_id] = reliability

        return max(ratings, key=ratings.get)

    def get_agent_statistics(self, agent_id: str) -> Dict:
        """Возвращает статистику взаимодействий агента."""
        sent = len([m for m in self.message_history if m.sender_id == agent_id])
        received = len([m for m in self.message_history if m.recipient_id == agent_id])

        relationships = self.agent_relationships.get(agent_id, {})
        avg_reputation = sum(relationships.values()) / len(relationships) if relationships else 0.5

        collaborations = [g for g, agents in self.collaboration_groups.items() if agent_id in agents]

        return {
            'agent_id': agent_id,
            'messages_sent': sent,
            'messages_received': received,
            'avg_reputation': avg_reputation,
            'active_collaborations': len(collaborations),
            'collaboration_groups': collaborations,
            'relationships': relationships
        }

    def _update_reputation(self, from_agent: str, to_agent: str, delta: float):
        """Обновляет репутацию одного агента в глазах другого."""
        if to_agent not in self.agent_relationships:
            self.agent_relationships[to_agent] = {}

        current = self.agent_relationships[to_agent].get(from_agent, 0.5)
        new_rep = max(0.0, min(1.0, current + delta))
        self.agent_relationships[to_agent][from_agent] = new_rep

    def save_state(self):
        """Сохраняет состояние хаба."""
        try:
            data = {
                'message_history': [m.to_dict() for m in self.message_history[-100:]],  # Последние 100
                'shared_knowledge': self.shared_knowledge_base,
                'agent_relationships': self.agent_relationships,
                'collaboration_groups': self.collaboration_groups,
                'saved_at': datetime.now().isoformat()
            }

            with open(self.hub_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        except Exception as e:
            print(f"Ошибка сохранения хаба: {e}")

    def _load_state(self):
        """Загружает состояние хаба."""
        if not os.path.exists(self.hub_file):
            return

        try:
            with open(self.hub_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            self.shared_knowledge_base = data.get('shared_knowledge', {})
            self.agent_relationships = data.get('agent_relationships', {})
            self.collaboration_groups = data.get('collaboration_groups', {})
        except Exception as e:
            print(f"Ошибка загрузки хаба: {e}")

    def visualize_network(self) -> str:
        """Возвращает визуализацию сети агентов."""
        lines = []
        lines.append(f"\n{'='*60}")
        lines.append(f"  🌐 СЕТЬ КООПЕРАЦИИ: {len(self.agents)} агентов")
        lines.append(f"{'='*60}")

        for agent_id, agent in self.agents.items():
            stats = self.get_agent_statistics(agent_id)
            lines.append(f"\n  🤖 {agent_id}")
            lines.append(f"     Отправил: {stats['messages_sent']} | Получил: {stats['messages_received']}")
            lines.append(f"     Репутация: {stats['avg_reputation']:.0%} | Сотрудничества: {stats['active_collaborations']}")

            pending = len(self.get_pending_messages(agent_id))
            if pending:
                lines.append(f"     ⚠️  {pending} ожидающих сообщений")

        if self.collaboration_groups:
            lines.append(f"\n  👥 ГРУППЫ СОТРУДНИЧЕСТВА:")
            for group_id, agents in self.collaboration_groups.items():
                lines.append(f"     {group_id}: {', '.join(agents)}")

        return '\n'.join(lines)


# Глобальный хаб кооперации (singleton)
cooperation_hub = AgentCooperationHub()
