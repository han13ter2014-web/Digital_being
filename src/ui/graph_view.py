"""Карта жизни: сборка графа из реальных данных Core.

Правило: граф не рисует связей, которых нет. У каждого ребра есть
основание — записанная связь ментальной модели, ссылка намерения на тему
или принадлежность действия к намерению. Нет основания — нет ребра.

Чистая логика без Tk: возвращает узлы, рёбра и раскладку, которые рисует
Canvas. Поэтому и сборку, и раскладку можно тестировать без экрана.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from src.ui import life_view
from src.ui.concept_filter import split_service_concepts

MAX_NODES = 200
MAX_EDGES = 500
MAX_CONCEPTS = 120
MAX_INTENTIONS = 40
MAX_VALUES = 8

# Русские подписи известных ценностей ядра. Неизвестную ценность показываем
# как есть: перевод — удобство чтения, а не новое знание.
_VALUE_LABELS = {
    "curiosity": "любознательность",
    "honesty": "честность",
    "learning": "обучение",
    "autonomy": "автономия",
    "connection": "связь",
    "growth": "рост",
    "truth": "правда",
    "kindness": "доброта",
}


def value_label(name: str) -> str:
    """Подпись ценности: русская для известных ключей, иначе исходная."""
    return _VALUE_LABELS.get(name, name)


def _concept_detail(node: Any) -> Dict[str, Any]:
    """Что известно о концепции: свидетельства, уверенность, источники, связи."""
    experiences = [item for item in (getattr(node, "experiences", []) or [])
                   if isinstance(item, dict)]
    sources = {str(item.get("source")) for item in experiences if item.get("source")}
    timestamps = [str(item.get("timestamp")) for item in experiences
                  if item.get("timestamp")]
    detail: Dict[str, Any] = {
        "свидетельств": len(experiences),
        "уверенность": round(float(getattr(node, "confidence", 0.0) or 0.0), 2),
        "источников": len(sources),
        "связей в модели": len(getattr(node, "connections", {}) or {}),
    }
    if timestamps:
        detail["последнее"] = max(timestamps)[:16].replace("T", " ")
    return detail


def _intention_label(entry: Dict[str, Any]) -> str:
    label = life_view.action_phrase(str(entry.get("action") or ""), entry.get("target"))
    if str(entry.get("status") or "") == "started":
        return f"{label} · сейчас"
    return label


def _is_forgotten(entry: Dict[str, Any]) -> bool:
    resolution = entry.get("resolution")
    return isinstance(resolution, dict) and resolution.get("kind") == "forgotten"


def build_life_graph(
    agent: Any,
    life_snapshot: Optional[Dict[str, Any]] = None,
    *,
    limit: int = MAX_NODES,
) -> Dict[str, Any]:
    """Собрать узлы и рёбра карты жизни.

    Args:
        agent: ``DigitalBeing``; читается без изменений.
        life_snapshot: готовый снимок жизни (намерения берём оттуда).
        limit: максимум узлов на экран.

    Returns:
        ``{"nodes", "edges", "truncated", "omitted"}``. Узлы и рёбра
        отсортированы детерминированно, чтобы раскладка не «прыгала».
    """
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    seen_ids: set = set()
    seen_edges: set = set()
    omitted = 0

    def add_node(node_id: str, kind: str, label: Any, weight: float,
                 detail: Optional[Dict[str, Any]] = None) -> bool:
        if node_id in seen_ids:
            return False
        seen_ids.add(node_id)
        nodes.append({
            "id": node_id,
            "kind": kind,
            "label": str(label),
            "weight": max(0.0, min(1.0, float(weight))),
            "detail": dict(detail or {}),
        })
        return True

    def add_edge(source: str, target: str, kind: str, label: str,
                 weight: float = 0.5) -> None:
        if source == target or source not in seen_ids or target not in seen_ids:
            return
        pair: Tuple[str, ...] = (
            tuple(sorted((source, target))) if kind == "association"
            else (source, target)
        )
        key = (pair, kind)
        if key in seen_edges:
            return
        seen_edges.add(key)
        edges.append({
            "source": source,
            "target": target,
            "kind": kind,
            "label": label,
            "weight": max(0.0, min(1.0, float(weight))),
        })

    # --- Концепции: только те, что реально есть в ментальной модели ---
    mental_models = getattr(agent, "mental_models", None)
    concepts = getattr(mental_models, "concepts", {}) or {}
    visible, hidden_service = split_service_concepts(concepts.items())
    ordered = sorted(
        visible,
        key=lambda item: (
            float(getattr(item[1], "confidence", 0.0) or 0.0),
            len(getattr(item[1], "experiences", []) or []),
        ),
        reverse=True,
    )
    kept = ordered[:MAX_CONCEPTS]
    omitted = max(0, len(visible) - len(kept))
    for name, node in kept:
        add_node(f"concept:{name}", "concept", name,
                 getattr(node, "confidence", 0.1), _concept_detail(node))

    kept_names = {name for name, _ in kept}
    for name, node in kept:
        for other, weight in (getattr(node, "connections", {}) or {}).items():
            if other not in kept_names:
                continue
            add_edge(f"concept:{name}", f"concept:{other}",
                     "association", "связано с", weight)

    # --- Намерения: из снимка жизни, без повторной записи в Core ---
    snapshot = life_snapshot or {}
    intents = snapshot.get("intentions") or {}
    entries = list(intents.get("recent") or [])
    waiting = list(intents.get("waiting") or [])
    forgotten = list(intents.get("forgotten") or [])
    # Один id — один узел; забытое состояние важнее прежнего «выполнено».
    combined: Dict[str, Dict[str, Any]] = {}
    for entry in entries + waiting + forgotten:
        if isinstance(entry, dict) and entry.get("id"):
            combined[str(entry["id"])] = entry
    for entry in list(combined.values())[-MAX_INTENTIONS:]:
        if not isinstance(entry, dict):
            continue
        entry_id = str(entry.get("id") or "")
        if not entry_id:
            continue
        kind = "forgotten" if _is_forgotten(entry) else "intention"
        weight = 0.8 if str(entry.get("status") or "") == "started" else 0.45
        add_node(f"intention:{entry_id}", kind, _intention_label(entry), weight, {
            "действие": entry.get("action"),
            "тема": entry.get("target"),
            "статус": entry.get("status"),
        })

        target = entry.get("target")
        if isinstance(target, str) and f"concept:{target}" in seen_ids:
            add_edge(f"intention:{entry_id}", f"concept:{target}",
                     "about", "о теме", 0.6)

        action = str(entry.get("action") or "")
        if action:
            activity_id = f"activity:{action}"
            add_node(activity_id, "activity",
                     _ACTIVITY_LABELS.get(action, action), 0.5,
                     {"действие": action})
            add_edge(f"intention:{entry_id}", activity_id, "uses",
                     "породило", 0.6)

    # --- Ценности ядра: реальные ключи innate_values, без выдуманных ---
    values = getattr(agent, "innate_values", None) or {}
    if isinstance(values, dict):
        for name in list(values)[:MAX_VALUES]:
            if isinstance(name, str) and name.strip():
                add_node(f"value:{name}", "value", value_label(name), 0.5,
                         {"ценность ядра": True})

    # --- Ограничения объёма: рабочая карта, а не вся память ---
    if len(nodes) > limit:
        ranked = sorted(nodes, key=lambda n: (-n["weight"], n["id"]))
        keep_ids = {n["id"] for n in ranked[:limit]}
        nodes = [n for n in nodes if n["id"] in keep_ids]
        edges = [e for e in edges
                 if e["source"] in keep_ids and e["target"] in keep_ids]

    if len(edges) > MAX_EDGES:
        edges = sorted(edges, key=lambda e: (-e["weight"], e["source"], e["target"]))[:MAX_EDGES]

    nodes.sort(key=lambda n: (n["kind"], n["id"]))
    return {
        "nodes": nodes,
        "edges": edges,
        "truncated": omitted > 0 or len(nodes) >= limit,
        "omitted": omitted,
        # Скрытые служебные записи не удалены из Core: счётчик нужен,
        # чтобы человек видел, что карта показывает не всё, но не читал
        # технические метки как знание.
        "hidden_service": hidden_service,
    }


# Кольца концепций: (доля максимального радиуса, сколько узлов помещается).
# Первый узел — в центре, как самая уверенная тема; дальше — орбиты.
_CONCEPT_RINGS = (
    (0.0, 1),
    (0.26, 7),
    (0.44, 12),
    (0.60, 18),
    (0.73, 24),
    (0.84, 30),
)

# Остальные группы живут внешними кольцами: забытое ближе к знанию,
# ценности — на самом краю.
_GROUP_RINGS = {
    "forgotten": (0.60, 0.70),
    "intention": (0.68, 0.78),
    "activity": (0.82, 0.90),
    "value": (0.96, 1.0),
}

# Короткие подписи занятий: в узком месте карты длинная фраза не читается.
_ACTIVITY_LABELS = {
    "play": "партия",
    "create_draft": "черновик",
    "explore": "исследование",
    "communicate": "общение",
    "rest": "отдых",
    "reflect": "размышление",
    "wait": "ожидание",
}

# Подписи длиннее не помещаются между узлами: лучше укоротить, чем рисовать кашу.
MAX_LABEL_CHARS = 34


def _place_ring(
    positions: Dict[str, Tuple[float, float]],
    items: List[Dict[str, Any]],
    center_x: float,
    center_y: float,
    radius: float,
    offset: float,
) -> None:
    """Разложить узлы кольца равномерно; один узел — по заданному углу."""
    count = len(items)
    if count == 0:
        return
    for index, node in enumerate(items):
        if radius <= 0.0:
            positions[node["id"]] = (center_x, center_y)
            continue
        angle = offset + 2.0 * math.pi * index / count
        positions[node["id"]] = (
            center_x + radius * math.cos(angle),
            center_y + radius * math.sin(angle),
        )


def layout_nodes(nodes: List[Dict[str, Any]], width: float, height: float) -> Dict[str, Tuple[float, float]]:
    """Детерминированная раскладка кольцами: без случайности и дрожания.

    Концепции идут от центра к краю по уверенности, остальные группы —
    внешними орбитами. Одинаковые данные всегда дают одинаковую картинку.
    """
    center_x, center_y = float(width) / 2.0, float(height) / 2.0
    max_radius = max(40.0, min(float(width), float(height)) / 2.0 - 26.0)
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for node in nodes:
        groups.setdefault(str(node.get("kind")), []).append(node)

    positions: Dict[str, Tuple[float, float]] = {}
    concepts = sorted(
        groups.pop("concept", []),
        key=lambda item: (-float(item.get("weight") or 0.0), str(item.get("id"))),
    )
    index = 0
    for ring_index, (fraction, capacity) in enumerate(_CONCEPT_RINGS):
        chunk = concepts[index:index + capacity]
        index += capacity
        _place_ring(positions, chunk, center_x, center_y,
                    max_radius * fraction, offset=0.4 * (ring_index + 1))

    kind_offsets = {"forgotten": 0.9, "intention": 1.7, "activity": 2.5, "value": 3.3}
    for kind, (inner, outer) in _GROUP_RINGS.items():
        items = sorted(
            groups.pop(kind, []),
            key=lambda item: (-float(item.get("weight") or 0.0), str(item.get("id"))),
        )
        first, rest = items[:16], items[16:]
        _place_ring(positions, first, center_x, center_y,
                    max_radius * inner, offset=kind_offsets[kind])
        _place_ring(positions, rest, center_x, center_y,
                    max_radius * outer, offset=kind_offsets[kind] + 0.3)

    # Неизвестный тип не выбрасываем с карты, а ставим на тихую орбиту.
    for kind, items in sorted(groups.items()):
        _place_ring(positions, items, center_x, center_y,
                    max_radius * 0.5, offset=0.0)
    return positions


def short_label(text: Any, limit: int = MAX_LABEL_CHARS) -> str:
    """Подпись узла, укороченная по границе символов."""
    value = str(text)
    return value if len(value) <= limit else value[:limit - 1] + "…"


def _boxes_overlap(first: Tuple[float, float, float, float],
                   second: Tuple[float, float, float, float],
                   padding: float = 3.0) -> bool:
    return not (
        first[2] + padding < second[0] or second[2] + padding < first[0]
        or first[3] + padding < second[1] or second[3] + padding < first[1]
    )


def layout_labels(
    nodes: List[Dict[str, Any]],
    positions: Dict[str, Tuple[float, float]],
    width: float,
    height: float,
) -> Dict[str, Tuple[float, float, str]]:
    """Разместить подписи без наложений: справа, слева, снизу или сверху.

    Возвращает ``{id: (x, y, anchor)}``. Если все варианты заняты, подпись
    пропускается: карта должна оставаться читаемой, а не превращаться в
    сплошной текст. Правило детерминированное — те же данные дают ту же
    картинку.
    """
    centers: List[Tuple[float, float, float]] = []
    for node in nodes:
        position = positions.get(str(node.get("id")))
        if position is None:
            continue
        centers.append((
            position[0], position[1],
            node_radius(node.get("weight"), str(node.get("kind"))),
        ))

    def hits_node(box: Tuple[float, float, float, float]) -> bool:
        for center_x, center_y, radius in centers:
            nearest_x = min(max(center_x, box[0]), box[2])
            nearest_y = min(max(center_y, box[1]), box[3])
            if (nearest_x - center_x) ** 2 + (nearest_y - center_y) ** 2 < (radius + 4.0) ** 2:
                return True
        return False

    used: List[Tuple[float, float, float, float]] = []
    labels: Dict[str, Tuple[float, float, str]] = {}
    ordered = sorted(
        nodes,
        key=lambda item: (-float(item.get("weight") or 0.0), str(item.get("id"))),
    )
    for node in ordered:
        kind = str(node.get("kind"))
        if not node_shows_label(node.get("weight"), kind):
            continue
        position = positions.get(str(node.get("id")))
        if position is None:
            continue
        x, y = position
        radius = node_radius(node.get("weight"), kind)
        text = short_label(node.get("label"))
        text_width = len(text) * 6.8 + 6.0
        text_height = 17.0
        gap = 8.0
        candidates = (
            (x + radius + gap, y, "w",
             (x + radius + gap, y - text_height / 2,
              x + radius + gap + text_width, y + text_height / 2)),
            (x - radius - gap, y, "e",
             (x - radius - gap - text_width, y - text_height / 2,
              x - radius - gap, y + text_height / 2)),
            (x, y + radius + gap, "n",
             (x - text_width / 2, y + radius + gap,
              x + text_width / 2, y + radius + gap + text_height)),
            (x, y - radius - gap, "s",
             (x - text_width / 2, y - radius - gap - text_height,
              x + text_width / 2, y - radius - gap)),
        )
        for label_x, label_y, anchor, box in candidates:
            if box[0] < 4 or box[1] < 4 or box[2] > width - 4 or box[3] > height - 4:
                continue
            if hits_node(box):
                continue
            if any(_boxes_overlap(box, other) for other in used):
                continue
            labels[str(node.get("id"))] = (label_x, label_y, anchor)
            used.append(box)
            break
    return labels


def node_radius(weight: Any, kind: str = "") -> float:
    """Радиус узла из веса. Вес — значимость, а не «истина»."""
    base = 5.0 + 13.0 * max(0.0, min(1.0, float(weight or 0.0)))
    return base + (2.0 if kind == "value" else 0.0)


def node_shows_label(weight: Any, kind: str = "") -> bool:
    """Подписи — только у заметных узлов, иначе карта превращается в текст."""
    return float(weight or 0.0) >= 0.35 or kind in {"value", "intention"}
