"""Consistency probe across the search surface.

For each case it asks three tools the same thing and compares the answers:

* ``search_knowledge(query)``        -> top tag row
* ``resolve_character(query)``       -> recommended canonical tag
* ``get_knowledge(tag)``             -> definitions the answer exposes

Reports two kinds of disagreement: a different tag, and a search answer with
negligible coverage where another tool knows the real tag. Read-only.

    .venv/Scripts/python.exe scripts/mcp_consistency_probe.py --json reports/x.json
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("TAGLIB_DB", str(REPO_ROOT / "tag_library.db"))

import weeb_alexandria_mcp.server as server  # noqa: E402

# Characters whose colloquial name is also a tag row, i.e. the dangerous ones.
CHARACTER_CASES = [
    ("Anya Forger", "anya_(spy_x_family)"),
    ("Yor Forger", "yor_briar"),
    ("Hu Tao", "hu_tao_(genshin_impact)"),
    ("Furina", "furina_(genshin_impact)"),
    ("Nahida", "nahida_(genshin_impact)"),
    ("Zero Two", "zero_two_(darling_in_the_franxx)"),
    ("Asuka Langley", "souryuu_asuka_langley"),
    ("Rem", "rem_(re:zero)"),
    ("Saber", "saber_(fate)"),
    ("Makima", "makima_(chainsaw_man)"),
    ("Bocchi", "bocchi_(bocchi_the_rock!)"),
    ("Hatsune Miku", "hatsune_miku"),
    ("Gawr Gura", "gawr_gura"),
    ("2B", "2b_(nier:automata)"),
    ("Raiden Shogun", "raiden_shogun"),
    ("Marin Kitagawa", "kitagawa_marin"),
    ("Tifa Lockhart", "tifa_lockhart"),
    ("Frieren", "frieren"),
    ("miku", "hatsune_miku"),
    ("gura", "gawr_gura"),
]

# Tags where the library holds several spellings and the top pick matters.
TAG_CASES = [
    ("blowjob", "fellatio"),
    ("titjob", "paizuri"),
    ("creampie", "cum_inside"),
    ("big tits", "large_breasts"),
    ("ahegao face", "ahegao"),
    ("facial cum", "facial"),
    ("mating", "mating_(animal)"),
    ("dog mounting", "bestiality"),
    ("censored penis", "censored_penis"),
    ("monster cock", "monster_cock"),
    ("pregnant belly", "pregnant_belly"),
    ("spread legs", "spread_legs"),
    ("tied up with rope", "bondage"),
    ("sexo oral", "oral"),
    ("tetas grandes", "large_breasts"),
]

THIN_POSTS = 1000


def post_count(con: sqlite3.Connection, name: str) -> int:
    row = con.execute("SELECT MAX(post_count) FROM tags WHERE name=?", (name,)).fetchone()
    return int(row[0] or 0) if row else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=None)
    ap.add_argument("--limit", type=int, default=5)
    args = ap.parse_args(argv)

    con = server._db()
    rows: list[dict] = []
    try:
        for kind, cases in (("character", CHARACTER_CASES), ("tag", TAG_CASES)):
            for query, expected in cases:
                search = server.search_knowledge(query, limit=args.limit)["tag_library"]
                top = (search.get("results") or [{}])[0]
                search_tag = top.get("name")
                search_posts = int(top.get("post_count") or 0)

                resolved = None
                resolved_posts = 0
                if kind == "character":
                    character = server.resolve_character(query)
                    resolved = character.get("recommended_tag")
                    resolved_posts = post_count(con, resolved) if resolved else 0

                definitions = len(server.get_knowledge(search_tag).get("definitions") or []) \
                    if search_tag else 0

                agree = (search_tag == resolved) if kind == "character" else None
                thin = 0 < search_posts < THIN_POSTS
                better_known = (bool(resolved) and resolved_posts >= THIN_POSTS and thin)
                rows.append({
                    "kind": kind,
                    "query": query,
                    "expected": expected,
                    "search_tag": search_tag,
                    "search_posts": search_posts,
                    "resolved_tag": resolved,
                    "resolved_posts": resolved_posts,
                    "agree": agree,
                    "search_is_thin": thin,
                    "resolver_knows_better": better_known,
                    "definitions": definitions,
                    "query_mode": search.get("query_mode", "single"),
                })
                flag = ""
                if better_known:
                    flag = "  <-- resolver knows better"
                elif agree is False:
                    flag = "  (different)"
                elif thin:
                    flag = "  <-- thin answer"
                print(f"{query:18} search={str(search_tag):34}{search_posts:>9}  "
                      f"resolve={str(resolved):30}{resolved_posts:>9}  "
                      f"defs={definitions}{flag}", flush=True)
    finally:
        con.close()

    characters = [r for r in rows if r["kind"] == "character"]
    tags = [r for r in rows if r["kind"] == "tag"]
    agree_n = sum(1 for r in characters if r["agree"])
    thin_n = sum(1 for r in rows if r["search_is_thin"])
    better = [r for r in rows if r["resolver_knows_better"]]
    expected_top1 = sum(1 for r in rows if r["search_tag"] == r["expected"])
    print(f"\ncharacters agree {agree_n}/{len(characters)} · "
          f"thin answers {thin_n} · resolver knows better {len(better)} · "
          f"expected top-1 {expected_top1}/{len(rows)}")
    if better:
        print("search answers below 1000 posts while a canonical tag exists: "
              + ", ".join(f"{r['query']}->{r['search_tag']} vs {r['resolved_tag']}"
                          for r in better))
    tag_thin = [r for r in tags if r["search_is_thin"]]
    if tag_thin:
        print("thin tag answers: " + ", ".join(f"{r['query']}->{r['search_tag']}"
                                              for r in tag_thin))

    if args.json:
        Path(args.json).write_text(json.dumps({
            "agreement": agree_n, "total": len(rows), "thin_answers": thin_n,
            "resolver_knows_better": len(better),
            "expected_top1": expected_top1, "cases": rows,
        }, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"written: {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
