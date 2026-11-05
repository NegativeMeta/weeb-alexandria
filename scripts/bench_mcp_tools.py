"""Latency guard for the Weeb Alexandria search paths.

Times the helpers behind ``search_knowledge`` in-process against the real
database and fails when a cold call blows the budget. The tool-surface cleanup
found a 20s+ query caused by an inner ORDER BY plus an outer ORDER BY inside
one CTE; this script keeps that regression from coming back unnoticed.

    .venv/Scripts/python.exe scripts/bench_mcp_tools.py
    .venv/Scripts/python.exe scripts/bench_mcp_tools.py --budget 2.0 --json

Exit code 0 when every measurement is within budget, 1 otherwise. Caches make
the second run of the same call look free, so the cold number is what gates.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("TAGLIB_DB", str(REPO_ROOT / "tag_library.db"))

import weeb_alexandria_mcp.server as server  # noqa: E402  (needs the env var)


def _time(fn):
    t0 = time.perf_counter()
    value = fn()
    return time.perf_counter() - t0, value


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=float, default=2.0, help="max cold seconds per call")
    ap.add_argument("--json", action="store_true", help="print machine-readable results")
    args = ap.parse_args(argv)

    con = sqlite3.connect(server.TAGLIB_DB)
    con.row_factory = sqlite3.Row
    cases = [
        ("fts_tag_rows(miku)", lambda: server._fts_tag_rows(con, "miku", None, 20)),
        ("tag_rows(hatsune miku)", lambda: server._tag_rows(con, "hatsune miku", None, 20)),
        ("tag_suggestions(anya forger)", lambda: server._tag_suggestions(con, "anya forger", "character", 5)),
        ("local_characters(hair_color=white)", lambda: server._local_characters(con, "", None, "white", None, None)),
        ("appearance_characters(white hair)", lambda: server._appearance_characters(con, "", {"hair_color": "white"})),
    ]
    results = []
    over = []
    try:
        for label, fn in cases:
            cold, value = _time(fn)
            warm, _ = _time(fn)
            count = len(value) if isinstance(value, list) else ("null" if value is None else 1)
            results.append({"case": label, "cold_s": round(cold, 3),
                            "warm_s": round(warm, 3), "rows": count})
            if cold > args.budget:
                over.append(label)
    finally:
        con.close()

    if args.json:
        print(json.dumps({"budget_s": args.budget, "results": results,
                          "over_budget": over}, indent=2))
    else:
        print(f"budget: {args.budget:.1f}s cold per call")
        for row in results:
            flag = "FAIL" if row["cold_s"] > args.budget else "ok"
            print(f"  {flag:4} {row['case']:38} cold={row['cold_s']:6.2f}s "
                  f"warm={row['warm_s']:6.2f}s rows={row['rows']}")
    if over:
        print(f"\nover budget: {', '.join(over)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
