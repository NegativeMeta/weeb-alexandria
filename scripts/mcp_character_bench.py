"""Regression bench for the character-resolution surface.

Runs ``resolve_character`` and ``get_character`` over a fixed list of popular
characters in their colloquial spelling and compares the recommendation with the
tag the library actually holds. Exit code 0 only when every character resolves to
its expected tag, so it gates changes to the resolver.

    .venv/Scripts/python.exe scripts/mcp_character_bench.py
    .venv/Scripts/python.exe scripts/mcp_character_bench.py --json reports/mcp_character_bench.json

`card` in the report is informational: most library characters are tag rows
without a reviewed appearance profile yet, so `found: false` is honest, not a bug.
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

# (colloquial spelling, expected canonical tag)
CASES = [
    ("Hatsune Miku", "hatsune_miku"),
    ("Gawr Gura", "gawr_gura"),
    ("Inugami Korone", "inugami_korone"),
    ("Usada Pekora", "usada_pekora"),
    ("Shirakami Fubuki", "shirakami_fubuki"),
    ("Mori Calliope", "mori_calliope"),
    ("Anya Forger", "anya_(spy_x_family)"),
    ("Yor Forger", "yor_briar"),
    ("Hu Tao", "hu_tao_(genshin_impact)"),
    ("Raiden Shogun", "raiden_shogun"),
    ("Furina", "furina_(genshin_impact)"),
    ("Nahida", "nahida_(genshin_impact)"),
    ("Marin Kitagawa", "kitagawa_marin"),
    ("Zero Two", "zero_two_(darling_in_the_franxx)"),
    ("Asuka Langley", "souryuu_asuka_langley"),
    ("Rem", "rem_(re:zero)"),
    ("Saber", "saber_(fate)"),
    ("Makima", "makima_(chainsaw_man)"),
    ("Tifa Lockhart", "tifa_lockhart"),
    ("2B", "2b_(nier:automata)"),
    ("Frieren", "frieren"),
    ("Bocchi", "bocchi_(bocchi_the_rock!)"),
    # Nickname = second word of the canonical tag; the prefix-only candidate scan
    # cannot see these, so they guard the suffix-recall step.
    ("miku", "hatsune_miku"),
    ("gura", "gawr_gura"),
    ("korone", "inugami_korone"),
    ("calliope", "mori_calliope"),
    ("pekora", "usada_pekora"),
]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=None, help="write the full report here")
    args = ap.parse_args(argv)

    rows = []
    failures = []
    for display, expected in CASES:
        t0 = time.perf_counter()
        result = server.resolve_character(display)
        elapsed = time.perf_counter() - t0
        card = server.get_character(display)
        got = result.get("recommended_tag")
        ok = got == expected
        rows.append({
            "character": display,
            "expected": expected,
            "recommended_tag": got,
            "ok": ok,
            "ambiguous": result.get("ambiguous"),
            "match_type": (result.get("recommendation") or {}).get("match_type"),
            "score": (result.get("recommendation") or {}).get("score"),
            "resolve_seconds": round(elapsed, 2),
            "card_found": card.get("found"),
            "card_features": sum(len(p.get("features") or [])
                                 for p in (card.get("profiles") or [])),
        })
        if not ok:
            failures.append(display)
        print(f"{'ok  ' if ok else 'FAIL'} {display:18} {str(got):36} "
              f"{elapsed:5.2f}s card={card.get('found')}", flush=True)

    total = len(rows)
    print(f"\nresolved {total - len(failures)}/{total}"
          + (f" — failing: {', '.join(failures)}" if failures else ""))
    if args.json:
        Path(args.json).write_text(
            json.dumps({"resolved": total - len(failures), "total": total,
                        "cases": rows}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"written: {args.json}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
