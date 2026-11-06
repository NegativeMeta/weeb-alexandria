"""Weeb Alexandria: unified owned profiles + tag-library MCP facade."""
from __future__ import annotations

import difflib
import hashlib
import json
import math
import os
import re
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Optional

from mcp.server.fastmcp import FastMCP
from weeb_alexandria_mcp.appearance_runtime import get_appearance_payload

ROOT = os.path.dirname(os.path.abspath(__file__))
TAGLIB_DB = os.path.abspath(os.environ.get(
    "TAGLIB_DB",
    os.path.join(ROOT, "..", "tag_library.db"),
))
CONTEXT_DB = os.path.abspath(os.environ.get(
    "CONTEXT_DB", os.path.join(ROOT, "..", "data", "character_context.sqlite")
))
SEARCH_DB = os.path.abspath(os.environ.get(
    "SEARCH_DB", os.path.join(ROOT, "..", "data", "tag_search.sqlite")
))

mcp = FastMCP(
    "Weeb Alexandria",
    instructions=(
        "Weeb Alexandria answers questions about anime/manga tags and characters from a "
        "local tag library (1.5M tags, 673k wiki definitions) and owned character profiles.\n"
        "\n"
        "Language: send tag-style ENGLISH whenever you know it, because the library is "
        "built on English tags. Spanish queries are accepted too: the server translates a "
        "curated vocabulary before searching and reports what it actually searched in "
        "`query_translation.searched_as`. If `query_translation.untranslated` lists words, "
        "those matched no tag - retry them in English.\n"
        "\n"
        "Routing: use `resolve_character` before any character-specific work (it resolves "
        "loose spellings, nicknames, translations and franchise ambiguity), `get_character` "
        "for the canonical card, `search_characters` to filter owned profiles by traits, and "
        "`search_knowledge` / `get_knowledge` for tag knowledge.\n"
        "\n"
        "Prompts: `search_knowledge` accepts a whole prompt. A query that looks like several "
        "tags comes back with `query_mode: multi_tag` and `query_parts` (one tag per part) "
        "plus `related_tags` when an umbrella tag links the parts. Prefer the tags with the "
        "highest `post_count`; answers under 1000 posts are flagged as thin."
    ),
)

# A small set of natural-language franchise hints that are not consistently
# copied into every source's alias column.
_WORK_NAME_HINTS = {
    "oshi_no_ko": {"hoshino_ai"},
}
_COPYRIGHT_TOKENS: Optional[set[str]] = None
_SourceCacheKey = tuple[str, tuple[tuple[int, int], ...]]
_SOURCE_HASH_CACHE: Optional[tuple[_SourceCacheKey, str]] = None
_SOURCE_TAG_COUNT_CACHE: Optional[tuple[_SourceCacheKey, int]] = None
_FTS_VALIDATION_CACHE: Optional[tuple[_SourceCacheKey, tuple[int, int], bool]] = None
_CONTEXT_VALIDATION_CACHE: Optional[tuple[_SourceCacheKey, tuple[int, int], bool]] = None
_SOURCE_STATUS_CACHE: Optional[tuple[_SourceCacheKey, dict[str, int]]] = None
_FTS_SCHEMA_VERSION = "1"
_CONTEXT_SCHEMA_VERSION = "3"


def _normalize_tag(value: str) -> str:
    """Normalize human-written tag forms to the usual underscore form."""
    return "_".join(value.strip().lower().replace("-", "_").split())


def _db() -> sqlite3.Connection:
    """Open the provisioned canonical database without implicit writes."""
    db_path = Path(TAGLIB_DB).resolve()
    uri = f"file:{db_path.as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=15)
    con.execute("PRAGMA busy_timeout=15000")
    con.row_factory = sqlite3.Row
    return con


def _file_signature(path: str) -> tuple[int, int]:
    try:
        stat = os.stat(path)
    except OSError:
        return (-1, -1)
    return (stat.st_size, stat.st_mtime_ns)


def _database_signature() -> tuple[tuple[int, int], ...]:
    """Return the source database signature, including SQLite sidecars."""
    return tuple(
        _file_signature(TAGLIB_DB + suffix)
        for suffix in ("", "-wal", "-shm")
    )


def _source_cache_key() -> _SourceCacheKey:
    return (os.path.abspath(TAGLIB_DB), _database_signature())


def _source_sha256() -> Optional[str]:
    global _SOURCE_HASH_CACHE
    cache_key = _source_cache_key()
    signature = cache_key[1]
    if signature[0][0] < 0:
        return None
    if _SOURCE_HASH_CACHE and _SOURCE_HASH_CACHE[0] == cache_key:
        return _SOURCE_HASH_CACHE[1]
    digest = hashlib.sha256()
    try:
        with open(TAGLIB_DB, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    if _source_cache_key() != cache_key:
        return None
    value = digest.hexdigest()
    _SOURCE_HASH_CACHE = (cache_key, value)
    return value


def _source_tag_count(con: sqlite3.Connection) -> Optional[int]:
    global _SOURCE_TAG_COUNT_CACHE
    cache_key = _source_cache_key()
    if _SOURCE_TAG_COUNT_CACHE and _SOURCE_TAG_COUNT_CACHE[0] == cache_key:
        return _SOURCE_TAG_COUNT_CACHE[1]
    try:
        count = int(con.execute("SELECT count(*) FROM tags").fetchone()[0])
    except (sqlite3.Error, TypeError, ValueError):
        return None
    _SOURCE_TAG_COUNT_CACHE = (cache_key, count)
    return count


def _derived_metadata_matches(
    derived: sqlite3.Connection,
    metadata_table: str,
    schema_version: str,
    row_counts: Optional[dict[str, str]] = None,
    source_con: Optional[sqlite3.Connection] = None,
) -> bool:
    """Validate a generated index against the current source snapshot."""
    try:
        metadata = dict(derived.execute(
            f"SELECT key, value FROM {metadata_table}"
        ).fetchall())
        required = {"schema_version", "source_db", "source_size", "source_sha256"}
        if not required <= metadata.keys():
            return False
        if metadata["schema_version"] != schema_version:
            return False
        if os.path.abspath(metadata["source_db"]) != os.path.abspath(TAGLIB_DB):
            return False
        if metadata["source_size"] != str(_file_signature(TAGLIB_DB)[0]):
            return False
        source_hash = _source_sha256()
        if not source_hash or metadata["source_sha256"] != source_hash:
            return False
        for table, metadata_key in (row_counts or {}).items():
            if metadata_key not in metadata:
                return False
            expected = int(metadata[metadata_key])
            actual = int(derived.execute(
                f"SELECT count(*) FROM {table}"
            ).fetchone()[0])
            if actual != expected:
                return False
        if source_con is not None and "indexed_rows" in metadata:
            source_count = _source_tag_count(source_con)
            actual = int(derived.execute(
                "SELECT count(*) FROM tag_search"
            ).fetchone()[0])
            if source_count is None or actual != int(metadata["indexed_rows"]):
                return False
            if actual != source_count:
                return False
        wal_size = _file_signature(TAGLIB_DB + "-wal")[0]
        wal_mtime_ns = _file_signature(TAGLIB_DB + "-wal")[1]
        if wal_size > 0 and (
            "source_wal_size" not in metadata
            or "source_wal_mtime_ns" not in metadata
        ):
            return False
        if "source_wal_size" in metadata and metadata["source_wal_size"] != str(wal_size):
            return False
        if ("source_wal_mtime_ns" in metadata
                and metadata["source_wal_mtime_ns"] != str(wal_mtime_ns)):
            return False
        return True
    except (OSError, sqlite3.Error, TypeError, ValueError):
        return False


def _open_valid_context() -> Optional[sqlite3.Connection]:
    global _CONTEXT_VALIDATION_CACHE
    if not os.path.isfile(CONTEXT_DB):
        return None
    source_key = _source_cache_key()
    context_signature = _file_signature(CONTEXT_DB)
    context: Optional[sqlite3.Connection] = None
    try:
        context = sqlite3.connect(CONTEXT_DB)
        context.row_factory = sqlite3.Row
        cached = (
            _CONTEXT_VALIDATION_CACHE
            and _CONTEXT_VALIDATION_CACHE[0] == source_key
            and _CONTEXT_VALIDATION_CACHE[1] == context_signature
        )
        valid = (
            _CONTEXT_VALIDATION_CACHE[2] if cached else _derived_metadata_matches(
                context,
                "context_index_metadata",
                _CONTEXT_SCHEMA_VERSION,
                {"character_context": "context_rows", "character_work_context": "work_rows"},
            )
        )
        _CONTEXT_VALIDATION_CACHE = (source_key, context_signature, valid)
        if not valid:
            context.close()
            return None
        return context
    except (OSError, sqlite3.Error):
        _CONTEXT_VALIDATION_CACHE = (source_key, context_signature, False)
        if context is not None:
            context.close()
        return None


def _context_tags(tokens: list[str]) -> set[str]:
    if not tokens:
        return set()
    context = _open_valid_context()
    if context is None:
        return set()
    try:
        placeholders = ",".join("?" for _ in tokens)
        rows = context.execute(
            f"SELECT DISTINCT tag FROM character_context WHERE context IN ({placeholders})",
            tokens,
        ).fetchall()
        return {row[0] for row in rows}
    except sqlite3.Error:
        return set()
    finally:
        context.close()


def _context_work_map(tags: set[str], context_tokens: list[str]) -> dict[str, str]:
    if not tags or not context_tokens:
        return {}
    context = _open_valid_context()
    if context is None:
        return {}
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
    except sqlite3.Error:
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


_APPEARANCE_LENGTH_SLUGS = {
    "very_short_hair", "short_hair", "medium_hair", "long_hair",
    "very_long_hair", "absurdly_long_hair",
}
_APPEARANCE_GENDER_SLUGS = {
    "female": "1girl", "woman": "1girl", "women": "1girl", "girl": "1girl",
    "1girl": "1girl",
    "male": "1boy", "man": "1boy", "men": "1boy", "boy": "1boy", "1boy": "1boy",
}


def _appearance_facet_rule(facet: str,
                           value: str) -> Optional[tuple[str, str, Optional[bool]]]:
    """Map a legacy trait filter onto an appearance facet + canonical slug.

    Returns ``(appearance_facet, canonical_slug, require_length)`` where
    ``require_length`` is True/False for hair filters (to keep colors and
    lengths apart, both live in the ``hair`` facet) and None otherwise.
    """
    normalized = _normalize_tag(value)
    if not normalized:
        return None
    if facet == "gender":
        slug = _APPEARANCE_GENDER_SLUGS.get(normalized)
        return ("gender", slug, None) if slug else None
    if facet == "eye_color":
        slug = normalized if normalized.endswith("_eyes") else f"{normalized}_eyes"
        return "eyes", slug, None
    if facet in {"hair_color", "hair_length"}:
        slug = normalized if normalized.endswith("_hair") else f"{normalized}_hair"
        return "hair", slug, facet == "hair_length"
    return None


def _appearance_characters(con: sqlite3.Connection, query: str = "",
                           filters: Optional[dict] = None,
                           limit: int = 100) -> list[dict]:
    """Return modern appearance-only characters, honoring trait filters."""
    normalized = _normalize_tag(query)
    rules = []
    for facet, value in (filters or {}).items():
        rule = _appearance_facet_rule(facet, value)
        if rule is None:
            return []
        rules.append(rule)
    if not normalized and not rules:
        return []

    sql = ("SELECT character_tag, display_name, appearance_key, is_default "
           "FROM character_appearance_profiles "
           "WHERE status IN ('reviewed', 'published')")
    params: list[Any] = []
    if normalized:
        sql += " AND (character_tag LIKE ? OR display_name LIKE ?)"
        params.extend([f"%{normalized}%", f"%{normalized}%"])
    rows = con.execute(sql, params).fetchall()

    selected: dict[str, sqlite3.Row] = {}
    for row in rows:
        current = selected.get(row["character_tag"])
        if current is None or row["is_default"] > current["is_default"]:
            selected[row["character_tag"]] = row

    if rules and selected:
        keys = sorted({row["appearance_key"] for row in selected.values()})
        placeholders = ", ".join("?" for _ in keys)
        feature_rows = con.execute(
            "SELECT appearance_key, facet, canonical_tag, value "
            f"FROM character_appearance_features WHERE appearance_key IN ({placeholders}) "
            "AND status IN ('reviewed', 'published')",
            keys,
        ).fetchall()
        by_key: dict[str, list[sqlite3.Row]] = {}
        for feature in feature_rows:
            by_key.setdefault(feature["appearance_key"], []).append(feature)

        def _matches(profile: sqlite3.Row) -> bool:
            features = by_key.get(profile["appearance_key"], [])
            for appearance_facet, slug, require_length in rules:
                satisfied = False
                for feature in features:
                    if feature["facet"] != appearance_facet:
                        continue
                    canonical = _normalize_tag(feature["canonical_tag"] or "")
                    if canonical != slug and _normalize_tag(feature["value"]) != slug:
                        continue
                    if require_length is True and canonical not in _APPEARANCE_LENGTH_SLUGS:
                        continue
                    if require_length is False and canonical in _APPEARANCE_LENGTH_SLUGS:
                        continue
                    satisfied = True
                    break
                if not satisfied:
                    return False
            return True

        selected = {tag: prof for tag, prof in selected.items() if _matches(prof)}

    out = []
    for character, profile in selected.items():
        count = con.execute(
            "SELECT COALESCE(MAX(post_count), 0) FROM tags WHERE name=?",
            (character,),
        ).fetchone()[0]
        traits = [dict(row) for row in con.execute(
            """SELECT f.facet, f.value, f.canonical_tag AS evidence_tag,
                      f.canonical_tag AS trait_slug, f.confidence
               FROM character_appearance_features f
               WHERE f.appearance_key=? AND f.status IN ('reviewed', 'published')
               ORDER BY f.facet, f.display_order, f.canonical_tag""",
            (profile["appearance_key"],),
        ).fetchall()]
        for trait in traits:
            trait["label"] = trait["value"]
            trait["provenance"] = "appearance_profile"
        out.append({
            "character": character,
            "name": profile["display_name"],
            "copyright": None,
            "copyright_name": None,
            "trigger": "",
            "count": count,
            "url": "",
            "profile_provenance": "appearance_profile",
            "profile_confidence": "high",
            "slug": character,
            "tags": [],
            "traits": traits,
        })
    return out[:limit] if limit else out


def _local_characters(con: sqlite3.Connection, query: str = "",
                      copyright: Optional[str] = None,
                      hair_color: Optional[str] = None,
                      hair_length: Optional[str] = None,
                      eye_color: Optional[str] = None,
                      gender: Optional[str] = None,
                      sort: str = "count", limit: int = 100) -> list[dict]:
    """Search the owned structured character profiles and trait mappings."""
    clauses = []
    params: list[Any] = []
    order_params: list[Any] = []
    normalized = _normalize_tag(query)
    if query:
        clauses.append(
            "(c.display_name_normalized LIKE ? OR c.character_tag LIKE ? "
            "OR c.trigger LIKE ? OR c.core_tags LIKE ?)"
        )
        needle = f"%{normalized}%"
        params.extend([needle, needle, needle, needle])
    if copyright:
        work = _normalize_tag(copyright)
        clauses.append("(c.work_tag = ? OR c.work_tag LIKE ? OR c.work_name LIKE ?)")
        params.extend([work, f"%{work}%", f"%{copyright}%"])
    for value, facet in (
        (hair_color, "hair_color"),
        (hair_length, "hair_length"),
        (eye_color, "eye_color"),
        (gender, "gender"),
    ):
        if value:
            trait_value = _normalize_tag(value)
            clauses.append(
                "EXISTS ("
                "SELECT 1 FROM character_traits ct "
                "JOIN trait_definitions td ON td.trait_slug = ct.trait_slug "
                "WHERE ct.character_tag = c.character_tag "
                "AND td.facet = ? AND td.status = 'active' "
                "AND (td.trait_slug = ? OR td.value LIKE ? OR td.label LIKE ?)"
                ")"
            )
            params.extend([facet, trait_value, f"%{value}%", f"%{value}%"])
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    if sort == "name":
        order = "c.display_name_normalized"
    elif sort == "random":
        order = "RANDOM()"
    elif normalized:
        order = (
            "CASE WHEN c.character_tag = ? OR c.display_name_normalized = ? THEN 3 "
            "WHEN c.character_tag LIKE ? OR c.display_name_normalized LIKE ? THEN 2 "
            "ELSE 1 END DESC, c.source_count DESC, c.display_name_normalized"
        )
        order_params = [normalized, normalized, f"{normalized}_%", f"{normalized}_%"]
    else:
        order = "c.source_count DESC, c.display_name_normalized"
    params = params + order_params
    params.append(max(1, min(int(limit), 100)))
    rows = con.execute(f"""
        SELECT c.character_tag AS character, c.display_name AS name,
               c.work_tag AS copyright, c.work_name AS copyright_name,
               c.trigger, c.core_tags, c.source_count AS count,
               c.source_url AS url, c.provenance AS profile_provenance,
               c.confidence AS profile_confidence
        FROM character_profiles c {where} ORDER BY {order} LIMIT ?
    """, params).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        item["slug"] = item.pop("character")
        item["tags"] = [tag.strip() for tag in item.pop("core_tags").split(",") if tag.strip()]
        item["traits"] = [dict(t) for t in con.execute(
            "SELECT td.facet, td.value, td.label, ct.evidence_tag, "
            "ct.provenance, ct.confidence "
            "FROM character_traits ct "
            "JOIN trait_definitions td ON td.trait_slug = ct.trait_slug "
            "WHERE ct.character_tag = ? AND td.status = 'active' "
            "ORDER BY td.facet, td.value",
            (item["slug"],),
        ).fetchall()]
        out.append(item)
    return out


def _local_artists(con: sqlite3.Connection, query: str = "", sort: str = "count", limit: int = 100) -> list[dict]:
    """Return artist tags from the unified tag library."""
    normalized = _normalize_tag(query)
    clauses = ["t.category_name = 'artist'"]
    params: list[Any] = []
    if normalized:
        # The range lets SQLite use idx_tags_name before applying the
        # category filter, avoiding a scan of every artist row.
        clauses.append("t.name >= ? AND t.name < ? AND t.name LIKE ?")
        params.extend([normalized, normalized + "\uffff", normalized + "%"])
    if sort == "name":
        order = "t.name"
        order_params: list[Any] = []
    elif sort == "random":
        order = "RANDOM()"
        order_params = []
    elif normalized:
        order = (
            "CASE WHEN t.name = ? THEN 3 ELSE 2 END DESC, "
            "MAX(COALESCE(t.post_count, 0)) DESC, t.name"
        )
        order_params = [normalized]
    else:
        order = "MAX(COALESCE(t.post_count, 0)) DESC, t.name"
        order_params = []
    params.extend(order_params)
    params.append(max(1, min(int(limit), 100)))
    rows = con.execute(f"""
        SELECT t.name AS artist, MAX(COALESCE(t.post_count, 0)) AS count
        FROM tags AS t INDEXED BY idx_tags_name WHERE {' AND '.join(clauses)}
        GROUP BY t.name ORDER BY {order} LIMIT ?
    """, params).fetchall()
    return [
        {
            "artist": row["artist"],
            "name": row["artist"].replace("_", " "),
            "trigger": row["artist"],
            "count": row["count"],
            "score": None,
            "url": f"https://danbooru.donmai.us/posts?tags={row['artist']}",
        }
        for row in rows
    ]


def _local_copyrights(con: sqlite3.Connection, query: str = "", limit: int = 100) -> list[dict]:
    """Aggregate copyright/work tags and their owned-profile coverage."""
    normalized = _normalize_tag(query)
    clauses = ["t.category_name = 'copyright'"]
    params: list[Any] = []
    if normalized:
        # Use the name index for the prefix range; the category predicate is
        # applied only to the small candidate range.
        clauses.append("t.name >= ? AND t.name < ? AND t.name LIKE ?")
        params.extend([normalized, normalized + "\uffff", normalized + "%"])
    if normalized:
        order = (
            "CASE WHEN t.name = ? THEN 3 ELSE 2 END DESC, "
            "MAX(COALESCE(t.post_count, 0)) DESC, t.name"
        )
        params.append(normalized)
    else:
        order = "MAX(COALESCE(t.post_count, 0)) DESC, t.name"
    params.append(max(1, min(int(limit), 100)))
    rows = con.execute(f"""
        SELECT t.name, COUNT(DISTINCT p.character_tag) AS character_count,
               MAX(COALESCE(t.post_count, 0)) AS post_count
        FROM tags AS t INDEXED BY idx_tags_name
        LEFT JOIN character_profiles p ON p.work_tag = t.name
        WHERE {' AND '.join(clauses)}
        GROUP BY t.name ORDER BY {order} LIMIT ?
    """, params).fetchall()
    return [dict(row) for row in rows]


def _tag_match(name: str, query: str, normalized: str) -> tuple[str, int]:
    lowered = name.lower()
    raw = query.strip().lower()
    if lowered == raw:
        return "exact", 3
    if lowered == normalized:
        return "normalized", 3
    if normalized and lowered.startswith(f"{normalized}_"):
        return "prefix", 2
    return "partial", 1


def _merge_tag_rows(rows: list[sqlite3.Row], query: str,
                    normalized: str, limit: int) -> list[dict]:
    merged: dict[str, dict] = {}
    for row in rows:
        name = row["name"]
        if not name:
            continue
        match_type, relevance = _tag_match(name, query, normalized)
        item = merged.get(name)
        if item is None:
            item = {
                "name": name,
                "category": row["category_name"],
                "post_count": row["post_count"],
                "sites": [],
                "aliases": row["aliases"] or "",
                "nsfw": False,
                "match_type": match_type,
                "confidence": ("high" if relevance == 3
                               else "medium" if relevance == 2
                               else "low"),
                "_relevance": relevance,
            }
            merged[name] = item
        elif relevance > item["_relevance"]:
            item["_relevance"] = relevance
            item["match_type"] = match_type
            item["confidence"] = ("high" if relevance == 3
                                   else "medium" if relevance == 2
                                   else "low")
        site = row["site"]
        if site and site not in item["sites"]:
            item["sites"].append(site)
        item["nsfw"] = item["nsfw"] or bool(row["nsfw"])
        incoming_count = row["post_count"]
        current_count = item["post_count"]
        if ((incoming_count is not None and current_count is None)
                or (incoming_count is not None and current_count is not None
                    and incoming_count > current_count)):
            item["category"] = row["category_name"]
            item["post_count"] = incoming_count
        if not item["aliases"] and row["aliases"]:
            item["aliases"] = row["aliases"]

    result = sorted(
        merged.values(),
        key=lambda item: (-item["_relevance"],
                          -(item["post_count"] or 0), item["name"]),
    )[:limit]
    for item in result:
        item.pop("_relevance", None)
    return result


def _legacy_tag_rows(con: sqlite3.Connection, query: str,
                     category: Optional[str], limit: int) -> list[dict]:
    normalized = _normalize_tag(query)
    sql = (
        "SELECT name, category_name, post_count, site, aliases, nsfw "
        "FROM tags WHERE lower(name) LIKE ?"
    )
    params: list[Any] = [f"%{normalized}%"]
    if category and category.lower() not in {"tag", "tags", "all"}:
        sql += " AND category_name = ?"
        params.append(category)
    sql += " ORDER BY post_count DESC NULLS LAST, name LIMIT ?"
    params.append(limit)
    rows = con.execute(sql, params).fetchall()
    return _merge_tag_rows(rows, query, normalized, limit)


def _fts_match_query(query: str) -> str:
    normalized = _normalize_tag(query)
    tokens = re.findall(r"[^\W_][\w:+!/-]*", normalized, re.UNICODE)
    return " AND ".join(
        f'"{token.replace(chr(34), chr(34) * 2)}"*' for token in tokens
    )


def _fts_tag_rows(con: sqlite3.Connection, query: str,
                  category: Optional[str], limit: int) -> Optional[list[sqlite3.Row]]:
    if not os.path.isfile(SEARCH_DB):
        return None
    match_query = _fts_match_query(query)
    if not match_query:
        return None
    search: Optional[sqlite3.Connection] = None
    try:
        search = sqlite3.connect(SEARCH_DB)
        search.row_factory = sqlite3.Row
        search.execute("PRAGMA query_only = ON")
        source_key = _source_cache_key()
        search_signature = _file_signature(SEARCH_DB)
        global _FTS_VALIDATION_CACHE
        cached = (
            _FTS_VALIDATION_CACHE
            and _FTS_VALIDATION_CACHE[0] == source_key
            and _FTS_VALIDATION_CACHE[1] == search_signature
        )
        valid = (
            _FTS_VALIDATION_CACHE[2] if cached else _derived_metadata_matches(
                search,
                "tag_search_metadata",
                _FTS_SCHEMA_VERSION,
                source_con=con,
            )
        )
        _FTS_VALIDATION_CACHE = (source_key, search_signature, valid)
        if not valid:
            return None
        category_clause = ""
        category_params: list[Any] = []
        if category and category.lower() not in {"tag", "tags", "all"}:
            category_clause = " AND category_name = ?"
            category_params.append(category)
        # Two bounded steps: aggregate names first, then fetch details for just
        # those names. The previous single CTE (inner ORDER BY + outer ORDER BY)
        # made SQLite re-run the MATCH once per output row: 20s+ per query.
        candidate_limit = max(50, min(limit * 4, 400))
        name_rows = search.execute(
            "SELECT name, MIN(rank) AS rank, MAX(COALESCE(post_count, 0)) AS max_count "
            "FROM tag_search WHERE tag_search MATCH ?"
            f"{category_clause} GROUP BY name "
            "ORDER BY rank, max_count DESC, name LIMIT ?",
            [match_query, *category_params, candidate_limit],
        ).fetchall()
        if not name_rows:
            return []
        order = {
            row["name"]: (index, row["rank"], row["max_count"])
            for index, row in enumerate(name_rows)
        }
        placeholders = ", ".join("?" for _ in order)
        detail_sql = (
            "SELECT site, name, category_name, post_count, aliases, nsfw "
            f"FROM tag_search WHERE name IN ({placeholders})"
            + (" AND category_name = ?" if category_clause else "")
        )
        detail_rows = search.execute(
            detail_sql, [*order.keys(), *category_params]
        ).fetchall()
        return sorted(
            detail_rows,
            key=lambda row: (
                order[row["name"]][0],
                -(row["post_count"] or 0),
                row["name"],
                row["site"],
            ),
        )
    except (OSError, sqlite3.Error):
        return None
    finally:
        if search is not None:
            search.close()


def _exact_tag_rows(con: sqlite3.Connection, normalized: str,
                    category: Optional[str]) -> list[sqlite3.Row]:
    sql = (
        "SELECT name, category_name, post_count, site, aliases, nsfw "
        "FROM tags INDEXED BY idx_tags_name WHERE name = ?"
    )
    params: list[Any] = [normalized]
    if category and category.lower() not in {"tag", "tags", "all"}:
        sql += " AND category_name = ?"
        params.append(category)
    return con.execute(sql, params).fetchall()


def _indexed_prefix_rows(con: sqlite3.Connection, normalized: str,
                         category: Optional[str], limit: int) -> list[sqlite3.Row]:
    sql = (
        "SELECT name, category_name, post_count, site, aliases, nsfw "
        "FROM tags INDEXED BY idx_tags_name "
        "WHERE name >= ? AND name < ? AND name LIKE ?"
    )
    params: list[Any] = [normalized, normalized + "\uffff", normalized + "%"]
    if category and category.lower() not in {"tag", "tags", "all"}:
        sql += " AND category_name = ?"
        params.append(category)
    sql += (
        " ORDER BY CASE WHEN name = ? THEN 3 "
        "WHEN name LIKE ? THEN 2 ELSE 1 END DESC, "
        "post_count DESC NULLS LAST, name LIMIT ?"
    )
    params.extend([normalized, normalized + "%", limit])
    return con.execute(sql, params).fetchall()


def _tag_rows(con: sqlite3.Connection, query: str,
              category: Optional[str], limit: int) -> list[dict]:
    limit = max(1, min(int(limit), 100))
    normalized = _normalize_tag(query)
    if not normalized:
        return _drop_placeholder_rows(_legacy_tag_rows(con, query, category, limit))

    exact_rows = _exact_tag_rows(con, normalized, category)
    usable_exact = [
        row for row in exact_rows
        if not _is_placeholder_item({"category": row["category_name"],
                                     "post_count": row["post_count"]})
    ]
    if usable_exact:
        return _merge_tag_rows(usable_exact, query, normalized, limit)

    # The only exact row is a stub: follow the alias table before guessing
    # (`titjob` is an alias of `paizuri`, 115 985 posts).
    redirect, _redirect_meta = _resolve_canonical_tag(con, normalized)
    if redirect and redirect != normalized:
        redirect_rows = [
            row for row in _exact_tag_rows(con, redirect, category)
            if not _is_placeholder_item({"category": row["category_name"],
                                         "post_count": row["post_count"]})
        ]
        if redirect_rows:
            merged = _merge_tag_rows(redirect_rows, query, normalized, limit)
            for item in merged:
                item["match_type"] = "alias"
                item["confidence"] = "high"
                item["note"] = f"alias of {normalized}"
            return merged

    fts_rows = _fts_tag_rows(con, query, category, limit)
    if fts_rows is None:
        # Keep installations without the derived index fully compatible.
        return _drop_placeholder_rows(_legacy_tag_rows(con, query, category, limit))
    prefix_rows = _indexed_prefix_rows(con, normalized, category, limit)
    merged = _merge_tag_rows(prefix_rows + fts_rows, query, normalized, min(100, limit + 4))
    real_rows = [item for item in merged if not _is_placeholder_item(item)][:limit]
    if real_rows:
        return real_rows
    # Nothing beats a placeholder row: return the stub rather than nothing.
    if exact_rows:
        return _merge_tag_rows(exact_rows, query, normalized, limit)
    return merged


def _split_extra_names(value: Optional[str]) -> list[str]:
    """Split a tag's extra-name/alias column into individual names."""
    if not value:
        return []
    return [part.strip() for part in re.split(r"[,;|]", value) if part.strip()]


def _drop_placeholder_rows(rows: list[dict]) -> list[dict]:
    """Alias/invalid stub rows are redirects, not search answers."""
    kept = [row for row in rows if not _is_placeholder_item(row)]
    return kept or rows


def _fts_or_search(con: sqlite3.Connection, terms: list[str],
                   limit: int = 30) -> list[dict]:
    """One FTS query matching any of several extra names (OR), deduped by name.

    Used only for multi-tag queries: ``dog`` and ``bestiality`` share the extra
    name 犬姦, which is how the umbrella tag for "dog mounting" is found without
    guessing from post counts.
    """
    cleaned = [term for term in terms if term and '"' not in term]
    if not cleaned or not os.path.isfile(SEARCH_DB):
        return []
    match = " OR ".join(f'"{term}"' for term in cleaned)
    search: Optional[sqlite3.Connection] = None
    try:
        search = sqlite3.connect(SEARCH_DB)
        search.row_factory = sqlite3.Row
        search.execute("PRAGMA query_only = ON")
        valid = _derived_metadata_matches(
            search, "tag_search_metadata", _FTS_SCHEMA_VERSION, source_con=con,
        )
        if not valid:
            return []
        rows = search.execute(
            "SELECT name, MIN(rank) AS rank, MAX(COALESCE(post_count, 0)) AS max_count, "
            "MAX(aliases) AS aliases, MAX(category_name) AS category_name "
            "FROM tag_search WHERE tag_search MATCH ? GROUP BY name "
            "ORDER BY rank, max_count DESC LIMIT ?",
            (match, max(1, min(int(limit), 60))),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        if search is not None:
            search.close()
    return [{"name": row["name"], "category": row["category_name"],
             "post_count": row["max_count"], "aliases": row["aliases"]}
            for row in rows]


def _tag_wiki_count(con: sqlite3.Connection, name: str) -> int:
    row = con.execute("SELECT count(*) FROM wiki WHERE title = ?", (name,)).fetchone()
    return int(row[0]) if row else 0


def _is_fragment_answer(con: sqlite3.Connection, item: dict) -> bool:
    """True for a low-coverage tag that no wiki documents as a real tag.

    ``ahegao_face`` (13 posts, 0 definitions) and ``facial_cumshot`` (3 posts,
    1 definition) are fragments; ``mating_(animal)`` (204 posts) is small but
    documented by three sites, so typing it must keep returning it first.
    """
    if (item.get("post_count") or 0) >= _MIN_ANSWER_POSTS:
        return False
    return _tag_wiki_count(con, str(item.get("name") or "")) < 2


def _coverage_fallback(con: sqlite3.Connection, query: str,
                       category: Optional[str], limit: int,
                       current: list[dict],
                       allow_character: bool = False) -> tuple[list[dict], Optional[str]]:
    """Answer with the tags the query's own words name when the match is a stub.

    ``search_knowledge("facial cum")`` used to answer ``facial_cumshot`` (3
    posts) while ``facial`` holds 115 172. ``allow_character`` additionally asks
    the character resolver, because ``"Anya Forger"`` used to answer the 17-post
    ``anya_forger`` while ``anya_(spy_x_family)`` has 8 796.
    """
    if not current:
        return current, None
    thin = (current[0].get("post_count") or 0) < _MIN_ANSWER_POSTS
    fragment = _is_fragment_answer(con, current[0])
    # The resolver is decisive evidence for a bare character name whose tag row is
    # thin, even when that row is wiki-documented (`nahida`, 1 post, 4 wikis).
    if not fragment and not (allow_character and thin):
        return current, None
    notes: list[str] = []
    picked: list[dict] = []
    seen = {str(item.get("name") or "").lower() for item in current}

    if allow_character and thin:
        try:
            recommendation = _character_recommendation(con, query, "character", 3)
        except Exception:  # the resolver is best-effort enrichment here
            recommendation = {}
        tag = recommendation.get("recommended_tag") if recommendation else None
        if tag and str(tag).lower() not in seen:
            rows = [
                row for row in _exact_tag_rows(con, tag, category)
                if not _is_placeholder_item({"category": row["category_name"],
                                             "post_count": row["post_count"]})
            ]
            if rows and (rows[0]["post_count"] or 0) >= _MIN_ANSWER_POSTS:
                for item in _merge_tag_rows(rows, query, tag, 1):
                    item["match_type"] = "character"
                    item["confidence"] = "medium"
                    item["note"] = f"character tag for {query!r}"
                    picked.append(item)
                    seen.add(str(item["name"]).lower())
                notes.append(f"character tag {tag} used for {query!r}")

    normalized = _normalize_tag(query)
    tokens = [token for token in normalized.split("_") if len(token) >= 3]
    for token in (tokens[:3] if fragment else []):
        for row in _tag_rows(con, token, category, 3):
            if (row.get("post_count") or 0) < _MIN_ANSWER_POSTS:
                continue
            # A single word must not be answered with a phrase that merely starts
            # with it: "two" must not become `two_piece_swimsuit`.
            if len(str(row.get("name") or "").split("_")) != 1:
                break
            key = str(row.get("name") or "").lower()
            if key in seen:
                break
            seen.add(key)
            row["match_type"] = "token"
            row["confidence"] = "medium"
            row["note"] = f"matched on token '{token}'"
            picked.append(row)
            break

    if not picked:
        return current, None
    top = current[0]
    notes.insert(0, f"thin answer {top['name']} ({top.get('post_count') or 0} posts) "
                    f"replaced by: {', '.join(item['name'] for item in picked)}")
    merged: list[dict] = []
    names: set[str] = set()
    for item in picked + current:
        key = str(item.get("name") or "").lower()
        if key in names:
            continue
        names.add(key)
        merged.append(item)
    return merged[:limit], "; ".join(notes)


def _prefer_richer_variant(con: sqlite3.Connection,
                           current: list[dict]) -> tuple[list[dict], Optional[str]]:
    """Prefer ``name_(franchise)`` when it has more posts than the bare name.

    ``saber`` (20 415) and ``hu_tao`` (1 301) are legacy bare-name aggregates;
    the canonical character tags ``saber_(fate)`` (23 972) and
    ``hu_tao_(genshin_impact)`` (14 950) carry more evidence. The rule only
    applies to bare names, never to tags that already carry a franchise suffix or
    to descriptive tags, and it costs one indexed prefix lookup.
    """
    if not current:
        return current, None
    top = current[0]
    name = str(top.get("name") or "")
    top_posts = int(top.get("post_count") or 0)
    if not name or "_(" in name or top_posts >= _VARIANT_TIEBREAK_MAX_POSTS:
        return current, None
    base = name
    pattern = base.replace("\\", "\\\\").replace("_", "\\_").replace("%", "\\%") + "\\_(%"
    rows = con.execute(
        "SELECT name, MAX(site) AS site, MAX(category_name) AS category_name, "
        "MAX(post_count) AS post_count, MAX(aliases) AS aliases, MAX(nsfw) AS nsfw "
        "FROM tags WHERE name LIKE ? ESCAPE '\\' GROUP BY name "
        "ORDER BY post_count DESC LIMIT 1",
        (pattern,),
    ).fetchall()
    variant = rows[0] if rows else None
    tokens = base.split("_")
    # Token order can flip: `miku_hatsune` (88 545) vs `hatsune_miku` (144 723).
    # The library writes sorted names, so only unsorted ones are worth a lookup,
    # and one contains-scan (0.17 s) is enough.
    if variant is None and len(tokens) == 2 and tokens != sorted(tokens):
        probe = max(tokens, key=len).replace("\\", "\\\\").replace("_", "\\_").replace("%", "\\%")
        rows = con.execute(
            "SELECT name, MAX(site) AS site, MAX(category_name) AS category_name, "
            "MAX(post_count) AS post_count, MAX(aliases) AS aliases, MAX(nsfw) AS nsfw "
            "FROM tags WHERE name LIKE ? ESCAPE '\\' AND name NOT LIKE '%(%' "
            "GROUP BY name ORDER BY post_count DESC LIMIT 30",
            (f"%{probe}%",),
        ).fetchall()
        want = frozenset(tokens)
        for row in rows:
            if frozenset(str(row["name"]).split("_")) == want:
                variant = row
                break
    if variant is None:
        return current, None
    variant_posts = int(variant["post_count"] or 0)
    if variant_posts <= top_posts or variant_posts < _MIN_ANSWER_POSTS:
        return current, None
    replacement = _merge_tag_rows([variant], name, name, 1)
    if not replacement:
        return current, None
    item = replacement[0]
    item["match_type"] = "variant"
    item["confidence"] = "high"
    item["note"] = (f"richer franchise variant: {variant['name']} ({variant_posts}) "
                    f"over {name} ({top_posts})")
    note = f"{name} is a bare-name aggregate; answered with {variant['name']} ({variant_posts} posts)"
    return [item] + [row for row in current if row.get("name") != variant["name"]], note


def _part_tag_is_named(part: dict) -> bool:
    """True when the part resolved to the tag it actually names.

    Linking concepts through a part that matched something else ("girl" ->
    ``girl_on_top``) produces confident nonsense, so the umbrella search only
    runs when every part is trustworthy.
    """
    if not part.get("results"):
        return False
    name = str(part["results"][0]["name"]).lower().replace("-", "_")
    slug = _normalize_tag(part.get("query") or "")
    if not slug:
        return False
    if name == slug:
        return True
    if set(name.split("_")) == set(slug.split("_")):
        return True  # hatsune_miku vs miku_hatsune
    return name.startswith(f"{slug}_(")  # franchise-suffixed canonical tag


def _concept_links(con: sqlite3.Connection,
                   part_results: list[dict], limit: int = 3) -> list[dict]:
    """Tags that tie the multi-tag parts together through a shared extra name."""
    if not part_results or not all(_part_tag_is_named(part) for part in part_results):
        return []
    part_tags = [part["results"][0]["name"] for part in part_results]
    part_names = {name.lower() for name in part_tags}
    terms: list[str] = []
    for part in part_results:
        for alias in _split_extra_names(part["results"][0].get("aliases")):
            if len(alias) >= 2 and alias.lower() not in part_names and alias not in terms:
                terms.append(alias)
    terms = sorted(terms, key=len, reverse=True)[:12]
    if len(terms) < 2:
        return []
    rows = _fts_or_search(con, terms, limit=30)
    if not rows:
        return []
    # An extra name shared by three or more tags is a generic word, not a link.
    hits = {
        term: sum(1 for row in rows if term in _split_extra_names(row.get("aliases")))
        for term in terms
    }
    generic = {term for term, count in hits.items() if count >= 3}
    links: list[dict] = []
    for row in rows:
        if row["name"].lower() in part_names:
            continue
        # A character/copyright tag that merely contains the word ("rope" ->
        # `rope_(arknights)`) is not the umbrella concept.
        if str(row.get("category") or "").lower() != "general":
            continue
        shared = [
            term for term in _split_extra_names(row.get("aliases"))
            if term in terms and term not in generic
        ]
        if not shared:
            continue
        links.append({
            "name": row["name"],
            "category": row["category"],
            "post_count": row["post_count"],
            "reason": "shares extra name with a query part: " + ", ".join(shared[:3]),
        })
    links.sort(key=lambda item: (-(item["post_count"] or 0), item["name"]))
    return links[:limit]


def _tag_suggestions(con: sqlite3.Connection, query: str,
                     category: Optional[str], limit: int) -> list[dict]:
    """Return likely tag names for a misspelled or non-canonical query."""
    normalized = _normalize_tag(query)
    if not normalized:
        return []
    tokens = [token for token in normalized.split("_") if len(token) >= 3]
    tokens = tokens or [normalized]
    # A prose prompt is 40+ tokens: probing every one of them with a 2000-row prefix
    # query plus a 1.5M-row suffix scan took 34 s. Suggestions answer misspellings,
    # so four of the longest tokens are plenty.
    if len(tokens) > 4:
        tokens = sorted(dict.fromkeys(tokens), key=len, reverse=True)[:4]
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
        # Before the expensive substring fallback, use a short indexed prefix
        # to obtain a bounded fuzzy candidate set (e.g. ``swa`` for
        # ``swalow``). Names are canonical lowercase tags in this database.
        for token in tokens:
            if len(token) < 3:
                continue
            prefix = token[:3]
            rows.extend(con.execute(
                "SELECT name, category_name, post_count, site, aliases, nsfw "
                f"FROM tags INDEXED BY idx_tags_name "
                f"WHERE name >= ? AND name < ? AND name LIKE ?{category_filter} "
                "ORDER BY post_count DESC NULLS LAST LIMIT 2000",
                [prefix, prefix + "\uffff", prefix + "%", *category_params],
            ).fetchall())
    if not rows:
        # Expensive fuzzy fallback is reserved for misspellings with no
        # indexed short-prefix candidates.
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


_WEAK_TAG_CATEGORIES = {"general", "invalid", "alias"}

# Rows in these categories are redirect stubs / deprecated placeholders when they
# also have negligible coverage: they may be returned as a last resort, but never
# as the answer when a real tag matches. A high-coverage alias row (``saber``,
# 20k posts; ``blushing``, 2.6k) is a real tag the source mis-categorised.
_PLACEHOLDER_CATEGORIES = {"alias", "invalid"}
_PLACEHOLDER_MIN_POSTS = 1000

# An exact-ish answer below this coverage is not trusted as the answer: the
# library holds plenty of 3-post fragments ("facial_cumshot") next to the real
# tag ("facial", 115k).
_MIN_ANSWER_POSTS = 1000

# Bare-name aggregates (`saber`, `hu_tao`) are only demoted when the franchise
# variant wins on posts; above this volume the tag is canonical on its own and the
# extra lookup is not worth it.
_VARIANT_TIEBREAK_MAX_POSTS = 300_000

# A narrative prompt produced 40-65 segments and took 34-42 s, because every part
# costs a lookup. Only the most specific segments are kept, and the character
# resolver (0.5-3 s per thin part) is tried for the first few only.
_MAX_MULTI_TAG_PARTS = 12
_MULTI_TAG_CHARACTER_PARTS = 4

# Words that glue a phrase together but are never a tag on their own. They are
# dropped from multi-tag segments so "tied up with rope" does not become
# ["tied up", "with", "rope"] and drag in `rope_(arknights)` as a concept link.
_QUERY_STOPWORDS = {
    "a", "an", "the", "of", "on", "in", "with", "and", "or", "for", "to", "at",
    "by", "from", "into", "over", "under", "her", "his", "their",
    "de", "del", "la", "el", "los", "las", "con", "en", "y", "o", "para", "por",
    "un", "una", "unos", "unas", "al", "que", "su", "sus",
    # Spanish verbs/particles left after translation: they are never tags.
    "mostrando", "mirando", "bajo", "sobre", "desde", "hasta", "muy", "sin",
    "entre", "hacia", "tras", "mientras", "como", "mas", "pero", "ya",
    "vista", "escena", "gran", "grande", "pequeña", "pequeño",
}


_ES_PHRASES_PATH = Path(__file__).with_name("query_aliases_es.json")


@lru_cache(maxsize=1)
def _es_phrases() -> dict[str, str]:
    """Spanish phrase -> English tag wording, verified against the tag library.

    The library only carries English plus Japanese/Chinese extra names per tag, so
    a Spanish query hit random low-coverage Spanish-named tags ("tetas grandes",
    5 posts) or nothing at all.
    """
    try:
        payload = json.loads(_ES_PHRASES_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    phrases = payload.get("phrases") if isinstance(payload, dict) else None
    if not isinstance(phrases, dict):
        return {}
    return {
        str(key).strip().lower(): str(value).strip()
        for key, value in phrases.items()
        if str(key).strip() and str(value).strip()
    }


def _translate_query(query: str) -> tuple[str, list[dict]]:
    """Replace known Spanish phrases by their English tag wording.

    Longest phrases win, so ``sexo oral`` is not eaten by the ``sexo`` entry.
    """
    phrases = _es_phrases()
    if not phrases:
        return query, []
    translated = query.lower()
    applied: list[dict] = []
    for spanish in sorted(phrases, key=len, reverse=True):
        pattern = r"(?<!\w)" + re.escape(spanish) + r"(?!\w)"
        if not re.search(pattern, translated):
            continue
        translated = re.sub(pattern, f" {phrases[spanish]} ", translated)
        applied.append({"spanish": spanish, "english": phrases[spanish]})
    if not applied:
        return query, []
    translated = re.sub(r"\s+", " ", translated)
    # The injected spaces must not break comma-separated prompt lists
    # (`1girl, kimono , sitting` is not segmentable).
    translated = re.sub(r"\s+([,;|])", r"\1", translated)
    translated = re.sub(r"([,;|])(?=\S)", r"\1 ", translated)
    return translated.strip(), applied


_NUMBER_WORDS = {"one": "1", "two": "2", "three": "3", "four": "4",
                 "five": "5", "six": "6", "seven": "7"}


def _normalize_count_words(query: str) -> str:
    """Turn ``two girls`` into ``2girls``, the tag the library actually holds.

    ``two_girls`` is a 69-post fragment while ``2girls`` has 1 320 802.
    """
    pattern = re.compile(
        r"\b(one|two|three|four|five|six|seven)\s+(girls?|boys?)\b", re.IGNORECASE)
    digits = re.compile(r"\b(\d)\s+(girls?|boys?)\b", re.IGNORECASE)

    def from_word(match: re.Match[str]) -> str:
        return _NUMBER_WORDS[match.group(1).lower()] + match.group(2).lower()

    def from_digit(match: re.Match[str]) -> str:
        return match.group(1) + match.group(2).lower()

    return digits.sub(from_digit, pattern.sub(from_word, query))


def _is_placeholder_item(item: dict) -> bool:
    """True for an alias/invalid row too thin to stand as a search answer."""
    category = str(item.get("category") or "").lower()
    if category == "invalid":
        return True
    return (category == "alias"
            and (item.get("post_count") or 0) < _PLACEHOLDER_MIN_POSTS)


def _exact_tag_is_weak(con: sqlite3.Connection, name: str) -> bool:
    """True when an exact tag is missing or too weak to trust over an alias."""
    row = con.execute(
        "SELECT category_name, COALESCE(post_count, 0) AS post_count "
        "FROM tags WHERE name = ? ORDER BY post_count DESC LIMIT 1",
        (name,),
    ).fetchone()
    if row is None:
        return True
    if row["category_name"] in _WEAK_TAG_CATEGORIES:
        return True
    return not row["post_count"]


def _alias_column_target(con: sqlite3.Connection,
                         current: str,
                         categories: Optional[set[str]] = None) -> Optional[str]:
    """Resolve a name listed only in the ``tags.aliases`` text column.

    ``tag_aliases`` and wiki redirects do not cover every alias shipped in the
    tag rows (``GawrGura``, ``gawrt``, ``がうるぐら`` live only in that column),
    so the FTS index over ``aliases`` is the lookup of last resort.
    """
    rows = _fts_tag_rows(con, current, None, 20)
    if not rows:
        return None
    best_name: Optional[str] = None
    best_count = -1
    for row in rows:
        if row["category_name"] in _WEAK_TAG_CATEGORIES:
            continue
        if categories and row["category_name"] not in categories:
            continue
        count = row["post_count"] or 0
        if count <= best_count:
            continue
        aliases = {
            _normalize_tag(part)
            for part in (row["aliases"] or "").split(",")
            if part.strip()
        }
        if current in aliases or _normalize_tag(row["name"]) == current:
            best_name = row["name"]
            best_count = count
    return best_name


def _resolve_canonical_tag(con: sqlite3.Connection, requested: str) -> tuple[str, Optional[dict]]:
    """Follow active aliases and wiki ``Use X instead`` redirects safely."""
    current = _normalize_tag(requested)
    first_resolution = None
    visited = set()
    for _ in range(5):
        if current in visited:
            break
        visited.add(current)
        try:
            alias = con.execute(
                "SELECT consequent_name FROM tag_aliases "
                "WHERE antecedent_name = ? AND status='active' "
                "ORDER BY consequent_name LIMIT 1", (current,)
            ).fetchone()
        except sqlite3.Error:
            # Minimal fixtures may lack the alias table; nothing to redirect.
            return requested, None
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
        if _exact_tag_is_weak(con, current):
            alias_target = _alias_column_target(con, current)
            if alias_target and alias_target != current:
                first_resolution = first_resolution or {
                    "from": current, "to": alias_target, "type": "alias_column"
                }
                current = alias_target
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


def _unmatched_words(query: str, segments: Iterable[str],
                     translations: Optional[list[dict]] = None) -> list[str]:
    """Words of the query that neither a tag segment nor a translation covers.

    Reported as ``query_translation.untranslated`` so the calling model can retry
    exactly those words in English instead of guessing why an answer was thin.
    """
    covered: set[str] = set()
    for segment in segments:
        covered.update(re.findall(r"[^\W\d_]+", str(segment).lower()))
    for item in translations or []:
        covered.update(re.findall(r"[^\W\d_]+", str(item.get("spanish") or "").lower()))

    unmatched: list[str] = []
    for word in re.findall(r"[^\W\d_]+", query.lower()):
        if word in covered or word in _QUERY_STOPWORDS or len(word) < 3:
            continue
        if word not in unmatched:
            unmatched.append(word)
    return unmatched


def _span_tag_segments(con: sqlite3.Connection, words: list[str],
                       category: Optional[str]) -> list[str]:
    """Cover a word list with the fewest known tag spans (dynamic programming)."""
    if len(words) < 2 or len(words) > 12:
        return []
    known_spans: dict[tuple[int, int], bool] = {}
    for start in range(len(words)):
        for end in range(start + 1, min(len(words), start + 5) + 1):
            phrase = " ".join(words[start:end])
            known_spans[(start, end)] = bool(
                _exact_tag_rows(con, _normalize_tag(phrase), category)
            )

    best: list[list[str] | None] = [None] * (len(words) + 1)
    best[-1] = []
    for start in range(len(words) - 1, -1, -1):
        candidates: list[list[str]] = []
        for end in range(start + 1, min(len(words), start + 5) + 1):
            if not known_spans.get((start, end)) or best[end] is None:
                continue
            candidates.append([" ".join(words[start:end]), *best[end]])
        if candidates:
            best[start] = min(candidates, key=lambda parts: (len(parts), -max(
                len(part.split()) for part in parts
            )))
        elif best[start + 1] is not None:
            # An unknown word ("escena", "grande") must not void the whole prompt:
            # skip it and keep the spans around it.
            best[start] = best[start + 1]
    return best[0] or []


def _query_tag_segments(con: sqlite3.Connection, query: str,
                        category: Optional[str]) -> list[str]:
    """Find known tag phrases inside a glued multi-tag query.

    The full-query resolver runs first. This helper is only used after that
    resolver found no strong result, so legitimate multi-word tags such as
    ``red face`` remain intact.

    A comma list used to be all-or-nothing: one unknown entry
    ("sitting in snow") discarded the whole prompt, so a written prompt block
    returned nothing. Unknown entries are now segmented word by word instead.
    """
    separator = re.compile(r"[,;|+\n]+")
    if separator.search(query):
        raw_parts = [part.strip() for part in separator.split(query) if part.strip()]
        if len(raw_parts) < 2:
            return []
        segments: list[str] = []
        for part in raw_parts:
            if _exact_tag_rows(con, _normalize_tag(part), category):
                segments.append(part)
                continue
            words = re.findall(r"[^\W_]+", part, re.UNICODE)
            segments.extend(_span_tag_segments(con, words, category))
        filtered = [
            part for part in segments
            if _normalize_tag(part) not in _QUERY_STOPWORDS
        ]
        return filtered if len(filtered) >= 2 else []

    words = re.findall(r"[^\W_]+", query, re.UNICODE)
    if len(words) > 12:
        # Narrative prompts run 40-80 words; the span DP only handles short queries,
        # so cut on punctuation first and then into 12-word windows with an overlap.
        pieces = [piece for piece in re.split(r"[.,;:!?\n—–]+", query) if piece.strip()]
        segments = []
        for piece in pieces:
            piece_words = re.findall(r"[^\W_]+", piece, re.UNICODE)
            if len(piece_words) <= 12:
                segments.extend(_span_tag_segments(con, piece_words, category))
                continue
            step = 10
            for start in range(0, len(piece_words), step):
                window = piece_words[start:start + 12]
                if len(window) < 2:
                    break
                segments.extend(_span_tag_segments(con, window, category))
    else:
        segments = _span_tag_segments(con, words, category)
    # Glue words are never tags: dropping them keeps the parts meaningful without
    # breaking phrases that legitimately contain one ("day of the dead").
    filtered = [
        part for part in segments
        if _normalize_tag(part) not in _QUERY_STOPWORDS
    ]
    return filtered if len(filtered) >= 2 else []


def _has_strong_tag_recommendation(suggestions: list[dict]) -> bool:
    return any(
        item.get("confidence") == "high"
        and item.get("match_type") in {"exact", "normalized", "contextual"}
        for item in suggestions
    )


def _multi_tag_part(con: sqlite3.Connection, query: str,
                    category: Optional[str], limit: int,
                    allow_character: bool = True) -> dict[str, Any]:
    # Segments come from exact tag spans, so the indexed exact lookup answers most
    # parts in milliseconds; only a miss needs the full FTS path.
    normalized = _normalize_tag(query)
    exact_rows = [
        row for row in _exact_tag_rows(con, normalized, category)
        if not _is_placeholder_item({"category": row["category_name"],
                                     "post_count": row["post_count"]})
    ]
    if exact_rows:
        rows = _merge_tag_rows(exact_rows, query, normalized, limit)
    else:
        rows = _tag_rows(con, query, category, limit)
    rows, coverage_note = _coverage_fallback(con, query, category, limit, rows,
                                             allow_character=allow_character)
    # A tag every source reports with zero posts is scraping noise ("vestido_largo"),
    # not something to hand back as a prompt segment.
    if rows and all((row.get("post_count") or 0) == 0 for row in rows):
        rows = []
    part: dict[str, Any] = {
        "query": query,
        "results": rows,
        "suggestions": [] if rows else _tag_suggestions(con, query, category, limit),
    }
    if coverage_note:
        part["notes"] = [coverage_note]
    return part


def _multi_tag_response(con: sqlite3.Connection, query: str,
                        parts: list[str], category: Optional[str],
                        limit: int) -> dict[str, Any]:
    # A narrative prompt yields 40-65 segments, and each part costs a lookup plus a
    # coverage check: the response took 34-42 s. Multi-word segments are the specific
    # ones, so keep the twelve most specific and drop the rest.
    unique: list[str] = []
    for part in parts:
        if part not in unique:
            unique.append(part)
    if len(unique) > _MAX_MULTI_TAG_PARTS:
        unique = sorted(unique, key=lambda p: (len(p.split()), len(p)), reverse=True)
        unique = unique[:_MAX_MULTI_TAG_PARTS]
    parts = unique
    part_results = [
        _multi_tag_part(con, part, category, limit,
                        allow_character=index < _MULTI_TAG_CHARACTER_PARTS)
        for index, part in enumerate(parts)
    ]
    concept_links = _concept_links(con, part_results)
    message = (
        "This looks like multiple tags in one query. Search each recommended "
        "tag separately and combine the results for better recall."
    )
    if concept_links:
        message += (
            " `related_tags` lists tags that share an extra name with the parts "
            "and usually act as the umbrella for the combination."
        )
    recommendation = {
        "action": "search_each_tag_separately",
        "original_query": query,
        "queries": parts,
        "message": message,
    }
    return {
        "results": [],
        "suggestions": [],
        "query_mode": "multi_tag",
        "query_parts": part_results,
        "query_parts_total": len(parts),
        "related_tags": concept_links,
        "recommendation": recommendation,
    }


@mcp.tool()
def search_knowledge(query: str, category: Optional[str] = None,
                     limit: int = 25) -> dict:
    """Search the unified tag library. Use search_characters for characters.

    Accepts a single tag, a Spanish phrase, or a whole written prompt. A query
    that looks like several tags returns `query_mode: multi_tag` with
    `query_parts` (one tag per part) and `related_tags`; otherwise `results`
    holds the ranked tags. Answers whose best tag has under 1000 posts come with
    a `note`, and `query_translation` shows the text actually searched plus any
    `untranslated` words that matched no tag.
    """
    result: dict[str, Any] = {"query": query, "tag_library": {}}
    try:
        con = _db()
        try:
            lookup_query, translations = _translate_query(query)
            lookup_query = _normalize_count_words(lookup_query)
            tag_results = _tag_rows(con, lookup_query, category, limit)
            tag_results, coverage_note = _coverage_fallback(
                con, lookup_query, category, limit, tag_results,
                allow_character=True,
            )
            tag_results, variant_note = _prefer_richer_variant(con, tag_results)
            if variant_note:
                coverage_note = "; ".join(filter(None, [coverage_note, variant_note]))
            result["tag_library"] = {"results": tag_results}
            if coverage_note:
                result["tag_library"]["notes"] = [coverage_note]
            if not tag_results:
                # Segment first: a written prompt usually yields parts, and computing
                # suggestions before that cost 34 s on a 47-word prose prompt.
                parts = _query_tag_segments(con, lookup_query, category)
                explicit_separator = bool(re.search(r"[,;|+\n]", query))
                if parts and (
                    explicit_separator
                    or len(parts) >= 3
                    or not _has_strong_tag_recommendation(
                        _tag_suggestions(con, lookup_query, category, limit)
                    )
                ):
                    result["tag_library"] = _multi_tag_response(
                        con, query, parts, category, limit
                    )
                    result["query_recommendation"] = result["tag_library"][
                        "recommendation"
                    ]
                else:
                    result["tag_library"]["suggestions"] = _tag_suggestions(
                        con, lookup_query, category, limit
                    )
            payload = result["tag_library"]
            if payload.get("query_mode") == "multi_tag":
                # Segments were capped for cost; the words of the dropped ones are
                # not "untranslated", so measure against the full segment list.
                covered_segments = list(parts)
            else:
                covered_segments = [row.get("name") for row in payload.get("results") or []]
            untranslated = _unmatched_words(
                query, [item for item in covered_segments if item], translations
            )
            if translations or untranslated:
                translation_block = payload.setdefault("query_translation", {})
                if translations:
                    translation_block["applied"] = translations
                    translation_block["searched_as"] = lookup_query
                if untranslated:
                    translation_block["untranslated"] = untranslated
        finally:
            con.close()
    except Exception as exc:
        result["error"] = str(exc)
    return result


@mcp.tool()
def get_knowledge(tag: str, include_relations: bool = True,
                  limit: int = 50) -> dict:
    """Return the combined card for one tag: wiki definitions, sources, aliases,
    implications, category, post count and NSFW status.

    Use it to explain a tag you already resolved; use search_knowledge to find
    the tag name first. `related_tags` may suggest an umbrella tag when the name
    you passed is a narrow variant.
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


def _summarize_character_row(row: dict) -> dict:
    """Drop per-trait evidence so a character page fits in a caller's context."""
    traits = [
        {"facet": trait.get("facet"), "value": trait.get("value")}
        for trait in row.get("traits") or []
    ]
    summary = {key: value for key, value in row.items() if key != "traits"}
    summary["trait_count"] = len(traits)
    summary["traits"] = traits
    return summary


@mcp.tool()
def search_characters(q: str = "", copyright: Optional[str] = None,
                       hair_color: Optional[str] = None,
                       hair_length: Optional[str] = None,
                       eye_color: Optional[str] = None,
                       gender: Optional[str] = None,
                       sort: str = "count", page: int = 1,
                       scope: str = "legacy", page_size: int = 25,
                       detail: str = "summary") -> dict:
    """Search characters in the owned profile and trait tables.

    `scope` picks the source: "legacy" (default) reads only the owned
    character_profiles/trait tables; "all" also merges reviewed appearance
    profiles, which is what makes facet-only filters reach them (for example
    hair_color="white" returns 4 legacy characters with scope="legacy" and
    every reviewed white-haired character with scope="all"). The `copyright`
    filter applies to legacy rows only, and appearance rows need either `q`
    or at least one facet filter before they are considered.
    `gender` only matches profiles that carry gender evidence; most reviewed
    appearance profiles do not yet, so a character without it returns nothing
    for that facet even when the wiki says 1girl/1boy.

    `page_size` defaults to 25 and `detail` to "summary", which keeps each trait
    as {facet, value}: a full 72-row page with per-trait evidence weighed 94 KB
    (~23 500 tokens). Ask for detail="full" when you need `evidence_tag`.
    """
    detail = (detail or "summary").strip().lower()
    if detail not in {"summary", "full"}:
        raise ValueError(f"detail must be 'summary' or 'full', got {detail!r}")
    scope = (scope or "legacy").strip().lower()
    if scope not in {"legacy", "all"}:
        raise ValueError(f"scope must be 'legacy' or 'all', got {scope!r}")
    con = _db()
    try:
        all_rows = _local_characters(con, q, copyright, hair_color, hair_length,
                                     eye_color, gender, sort, 100)
        exact_legacy_match = bool(q) and any(
            row["slug"] == _normalize_tag(q) for row in all_rows
        )
        merge_appearance = scope == "all" or (q and not exact_legacy_match)
        if merge_appearance:
            appearance_filters = {
                key: value for key, value in (
                    ("hair_color", hair_color),
                    ("hair_length", hair_length),
                    ("eye_color", eye_color),
                    ("gender", gender),
                ) if value
            }
            existing = {row["slug"] for row in all_rows}
            all_rows.extend(
                row for row in _appearance_characters(con, q, appearance_filters)
                if row["slug"] not in existing
            )
            if sort == "name":
                all_rows.sort(key=lambda row: row["name"].lower())
            elif sort != "random":
                all_rows.sort(key=lambda row: (-row["count"], row["name"].lower()))
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), 100))
        start = (page - 1) * page_size
        rows = all_rows[start:start + page_size]
        if detail != "full":
            rows = [_summarize_character_row(row) for row in rows]
        return {"total": len(all_rows), "page": page, "page_size": page_size,
                "pages": max(1, (len(all_rows) + page_size - 1) // page_size),
                "detail": detail,
                "results": rows}
    finally:
        con.close()


_MATCH_WEIGHTS = {
    "exact": 4.0,
    "normalized": 3.5,
    "alias": 3.0,
    "alias_column": 3.0,
    "wiki_redirect": 3.0,
    "variant_base": 3.0,
    "contextual": 2.0,
    "suffix": 1.2,
    "fuzzy": 1.0,
}


def _tag_category(con: sqlite3.Connection, name: str) -> Optional[str]:
    """Category of the most used tag row with this exact name."""
    if not name:
        return None
    row = con.execute(
        "SELECT category_name FROM tags WHERE name=? "
        "ORDER BY post_count DESC LIMIT 1",
        (name,),
    ).fetchone()
    return row["category_name"] if row else None


def _owned_profile_source(con: sqlite3.Connection, tag: str) -> Optional[str]:
    """Which owned structured source can serve this character tag, if any."""
    if not tag:
        return None
    if con.execute(
        "SELECT 1 FROM character_appearance_profiles "
        "WHERE character_tag=? AND status IN ('reviewed', 'published') LIMIT 1",
        (tag,),
    ).fetchone():
        return "appearance_profile"
    if con.execute(
        "SELECT 1 FROM character_profiles WHERE character_tag=? LIMIT 1", (tag,)
    ).fetchone():
        return "character_profile"
    return None


def _base_character_name(name: str) -> str:
    """Strip Danbooru's franchise/variant suffix: ``furina_(genshin_impact)``."""
    return name.split("_(", 1)[0]


def _base_character_key(name: str) -> frozenset:
    """Token set of the base name, so ``miku_hatsune`` and ``hatsune_miku`` agree."""
    return frozenset(_base_character_name(name).split("_"))


def _tag_post_count(con: sqlite3.Connection, name: str) -> int:
    """Best (max) post_count for an exact tag name."""
    if not name:
        return 0
    row = con.execute(
        "SELECT MAX(post_count) FROM tags WHERE name=?", (name,)
    ).fetchone()
    return int(row[0] or 0) if row else 0


def _match_score(item: dict, hinted: set[str], tokens: list[str]) -> float:
    """Popularity x match strength x query-token coverage.

    The old ranking preferred any match with a ``_(`` suffix last, which is
    exactly what canonical character tags look like, so ``zero_two`` (3 posts)
    beat ``zero_two_(darling_in_the_franxx)`` (5932). Multiplying post_count by
    the match weight keeps an exact hit on top when its coverage is comparable
    and lets a franchise-suffixed tag win when the bare tag is noise. Token
    coverage stops a single-token candidate (``anya``, 39 posts) from being
    recommended for a two-token query (``Anya Forger``).
    """
    weight = _MATCH_WEIGHTS.get(str(item.get("match_type") or "fuzzy").lower(), 1.0)
    score = float(item.get("post_count") or 0) * weight
    if tokens:
        name_text = str(item.get("name") or "").lower()
        matched = sum(1 for token in tokens if token in name_text)
        score *= matched / len(tokens)
    if item.get("name") in hinted:
        score *= 6
    if item.get("context_match"):
        score *= 2
    return round(score, 1)


def _character_recommendation(con: sqlite3.Connection, query: str,
                              category: Optional[str] = "character",
                              limit: int = 5) -> dict:
    """Resolve a loose character name to the canonical tag plus ranked candidates.

    Evidence order: owned card for the literal name, then the alias/redirect
    tables, then a ranked candidate pool where popularity multiplies the match
    strength. A candidate is recommended even when the name is ambiguous; the
    `ambiguous` flag then lists the competing bases instead of returning null.
    """
    requested = query
    slug = _normalize_tag(query)
    tokens = [token for token in slug.split("_") if len(token) >= 2]
    limit = max(1, min(int(limit or 5), 25))
    rows = _local_characters(con, slug, limit=100) if slug else []
    candidates = [row.get("slug") for row in rows[:10]]

    owned = next((row for row in rows if row.get("slug") == slug), None)
    owned_source = _owned_profile_source(con, slug)
    if owned_source:
        return {
            "query": requested,
            "slug": slug,
            "found": True,
            "tag_match": True,
            "tag": dict(owned) if owned is not None else None,
            "recommended_tag": slug,
            "recommendation": {"name": slug, "match_type": "exact",
                               "confidence": "high", "source": owned_source},
            "ambiguous": False,
            "ambiguity": None,
            "candidates": candidates,
            "recommendations": [],
            "notes": [],
            "message": f"Owned {owned_source} already exists for {slug}.",
        }

    exact_row = None
    if slug:
        exact_row = con.execute(
            "SELECT name, category_name, post_count, site, aliases, nsfw "
            "FROM tags WHERE name=? ORDER BY post_count DESC LIMIT 1",
            (slug,),
        ).fetchone()
    exact = dict(exact_row) if exact_row else None

    # Aliases, the tag-row alias column and wiki redirects already know most
    # franchise-suffixed names ("Furina" -> furina_(genshin_impact)); consult
    # them before guessing from popularity.
    canonical, resolution = _resolve_canonical_tag(con, slug) if slug else (slug, None)
    alias_target: Optional[dict] = None
    if slug and canonical and canonical != slug:
        target_source = _owned_profile_source(con, canonical)
        target_row = con.execute(
            "SELECT category_name, post_count, site FROM tags WHERE name=? "
            "ORDER BY post_count DESC LIMIT 1",
            (canonical,),
        ).fetchone()
        target_category = target_row["category_name"] if target_row else None
        if target_source or target_category == "character":
            alias_target = {
                "name": canonical,
                "category": target_category,
                "post_count": target_row["post_count"] if target_row else None,
                "site": target_row["site"] if target_row else None,
                "match_type": (resolution or {}).get("type") or "alias",
                "confidence": "high",
                "source": target_source,
            }

    hinted = {
        name for work, names in _WORK_NAME_HINTS.items()
        if work in slug for name in names
    }
    pool: list[dict] = []
    if exact and exact["category_name"] not in _WEAK_TAG_CATEGORIES:
        pool.append({
            "name": exact["name"],
            "category": exact["category_name"],
            "post_count": exact["post_count"],
            "site": exact["site"],
            "match_type": ("exact" if exact["name"] == requested else "normalized"),
            "confidence": "high",
        })
    for item in (_tag_suggestions(con, query, category, limit) if slug else []):
        canonical_name, item_resolution = _resolve_canonical_tag(con, item["name"])
        canonical_item = dict(item)
        variant_suffix = ""
        if "_(" in item["name"] and item["name"].endswith(")"):
            variant_suffix = item["name"].split("_(", 1)[1][:-1].lower()
        preserve_context = (
            item_resolution and item_resolution.get("type") == "variant_base"
            and (any(token in variant_suffix for token in slug.split("_") if len(token) >= 2)
                 # A suffixed tag with more posts is the stronger identity: keep
                 # anya_(spy_x_family) instead of collapsing to the 39-post anya.
                 or (item.get("post_count") or 0) > _tag_post_count(con, canonical_name))
        )
        canonical_item["name"] = item["name"] if preserve_context else canonical_name
        if item_resolution and not preserve_context:
            canonical_item["resolution"] = item_resolution
        pool.append(canonical_item)

    # Nicknames are the last word of the canonical tag ("miku" -> hatsune_miku,
    # "gura" -> gawr_gura). The candidate scan only walks prefixes, so those tags
    # are invisible to it; one bounded suffix scan (~0.15 s) recovers them.
    for token in ([tokens[-1]] if tokens and len(tokens[-1]) >= 4 else []):
        suffix_rows = con.execute(
            "SELECT name, category_name, MAX(post_count) AS pc FROM tags "
            "WHERE category_name='character' AND name LIKE ? ESCAPE '!' "
            "GROUP BY name ORDER BY pc DESC LIMIT 8",
            (f"%!_{token}",),
        ).fetchall()
        for row in suffix_rows:
            pool.append({
                "name": row["name"],
                "category": row["category_name"],
                "post_count": row["pc"],
                "site": None,
                "match_type": "suffix",
                "confidence": "medium",
            })

    deduped: dict[str, dict] = {}
    for item in pool:
        previous = deduped.get(item["name"])
        if previous is None or _match_score(item, hinted, tokens) > _match_score(previous, hinted, tokens):
            deduped[item["name"]] = item
    ranked = sorted(
        deduped.values(),
        key=lambda item: (-_match_score(item, hinted, tokens),
                          -(item.get("post_count") or 0), item["name"]),
    )
    for item in ranked:
        item["score"] = _match_score(item, hinted, tokens)
    if category and category.lower() not in {"tag", "tags", "all"}:
        matching_category = [item for item in ranked if item.get("category") == category]
        ranked = matching_category or ranked

    if alias_target is not None:
        alias_target.setdefault("score", _match_score(alias_target, hinted, tokens))
        winner: Optional[dict] = alias_target
        if not any(item["name"] == winner["name"] for item in ranked):
            ranked.insert(0, winner)
        else:
            winner = next(item for item in ranked if item["name"] == alias_target["name"])
    else:
        winner = ranked[0] if ranked else None

    bases = {_base_character_key(item["name"]) for item in ranked[:5]
             if item.get("category") == "character"}
    winner_base = _base_character_key(winner["name"]) if winner else frozenset()
    top_score = ranked[0]["score"] if ranked else 0
    # Only a candidate with a *different* base competes for the ambiguity ratio;
    # miku_hatsune next to hatsune_miku is the same identity, not a rival.
    rival_scores = [
        item["score"] for item in ranked[1:]
        if item.get("category") == "character"
        and _base_character_key(item["name"]) != winner_base
    ]
    second_score = max(rival_scores) if rival_scores else 0
    ambiguous = bool(
        winner is not None
        and alias_target is None
        and len(slug) <= 7
        and "_" not in slug
        and len(bases) >= 2
        and second_score
        and top_score < 3 * second_score
    )
    alternatives = [item["name"] for item in ranked if item["name"] != winner["name"]][:3] \
        if winner else []

    winner_source = (winner or {}).get("source") or _owned_profile_source(
        con, (winner or {}).get("name") or "")
    found = bool(winner_source)

    notes: list[str] = []
    if exact and exact["category_name"] not in {None, "character"}:
        notes.append(
            f"the exact tag {exact['name']} is a '{exact['category_name']}' tag with "
            f"{exact.get('post_count') or 0} posts, not a character tag; candidates "
            "prefer character-category tags"
        )
    if alias_target is not None:
        notes.append(
            f"{slug} resolves to {alias_target['name']} through the "
            f"{alias_target['match_type']} table"
        )

    if winner is None:
        message = "No structured character record or matching character tag was found."
    elif ambiguous:
        message = (f"Several character bases match this short name; the strongest "
                   f"candidate is {winner['name']}. Pass a franchise to pick another.")
    else:
        message = f"Recommended {winner['name']}."
        if not found:
            message += " No owned character card exists for it yet."
    if notes:
        message += " " + "; ".join(notes).capitalize() + "."

    return {
        "query": requested,
        "slug": slug,
        "found": found,
        "tag_match": bool(exact),
        "tag": exact,
        "recommended_tag": winner["name"] if winner else None,
        "recommendation": winner,
        "ambiguous": ambiguous,
        "ambiguity": ({
            "reason": "short_name_with_competing_bases",
            "candidates": alternatives,
            "message": "Provide a franchise or other context to select one character.",
        } if ambiguous else None),
        "candidates": candidates,
        "recommendations": ranked,
        "notes": notes,
        "message": message,
    }


@mcp.tool()
def resolve_character(query: str, category: Optional[str] = "character",
                      limit: int = 5) -> dict:
    """Resolve a free-form character name to the canonical tag to use.

    Use it when a name is spelled loosely ("Anya Forger", "GawrGura",
    "korone"), written in another language, or ambiguous across franchises.
    It returns `recommended_tag` (or null), the winning `recommendation` with
    match_type/confidence/source/score, the full ranked `recommendations`, the
    competing bases in `ambiguity` when the name is short and unclear, and
    `found` telling whether an owned character card can be served right now.

    Evidence order: owned card, alias/redirect tables, then a candidate pool
    ranked by post_count x match strength, so a bare 3-post tag no longer beats
    the 5932-post canonical tag. `category` restricts the candidate pool
    (default "character"; use "copyright" to resolve a franchise name).
    """
    con = _db()
    try:
        return _character_recommendation(con, query, category, limit)
    finally:
        con.close()


def _resolve_appearance_identity(con: sqlite3.Connection, requested: str) -> dict[str, Any]:
    """Resolve one character while preserving appearance-specific aliases."""
    status_params = ("reviewed", "published")
    current = _normalize_tag(requested)
    first_resolution: Optional[dict[str, Any]] = None
    visited: set[str] = set()

    for _ in range(5):
        if not current or current in visited:
            break
        visited.add(current)

        direct_profile = con.execute(
            """SELECT character_tag FROM character_appearance_profiles
               WHERE character_tag=? AND status IN (?, ?)
               ORDER BY is_default DESC LIMIT 1""",
            (current, *status_params),
        ).fetchone()
        if direct_profile:
            return {
                "character_tag": direct_profile["character_tag"],
                "variant": None,
                "resolution": first_resolution,
            }

        owned = con.execute(
            """SELECT character_tag FROM character_profiles
               WHERE character_tag=? OR display_name_normalized=? OR trigger=?
               ORDER BY character_tag LIMIT 2""",
            (current, current, current),
        ).fetchall()
        owned_names = sorted({row["character_tag"] for row in owned})
        if len(owned_names) > 1:
            return {
                "ambiguous": True,
                "candidates": owned_names,
                "message": "Provide a franchise or other context to select one character.",
            }
        if len(owned_names) == 1:
            return {
                "character_tag": owned_names[0],
                "variant": None,
                "resolution": first_resolution,
            }

        variant_profiles = con.execute(
            """SELECT character_tag, variant_tag FROM character_appearance_profiles
               WHERE variant_tag=? AND status IN (?, ?)
               ORDER BY character_tag LIMIT 2""",
            (current, *status_params),
        ).fetchall()
        variant_pairs = sorted({
            (row["character_tag"], row["variant_tag"])
            for row in variant_profiles
        })
        if len(variant_pairs) > 1:
            return {
                "ambiguous": True,
                "candidates": sorted({pair[0] for pair in variant_pairs}),
                "message": "The appearance variant matches more than one character.",
            }
        if len(variant_pairs) == 1:
            resolved_character, resolved_variant = variant_pairs[0]
            return {
                "character_tag": resolved_character,
                "variant": resolved_variant,
                "resolution": first_resolution or {
                    "from": current,
                    "to": resolved_character,
                    "type": "appearance_variant",
                },
            }

        # Follow active aliases before accepting an exact tag. This preserves
        # an appearance profile whose canonical name is the alias target.
        alias = con.execute(
            """SELECT consequent_name FROM tag_aliases
               WHERE antecedent_name=? AND status='active'
               ORDER BY consequent_name LIMIT 1""",
            (current,),
        ).fetchone()
        if alias:
            target = _normalize_tag(alias["consequent_name"])
            if target and target != current:
                first_resolution = first_resolution or {
                    "from": current,
                    "to": target,
                    "type": "alias",
                }
                current = target
                continue

        redirect_rows = con.execute(
            "SELECT body FROM wiki WHERE title=? "
            "ORDER BY CASE lang WHEN 'en' THEN 0 ELSE 1 END",
            (current,),
        ).fetchall()
        redirect_target = None
        for row in redirect_rows:
            match = re.search(
                r"\buse\s+(?:\[\[)?([A-Za-z0-9_()/-]+)(?:\]\])?\s+instead\b",
                row["body"] or "",
                re.IGNORECASE,
            )
            if match:
                candidate = _normalize_tag(match.group(1))
                exists = con.execute(
                    "SELECT 1 FROM tags WHERE name=? LIMIT 1", (candidate,)
                ).fetchone()
                if exists and candidate != current:
                    redirect_target = candidate
                    break
        if redirect_target:
            first_resolution = first_resolution or {
                "from": current,
                "to": redirect_target,
                "type": "wiki_redirect",
            }
            current = redirect_target
            continue

        exact_tag = con.execute(
            """SELECT name FROM tags
               WHERE name=? AND category_name='character'
               ORDER BY post_count DESC LIMIT 2""",
            (current,),
        ).fetchall()
        exact_names = sorted({row["name"] for row in exact_tag})
        if len(exact_names) == 1:
            return {
                "character_tag": exact_names[0],
                "variant": None,
                "resolution": first_resolution,
            }
        if len(exact_names) > 1:
            return {
                "ambiguous": True,
                "candidates": exact_names,
                "message": "Provide a franchise or other context to select one character.",
            }
        if _exact_tag_is_weak(con, current):
            alias_target = _alias_column_target(con, current, {"character"})
            if alias_target and alias_target != current:
                first_resolution = first_resolution or {
                    "from": current,
                    "to": alias_target,
                    "type": "alias_column",
                }
                current = alias_target
                continue
        break

    suggestions = _tag_suggestions(con, requested, "character", 10)
    contextual_names = sorted({
        item["name"] for item in suggestions
        if item.get("category") == "character"
        and item.get("confidence") == "high"
        and item.get("match_type") in {"exact", "normalized", "contextual"}
    })
    if len(contextual_names) == 1:
        return {
            "character_tag": contextual_names[0],
            "variant": None,
            "resolution": {
                "from": requested,
                "to": contextual_names[0],
                "type": "contextual_character",
            },
        }
    if len(contextual_names) > 1:
        return {
            "ambiguous": True,
            "candidates": contextual_names,
            "message": "Provide a franchise or other context to select one character.",
        }
    return {
        "ambiguous": False,
        "candidates": [item["name"] for item in suggestions[:10]],
        "message": "No canonical character tag was found.",
    }


def _resolve_appearance_target(con: sqlite3.Connection, character: str,
                               variant: Optional[str] = None) -> dict[str, Any]:
    """Resolve a character, then scope an optional variant to that character."""
    requested = _normalize_tag(character)
    requested_variant = _normalize_tag(variant) if variant else None
    identity = _resolve_appearance_identity(con, requested)
    if identity.get("ambiguous") or not identity.get("character_tag"):
        return identity

    character_tag = identity["character_tag"]
    resolved_variant = requested_variant or identity.get("variant")
    if requested_variant:
        scoped = con.execute(
            """SELECT 1 FROM character_appearance_profiles
               WHERE character_tag=? AND variant_tag=?
                 AND status IN ('reviewed', 'published')
               LIMIT 1""",
            (character_tag, requested_variant),
        ).fetchone()
        # A missing variant remains scoped to this character. The projection
        # will return available_variants instead of leaking another character.
        if not scoped:
            resolved_variant = requested_variant

    result = {
        "character_tag": character_tag,
        "variant": resolved_variant,
    }
    if identity.get("resolution"):
        result["resolution"] = identity["resolution"]
    return result


@mcp.tool()
def get_character(character: str, variant: Optional[str] = None,
                  include_evidence: bool = False,
                  evidence_limit: int = 100) -> dict:
    """Return the canonical character card: appearance and outfit profiles,
    features grouped by facet, and optional per-feature source evidence.

    Name resolution follows appearance profiles, owned profiles, tag aliases
    and wiki redirects. When it fails, `candidates` lists up to 10 owned
    profiles matching the string; it is not a fuzzy resolver, so call
    `resolve_character` first when the spelling is loose or ambiguous."""
    con = _db()
    try:
        target = _resolve_appearance_target(con, character, variant)
        base = {
            "requested_character": character,
            "requested_variant": variant,
        }
        if target.get("ambiguous"):
            return {
                **base,
                "found": False,
                "ambiguous": True,
                "candidates": target.get("candidates", []),
                "message": target.get("message"),
            }
        character_tag = target.get("character_tag")
        if not character_tag:
            return {
                **base,
                "found": False,
                "ambiguous": False,
                "candidates": target.get("candidates", []),
                "message": target.get("message"),
            }
        result = get_appearance_payload(
            con,
            character_tag,
            target.get("variant"),
            include_evidence,
            evidence_limit,
        )
        result = {**base, **result}
        if target.get("resolution"):
            result["resolution"] = target["resolution"]
        return result
    finally:
        con.close()


@mcp.tool()
def get_sources_status() -> dict:
    """Report which local sources are present and usable.

    Returns the database paths, the structured-source mode, row counts per table
    and whether caching is active. Call it when another tool looks wrong before
    assuming the query was bad.
    """
    global _SOURCE_STATUS_CACHE
    source_key = _source_cache_key()
    if _SOURCE_STATUS_CACHE and _SOURCE_STATUS_CACHE[0] == source_key:
        return {
            "name": "Weeb Alexandria",
            "db": TAGLIB_DB,
            "exists": os.path.exists(TAGLIB_DB),
            "counts": dict(_SOURCE_STATUS_CACHE[1]),
            "structured_mode": "owned_local_tables",
            "cached": True,
        }

    con = _db()
    try:
        # The runtime connection is read-only; cache the signature that was
        # observed for this source snapshot.
        signature = _source_cache_key()
        counts = {}
        for table in ("tags", "wiki", "tag_aliases", "tag_implications",
                      "character_profiles", "trait_definitions",
                      "character_traits", "trait_system_metadata",
                      "character_appearance_profiles",
                      "character_appearance_features",
                      "appearance_feature_catalog",
                      "appearance_facet_catalog",
                      "character_appearance_sources",
                      "character_appearance_feature_sources",
                      "appearance_schema_metadata"):
            counts[table] = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        _SOURCE_STATUS_CACHE = (signature, dict(counts))
        return {"name": "Weeb Alexandria", "db": TAGLIB_DB,
                "exists": os.path.exists(TAGLIB_DB), "counts": counts,
                "structured_mode": "owned_local_tables", "cached": False}
    finally:
        con.close()


if __name__ == "__main__":
    mcp.run()
