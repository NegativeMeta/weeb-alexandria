"""
Fase 1 del enriquecimiento de gelbooru: cruce por nombre con definiciones
YA EXISTENTES (danbooru/e621, lang='en'). Para los tags de gelbooru que no
tienen wiki propio pero cuyo nombre coincide con una definicion EN real de
otro site, la copiamos como site='gelbooru' (fuente real, no sintetica).

NO inventa nada: solo reusa definiciones verificadas que ya estan en la DB.
"""

from __future__ import annotations

import os
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "tag_library.db")


def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    before = cur.execute("SELECT COUNT(*) FROM wiki WHERE site='gelbooru'").fetchone()[0]

    # Para cada tag de gelbooru sin wiki de gelbooru, busca la mejor def EN
    # existente (danbooru优先, luego combined/e621) por nombre.
    rows = cur.execute("""
        SELECT DISTINCT t.name
        FROM tags t
        WHERE t.site='gelbooru'
          AND NOT EXISTS (SELECT 1 FROM wiki w WHERE w.title=t.name AND w.site='gelbooru')
          AND EXISTS (SELECT 1 FROM wiki w2 WHERE w2.title=t.name AND w2.lang='en')
    """).fetchall()

    copied = 0
    for (name,) in rows:
        # toma la definicion EN de mayor prioridad (danbooru > combined > e621)
        defn = cur.execute("""
            SELECT site, body, other_names, category_name, post_count, lang
            FROM wiki
            WHERE title=? AND lang='en'
            ORDER BY CASE site WHEN 'danbooru' THEN 0 WHEN 'combined' THEN 1 ELSE 2 END
            LIMIT 1
        """, (name,)).fetchone()
        if not defn:
            continue
        site, body, on, cat, pc, lang = defn
        if not (body or "").strip():
            continue
        cur.execute(
            "INSERT OR REPLACE INTO wiki "
            "(site,title,body,other_names,category_name,post_count,lang) "
            "VALUES (?,?,?,?,?,?,?)",
            ("gelbooru", name, body, on, cat, pc, "en"),
        )
        copied += 1
    con.commit()
    after = cur.execute("SELECT COUNT(*) FROM wiki WHERE site='gelbooru'").fetchone()[0]
    con.close()
    print(f"gelbooru wiki antes={before} | copiadas por cruce={copied} | despues={after}")


if __name__ == "__main__":
    main()
