"""Weeb Alexandria: unified AnimaDex + tag-library MCP facade."""
from __future__ import annotations

import json
import difflib
import math
import os
import re
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


def _normalize_tag(value: str) -> str:
    """Normalize human-written tag forms to the usual underscore form."""
    return "_".join(value.strip().lower().replace("-", "_").split())


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
    order_params: list[Any] = []
    normalized = _normalize_tag(query)
    if query:
        clauses.append("(c.name_lower LIKE ? OR c.character LIKE ? OR c.trigger LIKE ? OR c.core_tags LIKE ?)")
        needle = f"%{normalized}%"
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
    if sort == "name":
        order = "c.name_lower"
    elif sort == "random":
        order = "RANDOM()"
    elif normalized:
        order = "CASE WHEN lower(c.character)=? OR lower(c.name_lower)=? THEN 3 WHEN lower(c.character) LIKE ? OR lower(c.name_lower) LIKE ? THEN 2 ELSE 1 END DESC, c.count DESC, c.name_lower"
        order_params = [normalized, normalized, f"{normalized}_%", f"{normalized}_%"]
    else:
        order = "c.count DESC, c.name_lower"
    params = order_params + params
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
    normalized=query.strip().lower().replace(" ", "_")
    needle=f"%{normalized}%"
    if sort == "name":
        order="a.name_lower"
        order_params=[]
    elif sort == "random":
        order="RANDOM()"
        order_params=[]
    elif normalized:
        order="CASE WHEN lower(a.artist)=? OR lower(a.name_lower)=? THEN 3 WHEN lower(a.artist) LIKE ? OR lower(a.name_lower) LIKE ? THEN 2 ELSE 1 END DESC, a.count DESC, a.name_lower"
        order_params=[normalized,normalized,f"{normalized}_%",f"{normalized}_%"]
    else:
        order="a.count DESC, a.name_lower"
        order_params=[]
    params=[normalized,needle,needle,needle]+order_params+[max(1,min(int(limit),100))]
    rows=con.execute(f"SELECT artist,name,trigger,count,score,url FROM animadex_artists a WHERE (?='' OR a.name_lower LIKE ? OR a.artist LIKE ? OR a.trigger LIKE ?) ORDER BY {order} LIMIT ?",params).fetchall()
    return [dict(row) for row in rows]


def _local_copyrights(con: sqlite3.Connection, query: str = "", limit: int = 100) -> list[dict]:
    needle=f"%{query.lower()}%"
    rows=con.execute("SELECT copyright AS name, COUNT(*) AS character_count, SUM(count) AS post_count FROM animadex_characters WHERE (?='' OR lower(copyright) LIKE ? OR lower(copyright_name) LIKE ?) GROUP BY copyright,copyright_name ORDER BY post_count DESC LIMIT ?",(query,needle,needle,max(1,min(int(limit),100)))).fetchall()
    return [dict(row) for row in rows]


def _tag_rows(con: sqlite3.Connection, query: str,
              category: Optional[str], limit: int) -> list[dict]:
    limit = max(1, min(int(limit), 100))
    normalized = _normalize_tag(query)
    sql = (
        "SELECT name, category_name, post_count, site, aliases, nsfw, "
        "CASE WHEN lower(name)=? THEN 3 "
        "WHEN lower(name) LIKE ? THEN 2 ELSE 1 END AS relevance "
        "FROM tags WHERE lower(name) LIKE ?"
    )
    params: list[Any] = [normalized, f"{normalized}_%", f"%{normalized}%"]
    # Clients often call the general tag search with category="tag".
    # The database stores concrete categories (general, character, artist,
    # copyright, ...), so "tag" means all tag categories rather than a
    # literal category_name value.
    if category and category.lower() not in {"tag", "tags", "all"}:
        sql += " AND category_name = ?"
        params.append(category)
    sql += " ORDER BY relevance DESC, post_count DESC NULLS LAST LIMIT ?"
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
            "match_type": ("exact" if row["name"].lower() == query.strip().lower()
                           else "normalized" if row["name"].lower() == normalized
                           else "prefix" if row["name"].lower().startswith(f"{normalized}_")
                           else "partial"),
            "confidence": ("high" if row["relevance"] == 3
                           else "medium" if row["relevance"] == 2
                           else "low"),
        })
        item["sites"].append(row["site"])
        item["nsfw"] = item["nsfw"] or bool(row["nsfw"])
    return list(merged.values())


def _tag_suggestions(con: sqlite3.Connection, query: str,
                     category: Optional[str], limit: int) -> list[dict]:
    """Return likely tag names for a misspelled or non-canonical query."""
    normalized = _normalize_tag(query)
    if not normalized:
        return []
    tokens = [token for token in normalized.split("_") if len(token) >= 3]
    tokens = tokens or [normalized]
    token_where = " OR ".join("lower(name) LIKE ?" for _ in tokens)
    length_where = "(substr(lower(name), 1, 1) = ? AND length(name) BETWEEN ? AND ?)"
    where = f"({token_where} OR {length_where})"
    params: list[Any] = [f"%{token}%" for token in tokens]
    params.extend([normalized[0], max(1, len(normalized) - 3), len(normalized) + 8])
    if category and category.lower() not in {"tag", "tags", "all"}:
        where += " AND category_name = ?"
        params.append(category)
    rows = con.execute(
        f"SELECT name, category_name, post_count, site, aliases, nsfw "
        f"FROM tags WHERE {where} ORDER BY post_count DESC NULLS LAST LIMIT 20000",
        params,
    ).fetchall()
    scored: dict[str, tuple[float, dict]] = {}
    for row in rows:
        name = row["name"]
        candidate = name.lower().replace("-", "_")
        candidate_tokens = [token for token in candidate.split("_") if token]
        token_score = sum(
            max(difflib.SequenceMatcher(None, token, other).ratio()
                for other in candidate_tokens)
            for token in tokens
        ) / len(tokens)
        score = 0.6 * token_score + 0.4 * difflib.SequenceMatcher(
            None, normalized, candidate
        ).ratio()
        exact_token_score = sum(token in candidate_tokens for token in tokens) / len(tokens)
        score += 0.25 * exact_token_score
        if row["category_name"] == "character":
            score += 0.08
            # When names are similarly close, prefer the established character
            # tag with meaningful coverage over a one-post coincidence.
            score += 0.03 * math.log10(1 + (row["post_count"] or 0))
        if score < 0.45:
            continue
        item = {
            "name": name,
            "category": row["category_name"],
            "post_count": row["post_count"],
            "site": row["site"],
            "match_type": "fuzzy",
            "confidence": "medium" if score >= 0.65 else "low",
        }
        previous = scored.get(name)
        if previous is None or score > previous[0]:
            scored[name] = (score, item)
    fuzzy = [item for _, item in sorted(
        scored.values(), key=lambda pair: (-pair[0], -(pair[1]["post_count"] or 0), pair[1]["name"])
    )[:max(1, min(int(limit), 25))]]
    return _alias_suggestions(con, query, limit) + fuzzy


def _resolve_canonical_tag(con: sqlite3.Connection, requested: str) -> tuple[str, Optional[dict]]:
    """Follow active aliases and wiki ``Use X instead`` redirects safely."""
    current = _normalize_tag(requested)
    first_resolution = None
    visited = set()
    for _ in range(5):
        if current in visited:
            break
        visited.add(current)
        alias = con.execute(
            "SELECT consequent_name FROM tag_aliases "
            "WHERE antecedent_name = ? AND status='active' "
            "ORDER BY consequent_name LIMIT 1", (current,)
        ).fetchone()
        if alias and alias["consequent_name"] != current:
            target = _normalize_tag(alias["consequent_name"])
            first_resolution = first_resolution or {
                "from": current, "to": target, "type": "alias"
            }
            current = target
            continue
        wiki_rows = con.execute(
            "SELECT body FROM wiki WHERE lower(title)=? ORDER BY CASE lang WHEN 'en' THEN 0 ELSE 1 END",
            (current,),
        ).fetchall()
        target = None
        for row in wiki_rows:
            match = re.search(r"\buse\s+(?:\[\[)?([A-Za-z0-9_()/-]+)(?:\]\])?\s+instead\b",
                              row["body"] or "", re.IGNORECASE)
            if match:
                candidate = _normalize_tag(match.group(1))
                exists = con.execute(
                    "SELECT 1 FROM tags WHERE lower(name)=? LIMIT 1", (candidate,)
                ).fetchone()
                if exists and candidate != current:
                    target = candidate
                    break
        if target:
            first_resolution = first_resolution or {
                "from": current, "to": target, "type": "wiki_redirect"
            }
            current = target
            continue
        if "_(" in current and current.endswith(")"):
            base = current.split("_(", 1)[0]
            base_exists = con.execute(
                "SELECT 1 FROM tags WHERE lower(name)=? AND category_name='character' LIMIT 1",
                (base,),
            ).fetchone()
            if base_exists:
                first_resolution = first_resolution or {
                    "from": current, "to": base, "type": "variant_base"
                }
                current = base
                continue
        break
    return current, first_resolution


def _alias_suggestions(con: sqlite3.Connection, query: str,
                       limit: int) -> list[dict]:
    normalized = _normalize_tag(query)
    rows = con.execute(
        "SELECT antecedent_name, consequent_name FROM tag_aliases "
        "WHERE status='active' AND (lower(antecedent_name)=? OR lower(consequent_name)=?) "
        "ORDER BY antecedent_name, consequent_name LIMIT ?",
        (normalized, normalized, max(1, min(int(limit), 10))),
    ).fetchall()
    suggestions = []
    for row in rows:
        candidate = (row["consequent_name"] if row["antecedent_name"].lower() == normalized
                     else row["antecedent_name"])
        suggestions.append({
            "name": candidate,
            "match_type": "alias",
            "confidence": "high",
        })
    return suggestions


@mcp.tool()
def search_knowledge(query: str, category: Optional[str] = None,
                     limit: int = 25) -> dict:
    """Busca tags, personajes, artistas y franquicias en la base unificada."""
    result: dict[str, Any] = {"query": query, "tag_library": {}, "animadex": {}}
    try:
        con = _db()
        try:
            result["tag_library"] = {"results": _tag_rows(con, query, category, limit)}
            if not result["tag_library"]["results"]:
                result["tag_library"]["suggestions"] = _tag_suggestions(
                    con, query, category, limit
                )
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
        requested_tag = _normalize_tag(tag)
        tag, resolution = _resolve_canonical_tag(con, requested_tag)
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
            "requested_tag": requested_tag,
            "tag": tag,
            "tags": tags,
            "definitions": definitions,
        }
        if resolution:
            result["resolution"] = resolution
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
        slug = _normalize_tag(slug)
        rows = _local_characters(con, slug, limit=100)
        match = next((row for row in rows if row.get("slug") == slug), None)
        if not match:
            tag = con.execute(
                "SELECT name, category_name, post_count, site, aliases, nsfw "
                "FROM tags WHERE lower(name)=? ORDER BY post_count DESC LIMIT 1",
                (slug,),
            ).fetchone()
            fallback = dict(tag) if tag else None
            recommendations = _tag_suggestions(con, slug, "character", 5)
            canonical_recommendations = []
            for item in recommendations:
                canonical, item_resolution = _resolve_canonical_tag(con, item["name"])
                canonical_item = dict(item)
                canonical_item["name"] = canonical
                if item_resolution:
                    canonical_item["resolution"] = item_resolution
                if not any(existing["name"] == canonical for existing in canonical_recommendations):
                    canonical_recommendations.append(canonical_item)
            recommendation = next(
                (item for item in canonical_recommendations
                 if item.get("category") == "character"),
                None,
            )
            return {
                "found": False,
                "slug": slug,
                "tag_match": bool(fallback),
                "tag": fallback,
                "recommended_tag": recommendation["name"] if recommendation else None,
                "recommendation": recommendation,
                "message": (
                    "This name exists as a tag but has no structured AnimaDex character record."
                    if fallback else
                    "No structured character record or exact character tag was found."
                    + (" A likely character tag is included as a recommendation." if recommendation else "")
                ),
                "candidates": [row.get("slug") for row in rows[:10]],
                "recommendations": canonical_recommendations,
            }
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
