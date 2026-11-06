"""Regression gate for ``search_knowledge``.

A golden set of queries with the answer the library must produce, plus the rules
the last three fixes introduced:

* no thin answers (top-1 below 1000 posts) unless the tag is documented by two or
  more wikis, i.e. a legitimate small tag spelled out by the user;
* multi-tag queries expose the umbrella tag in ``related_tags``;
* Spanish phrasing resolves through the curated map.

Exit code 0 only when every case passes, so it gates search-quality changes.

    .venv/Scripts/python.exe scripts/mcp_knowledge_bench.py
    .venv/Scripts/python.exe scripts/mcp_knowledge_bench.py --json reports/mcp_knowledge_bench.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("TAGLIB_DB", str(REPO_ROOT / "tag_library.db"))

import weeb_alexandria_mcp.server as server  # noqa: E402

THIN_POSTS = 1000

# group: "tag" = top-1 must be this tag; "umbrella" = tag appears in related_tags;
#        "parts" = multi-tag segments must be these; "empty" = no results expected.
CASES: list[dict] = [
    # --- characters whose bare name is itself a thin tag row (the resolver wins)
    {"q": "Anya Forger", "expect": "anya_(spy_x_family)", "group": "tag"},
    {"q": "Yor Forger", "expect": "yor_briar", "group": "tag"},
    {"q": "Furina", "expect": "furina_(genshin_impact)", "group": "tag"},
    {"q": "Nahida", "expect": "nahida_(genshin_impact)", "group": "tag"},
    {"q": "Zero Two", "expect": "zero_two_(darling_in_the_franxx)", "group": "tag"},
    {"q": "Asuka Langley", "expect": "souryuu_asuka_langley", "group": "tag"},
    {"q": "Rem", "expect": "rem_(re:zero)", "group": "tag"},
    {"q": "Makima", "expect": "makima_(chainsaw_man)", "group": "tag"},
    {"q": "Bocchi", "expect": "bocchi_(bocchi_the_rock!)", "group": "tag"},
    {"q": "Marin Kitagawa", "expect": "kitagawa_marin", "group": "tag"},
    {"q": "gura", "expect": "gawr_gura", "group": "tag"},
    {"q": "Hatsune Miku", "expect": "hatsune_miku", "group": "tag"},
    # --- English colloquial and canonical tags
    {"q": "blowjob", "expect": "blowjob", "group": "tag"},
    {"q": "handjob", "expect": "handjob", "group": "tag"},
    {"q": "cum inside", "expect": "cum_inside", "group": "tag"},
    {"q": "spread legs", "expect": "spread_legs", "group": "tag"},
    {"q": "mosaic censoring", "expect": "mosaic_censoring", "group": "tag"},
    {"q": "clothed sex", "expect": "clothed_sex", "group": "tag"},
    {"q": "tentacle sex", "expect": "tentacle_sex", "group": "tag"},
    {"q": "body writing", "expect": "body_writing", "group": "tag"},
    {"q": "pregnant belly", "expect": "pregnant_belly", "group": "tag"},
    {"q": "censored penis", "expect": "censored_penis", "group": "tag"},
    {"q": "monster cock", "expect": "monster_cock", "group": "tag"},
    {"q": "big tits", "expect": "large_breasts", "group": "tag"},
    {"q": "huge breasts", "expect": "huge_breasts", "group": "tag"},
    {"q": "blushing", "expect": "blushing", "group": "tag"},
    {"q": "saber", "expect": "saber_(fate)", "group": "tag"},
    {"q": "hu tao", "expect": "hu_tao_(genshin_impact)", "group": "tag"},
    {"q": "miku", "expect": "hatsune_miku", "group": "tag"},
    {"q": "2b", "expect": "2b_(nier:automata)", "group": "tag"},
    {"q": "creampie", "expect": "creampie", "group": "tag"},
    # --- alias stub, fragment, documented small tag
    {"q": "titjob", "expect": "paizuri", "group": "tag"},
    {"q": "ahegao face", "expect": "ahegao", "group": "tag"},
    {"q": "facial cum", "expect": "facial", "group": "tag"},
    {"q": "mating_(animal)", "expect": "mating_(animal)", "group": "tag"},
    # --- Spanish through the curated map
    {"q": "tetas grandes", "expect": "large_breasts", "group": "tag"},
    {"q": "sexo oral", "expect": "oral", "group": "tag"},
    {"q": "corrida en la cara", "expect": "facial", "group": "tag"},
    {"q": "atada con cuerdas", "expect": "bondage", "group": "tag"},
    {"q": "vendas en los ojos", "expect": "blindfold", "group": "tag"},
    {"q": "ropa mojada", "expect": "wet_clothes", "group": "tag"},
    {"q": "sexo", "expect": "sex", "group": "tag"},
    {"q": "mamada", "expect": "fellatio", "group": "tag"},
    {"q": "piernas abiertas", "expect": "spread_legs", "group": "tag"},
    {"q": "embarazada", "expect": "pregnant", "group": "tag"},
    {"q": "colegiala", "expect": "school_uniform", "group": "tag"},
    {"q": "sin censura", "expect": "uncensored", "group": "tag"},
    # --- umbrella concept for a multi-tag query
    {"q": "dog mounting", "expect": "bestiality", "group": "umbrella"},
    {"q": "group sex threesome", "expect": "fivesome", "group": "umbrella"},
    {"q": "lactation milking", "expect": "projectile_lactation", "group": "umbrella"},
    {"q": "blindfold leash", "expect": "reins", "group": "umbrella"},
    # --- segment hygiene
    {"q": "tied up with rope", "expect": ["tied up", "rope"], "group": "parts"},
    # --- queries with no tag answer must stay empty, not guess
    {"q": "asdfqwer zxcvbn", "expect": None, "group": "empty"},
    {"q": "pene azul volador", "expect": None, "group": "empty"},
]


def post_count(con, name: str | None) -> int:
    if not name:
        return 0
    row = con.execute("SELECT MAX(post_count) FROM tags WHERE name=?", (name,)).fetchone()
    return int(row[0] or 0) if row else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)

    con = server._db()
    rows: list[dict] = []
    failures: list[str] = []
    thin: list[str] = []
    try:
        for case in CASES:
            query, expected, group = case["q"], case["expect"], case["group"]
            started = time.perf_counter()
            library = server.search_knowledge(query)["tag_library"]
            elapsed = time.perf_counter() - started
            results = library.get("results") or []
            top = results[0] if results else {}
            top_name = top.get("name")
            top_posts = int(top.get("post_count") or 0)
            related = [item["name"] for item in library.get("related_tags") or []]
            parts = [part["query"] for part in library.get("query_parts") or []]

            if group == "tag":
                ok = top_name == expected
                detail = f"top={top_name}"
            elif group == "umbrella":
                ok = expected in related
                detail = f"related={related}"
            elif group == "parts":
                ok = parts == expected
                detail = f"parts={parts}"
            else:  # empty
                ok = not results
                detail = f"top={top_name}"

            # A fragment answer is a failure even when the case "passes".
            if results and 0 < top_posts < THIN_POSTS:
                documented = server._tag_wiki_count(con, top_name) >= 2
                if not documented:
                    thin.append(f"{query}->{top_name} ({top_posts})")
                    ok = False

            rows.append({"query": query, "group": group, "expect": expected,
                         "top": top_name, "top_posts": top_posts,
                         "related": related, "parts": parts, "ok": ok,
                         "seconds": round(elapsed, 2)})
            if not ok:
                failures.append(f"{query} [{group}] {detail} expected={expected}")
            mark = "ok  " if ok else "FAIL"
            print(f"{mark} {group:8} {query:20} {str(top_name):34}{top_posts:>9} "
                  f"{elapsed:5.2f}s", flush=True)
    finally:
        con.close()

    total = len(rows)
    print(f"\npassed {total - len(failures)}/{total} · "
          f"accuracy {round(100 * (total - len(failures)) / total, 1)}%")
    if thin:
        print("thin answers (a fragment beat a real tag): " + ", ".join(thin))
    for failure in failures:
        print(f"  {failure}")
    if args.json:
        Path(args.json).write_text(json.dumps({
            "passed": total - len(failures), "total": total,
            "accuracy": round((total - len(failures)) / total, 3),
            "thin_answers": thin, "failures": failures, "cases": rows,
        }, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"written: {args.json}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
