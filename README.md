# Autonomous Agent Simulation Evaluator

[![Simulation CI](https://github.com/YOUR_USERNAME/autonomous-agent-eval/actions/workflows/ci.yml/badge.svg)](https://github.com/YOUR_USERNAME/autonomous-agent-eval/actions/workflows/ci.yml)

A continuous testing pipeline that evaluates autonomous agent behaviour against
defined pass/fail scenarios — a miniature analogue of how production AV stacks
are validated.

```
C++ simulation engine
        │
        ▼  (subprocess + JSON)
Python test orchestrator
        │
        ▼  (INSERT)
SQLite results database
        │
        ▼  (SELECT + aggregation)
Evaluation report  ←  GitHub Actions CI
```

---

## Architecture

| Layer | File | Role |
|---|---|---|
| **Simulation** | `simulation/simulator.cpp` | 2-D grid environment, A\* planner, collision detection, three decision behaviours |
| **Orchestration** | `runner/test_runner.py` | Loads scenario configs, dispatches simulator subprocess, writes structured results to SQLite |
| **Evaluation** | `runner/evaluate.py` | SQL queries for pass rate, per-behaviour metrics, failure mode analysis, efficiency distribution |
| **CI** | `.github/workflows/ci.yml` | GitHub Actions: compile → smoke test → full suite → evaluation report → upload DB artifact |

---

## Quick start

```bash
# 1. Clone and build
git clone https://github.com/YOUR_USERNAME/autonomous-agent-eval.git
cd autonomous-agent-eval
make                        # compiles simulation/simulator

# 2. Run the test suite
make test                   # executes all 6 scenarios, writes results.db

# 3. Query the results
make evaluate               # prints structured evaluation report
```

### One-shot
```bash
make full                   # build + test + evaluate
```

### Smoke test (single CLI invocation)
```bash
make smoke
```

---

## Decision behaviours

| Behaviour | Planning | Obstacle handling |
|---|---|---|
| `greedy` | A\* (unit cost) | Hard avoidance |
| `cautious` | A\* (cost×10 near obstacles) | Safety-margin routing |
| `reckless` | Naive alternating-axis movement | None — guaranteed collision on cluttered grids |

---

## Scenario suite

| # | Scenario | Behaviour | Expected | Why |
|---|---|---|---|---|
| 01 | Open field | greedy | **PASS** | Baseline; validates A\* on empty grid |
| 02 | Obstacle course | greedy | **PASS** | Scattered clusters force path detours |
| 03 | Reckless collision | reckless | **FAIL** | Obstacle sits on the naive straight-line path |
| 04 | Narrow corridor | greedy | **PASS** | 15-cell horizontal wall; single-cell gap at x≥15 |
| 05 | No valid path | greedy | **FAIL** | Goal is enclosed on all cardinal sides |
| 06 | Cautious S-path | cautious | **PASS** | Two walls; agent uses safety-margin routing |

---

## Simulator CLI

The C++ binary accepts all parameters on the command line so it can be driven
from any test harness:

```bash
./simulation/simulator \
  --id        scenario_01_open_field \
  --width     20  --height 20 \
  --start-x   0   --start-y  0 \
  --goal-x    19  --goal-y   19 \
  --max-steps 100 \
  --behavior  greedy \
  --obstacles "5,3;5,4;9,8"
```

Output (stdout):
```json
{
  "scenario_id":    "scenario_01_open_field",
  "passed":         true,
  "steps_taken":    38,
  "collisions":     0,
  "reached_goal":   true,
  "path_found":     true,
  "efficiency":     1.0000,
  "failure_reason": null
}
```

Exit codes: `0` = PASS, `1` = FAIL, `2` = runtime error.

---

## Database schema

```sql
CREATE TABLE runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT,       -- 8-char UUID prefix per test run
    timestamp       TEXT,
    scenario_id     TEXT,
    scenario_type   TEXT,       -- open_field | obstacle_course | narrow_corridor | …
    behavior        TEXT,       -- greedy | cautious | reckless
    passed          INTEGER,    -- 1 = PASS
    steps_taken     INTEGER,
    collisions      INTEGER,
    reached_goal    INTEGER,
    path_found      INTEGER,
    efficiency      REAL,       -- optimal_steps / actual_steps
    failure_reason  TEXT,       -- COLLISION | NO_PATH_FOUND | MAX_STEPS_EXCEEDED | …
    grid_width      INTEGER,
    grid_height     INTEGER,
    obstacle_count  INTEGER,
    expected_result TEXT
);
```

### Useful ad-hoc queries

```sql
-- Pass rate by behaviour across all runs
SELECT behavior,
       COUNT(*)                              AS runs,
       ROUND(100.0 * SUM(passed) / COUNT(*), 1) AS pass_pct
FROM runs GROUP BY behavior;

-- Failure mode frequency
SELECT failure_reason, COUNT(*) AS n
FROM runs WHERE passed = 0
GROUP BY failure_reason ORDER BY n DESC;

-- Efficiency regression: compare two runs
SELECT a.scenario_id,
       ROUND(a.efficiency, 3) AS eff_run_a,
       ROUND(b.efficiency, 3) AS eff_run_b,
       ROUND(b.efficiency - a.efficiency, 3) AS delta
FROM runs a JOIN runs b USING (scenario_id)
WHERE a.run_id = '<run_a>' AND b.run_id = '<run_b>';
```

---

## Adding scenarios

1. Create `scenarios/scenario_NN_name.json` following the existing format.
2. Set `"expected_result": "PASS"` or `"FAIL"`.
3. `make test` — the runner auto-discovers all `.json` files in `scenarios/`.

The CI pipeline will pick up new scenarios automatically on the next push.

---

## Requirements

- **C++17** compiler (`g++` or `clang++`)
- **Python 3.11+** (standard library only — no pip packages)
- `make`
