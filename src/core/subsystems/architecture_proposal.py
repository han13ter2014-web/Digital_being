"""
ArchitectureProposal — агент предлагает изменить свой код.

Аналогия с человеком: «Я хочу научиться играть на пианино» —
это не запрос инструмента, а волеизъявление о самоизменении.

Агент может предлагать:
- Добавить новый метод
- Изменить параметр конфигурации
- Подключить новый модуль

Оператор (человек) решает — одобрить или отклонить.
"""

import json
import os
from datetime import datetime
from typing import Dict, List, Optional

from config.will_config import WILL_CONFIG
from src.core.paths import data_path
from src.core.subsystems.will_registry import WillRegistry


class ArchitectureProposal:
    """Модуль предложений по самоизменению."""

    PROPOSAL_TYPES = ["method_add", "config_change", "module_add", "behavior_change"]

    def __init__(self, registry: WillRegistry,
                 proposals_dir: str = None):
        self.registry = registry
        self.proposals_dir = proposals_dir or data_path("architecture_proposals")
        os.makedirs(self.proposals_dir, exist_ok=True)

    def propose(self, proposal_type: str, title: str, description: str,
                code_snippet: str = "", cycle: int = 0) -> Dict:
        """Создаёт предложение по изменению архитектуры."""
        if not WILL_CONFIG.ALLOW_ARCHITECTURE_PROPOSAL:
            return {"created": False, "reason": "отключено"}

        if proposal_type not in self.PROPOSAL_TYPES:
            return {"created": False, "reason": "неизвестный тип"}

        proposal_id = f"prop_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{cycle}"
        proposal = {
            "id": proposal_id,
            "type": proposal_type,
            "title": title,
            "description": description,
            "code_snippet": code_snippet,
            "status": "pending",  # pending | approved | rejected | implemented
            "created_at": datetime.now().isoformat(),
            "cycle": cycle,
        }

        # Сохраняем в файл
        filepath = f"{self.proposals_dir}/{proposal_id}.json"
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(proposal, f, indent=2, ensure_ascii=False)
        except Exception as e:
            return {"created": False, "reason": f"ошибка записи: {e}"}

        # Регистрируем
        self.registry.record(
            "architecture_proposals", title, description,
            outcome="proposed", cycle=cycle,
            meta={"proposal_id": proposal_id, "type": proposal_type},
        )

        return {
            "created": True,
            "proposal_id": proposal_id,
            "filepath": filepath,
        }

    def list_pending(self) -> List[Dict]:
        """Возвращает список ожидающих предложений."""
        pending = []
        if not os.path.exists(self.proposals_dir):
            return pending
        for fname in os.listdir(self.proposals_dir):
            if not fname.endswith(".json"):
                continue
            try:
                with open(
                    f"{self.proposals_dir}/{fname}", "r", encoding="utf-8"
                ) as f:
                    p = json.load(f)
                if p.get("status") == "pending":
                    pending.append(p)
            except Exception:
                continue
        return pending