#!/usr/bin/env python3
"""
Autonomous Agent Simulation — Evaluation Report
─────────────────────────────────────────────────
Queries the SQLite results database and prints structured performance
metrics: overall pass rate, per-behavior breakdowns, failure analysis,
and per-scenario detail.

Usage:
    python3 runner/evaluate.py                 # latest run
    python3 runner/evaluate.py <run_id>        # specific run
    python3 runner/evaluate.py --all           # every run on record

This is the SQL evaluation layer of the pipeline:
  C++ sim → Python runner → SQLite → evaluate.py (this file)
"""

import argparse
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB   = PROJECT_ROOT / "results.db"

_GREEN  = "\033[32m"
_RED    = "\033[31m"
_CYAN   = "\033[36m"
_BOLD   = "\033[1m"
_DIM    = "\033[2m"
_RESET  = "\033[0m"
_W      = 70


# ── Helpers ────────────────────────────────────────────────────────────────────

def _sep(char="─", w=_W): print(char * w)

def _pct(n, d):
    return f"{100.0 * n / d:.1f}%" if d else "N/A"

def _eff(v):
    return f"{v:.3f}" if v is not None else "  N/A"

def _colored_result(passed: int) -> str:
    return f"{_GREEN}PASS{_RESET}" if passed else f"{_RED}FAIL{_RESET}"


# ── SQL queries ────────────────────────────────────────────────────────────────

SQL_OVERALL = """
    SELECT
        COUNT(*)                                           AS total,
        SUM(passed)                                        AS n_pass,
        COUNT(*) - SUM(passed)                             AS n_fail,
        ROUND(100.0 * SUM(passed) / COUNT(*), 1)          AS pass_pct,
        ROUND(AVG(CASE WHEN passed=1 THEN efficiency END), 4) AS avg_eff_pass,
        ROUND(AVG(steps_taken), 1)                         AS avg_steps,
        SUM(collisions)                                    AS total_collisions
    FROM runs WHERE run_id = ?
"""

SQL_BY_BEHAVIOR = """
    SELECT
        behavior,
        COUNT(*)                                           AS runs,
        SUM(passed)                                        AS n_pass,
        ROUND(100.0 * SUM(passed) / COUNT(*), 1)          AS pass_pct,
        ROUND(AVG(CASE WHEN passed=1 THEN efficiency END), 3) AS avg_eff,
        ROUND(AVG(steps_taken), 1)                         AS avg_steps
    FROM runs WHERE run_id = ?
    GROUP BY behavior
    ORDER BY behavior
"""

SQL_BY_TYPE = """
    SELECT
        scenario_type,
        COUNT(*)                                           AS runs,
        SUM(passed)                                        AS n_pass,
        ROUND(100.0 * SUM(passed) / COUNT(*), 1)          AS pass_pct
    FROM runs WHERE run_id = ?
    GROUP BY scenario_type
    ORDER BY scenario_type
"""

SQL_FAILURES = """
    SELECT
        COALESCE(failure_reason, 'UNKNOWN')               AS reason,
        COUNT(*)                                           AS cnt,
        ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 1) AS pct
    FROM runs
    WHERE run_id = ? AND passed = 0
    GROUP BY failure_reason
    ORDER BY cnt DESC
"""

SQL_SCENARIOS = """
    SELECT
        scenario_id, behavior, passed, steps_taken,
        efficiency, failure_reason, expected_result,
        obstacle_count, grid_width, grid_height
    FROM runs
    WHERE run_id = ?
    ORDER BY id
"""

SQL_TREND = """
    SELECT
        run_id,
        timestamp,
        COUNT(*)                                           AS total,
        SUM(passed)                                        AS n_pass,
        ROUND(100.0 * SUM(passed) / COUNT(*), 1)          AS pass_pct
    FROM runs
    GROUP BY run_id
    ORDER BY MIN(id) DESC
    LIMIT 10
"""


# ── Report sections ────────────────────────────────────────────────────────────

def section_overall(conn, run_id):
    row = conn.execute(SQL_OVERALL, (run_id,)).fetchone()
    if not row:
        print("  No data for this run.")
        return

    total, n_pass, n_fail, pass_pct, avg_eff, avg_steps, total_coll = row

    ts_row = conn.execute(
        "SELECT timestamp FROM runs WHERE run_id=? LIMIT 1", (run_id,)
    ).fetchone()

    print(f"\n{_BOLD}  OVERALL PERFORMANCE{_RESET}   [run: {run_id}]")
    if ts_row:
        print(f"  Recorded : {ts_row[0][:19]}")
    _sep()
    print(f"  Total scenarios  : {total}")
    print(f"  Passed           : {_GREEN}{n_pass}{_RESET}  ({pass_pct}%)")
    print(f"  Failed           : {_RED}{n_fail}{_RESET}")
    print(f"  Avg efficiency†  : {_eff(avg_eff)}")
    print(f"  Avg steps taken  : {avg_steps or 'N/A'}")
    print(f"  Total collisions : {total_coll}")
    print(f"  {_DIM}† efficiency = optimal_steps / actual_steps (1.000 = perfect){_RESET}")


def section_by_behavior(conn, run_id):
    rows = conn.execute(SQL_BY_BEHAVIOR, (run_id,)).fetchall()
    if not rows:
        return
    print(f"\n{_BOLD}  RESULTS BY BEHAVIOR{_RESET}")
    _sep()
    print(f"  {'Behavior':<12} {'Runs':>5} {'Pass':>5} {'Pass%':>7} "
          f"{'Avg Eff':>9} {'Avg Steps':>10}")
    _sep()
    for r in rows:
        beh, runs, n_pass, pct, eff, steps = r
        print(f"  {beh:<12} {runs:>5} {n_pass:>5} {pct:>6}% "
              f"{_eff(eff):>9} {str(steps or 'N/A'):>10}")


def section_by_type(conn, run_id):
    rows = conn.execute(SQL_BY_TYPE, (run_id,)).fetchall()
    if not rows:
        return
    print(f"\n{_BOLD}  RESULTS BY SCENARIO TYPE{_RESET}")
    _sep()
    print(f"  {'Scenario Type':<20} {'Runs':>5} {'Pass':>5} {'Pass%':>7}")
    _sep()
    for r in rows:
        stype, runs, n_pass, pct = r
        print(f"  {stype:<20} {runs:>5} {n_pass:>5} {pct:>6}%")


def section_failures(conn, run_id):
    rows = conn.execute(SQL_FAILURES, (run_id,)).fetchall()
    if not rows:
        print(f"\n{_BOLD}  FAILURE ANALYSIS{_RESET}")
        _sep()
        print(f"  {_GREEN}No failures recorded.{_RESET}")
        return
    print(f"\n{_BOLD}  FAILURE ANALYSIS{_RESET}")
    _sep()
    print(f"  {'Failure Reason':<30} {'Count':>6} {'% of Fails':>11}")
    _sep()
    for r in rows:
        reason, cnt, pct = r
        print(f"  {reason:<30} {cnt:>6} {pct:>10}%")


def section_scenarios(conn, run_id):
    rows = conn.execute(SQL_SCENARIOS, (run_id,)).fetchall()
    if not rows:
        return
    print(f"\n{_BOLD}  SCENARIO-LEVEL RESULTS{_RESET}")
    _sep()
    print(f"  {'Scenario':<36} {'Behavior':<10} {'Result':<6} "
          f"{'Steps':>6} {'Eff':>7}  {'Exp':>4}  {'✓?':>2}")
    _sep()
    for r in rows:
        sid, beh, passed, steps, eff, reason, expected, obs, gw, gh = r
        result_str   = "PASS" if passed else "FAIL"
        expected_str = expected or "?"
        match_sym    = (f"{_GREEN}✓{_RESET}" if result_str == expected_str
                        else f"{_RED}✗{_RESET}")
        tag          = _colored_result(passed)
        short_sid    = (sid[:34] + "..") if len(sid) > 36 else sid
        eff_str      = f"{eff:.3f}" if eff else "  N/A"
        print(f"  {short_sid:<36} {beh:<10} {tag:<6} "
              f"{steps or 0:>6} {eff_str:>7}  {expected_str:>4}  {match_sym}")


def section_trend(conn):
    rows = conn.execute(SQL_TREND).fetchall()
    if not rows or len(rows) < 2:
        return
    print(f"\n{_BOLD}  HISTORICAL TREND (last {len(rows)} runs){_RESET}")
    _sep()
    print(f"  {'Run ID':<12} {'Timestamp':<20} {'Total':>6} "
          f"{'Pass':>5} {'Pass%':>7}")
    _sep()
    for r in rows:
        run_id, ts, total, n_pass, pct = r
        print(f"  {run_id:<12} {str(ts[:19]):<20} {total:>6} {n_pass:>5} {pct:>6}%")


# ── Main ───────────────────────────────────────────────────────────────────────

def get_latest_run(conn) -> str | None:
    row = conn.execute(
        "SELECT run_id FROM runs ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return row[0] if row else None


def get_all_runs(conn) -> list[str]:
    rows = conn.execute(
        "SELECT run_id FROM runs GROUP BY run_id ORDER BY MIN(id)"
    ).fetchall()
    return [r[0] for r in rows]


def print_banner():
    _sep("═")
    print(f"{_BOLD}  AUTONOMOUS AGENT SIMULATION — EVALUATION REPORT{_RESET}")
    _sep("═")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Simulation evaluation report")
    p.add_argument("run_id",  nargs="?",    help="Run ID to report on (default: latest)")
    p.add_argument("--all",   action="store_true", help="Report all runs")
    p.add_argument("--db",    default=str(DEFAULT_DB), help="SQLite database path")
    p.add_argument("--trend", action="store_true",     help="Show historical trend")
    return p.parse_args()


def main() -> int:
    args    = parse_args()
    db_path = Path(args.db)

    if not db_path.exists():
        print(f"[ERROR] Database not found: {db_path}")
        print("        Run 'python3 runner/test_runner.py' first.")
        return 1

    conn = sqlite3.connect(str(db_path))
    print_banner()

    if args.all:
        run_ids = get_all_runs(conn)
        if not run_ids:
            print("[ERROR] No runs found in database.")
            return 1
    elif args.run_id:
        run_ids = [args.run_id]
    else:
        latest = get_latest_run(conn)
        if not latest:
            print("[ERROR] No runs found in database.")
            return 1
        run_ids = [latest]

    for run_id in run_ids:
        section_overall(conn, run_id)
        section_by_behavior(conn, run_id)
        section_by_type(conn, run_id)
        section_failures(conn, run_id)
        section_scenarios(conn, run_id)
        if args.trend or args.all:
            section_trend(conn)
        _sep("═")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
