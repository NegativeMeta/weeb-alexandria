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
CONTEXT_DB = os.path.abspath(os.environ.get(
    "CONTEXT_DB", os.path.join(ROOT, "..", "data", "character_context.sqlite")
))
ANIMADEX_BASE_URL = os.environ.get(
    "ANIMADEX_BASE_URL", "http://127.0.0.1:5000"
).rstrip("/")

mcp = FastMCP("Weeb Alexandria")

# A small set of natural-language franchise hints that are not consistently
# copied into every source's alias column.
_WORK_NAME_HINTS = {
    "oshi_no_ko": {"hoshino_ai"},
}
_COPYRIGHT_TOKENS: Optional[set[str]] = None


def _normalize_tag(value: str) -> str:
    """Normalize human-written tag forms to the usual underscore form."""
    return "_".join(value.strip().lower().replace("-", "_").split())


def _db() -> sqlite3.Connection:
    con = sqlite3.connect(TAGLIB_DB)
    con.row_factory = sqlite3.Row
    return con


def _context_tags(tokens: list[str]) -> set[str]:
    if not tokens or not os.path.exists(CONTEXT_DB):
        return set()
    context = sqlite3.connect(CONTEXT_DB)
    try:
        placeholders = ",".join("?" for _ in tokens)
        rows = context.execute(
            f"SELECT DISTINCT tag FROM character_context WHERE context IN ({placeholders})",
            tokens,
        ).fetchall()
        return {row[0] for row in rows}
    finally:
        context.close()


def _context_work_map(tags: set[str], context_tokens: list[str]) -> dict[str, str]:
    if not tags or not context_tokens or not os.path.exists(CONTEXT_DB):
        return {}
    context = sqlite3.connect(CONTEXT_DB)
    try:
        try:
            result: dict[str, tuple[int, str]] = {}
            names = list(tags)
            for start in range(0, len(names), 500):
                chunk = names[start:start + 500]
                placeholders = ",".join("?" for _ in chunk)
                rows = context.execute(
                    "SELECT tag, work_tag, matched_terms, score FROM character_work_context "
                    f"WHERE tag IN ({placeholders})",
                    chunk,
                ).fetchall()
                for tag, work, matched_terms, score in rows:
                    matched = set(matched_terms.split(","))
                    if not matched.intersection(context_tokens):
                        continue
                    previous = result.get(tag)
                    if (
                        previous is None
                        or score > previous[0]
                        or (
                            score == previous[0]
                            and (len(work), work) < (len(previous[1]), previous[1])
                        )
                    ):
                        result[tag] = (score, work)
            return {tag: work for tag, (_, work) in result.items()}
        except sqlite3.OperationalError:
            return {}
    finally:
        context.close()


def _copyright_tokens(con: sqlite3.Connection) -> set[str]:
    global _COPYRIGHT_TOKENS
    if _COPYRIGHT_TOKENS is None:
        _COPYRIGHT_TOKENS = set()
        for row in con.execute(
            "SELECT DISTINCT name FROM tags WHERE category_name='copyright'"
        ):
            _COPYRIGHT_TOKENS.update(
                token for token in re.split(r"[_\s]+", row[0].lower())
                if len(token) >= 3
            )
    return _COPYRIGHT_TOKENS
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
    category_filter = ""
    category_params: list[Any] = []
    if category and category.lower() not in {"tag", "tags", "all"}:
        category_filter = " AND category_name = ?"
        category_params.append(category)
    rows: list[sqlite3.Row] = []
    for token in tokens:
        rows.extend(con.execute(
            "SELECT name, category_name, post_count, site, aliases, nsfw "
            f"FROM tags INDEXED BY idx_tags_name "
            f"WHERE name >= ? AND name < ? AND name LIKE ?{category_filter} "
            "ORDER BY post_count DESC NULLS LAST LIMIT 2000",
            [token, token + "\uffff", f"{token}%", *category_params],
        ).fetchall())
    has_complete_name_candidate = any(
        all(token in row["name"].lower().split("_") for token in tokens)
        for row in rows
    )
    if len(tokens) > 1 and not has_complete_name_candidate:
        for token in tokens:
            rows.extend(con.execute(
                "SELECT name, category_name, post_count, site, aliases, nsfw "
                f"FROM tags WHERE name LIKE ? ESCAPE '!'{category_filter} "
                "ORDER BY post_count DESC NULLS LAST LIMIT 2000",
                [f"%!_{token}", *category_params],
            ).fetchall())
    if not rows:
        # Expensive fuzzy fallback is reserved for misspellings with no
        # indexed prefix/suffix candidates (e.g. ``swalow``).
        token_where = " OR ".join("lower(name) LIKE ? OR lower(aliases) LIKE ?" for _ in tokens)
        length_where = "(substr(lower(name), 1, 1) = ? AND length(name) BETWEEN ? AND ?)"
        where = f"({token_where} OR {length_where}){category_filter}"
        params: list[Any] = [value for token in tokens for value in (f"%{token}%", f"%{token}%")]
        params.extend([normalized[0], max(1, len(normalized) - 3), len(normalized) + 8])
        params.extend(category_params)
        rows = list(con.execute(
            f"SELECT name, category_name, post_count, site, aliases, nsfw "
            f"FROM tags WHERE {where} ORDER BY post_count DESC NULLS LAST LIMIT 5000",
            params,
        ).fetchall())
    exact_character_tokens = {
        token for token in tokens
        if con.execute(
            "SELECT 1 FROM tags WHERE category_name='character' AND name=? LIMIT 1",
            (token,),
        ).fetchone()
    }
    context_search_tokens = (
        [token for token in tokens if token not in exact_character_tokens]
        or tokens
    )
    copyright_tokens = _copyright_tokens(con)
    context_tokens = [
        token for token in context_search_tokens
        if token in copyright_tokens
    ]
    context_names: set[str] = set()
    for token in context_tokens:
        token_names = _context_tags([token])
        if len(token_names) <= 5000:
            context_names.update(token_names)
    character_tokens = [token for token in tokens if token not in context_tokens]
    if character_tokens:
        context_names = {
            name for name in context_names
            if any(token in name.lower().split("_") for token in character_tokens)
        }
    else:
        context_names = set()
    context_works = _context_work_map(context_names, context_tokens)
    if context_names:
        names = list(context_names)
        for start in range(0, len(names), 500):
            chunk = names[start:start + 500]
            placeholders = ",".join("?" for _ in chunk)
            rows.extend(con.execute(
                f"SELECT name, category_name, post_count, site, aliases, nsfw FROM tags "
                f"WHERE category_name='character' AND lower(name) IN ({placeholders})",
                chunk,
            ).fetchall())
    wiki_context_names = set()
    for work, names in _WORK_NAME_HINTS.items():
        if work in normalized:
            wiki_context_names.update(names)
            for hinted_name in names:
                hinted_rows = con.execute(
                    "SELECT name, category_name, post_count, site, aliases, nsfw "
                    "FROM tags WHERE lower(name)=?", (hinted_name,)
                ).fetchall()
                rows.extend(hinted_rows)
    scored: dict[str, tuple[float, dict]] = {}
    for row in rows:
        name = row["name"]
        candidate = name.lower().replace("-", "_")
        candidate_tokens = [token for token in candidate.split("_") if token]
        alias_text = row["aliases"] or ""
        alias_tokens = [token for token in re.split(r"[\s,]+", alias_text.lower()) if token]
        match_tokens = candidate_tokens + alias_tokens
        token_ratios = [
            max(difflib.SequenceMatcher(None, token, other).ratio()
                for other in match_tokens)
            for token in tokens
        ]
        token_score = sum(token_ratios) / len(tokens)
        score = 0.6 * token_score + 0.4 * difflib.SequenceMatcher(
            None, normalized, candidate
        ).ratio()
        exact_token_score = sum(token in match_tokens for token in tokens) / len(tokens)
        score += 0.25 * exact_token_score
        if name.lower() in wiki_context_names:
            score += 0.25
        if name.lower() in context_names:
            score += 0.30
            if any(token in candidate_tokens for token in tokens if token not in context_tokens):
                score += 1.5
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
            "confidence": "medium" if score >= 0.65 and min(token_ratios) >= (0.8 if len(tokens) > 1 else 0.72) else "low",
            "context_match": bool(name.lower() in context_names),
            "matched_work": context_works.get(name.lower()),
        }
        if item["context_match"] and any(
            token in candidate_tokens for token in tokens if token not in context_tokens
        ):
            item["match_type"] = "contextual"
            item["confidence"] = "high"
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
            "SELECT body FROM wiki WHERE title=? ORDER BY CASE lang WHEN 'en' THEN 0 ELSE 1 END",
            (current,),
        ).fetchall()
        target = None
        for row in wiki_rows:
            match = re.search(r"\buse\s+(?:\[\[)?([A-Za-z0-9_()/-]+)(?:\]\])?\s+instead\b",
                              row["body"] or "", re.IGNORECASE)
            if match:
                candidate = _normalize_tag(match.group(1))
                exists = con.execute(
                    "SELECT 1 FROM tags WHERE name=? LIMIT 1", (candidate,)
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
                "SELECT 1 FROM tags WHERE name=? AND category_name='character' LIMIT 1",
                (base,),
            ).fetchone()
            base_has_wiki = con.execute(
                "SELECT 1 FROM wiki WHERE title=? AND trim(body) <> '' LIMIT 1",
                (base,),
            ).fetchone()
            if base_exists and base_has_wiki:
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
        if not tags and not definitions:
            contextual_items = [
                item for item in _tag_suggestions(con, requested_tag, "character", 10)
                if item.get("match_type") == "contextual"
                and item.get("confidence") == "high"
            ]
            contextual = {item["name"] for item in contextual_items}
            if len(contextual) == 1:
                candidate_item = contextual_items[0]
                candidate = candidate_item["name"]
                tag, _ = _resolve_canonical_tag(con, candidate)
                resolution = {
                    "from": requested_tag,
                    "to": tag,
                    "type": "contextual_character",
                }
                if candidate_item.get("matched_work"):
                    resolution["matched_work"] = candidate_item["matched_work"]
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
        requested_slug = slug
        slug = _normalize_tag(slug)
        rows = _local_characters(con, slug, limit=100)
        match = next((row for row in rows if row.get("slug") == slug), None)
        if not match:
            tag = con.execute(
                "SELECT name, category_name, post_count, site, aliases, nsfw "
                "FROM tags WHERE name=? ORDER BY post_count DESC LIMIT 1",
                (slug,),
            ).fetchone()
            fallback = dict(tag) if tag else None
            recommendations = _tag_suggestions(con, slug, "character", 5)
            if fallback and fallback.get("category_name") != "alias":
                exact_item = {
                    "name": fallback["name"],
                    "category": fallback["category_name"],
                    "post_count": fallback["post_count"],
                    "site": fallback["site"],
                    "match_type": ("exact" if fallback["name"] == requested_slug
                                   else "normalized"),
                    "confidence": "high",
                }
                recommendations.insert(0, exact_item)
            canonical_recommendations = []
            for item in recommendations:
                canonical, item_resolution = _resolve_canonical_tag(con, item["name"])
                canonical_item = dict(item)
                variant_suffix = ""
                if "_(" in item["name"] and item["name"].endswith(")"):
                    variant_suffix = item["name"].split("_(", 1)[1][:-1].lower()
                preserve_context = (
                    item_resolution and item_resolution.get("type") == "variant_base"
                    and any(token in variant_suffix for token in slug.split("_") if len(token) >= 2)
                )
                canonical_item["name"] = item["name"] if preserve_context else canonical
                if item_resolution and not preserve_context:
                    canonical_item["resolution"] = item_resolution
                if not any(existing["name"] == canonical for existing in canonical_recommendations):
                    canonical_recommendations.append(canonical_item)
            contextual_characters = [
                item for item in canonical_recommendations
                if item.get("category") == "character"
                and item.get("confidence") in {"medium", "high"}
            ]
            hinted_characters = {
                name for work, names in _WORK_NAME_HINTS.items()
                if work in slug for name in names
            }
            contextual_characters.sort(
                key=lambda item: (not item.get("context_match", False),
                                  item["name"] not in hinted_characters,
                                  "_(" in item["name"], -(item.get("post_count") or 0))
            )
            contextual_character = contextual_characters[0] if contextual_characters else None
            hinted_recommendation = next(
                (item for item in contextual_characters if item["name"] in hinted_characters),
                None,
            )
            recommendation = (hinted_recommendation or (contextual_character if fallback and
                              fallback.get("category_name") == "general" and
                              contextual_character else next(
                (item for item in canonical_recommendations
                 if item.get("confidence") == "high"),
                None,
            ) or next(
                (item for item in canonical_recommendations
                 if item.get("category") == "character"),
                None,
            )))
            strong_character_names = {
                item["name"] for item in canonical_recommendations
                if item.get("category") == "character"
                and item.get("confidence") in {"medium", "high"}
            }
            has_contextual_evidence = (
                len(slug.split("_")) > 1
                and any(
                    item.get("context_match") or item.get("match_type") == "contextual"
                    for item in canonical_recommendations
                )
            )
            ambiguous = (
                len(slug) <= 7
                and "_" not in slug
                and len(strong_character_names) >= 2
                and not has_contextual_evidence
            )
            if ambiguous:
                recommendation = None
            return {
                "found": False,
                "slug": slug,
                "tag_match": bool(fallback),
                "ambiguous": ambiguous,
                "tag": fallback,
                "recommended_tag": recommendation["name"] if recommendation else None,
                "recommendation": recommendation,
                "ambiguity": ({
                    "reason": "short_name_multiple_character_candidates",
                    "candidates": sorted(strong_character_names),
                    "message": "Provide a franchise or other context to select one character."
                } if ambiguous else None),
                "message": (
                    "The character name is ambiguous. Provide a franchise or other context."
                    if ambiguous else
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
