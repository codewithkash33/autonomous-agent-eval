#!/usr/bin/env python3
"""
Autonomous Agent Simulation — Test Runner
──────────────────────────────────────────
Discovers all scenario configs in scenarios/, runs the C++ simulator
for each one, and persists structured results in a SQLite database.

This is the Python orchestration layer of the pipeline:
  C++ sim → Python runner (this file) → SQLite → evaluate.py

Usage:
    python3 runner/test_runner.py [--db PATH] [--scenarios DIR]
"""

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

# ── Project paths ──────────────────────────────────────────────────────────────
PROJECT_ROOT  = Path(__file__).resolve().parent.parent
SIMULATOR_BIN = PROJECT_ROOT / "simulation" / "simulator"
SCENARIOS_DIR = PROJECT_ROOT / "scenarios"
DEFAULT_DB    = PROJECT_ROOT / "results.db"

# ── Database schema ────────────────────────────────────────────────────────────
SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT    NOT NULL,
    timestamp       TEXT    NOT NULL,
    scenario_id     TEXT    NOT NULL,
    scenario_type   TEXT,
    behavior        TEXT    NOT NULL,
    passed          INTEGER NOT NULL,       -- 1 = PASS, 0 = FAIL
    steps_taken     INTEGER,
    collisions      INTEGER,
    reached_goal    INTEGER,               -- 1 = true
    path_found      INTEGER,               -- 1 = true
    efficiency      REAL,                  -- optimal_steps / steps_taken
    failure_reason  TEXT,
    grid_width      INTEGER,
    grid_height     INTEGER,
    obstacle_count  INTEGER,
    expected_result TEXT
);
"""


def init_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute(SCHEMA)
    conn.commit()
    return conn


def insert_result(conn: sqlite3.Connection,
                  run_id: str,
                  timestamp: str,
                  scenario: dict,
                  result: dict) -> None:
    conn.execute(
        """
        INSERT INTO runs (
            run_id, timestamp, scenario_id, scenario_type,
            behavior, passed, steps_taken, collisions,
            reached_goal, path_found, efficiency, failure_reason,
            grid_width, grid_height, obstacle_count, expected_result
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            run_id,
            timestamp,
            result.get("scenario_id", scenario.get("scenario_id", "unknown")),
            scenario.get("scenario_type", "unknown"),
            scenario.get("behavior", "greedy"),
            1 if result.get("passed") else 0,
            result.get("steps_taken", 0),
            result.get("collisions", 0),
            1 if result.get("reached_goal") else 0,
            1 if result.get("path_found") else 0,
            result.get("efficiency", 0.0),
            result.get("failure_reason"),
            scenario.get("grid_width", 20),
            scenario.get("grid_height", 20),
            len(scenario.get("obstacles", [])),
            scenario.get("expected_result", "PASS"),
        ),
    )
    conn.commit()


# ── Simulator execution ────────────────────────────────────────────────────────

def build_cmd(scenario: dict) -> list[str]:
    """Convert a scenario dict into simulator CLI arguments."""
    obs_str = ";".join(
        f"{o['x']},{o['y']}" for o in scenario.get("obstacles", [])
    )
    return [
        str(SIMULATOR_BIN),
        "--id",        scenario["scenario_id"],
        "--width",     str(scenario["grid_width"]),
        "--height",    str(scenario["grid_height"]),
        "--start-x",   str(scenario["start"]["x"]),
        "--start-y",   str(scenario["start"]["y"]),
        "--goal-x",    str(scenario["goal"]["x"]),
        "--goal-y",    str(scenario["goal"]["y"]),
        "--max-steps", str(scenario["max_steps"]),
        "--behavior",  scenario.get("behavior", "greedy"),
        "--obstacles", obs_str,
    ]


_FALLBACK = dict(
    passed=False, steps_taken=0, collisions=0,
    reached_goal=False, path_found=False, efficiency=0.0,
)


def run_scenario(scenario: dict) -> dict:
    """Execute the simulator for one scenario and return a result dict."""
    cmd = build_cmd(scenario)
    sid = scenario["scenario_id"]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=15,
        )
        stdout = proc.stdout.strip()
        if not stdout:
            stderr = proc.stderr.strip()
            return {**_FALLBACK, "scenario_id": sid,
                    "failure_reason": f"NO_OUTPUT (stderr: {stderr[:120]})"}
        return json.loads(stdout)

    except subprocess.TimeoutExpired:
        return {**_FALLBACK, "scenario_id": sid, "failure_reason": "TIMEOUT"}
    except FileNotFoundError:
        return {**_FALLBACK, "scenario_id": sid,
                "failure_reason": "BINARY_NOT_FOUND"}
    except json.JSONDecodeError as exc:
        return {**_FALLBACK, "scenario_id": sid,
                "failure_reason": f"JSON_PARSE_ERROR: {exc}"}


# ── Pretty printing ────────────────────────────────────────────────────────────
_GREEN  = "\033[32m"
_RED    = "\033[31m"
_YELLOW = "\033[33m"
_RESET  = "\033[0m"
_BOLD   = "\033[1m"
_W      = 66


def _sep(char="─"): print(char * _W)


def _tag(passed: bool) -> str:
    return f"{_GREEN}PASS{_RESET}" if passed else f"{_RED}FAIL{_RESET}"


def print_header(run_id: str, n_scenarios: int) -> None:
    _sep("═")
    print(f"{_BOLD}  Autonomous Agent Simulation Evaluator{_RESET}")
    print(f"  Run ID    : {run_id}")
    print(f"  Timestamp : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Scenarios : {n_scenarios}")
    _sep("═")


def print_row(idx: int, total: int, scenario_id: str, result: dict) -> None:
    passed = result.get("passed", False)
    steps  = result.get("steps_taken", 0)
    reason = result.get("failure_reason") or ""
    suffix = f"{steps} steps" if passed else reason
    print(f"  [{idx:2d}/{total}] {scenario_id:<38} {_tag(passed)}  ({suffix})")


def print_summary(run_id: str, total: int, passed: int, db_path: Path,
                  mismatches: list[dict]) -> None:
    failed  = total - passed
    pct     = 100.0 * passed / total if total else 0.0
    _sep("─")
    print(f"  Total : {total}  │  "
          f"{_GREEN}Passed : {passed}{_RESET}  │  "
          f"{_RED}Failed : {failed}{_RESET}  │  "
          f"Pass rate : {pct:.1f}%")

    if mismatches:
        print()
        print(f"  {_YELLOW}⚠  UNEXPECTED RESULTS (actual ≠ expected):{_RESET}")
        for m in mismatches:
            print(f"     {m['scenario_id']}: "
                  f"expected {m['expected']}, got {m['actual']}")

    _sep("═")
    print(f"  Results saved → {db_path}")
    print()


# ── Main ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Autonomous agent simulation test runner")
    p.add_argument("--db",        default=str(DEFAULT_DB),    help="SQLite database path")
    p.add_argument("--scenarios", default=str(SCENARIOS_DIR), help="Scenario directory")
    return p.parse_args()


def main() -> int:
    args       = parse_args()
    db_path    = Path(args.db)
    scen_dir   = Path(args.scenarios)

    # ── Pre-flight checks ──────────────────────────────────────────────────────
    if not SIMULATOR_BIN.exists():
        print(f"[ERROR] Simulator binary not found: {SIMULATOR_BIN}")
        print("        Run 'make' in the project root first.")
        return 1

    scenario_files = sorted(scen_dir.glob("*.json"))
    if not scenario_files:
        print(f"[ERROR] No scenario JSON files found in {scen_dir}")
        return 1

    # ── Load scenarios ─────────────────────────────────────────────────────────
    scenarios: list[dict] = []
    for f in scenario_files:
        with open(f) as fp:
            scenarios.append(json.load(fp))

    run_id    = str(uuid.uuid4())[:8]
    timestamp = datetime.now().isoformat()
    conn      = init_db(db_path)

    print_header(run_id, len(scenarios))

    # ── Execute all scenarios ──────────────────────────────────────────────────
    all_results: list[tuple[dict, dict]] = []
    passed_count = 0

    for i, scenario in enumerate(scenarios, start=1):
        result = run_scenario(scenario)
        all_results.append((scenario, result))

        if result.get("passed"):
            passed_count += 1

        insert_result(conn, run_id, timestamp, scenario, result)
        print_row(i, len(scenarios), scenario["scenario_id"], result)

    conn.close()

    # ── Validate against expected outcomes ────────────────────────────────────
    mismatches: list[dict] = []
    for scenario, result in all_results:
        expected = scenario.get("expected_result", "PASS").upper()
        actual   = "PASS" if result.get("passed") else "FAIL"
        if actual != expected:
            mismatches.append({
                "scenario_id": scenario["scenario_id"],
                "expected":    expected,
                "actual":      actual,
            })

    print_summary(run_id, len(scenarios), passed_count, db_path, mismatches)

    # Exit non-zero only when a scenario produces an unexpected outcome.
    return 0 if not mismatches else 1


if __name__ == "__main__":
    sys.exit(main())
