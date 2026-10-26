"""Явная копия/проверка/восстановление профиля. Перед create остановите приложение."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.memory.profile_backup import create_backup, restore_backup, verify_backup


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["create", "verify", "restore"])
    parser.add_argument("source")
    parser.add_argument("destination", nargs="?")
    args = parser.parse_args()
    if args.operation == "verify":
        result = verify_backup(args.source)
        print(f"Verified files: {len(result['files'])}")
    else:
        if not args.destination:
            parser.error("Нужна новая папка назначения")
        function = create_backup if args.operation == "create" else restore_backup
        print(function(args.source, args.destination))
