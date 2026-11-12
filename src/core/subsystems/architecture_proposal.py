"""
ArchitectureProposal — агент предлагает изменить свой код.

Аналогия с человеком: «Я хочу научиться играть на пианино» —
это не запрос инструмента, а волеизъявление о самоизменении.

Агент может предлагать:
- Добавить новый метод
- Изменить параметр конфигурации
- Подключить новый модуль

Оператор (человек) решает — одобрить или отклонить.

Этап 5C: у managed-жизни (с UUID) источник истины — таблица
``architecture_proposals`` её базы ``life.sqlite3``: создание, обогащение
результатом пробы и решение человека фиксируются в SQL. JSON-файл —
переносимый экспорт, записываемый внутрь каталога жизни и
зарегистрированный в реестре ``artifacts``; состояние из него никогда
не читается, поэтому он не становится второй изменяемой истиной.
Standalone-режим (без UUID) сохраняет прежнее файловое поведение.
"""

import json
import os
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from config.will_config import WILL_CONFIG
from src.core.paths import data_path
from src.core.subsystems.will_registry import WillRegistry


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ArchitectureProposal:
    """Модуль предложений по самоизменению."""

    PROPOSAL_TYPES = ["method_add", "config_change", "module_add", "behavior_change"]
    # Экспорт внутри каталога жизни; путь регистрируется в artifacts.
    EXPORT_DIR = Path("artifacts") / "architecture_proposals"

    def __init__(
        self, registry: WillRegistry, proposals_dir: str = None, life_id: str = None
    ):
        self.registry = registry
        self.database = None
        self.life_id = None
        if life_id is not None:
            from src.core.life_identity import validate_life_id
            from src.memory.life_database import LifeDatabase

            self.life_id = validate_life_id(life_id)
            self.database = LifeDatabase(
                data_path("lives", self.life_id, "life.sqlite3"), self.life_id
            )
        self.proposals_dir = proposals_dir or data_path("architecture_proposals")
        if self.database is None:
            os.makedirs(self.proposals_dir, exist_ok=True)

    def rebind(self, life_id: str) -> None:
        """Переключить managed-объект на авторитетную базу другого UUID.

        Standalone-объект (без базы) не переключается: файловый режим
        не принадлежит ни одной жизни.
        """
        if self.database is None:
            return
        from src.core.life_identity import validate_life_id

        target = validate_life_id(life_id)
        if self.life_id == target:
            return
        from src.memory.life_database import LifeDatabase

        self.life_id = target
        self.database = LifeDatabase(data_path("lives", target, "life.sqlite3"), target)

    # ------------------------------------------------------------------
    # Создание предложения
    # ------------------------------------------------------------------

    def propose(
        self,
        proposal_type: str,
        title: str,
        description: str,
        code_snippet: str = "",
        cycle: int = 0,
        extra: Optional[Dict] = None,
    ) -> Dict:
        """Создаёт предложение по изменению архитектуры.

        ``extra`` — необязательные дополнительные поля предложения
        (например, diff и результат пробы из «Эволюции-1»); они честно
        сохраняются вместе с предложением.
        """
        if not WILL_CONFIG.ALLOW_ARCHITECTURE_PROPOSAL:
            return {"created": False, "reason": "отключено"}

        if proposal_type not in self.PROPOSAL_TYPES:
            return {"created": False, "reason": "неизвестный тип"}

        # Секунда и цикл не уникальны: standalone-запись по совпавшему ID
        # перезаписывала прежнее предложение и решение человека по нему.
        from uuid import uuid4

        proposal_id = (
            f"prop_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{cycle}_{uuid4().hex}"
        )
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

        if self.database is not None:
            return self._propose_sql(proposal, proposal_type)

        # Сохраняем в файл (standalone)
        filepath = f"{self.proposals_dir}/{proposal_id}.json"
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(proposal, f, indent=2, ensure_ascii=False)
        except Exception as e:
            return {"created": False, "reason": f"ошибка записи: {e}"}

        # Регистрируем
        self.registry.record(
            "architecture_proposals",
            title,
            description,
            outcome="proposed",
            cycle=cycle,
            meta={"proposal_id": proposal_id, "type": proposal_type},
        )

        return {
            "created": True,
            "proposal_id": proposal_id,
            "filepath": filepath,
        }

    def _propose_sql(self, proposal: Dict, proposal_type: str) -> Dict:
        proposal_id = proposal["id"]
        try:
            with self.database.write() as connection:
                artifact = self.database.write_artifact(
                    *self._export_parts(proposal),
                    kind="architecture_proposal",
                    metadata={
                        "proposal_id": proposal_id,
                        "type": proposal_type,
                        "status": proposal["status"],
                    },
                    connection=connection,
                )
                self._insert_row(connection, proposal)
        except Exception as e:
            return {"created": False, "reason": f"ошибка записи: {e}"}

        self.registry.record(
            "architecture_proposals",
            proposal["title"],
            proposal["description"],
            outcome="proposed",
            cycle=int(proposal.get("cycle", 0) or 0),
            meta={"proposal_id": proposal_id, "type": proposal_type},
        )
        return {
            "created": True,
            "proposal_id": proposal_id,
            "filepath": str(self.database.life_dir / artifact["relative_path"]),
        }

    # ------------------------------------------------------------------
    # Чтение состояния — только из SQL
    # ------------------------------------------------------------------

    _COLUMNS = (
        "id, type, title, description, code_snippet, status, created_at, "
        "cycle, decided_at, decision_note, payload_json, updated_at"
    )

    def _export_parts(self, proposal: Dict):
        relative_path = (self.EXPORT_DIR / f"{proposal['id']}.json").as_posix()
        payload = json.dumps(proposal, indent=2, ensure_ascii=False)
        return relative_path, payload.encode("utf-8")

    def _insert_row(self, connection, proposal: Dict) -> None:
        connection.execute(
            "INSERT INTO architecture_proposals"
            "(id, type, title, description, code_snippet, status, created_at, "
            "cycle, payload_json, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                proposal["id"],
                proposal["type"],
                proposal["title"],
                proposal.get("description", ""),
                proposal.get("code_snippet", ""),
                proposal["status"],
                proposal["created_at"],
                int(proposal.get("cycle", 0) or 0),
                json.dumps(proposal, ensure_ascii=False),
                _now(),
            ),
        )

    @staticmethod
    def _payload_from_row(row) -> Dict:
        payload = json.loads(row["payload_json"])
        payload.update(
            {
                "id": row["id"],
                "type": row["type"],
                "title": row["title"],
                "description": row["description"],
                "code_snippet": row["code_snippet"],
                "status": row["status"],
                "created_at": row["created_at"],
                "cycle": row["cycle"],
            }
        )
        if row["decided_at"] is not None:
            payload["decided_at"] = row["decided_at"]
        if row["decision_note"]:
            payload["decision_note"] = row["decision_note"]
        return payload

    def _update_payload(self, connection, payload: Dict) -> None:
        connection.execute(
            "UPDATE architecture_proposals SET payload_json = ?, status = ?, "
            "decided_at = ?, decision_note = ?, updated_at = ? WHERE id = ?",
            (
                json.dumps(payload, ensure_ascii=False),
                payload["status"],
                payload.get("decided_at"),
                payload.get("decision_note"),
                _now(),
                payload["id"],
            ),
        )

    def _resync_export(self, connection, payload: Dict) -> None:
        self.database.write_artifact(
            *self._export_parts(payload),
            kind="architecture_proposal",
            metadata={
                "proposal_id": payload["id"],
                "type": payload["type"],
                "status": payload["status"],
            },
            connection=connection,
        )

    def list_pending(self) -> List[Dict]:
        """Возвращает список ожидающих предложений."""
        if self.database is not None:
            with closing(self.database.connect(readonly=True)) as connection:
                rows = connection.execute(
                    f"SELECT {self._COLUMNS} FROM architecture_proposals "  # nosec B608
                    "WHERE status = 'pending' ORDER BY created_at, id"
                ).fetchall()
            return [self._payload_from_row(row) for row in rows]
        pending = []
        if not os.path.exists(self.proposals_dir):
            return pending
        for fname in os.listdir(self.proposals_dir):
            if not fname.endswith(".json"):
                continue
            try:
                with open(f"{self.proposals_dir}/{fname}", "r", encoding="utf-8") as f:
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

    # ------------------------------------------------------------------
    # Обогащение результатом проверки
    # ------------------------------------------------------------------

    def enrich(self, proposal_id: str, extra: Dict) -> Dict:
        """Дописать результат пробы/проверки в предложение.

        У managed-жизни меняется SQL-строка, затем из неё повторно
        синхронизируется экспорт. Standalone дописывает файл, как раньше.
        """
        if not proposal_id or not isinstance(extra, dict) or not extra:
            return {"enriched": False, "reason": "нет данных"}
        if self.database is None:
            return self._enrich_file(proposal_id, extra)
        try:
            with self.database.write() as connection:
                row = connection.execute(
                    f"SELECT {self._COLUMNS} FROM architecture_proposals "  # nosec B608
                    "WHERE id = ?",
                    (proposal_id,),
                ).fetchone()
                if row is None:
                    return {"enriched": False, "reason": "не найдено"}
                payload = self._payload_from_row(row)
                payload.update(extra)
                self._update_payload(connection, payload)
                self._resync_export(connection, payload)
        except Exception as e:
            return {"enriched": False, "reason": f"ошибка записи: {e}"}
        return {"enriched": True, "proposal_id": proposal_id}

    def _enrich_file(self, proposal_id: str, extra: Dict) -> Dict:
        path = os.path.join(self.proposals_dir, f"{proposal_id}.json")
        temporary = path + ".tmp"
        try:
            with open(path, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
            payload.update(extra)
            with open(temporary, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, ensure_ascii=False)
            os.replace(temporary, path)
        except Exception as e:
            try:
                os.remove(temporary)
            except OSError:
                pass
            return {"enriched": False, "reason": f"ошибка записи: {e}"}
        return {"enriched": True, "proposal_id": proposal_id}

    # ------------------------------------------------------------------
    # Решение человека
    # ------------------------------------------------------------------

    def decide(self, proposal_id: str, approved: bool, note: str = "") -> Dict:
        """Фиксирует решение человека: approved → «approved», иначе «rejected».

        Решение — только человека: вызывается из двери диалога по его
        явным словам. Само предложение никогда не применяется этим
        методом — статус «implemented» выставляет человек после
        фактического внедрения. Источник состояния — SQL; экспорт
        синхронизируется после записи.
        """
        if not proposal_id:
            return {"decided": False, "reason": "нет id"}
        if self.database is not None:
            return self._decide_sql(proposal_id, approved, note)
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
        temporary = filepath + ".tmp"
        try:
            with open(temporary, "w", encoding="utf-8") as f:
                json.dump(proposal, f, indent=2, ensure_ascii=False)
            os.replace(temporary, filepath)
        except Exception as e:
            try:
                os.remove(temporary)
            except OSError:
                pass
            return {"decided": False, "reason": f"ошибка записи: {e}"}
        self.registry.record(
            "architecture_proposals",
            proposal.get("title", proposal_id),
            "решение человека: " + ("одобрено" if approved else "отклонено"),
            outcome="approved" if approved else "rejected",
            cycle=int(proposal.get("cycle", 0) or 0),
            meta={"proposal_id": proposal_id},
        )
        return {
            "decided": True,
            "status": proposal["status"],
            "title": proposal.get("title", proposal_id),
        }

    def _decide_sql(self, proposal_id: str, approved: bool, note: str = "") -> Dict:
        try:
            with self.database.write() as connection:
                row = connection.execute(
                    f"SELECT {self._COLUMNS} FROM architecture_proposals "  # nosec B608
                    "WHERE id = ?",
                    (proposal_id,),
                ).fetchone()
                if row is None:
                    return {"decided": False, "reason": "не найдено"}
                if row["status"] != "pending":
                    return {
                        "decided": False,
                        "reason": f"уже решено: {row['status']}",
                    }
                payload = self._payload_from_row(row)
                payload["status"] = "approved" if approved else "rejected"
                payload["decided_at"] = _now()
                if note:
                    payload["decision_note"] = note
                self._update_payload(connection, payload)
                self._resync_export(connection, payload)
        except Exception as e:
            return {"decided": False, "reason": f"ошибка записи: {e}"}
        self.registry.record(
            "architecture_proposals",
            payload.get("title", proposal_id),
            "решение человека: " + ("одобрено" if approved else "отклонено"),
            outcome="approved" if approved else "rejected",
            cycle=int(payload.get("cycle", 0) or 0),
            meta={"proposal_id": proposal_id},
        )
        return {
            "decided": True,
            "status": payload["status"],
            "title": payload.get("title", proposal_id),
        }

    # ------------------------------------------------------------------
    # Разовый учёт legacy-файлов (без удаления оригиналов)
    # ------------------------------------------------------------------

    def import_legacy(self, source_dir=None) -> Dict:
        """Учесть legacy JSON-предложения в SQL и реестре артефактов.

        Оригинальные файлы не изменяются и не удаляются: копия попадает
        в каталог жизни и регистрируется в ``artifacts``, статус — в SQL.
        Повторный запуск пропускает уже известные id. Доступен только
        managed-режиму.
        """
        report = {"imported": 0, "skipped": 0, "errors": []}
        if self.database is None:
            report["errors"].append("режим без UUID жизни управляется файлами")
            return report
        source = Path(source_dir or self.proposals_dir)
        if not source.is_dir():
            report["errors"].append(f"каталог предложений отсутствует: {source}")
            return report
        for path in sorted(source.glob("*.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(raw, dict):
                    raise ValueError("предложение должно быть словарём")
                proposal = self._normalize(raw, path.stem)
                with self.database.write() as connection:
                    exists = connection.execute(
                        "SELECT 1 FROM architecture_proposals WHERE id = ?",
                        (proposal["id"],),
                    ).fetchone()
                    if exists is not None:
                        report["skipped"] += 1
                        continue
                    self.database.register_artifact(
                        path,
                        kind="architecture_proposal",
                        relative_path=(self.EXPORT_DIR / path.name).as_posix(),
                        metadata={
                            "proposal_id": proposal["id"],
                            "status": proposal["status"],
                            "source": "legacy_import",
                        },
                        connection=connection,
                    )
                    self._insert_row(connection, proposal)
                report["imported"] += 1
            except Exception as e:
                report["errors"].append(f"{path.name}: {e}")
        return report

    def _normalize(self, raw: Dict, fallback_id: str) -> Dict:
        allowed = {"pending", "approved", "rejected", "implemented"}
        status = raw.get("status")
        proposal = dict(raw)
        proposal["id"] = str(raw.get("id") or fallback_id)
        proposal["type"] = str(raw.get("type") or "behavior_change")
        proposal["title"] = str(raw.get("title") or proposal["id"])
        proposal["description"] = str(raw.get("description") or "")
        proposal["code_snippet"] = str(raw.get("code_snippet") or "")
        proposal["status"] = status if status in allowed else "pending"
        proposal["created_at"] = str(raw.get("created_at") or _now())
        proposal["cycle"] = int(raw.get("cycle", 0) or 0)
        return proposal
