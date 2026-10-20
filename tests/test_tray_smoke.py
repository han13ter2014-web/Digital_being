"""Headless smoke-тест main_tray.py: запустить, подождать, послать SIGTERM, проверить лог."""
import io
import os
import signal
import subprocess
import sys
import time

# UTF-8 для вывода теста (иначе упадёт на эмодзи)
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
if sys.stderr.encoding != "utf-8":
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

LOG = "data/logs/tray_agent.log"

# Не удаляем лог (файл может быть занят). Просто читаем с конца.
log_size_before = os.path.getsize(LOG) if os.path.exists(LOG) else 0

print(f"Запускаю main_tray.py --headless --new в {os.getcwd()}")
p = subprocess.Popen(
    [sys.executable, "main_tray.py", "--headless", "--new"],
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    cwd=os.getcwd(),
    encoding="utf-8",
    errors="replace",
    bufsize=1,
)

# Подождём 6 секунд, потом SIGTERM
start = time.time()
deadline = start + 8
output_lines = []

try:
    while time.time() < deadline:
        if p.poll() is not None:
            print(f"Процесс завершился сам с кодом {p.returncode}")
            break
        line = p.stdout.readline()
        if line:
            output_lines.append(line.rstrip())
            print(f"[child] {line.rstrip()}")
            if "засыпает" in line:
                print("Увидели 'засыпает' — завершаемся штатно")
                break
        else:
            time.sleep(0.2)

    if p.poll() is None:
        print(f"\nПосылаю SIGTERM через {time.time()-start:.1f}с...")
        p.terminate()
        try:
            p.wait(timeout=3)
        except subprocess.TimeoutExpired:
            print("SIGTERM не помог, kill")
            p.kill()
            p.wait()

    # Дочитать остаток
    try:
        rest, _ = p.communicate(timeout=2)
        if rest:
            for line in rest.splitlines():
                print(f"[child-rest] {line}")
                output_lines.append(line)
    except Exception:
        pass

except KeyboardInterrupt:
    p.kill()
    p.wait()

print(f"\n=== Всего строк вывода: {len(output_lines)} ===")
print("\n=== Проверки ===")

required = [
    "Создаю агента",
    "EventBus",
    "ЖИВЁТ В ТРЕЕ",
    "Иконка в трее",
    "Окно чата",
    "Уведомления",
    "Циклов: ∞",
]
all_ok = True
for r in required:
    found = any(r in line for line in output_lines)
    icon = "✅" if found else "❌"
    print(f"  {icon} '{r}'")
    if not found:
        all_ok = False

# Проверяем лог-файл
print(f"\n=== Лог {LOG} ===")
if os.path.exists(LOG):
    with open(LOG, encoding="utf-8") as f:
        f.seek(log_size_before)
        new_log = f.read()
    log_lines = new_log.splitlines()
    print(f"  Новых строк в логе: {len(log_lines)}")
    tick_count = sum(1 for line in log_lines if "[AgentRunner]" in line and "Старт" in line)
    print(f"  AgentRunner старт: {'✅' if tick_count > 0 else '❌'}")
    # Дополнительно: ищем признаки циклов (TICK в chat или log)
    cycle_hits = sum(1 for line in log_lines if "AgentRunner" in line and "Старт" in line)
    print(f"  Признаки циклов: {cycle_hits}")
else:
    print("  ❌ Лог-файл не создан")
    all_ok = False

print(f"\n{'='*40}")
if all_ok:
    print("✅ Smoke-тест ПРОШЁЛ")
else:
    print("❌ Smoke-тест ПРОВАЛЕН")
    sys.exit(1)