"""Guard the payload size of every MCP answer.

A tool answer lands in the calling model's context, so a fat payload is a real defect:
`search_characters(scope="all")` returned 94 KB (~23 500 tokens) before this gate
existed. Each case has a byte budget; exceeding it fails the run.

    .venv/Scripts/python.exe scripts/mcp_payload_budget.py --json reports/mcp_payload_budget.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("TAGLIB_DB", str(REPO_ROOT / "tag_library.db"))

import weeb_alexandria_mcp.server as server  # noqa: E402

KB = 1024

CASES = [
    ("search_knowledge(limit=25)", 12 * KB,
     lambda: server.search_knowledge("1girl, solo, long hair, blue eyes, large breasts")),
    ("search_knowledge(prompt ES)", 12 * KB,
     lambda: server.search_knowledge("chica con kimono rojo sentada en la nieve, vista amplia")),
    ("search_knowledge(prose)", 20 * KB,
     lambda: server.search_knowledge(
         "Two girls in a nighttime onsen, wildly fucked in mating press by two men, "
         "steam rising, cinematic lighting, wet skin, from behind, wide shot")),
    ("get_knowledge(+relations)", 20 * KB,
     lambda: server.get_knowledge("large_breasts", include_relations=True)),
    ("get_knowledge(deep)", 30 * KB,
     lambda: server.get_knowledge("hatsune_miku", include_relations=True, limit=100)),
    ("resolve_character", 10 * KB,
     lambda: server.resolve_character("Anya Forger")),
    ("search_characters(default)", 30 * KB,
     lambda: server.search_characters(hair_color="white", scope="all")),
    ("search_characters(page)", 30 * KB,
     lambda: server.search_characters(gender="female", scope="all", page=2)),
    ("get_character(card)", 20 * KB,
     lambda: server.get_character("hatsune_miku")),
    ("get_character(+evidence)", 40 * KB,
     lambda: server.get_character("hatsune_miku", include_evidence=True)),
    ("get_sources_status", 6 * KB,
     lambda: server.get_sources_status()),
]


def size(payload: dict) -> int:
    return len(json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)

    rows, failures = [], 0
    for name, budget, call in CASES:
        try:
            payload = call()
            measured = size(payload)
            error = None
        except Exception as exc:  # noqa: BLE001 - a crash is also a failure to report
            measured, error = 0, str(exc)
        ok = error is None and measured <= budget
        failures += 0 if ok else 1
        rows.append({"case": name, "bytes": measured, "budget": budget,
                     "tokens_est": measured // 4, "ok": ok, "error": error})
        state = "ok  " if ok else "OVER"
        print(f"{state} {measured:>7,} B / {budget:>7,} B  ~{measured // 4:>6,} tok  {name}"
              + (f"  ERROR: {error}" if error else ""), flush=True)

    biggest = max(rows, key=lambda row: row["bytes"])
    print(f"\ncases {len(rows)} · over budget {failures} · biggest {biggest['case']} "
          f"{biggest['bytes']:,} B (~{biggest['tokens_est']:,} tokens)")

    if args.json:
        Path(args.json).write_text(json.dumps({
            "cases": rows, "over_budget": failures,
            "biggest": {"case": biggest["case"], "bytes": biggest["bytes"]},
        }, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"written: {args.json}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
