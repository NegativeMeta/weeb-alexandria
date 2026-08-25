"""Weeb Alexandria: unified AnimaDex + tag-library MCP facade."""
from __future__ import annotations

import json
import os
import sqlite3
import urllib.parse
import urllib.request
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

ROOT = os.path.dirname(os.path.abspath(__file__))
TAGLIB_DB = os.path.abspath(os.environ.get(
    "TAGLIB_DB",
    os.path.join(ROOT, "..", "tag_library.db"),
))
ANIMADEX_BASE_URL = os.environ.get(
    "ANIMADEX_BASE_URL", "http://127.0.0.1:5000"
).rstrip("/")

mcp = FastMCP("Weeb Alexandria")


def _db() -> sqlite3.Connection:
    con = sqlite3.connect(TAGLIB_DB)
    con.row_factory = sqlite3.Row
    return con


def _api_get(path: str, params: Optional[dict[str, Any]] = None) -> dict:
    url = ANIMADEX_BASE_URL + path
    clean = {k: v for k, v in (params or {}).items() if v is not None}
    if clean:
        url += "?" + urllib.parse.urlencode(clean, doseq=True)
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _absolute(url: str) -> str:
    if url.startswith(("http://", "https://")):
        return url
    return ANIMADEX_BASE_URL + url


def _local_characters(con: sqlite3.Connection, query: str = "",
                      copyright: Optional[str] = None,
                      hair_color: Optional[str] = None,
                      hair_length: Optional[str] = None,
                      eye_color: Optional[str] = None,
                      gender: Optional[str] = None,
                      sort: str = "count", limit: int = 100) -> list[dict]:
    """Busca personajes en las tablas migradas de AnimaDex."""
    clauses = []
    params: list[Any] = []
    if query:
        clauses.append("(c.name_lower LIKE ? OR c.character LIKE ? OR c.trigger LIKE ? OR c.core_tags LIKE ?)")
        needle = f"%{query.lower()}%"
        params.extend([needle, needle, needle, needle])
    for value, column in ((copyright, "c.copyright"), (gender, "t.value")):
        if value:
            if column == "t.value":
                clauses.append("EXISTS (SELECT 1 FROM animadex_character_traits tx WHERE tx.character=c.character AND tx.facet='gender' AND tx.value=?)")
                params.append(value)
            else:
                clauses.append(f"{column} LIKE ?")
                params.append(f"%{value}%")
    for value, facet in ((hair_color, "hair_color"), (hair_length, "hair_length"), (eye_color, "eye_color")):
        if value:
            clauses.append("EXISTS (SELECT 1 FROM animadex_character_traits tx WHERE tx.character=c.character AND tx.facet=? AND (tx.value=? OR tx.label LIKE ?))")
            params.extend([facet, value, f"%{value}%"])
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    order = "c.name_lower" if sort == "name" else "RANDOM()" if sort == "random" else "c.count DESC, c.name_lower"
    params.append(max(1, min(int(limit), 100)))
    rows = con.execute(f"""
        SELECT c.character,c.name,c.copyright,c.trigger,c.core_tags,c.count,c.url
        FROM animadex_characters c {where} ORDER BY {order} LIMIT ?
    """, params).fetchall()
    out=[]
    for row in rows:
        item=dict(row)
        item["slug"] = item.pop("character")
        item["tags"] = item.pop("core_tags").split(", ") if item.get("core_tags") else []
        item["traits"] = [dict(t) for t in con.execute(
            "SELECT facet,value,label FROM animadex_character_traits WHERE character=? ORDER BY facet,value",
            (item["slug"],)).fetchall()]
        out.append(item)
    return out


def _local_artists(con: sqlite3.Connection, query: str = "", sort: str = "count", limit: int = 100) -> list[dict]:
    needle=f"%{query.lower()}%"
    order="a.name_lower" if sort == "name" else "RANDOM()" if sort == "random" else "a.count DESC, a.name_lower"
    rows=con.execute(f"SELECT artist,name,trigger,count,score,url FROM animadex_artists a WHERE (?='' OR a.name_lower LIKE ? OR a.artist LIKE ? OR a.trigger LIKE ?) ORDER BY {order} LIMIT ?",(query,needle,needle,needle,max(1,min(int(limit),100)))).fetchall()
    return [dict(row) for row in rows]


def _local_copyrights(con: sqlite3.Connection, query: str = "", limit: int = 100) -> list[dict]:
    needle=f"%{query.lower()}%"
    rows=con.execute("SELECT copyright AS name, COUNT(*) AS character_count, SUM(count) AS post_count FROM animadex_characters WHERE (?='' OR lower(copyright) LIKE ? OR lower(copyright_name) LIKE ?) GROUP BY copyright,copyright_name ORDER BY post_count DESC LIMIT ?",(query,needle,needle,max(1,min(int(limit),100)))).fetchall()
    return [dict(row) for row in rows]


def _tag_rows(con: sqlite3.Connection, query: str,
              category: Optional[str], limit: int) -> list[dict]:
    limit = max(1, min(int(limit), 100))
    sql = (
        "SELECT name, category_name, post_count, site, aliases, nsfw "
        "FROM tags WHERE name LIKE ?"
    )
    params: list[Any] = [f"%{query}%"]
    if category:
        sql += " AND category_name = ?"
        params.append(category)
    sql += " ORDER BY post_count DESC NULLS LAST LIMIT ?"
    params.append(limit)
    rows = con.execute(sql, params).fetchall()
    merged: dict[str, dict] = {}
    for row in rows:
        item = merged.setdefault(row["name"], {
            "name": row["name"],
            "category": row["category_name"],
            "post_count": row["post_count"],
            "sites": [],
            "aliases": row["aliases"] or "",
            "nsfw": False,
        })
        item["sites"].append(row["site"])
        item["nsfw"] = item["nsfw"] or bool(row["nsfw"])
    return list(merged.values())


@mcp.tool()
def search_knowledge(query: str, category: Optional[str] = None,
                     limit: int = 25) -> dict:
    """Busca tags, personajes, artistas y franquicias en la base unificada."""
    result: dict[str, Any] = {"query": query, "tag_library": {}, "animadex": {}}
    try:
        con = _db()
        try:
            result["tag_library"] = {"results": _tag_rows(con, query, category, limit)}
            result["animadex"] = {
                "characters": _local_characters(con, query, limit=limit),
                "artists": _local_artists(con, query, limit=limit),
                "copyrights": _local_copyrights(con, query, limit=limit),
            }
        finally:
            con.close()
    except Exception as exc:
        result["error"] = str(exc)
    return result


@mcp.tool()
def get_tag_knowledge(tag: str, include_relations: bool = True,
                       limit: int = 50) -> dict:
    """Devuelve la ficha combinada de una tag: definiciones, fuentes,
    aliases, implicaciones, categoría, frecuencia y estado NSFW.
    """
    con = _db()
    try:
        tags = [dict(row) for row in con.execute(
            "SELECT site, name, category_name, post_count, aliases, nsfw "
            "FROM tags WHERE name = ? ORDER BY post_count DESC", (tag,)
        )]
        definitions = [dict(row) for row in con.execute(
            "SELECT site, title, body, other_names, lang, post_count "
            "FROM wiki WHERE title = ? ORDER BY CASE lang WHEN 'en' THEN 0 ELSE 1 END, site",
            (tag,),
        )]
        result: dict[str, Any] = {
            "found": bool(tags or definitions),
            "tag": tag,
            "tags": tags,
            "definitions": definitions,
        }
        if include_relations:
            status = " AND status = 'active'"
            params = [tag, tag, max(1, min(int(limit), 200))]
            result["aliases"] = [dict(row) for row in con.execute(
                "SELECT antecedent_name, consequent_name, status, reason "
                "FROM tag_aliases WHERE (antecedent_name = ? OR consequent_name = ?)"
                + status + " ORDER BY antecedent_name, consequent_name LIMIT ?", params
            )]
            result["implications"] = [dict(row) for row in con.execute(
                "SELECT antecedent_name, consequent_name, status, reason "
                "FROM tag_implications WHERE (antecedent_name = ? OR consequent_name = ?)"
                + status + " ORDER BY antecedent_name, consequent_name LIMIT ?", params
            )]
        return result
    finally:
        con.close()


@mcp.tool()
def search_characters(q: str = "", copyright: Optional[str] = None,
                       hair_color: Optional[str] = None,
                       hair_length: Optional[str] = None,
                       eye_color: Optional[str] = None,
                       gender: Optional[str] = None,
                       sort: str = "count", page: int = 1) -> dict:
    """Busca personajes en las tablas AnimaDex migradas."""
    con = _db()
    try:
        all_rows = _local_characters(con, q, copyright, hair_color, hair_length,
                                     eye_color, gender, sort, 100)
        page = max(1, int(page))
        page_size = 72
        start = (page - 1) * page_size
        return {"total": len(all_rows), "page": page, "page_size": page_size,
                "pages": max(1, (len(all_rows) + page_size - 1) // page_size),
                "results": all_rows[start:start + page_size]}
    finally:
        con.close()


@mcp.tool()
def get_character(slug: str) -> dict:
    """Obtiene el registro completo de un personaje migrado de AnimaDex."""
    con = _db()
    try:
        rows = _local_characters(con, slug, limit=100)
        match = next((row for row in rows if row.get("slug") == slug), None)
        if not match:
            return {"found": False, "slug": slug,
                    "candidates": [row.get("slug") for row in rows[:10]]}
        match["loras"] = [dict(row) for row in con.execute(
            "SELECT model_id,name,url,thumb,published FROM animadex_loras WHERE character=? ORDER BY model_id",
            (slug,)).fetchall()]
        return {"found": True, **match}
    finally:
        con.close()


@mcp.tool()
def get_sources_status() -> dict:
    """Comprueba las fuentes locales de Weeb Alexandria."""
    con = _db()
    try:
        counts = {}
        for table in ("tags", "wiki", "tag_aliases", "tag_implications",
                      "animadex_characters", "animadex_character_traits",
                      "animadex_artists", "animadex_loras"):
            counts[table] = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        return {"name": "Weeb Alexandria", "db": TAGLIB_DB,
                "exists": os.path.exists(TAGLIB_DB), "counts": counts,
                "animadex_mode": "migrated_local_tables"}
    finally:
        con.close()


if __name__ == "__main__":
    mcp.run()
