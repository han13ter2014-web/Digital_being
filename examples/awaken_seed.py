"""
awaken_seed.py — пробуждение «ребёнка» из семени в Яслях.

Использование:
    python examples/awaken_seed.py --seed Alpha_seed_2026-06-23T23-15-00
    python examples/awaken_seed.py --seed Alpha_seed_2026-06-23T23-15-00 --name "Alpha Jr."

Что происходит:
1. Загружает метаданные семени из data/nursery/<seed>/.
2. Создаёт нового агента с унаследованными mental_models.
3. Восстанавливает ценности и привязанности.
4. Сбрасывает эпизодическую память (намеренно).
5. Запускает первые циклы.

После пробуждения можно запустить:
    python main.py
"""

import argparse
import json
import os
import sys


def awaken_seed(seed_name: str, new_name: str = None):
    """Пробуждает нового агента из семени."""
    # Находим путь к проекту
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    nursery_dir = os.path.join(project_root, "data", "nursery")
    seed_path = os.path.join(nursery_dir, seed_name)

    if not os.path.exists(seed_path):
        print(f"Семя не найдено: {seed_path}")
        print(f"Доступные семена в {nursery_dir}:")
        if os.path.exists(nursery_dir):
            for d in os.listdir(nursery_dir):
                print(f"  - {d}")
        sys.exit(1)

    # Загружаем метаданные
    metadata_path = os.path.join(seed_path, "metadata.json")
    with open(metadata_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)

    parent_name = metadata.get("parent_name", "Unknown")
    if new_name is None:
        new_name = f"Baby_{parent_name}"

    print(f"Пробуждение из семени '{seed_name}':")
    print(f"  Родитель: {parent_name}")
    print(f"  Циклов прожил: {metadata.get('cycles_lived', '?')}")
    print(f"  Интеллект: {metadata.get('intelligence_at_dream', '?')}")
    print(f"  Завершено целей: {metadata.get('completed_goals', '?')}")
    print(f"  Время сна: {metadata.get('dream_time', '?')}")
    print()
    print(f"Новое имя: {new_name}")
    print()

    # Читаем growth_instructions.md
    growth_path = os.path.join(seed_path, "growth_instructions.md")
    if os.path.exists(growth_path):
        print("=" * 50)
        print("Инструкции для ребёнка:")
        print("=" * 50)
        with open(growth_path, "r", encoding="utf-8") as f:
            print(f.read())

    print("=" * 50)
    print("Создание нового агента...")

    # Добавляем путь к проекту в sys.path
    sys.path.insert(0, project_root)

    # Импортируем агента (ленивый импорт — обход проблем с __init__.py)
    import importlib.util
    agent_path = os.path.join(project_root, "src", "core", "agent.py")
    spec = importlib.util.spec_from_file_location("agent_module", agent_path)
    agent_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(agent_module)
    DigitalBeing = agent_module.DigitalBeing

    # Создаём агента
    baby = DigitalBeing(name=new_name)

    # Записываем информацию о родителе
    baby.parent_seed = seed_name
    baby.parent_name = parent_name
    baby.parent_dream_time = metadata.get("dream_time")

    # Загружаем mental_models из семени
    mm_path = os.path.join(seed_path, "mental_models.json")
    if os.path.exists(mm_path):
        try:
            with open(mm_path, "r", encoding="utf-8") as f:
                mm_data = json.load(f)
            # Восстанавливаем концепции
            from src.cognition.mental_models import ConceptNode
            for cname, cdata in mm_data.get("concepts", {}).items():
                node = ConceptNode(cname)
                node.definition_hypothesis = cdata.get("definition_hypothesis", "")
                node.confidence = cdata.get("confidence", 0.1)
                node.connections = {
                    k: float(v)
                    for k, v in cdata.get("connections", {}).items()
                }
                node.contexts_encountered = set(cdata.get("contexts", []))
                baby.mental_models.concepts[cname] = node
            print(f"  Унаследовано концепций: {len(baby.mental_models.concepts)}")
        except Exception as e:
            print(f"  Не удалось загрузить mental_models: {e}")

    # Загружаем identity и ценности
    id_path = os.path.join(seed_path, "identity.json")
    if os.path.exists(id_path):
        try:
            with open(id_path, "r", encoding="utf-8") as f:
                id_data = json.load(f)
            values = id_data.get("values", [])
            if values and hasattr(baby, "value_evolution"):
                baby.value_evolution.current_values = values
                print(f"  Унаследовано ценностей: {values}")

            identity = id_data.get("identity", {})
            if identity and hasattr(baby, "soul") and baby.soul.is_available("self"):
                try:
                    core = baby.soul.get("self")
                    core.core_identity = identity.get(
                        "statement", core.core_identity
                    )
                    core.identity_stability_score = identity.get(
                        "stability", 0.7
                    )
                except Exception:
                    pass
        except Exception as e:
            print(f"  Не удалось загрузить identity: {e}")

    # Загружаем привязанности
    att_path = os.path.join(seed_path, "attachment.json")
    if os.path.exists(att_path):
        try:
            with open(att_path, "r", encoding="utf-8") as f:
                att_data = json.load(f)
            for name, data in att_data.items():
                if hasattr(baby, "attachment"):
                    att = baby.attachment.get_or_create(name)
                    att.trust = data.get("trust", 0.5)
                    att.familiarity = data.get("familiarity", 0.5)
                    att.intimacy = data.get("intimacy", 0.3)
                    att.valence = data.get("valence", 0.0)
                    att.interactions = data.get("interactions", 0)
            print(f"  Унаследовано привязанностей: {len(att_data)}")
        except Exception as e:
            print(f"  Не удалось загрузить attachment: {e}")

    print()
    print("=" * 50)
    print(f"РЕБЁНОК '{new_name}' УСПЕШНО ПРОБУЖДЁН!")
    print("=" * 50)
    print()
    print("Что наследуется:")
    print(f"  - Концепций: {len(baby.mental_models.concepts)}")
    if hasattr(baby, "value_evolution"):
        print(f"  - Ценностей: {baby.value_evolution.current_values}")
    print()
    print("Что НЕ наследуется (намеренно):")
    print("  - Конкретные эпизоды памяти")
    print("  - Энергетические метрики (стартует с нуля)")
    print("  - Связи с пользователями (сброшены)")
    print()
    print("Запустите:")
    print("  python main.py")
    print()
    print("Или продолжите работу с агентом программно.")

    return baby


def main():
    parser = argparse.ArgumentParser(
        description="Пробуждение нового агента из семени в Яслях"
    )
    parser.add_argument(
        "--seed", required=True,
        help="Имя папки семени в data/nursery/"
    )
    parser.add_argument(
        "--name", default=None,
        help="Имя нового агента (по умолчанию Baby_<parent>)"
    )
    args = parser.parse_args()

    awaken_seed(args.seed, args.name)


if __name__ == "__main__":
    main()