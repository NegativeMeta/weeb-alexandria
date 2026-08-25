"""
Fusiona wiki_pages.parquet (itterative/danbooru_wikis_full) a la DB.
Es un refuerzo de definiciones EN de danbooru (INSERT OR REPLACE, asi
las que ya existen se conservan y las nuevas se anaden).
"""

from __future__ import annotations

import os
import sqlite3

import pyarrow.parquet as pq

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "tag_library.db")
PARQUET = os.path.join(ROOT, "raw", "danbooru_wiki_extra", "wiki_pages.parquet")


def main():
    if not os.path.exists(PARQUET):
        raise SystemExit(f"Falta {PARQUET}")
    con = sqlite3.connect(DB)
    cur = con.cursor()
    before = cur.execute("SELECT COUNT(*) FROM wiki WHERE site='danbooru'").fetchone()[0]

    t = pq.read_table(PARQUET)
    added = 0
    for i in range(t.num_rows):
        row = {c: t.column(c)[i].as_py() for c in t.schema.names}
        title = (row.get("title") or "").strip()
        if not title or row.get("is_deleted"):
            continue
        on = row.get("other_names")
        if isinstance(on, (list, tuple)):
            on = ", ".join(str(x) for x in on)
        cur.execute(
            "INSERT OR REPLACE INTO wiki "
            "(site,title,body,other_names,category_name,post_count,lang) "
            "VALUES (?,?,?,?,?,?,?)",
            ("danbooru", title, row.get("body"), on,
             None, row.get("post_count"), "en"),
        )
        added += 1
    con.commit()
    after = cur.execute("SELECT COUNT(*) FROM wiki WHERE site='danbooru'").fetchone()[0]
    con.close()
    print(f"wiki danbooru antes={before} | leidas={added} | despues={after}")


if __name__ == "__main__":
    main()
