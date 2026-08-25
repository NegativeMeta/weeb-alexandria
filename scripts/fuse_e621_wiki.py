"""
Fusiona raw/e621/e621_wiki.jsonl a la DB como site='e621' lang='en'.
Se corre una vez al terminar la descarga (o puntualmente). INSERT OR REPLACE.
"""

from __future__ import annotations

import json
import os
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "tag_library.db")
DUMP = os.path.join(ROOT, "raw", "e621", "e621_wiki.jsonl")


def main():
    if not os.path.exists(DUMP):
        raise SystemExit(f"Falta {DUMP}")
    con = sqlite3.connect(DB, timeout=60)
    con.execute("PRAGMA busy_timeout=60000")
    cur = con.cursor()
    before = cur.execute("SELECT COUNT(*) FROM wiki WHERE site='e621'").fetchone()[0]
    added = 0
    with open(DUMP, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            title = (r.get("title") or "").strip()
            if not title or r.get("is_deleted"):
                continue
            on = r.get("other_names")
            if isinstance(on, (list, tuple)):
                on = json.dumps(list(on))
            cur.execute(
                "INSERT OR REPLACE INTO wiki "
                "(site,title,body,other_names,category_name,post_count,lang) "
                "VALUES (?,?,?,?,?,?,?)",
                ("e621", title, r.get("body"), on, None, r.get("post_count"), "en"),
            )
            added += 1
        con.commit()
    after = cur.execute("SELECT COUNT(*) FROM wiki WHERE site='e621'").fetchone()[0]
    con.close()
    print(f"e621 wiki antes={before} | leidas={added} | despues={after}")


if __name__ == "__main__":
    main()
