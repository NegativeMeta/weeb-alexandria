"""
Genera definiciones SINTETICAS (LLM via OpenRouter) para las tags de gelbooru
que aun no tienen definicion, priorizando por post_count DESC (mas importantes
primero). Va despacio (rate limit bajo) y es REANUDABLE (guarda progreso en
raw/gelbooru/llm_defs.jsonl).

IMPORTANTE: las definiciones son generadas por LLM, NO del booru. Se marcan
lang='llm' en la DB para no confundirlas con las reales.

Uso:
  OPENROUTER_API_KEY=sk-or-... python gen_gelbooru_llm_defs.py \
      --limit 5000 --min-posts 1000 --model meta-llama/llama-3.1-8b-instruct

Reanuda solo: los tags ya en llm_defs.jsonl se saltan.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "tag_library.db")
PROGRESS = os.path.join(ROOT, "raw", "gelbooru", "llm_defs.jsonl")

API_URL = "https://openrouter.ai/api/v1/chat/completions"
KEY = os.environ.get("OPENROUTER_API_KEY", "")
if not KEY:
    raise SystemExit("Falta OPENROUTER_API_KEY")


def ask_def(tag: str, model: str, key: str) -> str | None:
    prompt = (
        "You are writing concise entries for an anime/booru image-tag wiki, "
        "in the style of Danbooru's tag wiki. Define the tag below in ONE or "
        "TWO short sentences describing what the tag depicts. Be factual. "
        "If it is a posture/pose, say the body position. If it is an object, "
        "name it. No markdown, no bullet points.\n\n"
        f"Tag: {tag}"
    )
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 120,
        "temperature": 0.3,
    }
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost",
            "X-Title": "tag-library",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"  [LLM error para '{tag}']: {e}")
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=2000,
                    help="cuantas definiciones generar en esta corrida")
    ap.add_argument("--min-posts", type=int, default=0,
                    help="solo tags con post_count >= N")
    ap.add_argument("--model", default="meta-llama/llama-3.1-8b-instruct")
    ap.add_argument("--sleep", type=float, default=1.2,
                    help="segundos entre llamadas (lento=barato)")
    args = ap.parse_args()

    # tags ya procesados (reanudable)
    done = set()
    if os.path.exists(PROGRESS):
        with open(PROGRESS, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        done.add(json.loads(line)["tag"])
                    except Exception:
                        pass
    print(f"ya procesadas (reanudacion): {len(done)}")

    con = sqlite3.connect(DB, timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    cur = con.cursor()
    before = cur.execute(
        "SELECT COUNT(*) FROM wiki WHERE site='gelbooru' AND lang='llm'"
    ).fetchone()[0]

    # tags de gelbooru sin wiki, por post_count DESC
    rows = cur.execute("""
        SELECT t.name, t.post_count
        FROM tags t
        WHERE t.site='gelbooru'
          AND NOT EXISTS (SELECT 1 FROM wiki w WHERE w.title=t.name AND w.site='gelbooru')
        ORDER BY CAST(t.post_count AS INTEGER) DESC
        LIMIT ?
    """, (args.limit + len(done),)).fetchall()

    gen = 0
    with open(PROGRESS, "a", encoding="utf-8") as out:
        for name, pc in rows:
            if name in done:
                continue
            if args.min_posts and (int(pc or 0) < args.min_posts):
                continue
            d = ask_def(name, args.model, KEY)
            if not d:
                time.sleep(3)
                continue
            cur.execute(
                "INSERT OR REPLACE INTO wiki "
                "(site,title,body,other_names,category_name,post_count,lang) "
                "VALUES (?,?,?,?,?,?,?)",
                ("gelbooru", name, d, None, None, pc, "llm"),
            )
            out.write(json.dumps({"tag": name, "def": d, "posts": pc}) + "\n")
            out.flush()
            done.add(name)
            gen += 1
            if gen % 50 == 0:
                con.commit()
                print(f"  generadas {gen} (ultima: {name})")
            time.sleep(args.sleep)
    con.commit()
    after = cur.execute(
        "SELECT COUNT(*) FROM wiki WHERE site='gelbooru' AND lang='llm'"
    ).fetchone()[0]
    con.close()
    print(f"LLM gelbooru: antes={before} | nuevas={gen} | total llm={after}")


if __name__ == "__main__":
    main()
