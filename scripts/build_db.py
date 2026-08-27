"""
Tag Library - builder unificado.

Fuentes:
  raw/danbooru/danbooru_tags.csv     (tag, category, count, alias)  [danbooru]
  raw/danbooru/danbooru_wiki.jsonl   (title, body, ...)             [danbooru, EN]
  tags_enhanced.csv                  (name, cn_name, wiki, post_count,
                                      category, nsfw)               [danbooru+e621 combinado, CN]

Estrategia de fusion:
  - Una sola tabla `tags` y `wiki`, clave primaria (site, name).
  - danbooru se carga con site='danbooru' (tags + wiki EN).
  - El CSV combinado se carga con site='combined' (tags + wiki CN).
    Sus tags que ya existen en danbooru se tratan como refuerzo de
    post_count/definicion, no duplicado inutil.
  - Para el MCP, las tools buscan en TODOS los sites y priorizan la
    definicion en ingles (danbooru) cuando existe.

Uso:
  python build_db.py
"""

from __future__ import annotations

import csv
import json
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from weeb_alexandria_mcp.owned_schema import ensure_owned_schema  # noqa: E402

RAW = os.path.join(ROOT, "raw", "danbooru")
RAW_GEL = os.path.join(ROOT, "raw", "gelbooru")
DB = os.path.join(ROOT, "tag_library.db")

CSV_DANBOORU = os.path.join(RAW, "danbooru_tags.csv")
WIKI_DANBOORU = os.path.join(RAW, "danbooru_wiki.jsonl")
CSV_COMBINED = os.path.join(ROOT, "raw", "e621", "tags_enhanced.csv")
GELBOORU_JSONL = os.path.join(RAW_GEL, "gelbooru_tags.jsonl")

CAT_NAME = {
    "0": "general",
    "1": "artist",
    "3": "copyright",
    "4": "character",
    "5": "meta",
    "6": "alias",   # gelbooru: deprecated/alias tags
    "7": "meta",
}


def main():
    con = sqlite3.connect(DB)
    ensure_owned_schema(con)
    cur = con.cursor()
    cur.executescript(
        """
        DROP TABLE IF EXISTS tags;
        DROP TABLE IF EXISTS wiki;
        CREATE TABLE tags (
            site TEXT NOT NULL,
            name TEXT NOT NULL,
            category INTEGER,
            category_name TEXT,
            post_count INTEGER,
            aliases TEXT,
            nsfw INTEGER,
            PRIMARY KEY (site, name)
        );
        CREATE TABLE wiki (
            site TEXT NOT NULL,
            title TEXT NOT NULL,
            body TEXT,
            other_names TEXT,
            category_name TEXT,
            post_count INTEGER,
            lang TEXT,
            PRIMARY KEY (site, title)
        );
        CREATE INDEX IF NOT EXISTS idx_tags_name ON tags(name);
        CREATE INDEX IF NOT EXISTS idx_tags_cat ON tags(category_name);
        CREATE INDEX IF NOT EXISTS idx_wiki_title ON wiki(title);
        CREATE INDEX IF NOT EXISTS idx_wiki_body ON wiki(body);
        """
    )

    # ---------- 1) danbooru (tags + wiki EN) ----------
    n_tags = 0
    if os.path.exists(CSV_DANBOORU):
        with open(CSV_DANBOORU, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                cat = (row.get("category") or "").strip()
                name = (row.get("tag") or "").strip()
                if not name:
                    continue
                c = (row.get("count") or "").strip()
                cur.execute(
                    "INSERT OR REPLACE INTO tags "
                    "(site,name,category,category_name,post_count,aliases) "
                    "VALUES (?,?,?,?,?,?)",
                    (
                        "danbooru", name,
                        int(cat) if cat.isdigit() else None,
                        CAT_NAME.get(cat, cat or None),
                        int(c) if c.isdigit() else None,
                        row.get("alias") or None,
                    ),
                )
                n_tags += 1

    n_wiki_en = 0
    if os.path.exists(WIKI_DANBOORU):
        with open(WIKI_DANBOORU, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                title = (d.get("title") or "").strip()
                if not title or d.get("is_deleted"):
                    continue
                on = d.get("other_names")
                if isinstance(on, (list, tuple)):
                    on = ", ".join(str(x) for x in on)
                cur.execute(
                    "INSERT OR REPLACE INTO wiki "
                    "(site,title,body,other_names,category_name,post_count,lang) "
                    "VALUES (?,?,?,?,?,?,?)",
                    ("danbooru", title, d.get("body"), on,
                     d.get("category_name"), d.get("post_count"), "en"),
                )
                n_wiki_en += 1

    # ---------- 2) CSV combinado danbooru+e621 (wiki CN) ----------
    n_comb = 0
    if os.path.exists(CSV_COMBINED):
        with open(CSV_COMBINED, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                name = (row.get("name") or "").strip()
                if not name:
                    continue
                cat = (row.get("category") or "").strip()
                c = (row.get("post_count") or "").strip()
                nsfw = (row.get("nsfw") or "").strip()
                wiki_body = (row.get("wiki") or "").strip() or None
                cur.execute(
                    "INSERT OR REPLACE INTO tags "
                    "(site,name,category,category_name,post_count,aliases,nsfw) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (
                        "combined", name,
                        int(cat) if cat.isdigit() else None,
                        CAT_NAME.get(cat, cat or None),
                        int(c) if c.isdigit() else None,
                        row.get("cn_name") or None,
                        int(nsfw) if nsfw.isdigit() else None,
                    ),
                )
                # wiki solo si hay body
                if wiki_body:
                    cur.execute(
                        "INSERT OR REPLACE INTO wiki "
                        "(site,title,body,other_names,category_name,"
                        "post_count,lang) "
                        "VALUES (?,?,?,?,?,?,?)",
                        ("combined", name, wiki_body, row.get("cn_name"),
                         CAT_NAME.get(cat, cat or None),
                         int(c) if c.isdigit() else None, "zh"),
                    )
                n_comb += 1

    # ---------- 3) gelbooru (tags + post_count, sin definiciones) ----------
    n_gel = 0
    if os.path.exists(GELBOORU_JSONL):
        with open(GELBOORU_JSONL, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                name = (d.get("tag_name") or "").strip()
                if not name:
                    continue
                cat = str(d.get("category_id", "")).strip()
                pc = d.get("post_count") or 0
                c = str(pc) if isinstance(pc, int) else str(pc).strip()
                cur.execute(
                    "INSERT OR REPLACE INTO tags "
                    "(site,name,category,category_name,post_count) "
                    "VALUES (?,?,?,?,?)",
                    (
                        "gelbooru", name,
                        int(cat) if cat.isdigit() else None,
                        CAT_NAME.get(cat, cat or None),
                        int(c) if c.isdigit() else None,
                    ),
                )
                n_gel += 1

    con.commit()
    cur.execute("SELECT COUNT(*) FROM tags")
    total_tags = cur.fetchone()[0]
    cur.execute("SELECT site, COUNT(*) FROM tags GROUP BY site")
    by_site = dict(cur.fetchall())
    cur.execute("SELECT COUNT(*) FROM wiki")
    total_wiki = cur.fetchone()[0]
    cur.execute("SELECT lang, COUNT(*) FROM wiki GROUP BY lang")
    wiki_lang = dict(cur.fetchall())
    con.close()

    print(f"OK tags(total)={total_tags}  por site={by_site}")
    print(f"OK wiki(total)={total_wiki}  por lang={wiki_lang}")
    print(f"   (danbooru tags={n_tags}, wiki_en={n_wiki_en}; "
          f"combined={n_comb}; gelbooru={n_gel})")
    print(f"DB -> {DB}")


if __name__ == "__main__":
    main()
