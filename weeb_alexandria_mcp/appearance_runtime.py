"""Read-only projection of canonical appearance rows into MCP cards."""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from typing import Any, Optional

from weeb_alexandria_mcp.appearance_schema import normalize_tag

PUBLISHED_STATUSES = ("reviewed", "published")


def _source_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "source_site": row["source_site"],
        "source_kind": row["source_kind"],
        "source_key": row["source_key"],
        "source_url": row["source_url"],
        "source_tier": row["source_tier"],
        "title": row["title"],
        "excerpt": row["excerpt"],
        "captured_at": row["captured_at"],
    }


def _feature_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "feature_id": row["feature_id"],
        "value": row["value"],
        "canonical_tag": row["canonical_tag"],
        "role": row["role"],
        "status": row["status"],
        "confidence": row["confidence"],
    }


def _appearance_profile(con: sqlite3.Connection, profile: sqlite3.Row,
                        include_evidence: bool, limit: int) -> dict[str, Any]:
    feature_rows = con.execute(
        """SELECT feature_id, facet, value, canonical_tag, role, status,
                  confidence, display_order
           FROM character_appearance_features
           WHERE appearance_key=? AND status IN (?, ?)
           ORDER BY facet, display_order, canonical_tag
           LIMIT ?""",
        (profile["appearance_key"], *PUBLISHED_STATUSES, limit),
    ).fetchall()
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in feature_rows:
        grouped[row["facet"]].append(_feature_dict(row))

    result: dict[str, Any] = {
        "appearance_key": profile["appearance_key"],
        "character_tag": profile["character_tag"],
        "variant_tag": profile["variant_tag"],
        "display_name": profile["display_name"],
        "appearance_kind": profile["appearance_kind"],
        "is_default": bool(profile["is_default"]),
        "status": profile["status"],
        "confidence": profile["confidence"],
        "provenance": profile["provenance"],
        "notes": profile["notes"],
        "features": dict(grouped),
        "feature_count": len(feature_rows),
        "sources": [],
        "evidence": [],
    }
    if not include_evidence or not feature_rows:
        return result

    source_rows = con.execute(
        """SELECT fs.feature_id, f.facet, f.canonical_tag,
                  fs.polarity, fs.observed_tag, fs.support_count,
                  fs.sample_size, fs.evidence_text, fs.confidence AS evidence_confidence,
                  s.source_site, s.source_kind, s.source_key, s.source_url,
                  s.source_tier, s.title, s.excerpt, s.captured_at
           FROM character_appearance_feature_sources fs
           JOIN character_appearance_features f ON f.feature_id=fs.feature_id
           JOIN character_appearance_sources s ON s.source_id=fs.source_id
           WHERE f.appearance_key=? AND f.status IN (?, ?)
           ORDER BY f.facet, f.canonical_tag, s.source_tier, s.source_site,
                    s.source_kind, s.source_key""",
        (profile["appearance_key"], *PUBLISHED_STATUSES),
    ).fetchall()
    source_keys: set[tuple[str, str, str]] = set()
    evidence: list[dict[str, Any]] = []
    for row in source_rows:
        source_key = (row["source_site"], row["source_kind"], row["source_key"])
        if source_key not in source_keys:
            source_keys.add(source_key)
            result["sources"].append(_source_dict(row))
        evidence.append({
            "feature_id": row["feature_id"],
            "facet": row["facet"],
            "canonical_tag": row["canonical_tag"],
            "polarity": row["polarity"],
            "observed_tag": row["observed_tag"],
            "support_count": row["support_count"],
            "sample_size": row["sample_size"],
            "evidence_text": row["evidence_text"],
            "confidence": row["evidence_confidence"],
            "source": _source_dict(row),
        })
    result["evidence"] = evidence
    return result


def get_appearance_payload(con: sqlite3.Connection, character_tag: str,
                           variant: Optional[str] = None,
                           include_evidence: bool = True,
                           limit: int = 100) -> dict[str, Any]:
    """Return canonical appearance profiles for one resolved character tag."""
    character_tag = normalize_tag(character_tag)
    requested_variant = normalize_tag(variant) if variant else None
    try:
        limit = max(1, min(500, int(limit)))
    except (TypeError, ValueError):
        limit = 100
    conditions = ["character_tag=?", "status IN (?, ?)"]
    params: list[Any] = [character_tag, *PUBLISHED_STATUSES]
    if requested_variant:
        conditions.append("variant_tag=?")
        params.append(requested_variant)
    sql = (
        """SELECT appearance_key, character_tag, variant_tag, display_name,
                  appearance_kind, is_default, status, confidence, provenance, notes
           FROM character_appearance_profiles
           WHERE """
        + " AND ".join(conditions)
        + """
           ORDER BY is_default DESC, display_name, appearance_key"""
    )
    profiles = con.execute(sql, params).fetchall()
    if not profiles:
        available = [row[0] for row in con.execute(
            """SELECT variant_tag FROM character_appearance_profiles
               WHERE character_tag=? AND status IN (?, ?)
               ORDER BY is_default DESC, variant_tag""",
            (character_tag, *PUBLISHED_STATUSES),
        ).fetchall()]
        return {
            "found": False,
            "character_tag": character_tag,
            "variant": requested_variant,
            "profiles": [],
            "available_variants": available,
            "message": (
                "No published appearance profile exists for this variant."
                if requested_variant else
                "No published appearance profile exists for this character."
            ),
        }
    return {
        "found": True,
        "character_tag": character_tag,
        "variant": requested_variant,
        "profiles": [
            _appearance_profile(con, profile, bool(include_evidence), limit)
            for profile in profiles
        ],
        "profile_count": len(profiles),
    }
