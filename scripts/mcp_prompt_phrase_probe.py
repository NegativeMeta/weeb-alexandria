"""Probe how prompt-style phrases survive segmentation.

Real prompts are not one or two tag words: they are comma lists and sentences with
articles, prepositions and clothing/lighting/context wording. This probe measures,
per phrase, how many of the produced segments resolve to a real tag and whether the
caller gets any usable answer at all. Read-only.

    .venv/Scripts/python.exe scripts/mcp_prompt_phrase_probe.py --json reports/x.json
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

USEFUL_POSTS = 1000

PHRASES = [
    # --- Spanish, written the way a prompt is written
    "chica con kimono rojo sentada en la nieve, vista amplia",
    "gura de espaldas mirando el mar al atardecer",
    "dos chicas abrazadas en la cama con luz suave",
    "primer plano de cara con ahegao y lengua fuera",
    "cuerpo completo en la playa con traje de baño blanco",
    "chica gato con medias negras y falda corta",
    "escena de oficina con camisa blanca arremangada",
    "vista desde arriba de una chica acostada en sábanas",
    "retrato nocturno con luces de neón y lluvia",
    "chica pelirroja con gafas y suéter grande",
    "plano medio de espaldas mostrando la espalda y el culo",
    "kimono blanco con flores y paraguas bajo la lluvia",
    # --- English tag lists
    "1girl, kimono, sitting in snow, wide shot",
    "from behind, looking at viewer, beach, sunset",
    "two girls, hugging, bed, soft lighting",
    "close-up, ahegao, tongue out",
    "full body, swimsuit, beach, white bikini",
    "cat girl, black thighhighs, miniskirt",
    "office lady, white shirt, rolled-up sleeves",
    "from above, lying, bedsheet",
    "night, neon lights, rain, portrait",
    "red hair, glasses, oversized sweater",
    "from behind, bare back, ass",
    "white kimono, floral print, umbrella, rain",
    # --- canonical prompt block
    "1girl, solo, long hair, blue eyes, large breasts, looking at viewer, "
    "from side, indoors, morning light",
]


def resolve_posts(con, name: str | None) -> int:
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
    try:
        for phrase in PHRASES:
            library = server.search_knowledge(phrase)["tag_library"]
            mode = library.get("query_mode", "single")
            results = library.get("results") or []
            if mode == "multi_tag":
                parts = []
                for part in library.get("query_parts") or []:
                    top = (part.get("results") or [{}])[0]
                    posts = int(top.get("post_count") or 0)
                    parts.append({"segment": part["query"], "tag": top.get("name"),
                                  "posts": posts, "useful": posts >= USEFUL_POSTS})
            else:
                parts = []
                for row in results[:6]:
                    posts = int(row.get("post_count") or 0)
                    parts.append({"segment": row["name"], "tag": row["name"],
                                  "posts": posts, "useful": posts >= USEFUL_POSTS})
            usable = sum(1 for p in parts if p["useful"])
            coverage = round(usable / len(parts), 2) if parts else 0.0
            rows.append({"phrase": phrase, "mode": mode, "results": len(results),
                         "segments": parts, "usable": usable,
                         "coverage": coverage,
                         "translated_as": (library.get("query_translation") or {}).get(
                             "searched_as")})
            preview = ", ".join(f"{p['segment']}->{p['tag']}" for p in parts[:4])
            print(f"{mode:9} cov={coverage:4} {usable}/{len(parts)} "
                  f"{phrase[:52]:54} [{preview}]", flush=True)
    finally:
        con.close()

    total = len(rows)
    multi = [r for r in rows if r["mode"] == "multi_tag"]
    single = [r for r in rows if r["mode"] != "multi_tag"]
    segments = sum(len(r["segments"]) for r in rows)
    usable = sum(r["usable"] for r in rows)
    print(f"\nphrases {total} (multi_tag {len(multi)}, single {len(single)}) · "
          f"segments {segments} · useful {usable} "
          f"({round(100 * usable / segments, 1) if segments else 0}%)")
    bad = [r for r in rows if r["coverage"] < 0.6]
    print(f"phrases under 60% useful: {len(bad)}")
    for r in bad:
        print(f"  {r['coverage']:4} {r['phrase']}")

    if args.json:
        Path(args.json).write_text(json.dumps({
            "phrases": total, "multi_tag": len(multi), "single": len(single),
            "segments": segments, "useful": usable,
            "useful_rate": round(usable / segments, 3) if segments else 0,
            "cases": rows,
        }, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"written: {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
