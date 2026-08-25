"""
Descarga las wiki_pages de e621 (autenticado) a un JSONL, pagina por pagina.
NO escribe a la DB en vivo (evita 'database is locked' si otro proceso
lee/escribe la DB). Reanuda desde --start-page (por defecto 1).

Al terminar, fusiona con fuse_e621_wiki.py.

Auth: env E621_LOGIN / E621_API_KEY. Rate limit ~0.5s/pagina.
"""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.parse
import urllib.request
import argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DUMP = os.path.join(ROOT, "raw", "e621", "e621_wiki.jsonl")

LOGIN = os.environ.get("E621_LOGIN", "")
API_KEY = os.environ.get("E621_API_KEY", "")
if not (LOGIN and API_KEY):
    raise SystemExit("Falta E621_LOGIN / E621_API_KEY")

UA = "taglib/1.0 (johiny)"
BASE = "https://e621.net/wiki_pages.json"


def fetch_page(page: int) -> list:
    params = urllib.parse.urlencode({"page": page, "limit": 200})
    req = urllib.request.Request(
        f"{BASE}?{params}",
        headers={
            "User-Agent": UA,
            "Authorization": "Basic "
            + base64.b64encode(f"{LOGIN}:{API_KEY}".encode()).decode(),
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-page", type=int, default=1)
    ap.add_argument("--max-pages", type=int, default=0,
                    help="0 = hasta el final")
    args = ap.parse_args()

    os.makedirs(os.path.dirname(DUMP), exist_ok=True)
    mode = "a" if args.start_page > 1 else "w"
    with open(DUMP, mode, encoding="utf-8") as out:
        page = args.start_page
        total = 0
        while True:
            if args.max_pages and (page - args.start_page) >= args.max_pages:
                print(f"[page {page}] alcanzado max-pages -> fin")
                break
            try:
                rows = fetch_page(page)
            except Exception as e:
                print(f"[page {page}] error: {e}; reintento en 5s")
                time.sleep(5)
                continue
            if not rows:
                print(f"[page {page}] vacio -> fin")
                break
            for r in rows:
                if r.get("is_deleted"):
                    continue
                title = (r.get("title") or "").strip()
                if not title:
                    continue
                out.write(json.dumps(r, ensure_ascii=False) + "\n")
                total += 1
            out.flush()
            if page % 50 == 0:
                print(f"[page {page}] acumuladas {total} definiciones e621")
            page += 1
            time.sleep(0.5)
    print(f"e621 descarga terminada: {total} definiciones nuevas (desde page {args.start_page})")


if __name__ == "__main__":
    main()
