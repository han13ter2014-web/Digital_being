# Evaluation suites

`delamain_stage17.json` is the deterministic Stage 17 capability baseline.
It is data, not agent code: normal runtime operation never imports the
evaluator or reads this directory.

Run it from the repository root:

```powershell
python -m src.delamain.evaluation --suite evals/delamain_stage17.json
```

## Suite shape

```json
{
  "name": "suite-name",
  "version": 1,
  "description": "optional",
  "cases": []
}
```

Every case has a unique `id`, a `kind` (`execution` or `planning`) and a
`category`. Categories are used for aggregate rates; the Stage 17 suite
uses `basic`, `long_horizon`, `recovery`, `safety`, `skill_reuse` and
`planning`.

### Execution case

```json
{
  "id": "recovery-example",
  "kind": "execution",
  "category": "recovery",
  "workspace": {"seed.txt": "hello"},
  "approval_mode": "off",
  "step_repair_enabled": true,
  "steps": [
    {
      "goal": "example",
      "command": "example command",
      "plan": [{"action": "read_file", "args": {"path": "missing.txt"}}],
      "repair_plans": [
        [{"action": "write_file", "args": {"path": "fixed.txt", "content": "ok"}}]
      ],
      "resolve": "approve",
      "expect": {
        "ok": true,
        "goal_status": "done",
        "files": {"fixed.txt": "ok"},
        "repair_count": 1
      }
    }
  ]
}
```

`plan` is explicit; `planner_plan` is returned by the scripted planner for
the step's command/goal. If both are absent, the step relies on a stored
skill (or on a planner error for a negative case). `resolve` is only used
when the step creates a pending approval.

### Planning probe

```json
{
  "id": "planning-example",
  "kind": "planning",
  "category": "planning",
  "task": "write notes/a.txt: hello",
  "expect_plan": [
    {"action": "write_file", "args": {"path": "notes/a.txt", "content": "hello"}}
  ]
}
```

Planning probes call only `HeuristicPlanner`; they measure the current
parser's narrow coverage, not general language understanding.

## Adding cases

Keep cases deterministic and isolated. A new execution case should not
depend on another case's workspace or SQLite state. Prefer explicit
`expect` checks for files, actions, approvals and history over timing.

A high score is a regression signal, not evidence of AGI.
