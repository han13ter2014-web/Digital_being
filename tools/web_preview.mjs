import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";

// Kimi Work запускает `npm run dev -- --host ... --port ...`.
// Node здесь только launcher: сам read-only транспорт остаётся aiohttp.
const root = process.cwd();
const localPython = path.join(root, ".venv", "Scripts", "python.exe");
const python = existsSync(localPython) ? localPython : "python";
const args = process.argv.slice(2);
const hasPort = args.some((arg, index) => arg === "--port" || arg.startsWith("--port="));
const forwarded = hasPort ? args : [...args, "--port", "7100"];
const child = spawn(python, ["-m", "src.ui.web_dashboard", ...forwarded], {
  cwd: root,
  stdio: "inherit",
  windowsHide: false,
});

let stopping = false;
function stop() {
  if (stopping) return;
  stopping = true;
  if (!child.killed) child.kill();
}
process.on("SIGINT", stop);
process.on("SIGTERM", stop);
process.on("exit", stop);
child.on("error", (error) => {
  console.error(`Не удалось запустить Python: ${error.message}`);
  process.exitCode = 1;
});
child.on("exit", (code, signal) => {
  process.exitCode = code ?? (signal ? 1 : 0);
});
