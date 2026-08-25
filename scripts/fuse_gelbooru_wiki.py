"""
Fusiona gelbooru_wiki.parquet (gravebloom/gelbooru_wiki) a la DB como
site='gelbooru' lang='en'. Cruza por title==name con los tags existentes.
INSERT OR REPLACE para no duplicar.
"""

from __future__ import annotations

import os
import sqlite3

import pyarrow.parquet as pq

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "tag_library.db")
PARQUET = os.path.join(ROOT, "raw", "gelbooru", "gelbooru_wiki.parquet")


def main():
    if not os.path.exists(PARQUET):
        raise SystemExit(f"Falta {PARQUET}")
    con = sqlite3.connect(DB)
    cur = con.cursor()
    before = cur.execute("SELECT COUNT(*) FROM wiki WHERE site='gelbooru'").fetchone()[0]

    t = pq.read_table(PARQUET)
    added = 0
    for i in range(t.num_rows):
        row = {c: t.column(c)[i].as_py() for c in t.schema.names}
        title = (row.get("title") or "").strip()
        content = (row.get("content") or "").strip()
        if not title:
            continue
        cur.execute(
            "INSERT OR REPLACE INTO wiki "
            "(site,title,body,other_names,category_name,post_count,lang) "
            "VALUES (?,?,?,?,?,?,?)",
            ("gelbooru", title, content, None,
             row.get("tag_type"), None, "en"),
        )
        added += 1
    con.commit()
    after = cur.execute("SELECT COUNT(*) FROM wiki WHERE site='gelbooru'").fetchone()[0]
    con.close()
    print(f"gelbooru wiki antes={before} | leidas={added} | despues={after}")


if __name__ == "__main__":
    main()
