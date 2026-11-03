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
                code_snippet: str = "", cycle: int = 0,
                extra: Optional[Dict] = None) -> Dict:
        """Создаёт предложение по изменению архитектуры.

        ``extra`` — необязательные дополнительные поля предложения
        (например, diff и результат пробы из «Эволюции-1»); они честно
        сохраняются вместе с предложением.
        """
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
        if extra:
            proposal.update(extra)

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

    def latest_pending(self) -> Dict:
        """Последнее по времени ожидающее предложение (или {})."""
        pending = self.list_pending()
        if not pending:
            return {}
        return max(pending, key=lambda p: str(p.get("created_at", "")))

    def decide(self, proposal_id: str, approved: bool,
               note: str = "") -> Dict:
        """Фиксирует решение человека: approved → «approved», иначе «rejected».

        Решение — только человека: вызывается из двери диалога по его
        явным словам. Само предложение никогда не применяется этим
        методом — статус «implemented» выставляет человек после
        фактического внедрения.
        """
        if not proposal_id:
            return {"decided": False, "reason": "нет id"}
        filepath = os.path.join(self.proposals_dir, f"{proposal_id}.json")
        if not os.path.exists(filepath):
            return {"decided": False, "reason": "не найдено"}
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                proposal = json.load(f)
        except Exception as e:
            return {"decided": False, "reason": f"ошибка чтения: {e}"}
        if proposal.get("status") != "pending":
            return {
                "decided": False,
                "reason": f"уже решено: {proposal.get('status')}",
            }
        proposal["status"] = "approved" if approved else "rejected"
        proposal["decided_at"] = datetime.now().isoformat()
        if note:
            proposal["decision_note"] = note
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(proposal, f, indent=2, ensure_ascii=False)
        except Exception as e:
            return {"decided": False, "reason": f"ошибка записи: {e}"}
        self.registry.record(
            "architecture_proposals",
            proposal.get("title", proposal_id),
            "решение человека: " + ("одобрено" if approved else "отклонено"),
            outcome="approved" if approved else "rejected",
            cycle=int(proposal.get("cycle", 0) or 0),
            meta={"proposal_id": proposal_id},
        )
        return {"decided": True, "status": proposal["status"],
                "title": proposal.get("title", proposal_id)}