"""CLI: python -m assistant_memory [--dir PATH] store|recall|recent|stats|forget."""

from __future__ import annotations

import argparse
import json

from assistant_memory.memory import AssistantMemory


def main() -> None:
    parser = argparse.ArgumentParser(description="Локальная память ассистента")
    parser.add_argument("--dir", dest="storage_dir", help="Каталог хранения")
    commands = parser.add_subparsers(dest="command", required=True)

    store = commands.add_parser("store")
    store.add_argument("content")
    store.add_argument("--importance", type=float, default=0.5)
    store.add_argument("--context", default="")
    store.add_argument(
        "--type", choices=("episodic", "semantic", "procedural"), default="episodic"
    )

    recall = commands.add_parser("recall")
    recall.add_argument("query")
    recall.add_argument("--max-results", type=int, default=4)
    recall.add_argument("--max-chars", type=int, default=2_000)

    recent = commands.add_parser("recent")
    recent.add_argument("--days", type=int, default=7)
    recent.add_argument("--count", type=int, default=10)

    commands.add_parser("stats")

    forget = commands.add_parser("forget")
    forget.add_argument("memory_id")

    args = parser.parse_args()
    memory = AssistantMemory(args.storage_dir)
    if args.command == "store":
        print(
            memory.store(
                args.content,
                importance=args.importance,
                context=args.context,
                memory_type=args.type,
            )
        )
    elif args.command == "recall":
        print(
            memory.recall_context(
                args.query, max_results=args.max_results, max_chars=args.max_chars
            )
        )
    elif args.command == "recent":
        print(
            json.dumps(
                memory.get_recent_episodes(days=args.days, count=args.count),
                ensure_ascii=False,
                indent=2,
            )
        )
    elif args.command == "stats":
        print(json.dumps(memory.get_memory_stats(), ensure_ascii=False, indent=2))
    elif args.command == "forget":
        print("forgotten" if memory.forget(args.memory_id) else "not_found")


if __name__ == "__main__":
    main()
