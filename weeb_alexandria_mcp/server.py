"""Weeb Alexandria: unified owned profiles + tag-library MCP facade."""
from __future__ import annotations

import difflib
import hashlib
import math
import os
import re
import sqlite3
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP
from weeb_alexandria_mcp.appearance_runtime import get_appearance_payload
from weeb_alexandria_mcp.owned_schema import ensure_owned_schema

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

mcp = FastMCP("Weeb Alexandria")

# A small set of natural-language franchise hints that are not consistently
# copied into every source's alias column.
_WORK_NAME_HINTS = {
    "oshi_no_ko": {"hoshino_ai"},
}
_COPYRIGHT_TOKENS: Optional[set[str]] = None
_OWNED_SCHEMA_READY = False
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
    global _OWNED_SCHEMA_READY
    con = sqlite3.connect(TAGLIB_DB)
    con.row_factory = sqlite3.Row
    if not _OWNED_SCHEMA_READY:
        ensure_owned_schema(con)
        _OWNED_SCHEMA_READY = True
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
        outer_category_clause = ""
        category_params: list[Any] = []
        outer_category_params: list[Any] = []
        if category and category.lower() not in {"tag", "tags", "all"}:
            category_clause = " AND category_name = ?"
            outer_category_clause = " WHERE t.category_name = ?"
            category_params.append(category)
            outer_category_params.append(category)
        candidate_limit = max(50, min(limit * 4, 400))
        sql = (
            "WITH matched_names AS ("
            "SELECT name, MIN(rank) AS rank, "
            "MAX(COALESCE(post_count, 0)) AS max_count "
            "FROM tag_search WHERE tag_search MATCH ?"
            f"{category_clause} GROUP BY name "
            "ORDER BY rank, max_count DESC, name LIMIT ?"
            ") SELECT t.site, t.name, t.category_name, t.post_count, t.aliases, t.nsfw "
            "FROM tag_search AS t JOIN matched_names AS m ON m.name = t.name"
            f"{outer_category_clause} "
            "ORDER BY m.rank, m.max_count DESC, t.post_count DESC NULLS LAST, t.name, t.site"
        )
        params: list[Any] = [
            match_query, *category_params, candidate_limit, *outer_category_params
        ]
        return search.execute(sql, params).fetchall()
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
        return _legacy_tag_rows(con, query, category, limit)

    exact_rows = _exact_tag_rows(con, normalized, category)
    if exact_rows:
        return _merge_tag_rows(exact_rows, query, normalized, limit)

    fts_rows = _fts_tag_rows(con, query, category, limit)
    if fts_rows is None:
        # Keep installations without the derived index fully compatible.
        return _legacy_tag_rows(con, query, category, limit)
    prefix_rows = _indexed_prefix_rows(con, normalized, category, limit)
    return _merge_tag_rows(prefix_rows + fts_rows, query, normalized, limit)


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


def _query_tag_segments(con: sqlite3.Connection, query: str,
                        category: Optional[str]) -> list[str]:
    """Find known tag phrases inside a glued multi-tag query.

    The full-query resolver runs first. This helper is only used after that
    resolver found no strong result, so legitimate multi-word tags such as
    ``red face`` remain intact.
    """
    separator = re.compile(r"[,;|+\n]+")
    if separator.search(query):
        parts = [part.strip() for part in separator.split(query) if part.strip()]
        if len(parts) < 2:
            return []
        if all(_exact_tag_rows(con, _normalize_tag(part), category) for part in parts):
            return parts
        return []

    words = re.findall(r"[^\W_]+", query, re.UNICODE)
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
    segments = best[0]
    return segments if segments and len(segments) >= 2 else []


def _has_strong_tag_recommendation(suggestions: list[dict]) -> bool:
    return any(
        item.get("confidence") == "high"
        and item.get("match_type") in {"exact", "normalized", "contextual"}
        for item in suggestions
    )


def _multi_tag_part(con: sqlite3.Connection, query: str,
                    category: Optional[str], limit: int) -> dict[str, Any]:
    rows = _tag_rows(con, query, category, limit)
    return {
        "query": query,
        "results": rows,
        "suggestions": [] if rows else _tag_suggestions(con, query, category, limit),
    }


def _multi_tag_response(con: sqlite3.Connection, query: str,
                        parts: list[str], category: Optional[str],
                        limit: int) -> dict[str, Any]:
    part_results = [
        _multi_tag_part(con, part, category, limit) for part in parts
    ]
    recommendation = {
        "action": "search_each_tag_separately",
        "original_query": query,
        "queries": parts,
        "message": (
            "This looks like multiple tags in one query. Search each recommended "
            "tag separately and combine the results for better recall."
        ),
    }
    return {
        "results": [],
        "suggestions": [],
        "query_mode": "multi_tag",
        "query_parts": part_results,
        "recommendation": recommendation,
    }


@mcp.tool()
def search_knowledge(query: str, category: Optional[str] = None,
                     limit: int = 25) -> dict:
    """Busca tags, personajes, artistas y franquicias en la base unificada."""
    result: dict[str, Any] = {"query": query, "tag_library": {}, "entities": {}}
    try:
        con = _db()
        try:
            tag_results = _tag_rows(con, query, category, limit)
            result["tag_library"] = {"results": tag_results}
            if not tag_results:
                full_suggestions = _tag_suggestions(con, query, category, limit)
                parts = _query_tag_segments(con, query, category)
                explicit_separator = bool(re.search(r"[,;|+\n]", query))
                if parts and (
                    explicit_separator
                    or not _has_strong_tag_recommendation(full_suggestions)
                ):
                    result["tag_library"] = _multi_tag_response(
                        con, query, parts, category, limit
                    )
                    result["query_recommendation"] = result["tag_library"][
                        "recommendation"
                    ]
                else:
                    result["tag_library"]["suggestions"] = full_suggestions
            category_key = (category or "").strip().lower()
            if category_key in {"character", "characters"}:
                entities = {
                    "characters": _local_characters(con, query, limit=limit),
                    "artists": [],
                    "copyrights": [],
                }
            elif category_key in {"artist", "artists"}:
                entities = {
                    "characters": [],
                    "artists": _local_artists(con, query, limit=limit),
                    "copyrights": [],
                }
            elif category_key in {"copyright", "copyrights", "franchise", "franchises"}:
                entities = {
                    "characters": [],
                    "artists": [],
                    "copyrights": _local_copyrights(con, query, limit=limit),
                }
            else:
                entities = {
                    "characters": _local_characters(con, query, limit=limit),
                    "artists": _local_artists(con, query, limit=limit),
                    "copyrights": _local_copyrights(con, query, limit=limit),
                }
            result["entities"] = entities
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
    """Search characters in the owned profile and trait tables."""
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
    """Return a complete owned character profile."""
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
                    "This name exists as a tag but has no owned structured character profile."
                    if fallback else
                    "No structured character record or exact character tag was found."
                    + (" A likely character tag is included as a recommendation." if recommendation else "")
                ),
                "candidates": [row.get("slug") for row in rows[:10]],
                "recommendations": canonical_recommendations,
            }
        # Appearance is additive: legacy character fields remain unchanged.
        match["appearance"] = get_appearance_payload(con, slug)
        match["loras"] = []
        return {"found": True, **match}
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
def get_character_appearance(character: str, variant: Optional[str] = None,
                              include_evidence: bool = True,
                              limit: int = 100) -> dict:
    """Return canonical appearance and outfit cards with source evidence."""
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
            limit,
        )
        result = {**base, **result}
        if target.get("resolution"):
            result["resolution"] = target["resolution"]
        return result
    finally:
        con.close()


@mcp.tool()
def get_sources_status() -> dict:
    """Comprueba las fuentes locales de Weeb Alexandria."""
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
        # ensure_owned_schema() may modify a newly opened database; capture the
        # signature after that initialization before storing the cache entry.
        signature = _source_cache_key()
        counts = {}
        for table in ("tags", "wiki", "tag_aliases", "tag_implications",
                      "character_profiles", "trait_definitions",
                      "character_traits", "trait_system_metadata",
                      "character_appearance_profiles",
                      "character_appearance_features",
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
