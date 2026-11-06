"""Measure search_knowledge against a corpus of real prompts.

Real prompts are not tag lists: they are narrative prose ("Two girls in a nighttime
onsen, wildly fucked in mating press ..."). This probe reads a JSON corpus
([{"text": ...}, ...]) and reports, per prompt, whether the answer carries usable
segments and which words were dropped.

The corpus stays outside the repo (it is private, NSFW work); only aggregate numbers
are committed.

    .venv/Scripts/python.exe scripts/mcp_real_prompt_probe.py --corpus <path.json> \
        --json reports/mcp_real_prompt_probe.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("TAGLIB_DB", str(REPO_ROOT / "tag_library.db"))

import weeb_alexandria_mcp.server as server  # noqa: E402

USEFUL_POSTS = 1000
# The corpus is private work: the committed report carries hashes, not prompt text.
INCLUDE_TEXT = False


def measure(prompt: str) -> dict:
    started = time.perf_counter()
    library = server.search_knowledge(prompt)["tag_library"]
    elapsed = time.perf_counter() - started
    mode = library.get("query_mode", "single")
    parts = []
    for part in library.get("query_parts") or []:
        top = (part.get("results") or [{}])[0]
        parts.append({"query": part.get("query"), "tag": top.get("name"),
                      "posts": int(top.get("post_count") or 0)})
    if not parts:
        for row in (library.get("results") or [])[:8]:
            parts.append({"query": row.get("name"), "tag": row.get("name"),
                          "posts": int(row.get("post_count") or 0)})

    useful = [p for p in parts if p["posts"] >= USEFUL_POSTS]
    return {
        "prompt_sha1": hashlib.sha1(prompt.encode("utf-8")).hexdigest()[:12],
        "prompt": prompt[:160] if INCLUDE_TEXT else None,
        "words": len(prompt.split()),
        "mode": mode,
        "segments": len(parts),
        "useful": len(useful),
        "best_posts": max((p["posts"] for p in parts), default=0),
        "untranslated": (library.get("query_translation") or {}).get("untranslated") or [],
        "seconds": round(elapsed, 2),
        "tags": [p["tag"] for p in parts[:8]],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True, help="JSON list of {text: ...} or [str]")
    ap.add_argument("--json", default=None)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--include-text", action="store_true",
                    help="keep prompt text in the report (do not commit that output)")
    ap.add_argument("--budget", type=float, default=8.0, help="seconds per prompt")
    args = ap.parse_args(argv)

    global INCLUDE_TEXT
    INCLUDE_TEXT = args.include_text

    raw = json.loads(Path(args.corpus).read_text(encoding="utf-8"))
    prompts = [item["text"] if isinstance(item, dict) else item for item in raw]
    if args.limit:
        prompts = prompts[: args.limit]

    rows = []
    print(f"corpus: {len(prompts)} prompts\n")
    for prompt in prompts:
        row = measure(prompt)
        rows.append(row)
        flag = "ok " if row["useful"] else "MISS"
        print(f"{flag} mode={row['mode']:9} seg={row['segments']:2} "
              f"use={row['useful']:2} best={row['best_posts']:>8} "
              f"{row['seconds']:5.1f}s  {row['prompt_sha1']} "
              f"{row['tags'][:3]}", flush=True)

    total = len(rows)
    with_segments = sum(1 for r in rows if r["segments"])
    useful = sum(1 for r in rows if r["useful"])
    segments = sum(r["segments"] for r in rows)
    useful_segments = sum(r["useful"] for r in rows)
    slow = [r for r in rows if r["seconds"] > args.budget]
    dropped: dict[str, int] = {}
    for row in rows:
        for word in row["untranslated"]:
            dropped[word] = dropped.get(word, 0) + 1

    print(f"\nprompts {total} · with segments {with_segments} ({with_segments / total:.0%})"
          f" · with a usable tag {useful} ({useful / total:.0%})")
    print(f"segments {segments} · useful {useful_segments} "
          f"({useful_segments / segments:.0%} of segments)")
    print(f"p50 latency {statistics.median(r['seconds'] for r in rows):.2f}s"
          f" · p95 {sorted(r['seconds'] for r in rows)[max(0, int(0.95 * total) - 1)]:.2f}s"
          f" · over budget {len(slow)}")
    print(f"dropped words: {sorted(dropped.items(), key=lambda kv: -kv[1])[:12]}")

    if args.json:
        Path(args.json).write_text(json.dumps({
            "prompts": total, "with_segments": with_segments, "useful": useful,
            "segments": segments, "useful_segments": useful_segments,
            "useful_prompt_rate": round(useful / total, 3),
            "useful_segment_rate": round(useful_segments / segments, 3) if segments else 0,
            "p50_seconds": round(statistics.median(r["seconds"] for r in rows), 2),
            "over_budget": len(slow),
            "dropped_words": sorted(dropped.items(), key=lambda kv: -kv[1])[:20],
            "cases": rows,
        }, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"written: {args.json}")
    return 0 if not slow else 1


if __name__ == "__main__":
    sys.exit(main())
