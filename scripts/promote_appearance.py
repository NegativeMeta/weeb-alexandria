#!/usr/bin/env python3
"""Promote an explicitly reviewed appearance seed into the owned schema.

This is intentionally separate from the statistical candidate builder. The
input must name every source used by every published feature.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from weeb_alexandria_mcp.appearance_schema import (  # noqa: E402
    appearance_kind_for_variant,
    ensure_appearance_schema,
    humanize_tag,
    normalize_tag,
)
from weeb_alexandria_mcp.owned_schema import ensure_owned_schema  # noqa: E402

DEFAULT_DB = ROOT / "tag_library.db"


def read_seed(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("appearance seed must be a JSON object")
    if not data.get("character_tag"):
        raise ValueError("appearance seed requires character_tag")
    if not isinstance(data.get("sources"), list) or not data["sources"]:
        raise ValueError("appearance seed requires a non-empty sources list")
    if not isinstance(data.get("profiles"), list) or not data["profiles"]:
        raise ValueError("appearance seed requires a non-empty profiles list")
    return data


def stable_appearance_key(character_tag: str, variant_tag: str) -> str:
    return (
        f"{character_tag}::default"
        if variant_tag == character_tag
        else f"{character_tag}::{variant_tag}"
    )


def source_ref(source: dict[str, Any]) -> str:
    return str(source.get("id") or "")


_PUBLISHED_STATUSES = {"reviewed", "published"}


def validate_registered_character(
    con: sqlite3.Connection, character_tag: str, raw_character_tag: str | None = None
) -> None:
    owned = con.execute(
        "SELECT 1 FROM character_profiles WHERE character_tag=? LIMIT 1",
        (character_tag,),
    ).fetchone()
    canonical = con.execute(
        """SELECT 1 FROM tags
           WHERE name=? AND category_name='character' LIMIT 1""",
        (character_tag,),
    ).fetchone()
    if canonical is None and raw_character_tag and raw_character_tag != character_tag:
        canonical = con.execute(
            """SELECT 1 FROM tags
               WHERE name=? AND category_name='character' LIMIT 1""",
            (raw_character_tag,),
        ).fetchone()
    if owned is None and canonical is None:
        raise ValueError(
            f"character_tag is not registered as an owned profile or canonical character tag: "
            f"{character_tag}"
        )


def validate_seed_profiles(character_tag: str, profiles: list[Any]) -> None:
    seen_profile_keys: set[str] = set()
    for profile in profiles:
        if not isinstance(profile, dict):
            raise ValueError("each profile must be a JSON object")
        variant_tag = normalize_tag(str(profile.get("variant_tag", "") or character_tag))
        expected_key = stable_appearance_key(character_tag, variant_tag)
        profile_key = str(profile.get("appearance_key") or expected_key)
        if profile_key != expected_key:
            raise ValueError(
                f"appearance_key must be {expected_key!r} for profile {variant_tag!r}"
            )
        if variant_tag != character_tag and not variant_tag.startswith(character_tag + "_("):
            raise ValueError(
                f"variant_tag {variant_tag!r} is not scoped to {character_tag!r}"
            )
        status = str(profile.get("status", "published"))
        if status not in _PUBLISHED_STATUSES:
            raise ValueError(
                f"profile {profile_key} must be reviewed or published, got {status!r}"
            )
        if profile_key in seen_profile_keys:
            raise ValueError(f"duplicate appearance profile in seed: {profile_key}")
        seen_profile_keys.add(profile_key)
        features = profile.get("features", [])
        if not isinstance(features, list):
            raise ValueError(f"features must be a list for {profile_key}")
        seen_tags: set[str] = set()
        for feature in features:
            if not isinstance(feature, dict):
                raise ValueError(f"feature must be an object for {profile_key}")
            canonical_tag = normalize_tag(str(feature.get("canonical_tag", "")))
            facet = normalize_tag(str(feature.get("facet", "")))
            if not canonical_tag or not facet:
                raise ValueError(
                    f"feature requires facet and canonical_tag for {profile_key}"
                )
            if canonical_tag in seen_tags:
                raise ValueError(
                    f"duplicate canonical_tag in profile {profile_key}: {canonical_tag}"
                )
            seen_tags.add(canonical_tag)
            feature_status = str(feature.get("status", "published"))
            if feature_status not in _PUBLISHED_STATUSES:
                raise ValueError(
                    f"feature {profile_key}/{canonical_tag} must be reviewed or published, "
                    f"got {feature_status!r}"
                )


def upsert_source(con: sqlite3.Connection, source: dict[str, Any]) -> int:
    required = ("id", "source_site", "source_kind", "source_key", "source_tier")
    missing = [key for key in required if source.get(key) in (None, "")]
    if missing:
        raise ValueError(f"source missing required fields: {', '.join(missing)}")
    con.execute(
        """INSERT INTO character_appearance_sources(
            source_site, source_kind, source_key, source_url, source_tier,
            title, excerpt, captured_at, source_sha256
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_site, source_kind, source_key) DO UPDATE SET
            source_url=excluded.source_url,
            source_tier=excluded.source_tier,
            title=excluded.title,
            excerpt=excluded.excerpt,
            captured_at=excluded.captured_at,
            source_sha256=excluded.source_sha256""",
        (
            normalize_tag(str(source["source_site"])),
            normalize_tag(str(source["source_kind"])),
            str(source["source_key"]),
            str(source.get("source_url", "")),
            int(source["source_tier"]),
            str(source.get("title", "")),
            str(source.get("excerpt", "")),
            str(source.get("captured_at", "")),
            str(source.get("source_sha256", "")),
        ),
    )
    row = con.execute(
        """SELECT source_id FROM character_appearance_sources
           WHERE source_site=? AND source_kind=? AND source_key=?""",
        (
            normalize_tag(str(source["source_site"])),
            normalize_tag(str(source["source_kind"])),
            str(source["source_key"]),
        ),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"could not retrieve source {source_ref(source)}")
    return int(row[0])


def upsert_profile(con: sqlite3.Connection, character_tag: str,
                   profile: dict[str, Any]) -> str:
    variant_tag = normalize_tag(str(profile.get("variant_tag", "") or character_tag))
    key = str(profile.get("appearance_key") or stable_appearance_key(character_tag, variant_tag))
    kind = str(profile.get("appearance_kind") or appearance_kind_for_variant(variant_tag, character_tag))
    con.execute(
        """INSERT INTO character_appearance_profiles(
            appearance_key, character_tag, variant_tag, display_name,
            appearance_kind, is_default, status, confidence, provenance, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(appearance_key) DO UPDATE SET
            character_tag=excluded.character_tag,
            variant_tag=excluded.variant_tag,
            display_name=excluded.display_name,
            appearance_kind=excluded.appearance_kind,
            is_default=excluded.is_default,
            status=excluded.status,
            confidence=excluded.confidence,
            provenance=excluded.provenance,
            notes=excluded.notes""",
        (
            key,
            character_tag,
            variant_tag,
            str(profile.get("display_name") or variant_tag),
            kind,
            int(bool(profile.get("is_default", variant_tag == character_tag))),
            str(profile.get("status", "published")),
            str(profile.get("confidence", "high")),
            str(profile.get("provenance", "booru_reviewed")),
            str(profile.get("notes", "")),
        ),
    )
    return key


def upsert_conflicts(con: sqlite3.Connection, profile_key: str,
                     conflicts: list[Any], source_ids: dict[str, int]) -> int:
    if not isinstance(conflicts, list):
        raise ValueError(f"conflicts must be a list for {profile_key}")
    count = 0
    for conflict in conflicts:
        if not isinstance(conflict, dict):
            raise ValueError(f"conflict must be an object for {profile_key}")
        key = normalize_tag(str(conflict.get("conflict_key", "")))
        facet = normalize_tag(str(conflict.get("facet", "")))
        alternatives = conflict.get("alternatives", [])
        refs = conflict.get("source_refs", [])
        if not key or not facet or not isinstance(alternatives, list) or len(alternatives) < 2:
            raise ValueError(f"conflict requires key, facet, and two alternatives for {profile_key}")
        if not isinstance(refs, list) or not refs:
            raise ValueError(f"conflict has no evidence: {profile_key}/{key}")
        missing = sorted(set(str(ref) for ref in refs) - source_ids.keys())
        if missing:
            raise ValueError(f"unknown conflict source refs for {profile_key}/{key}: {missing}")
        con.execute(
            """INSERT INTO character_appearance_conflicts(
                appearance_key, facet, conflict_key, alternatives_json, status,
                reason, source_refs_json, resolution_note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(appearance_key, conflict_key) DO UPDATE SET
                facet=excluded.facet, alternatives_json=excluded.alternatives_json,
                status=excluded.status, reason=excluded.reason,
                source_refs_json=excluded.source_refs_json,
                resolution_note=excluded.resolution_note""",
            (profile_key, facet, key, json.dumps(alternatives, sort_keys=True),
             str(conflict.get("status", "open")), str(conflict.get("reason", "")),
             json.dumps([str(ref) for ref in refs], sort_keys=True),
             str(conflict.get("resolution_note", ""))),
        )
        count += 1
    return count


def promote(db: Path, seed_path: Path) -> dict[str, int]:
    data = read_seed(seed_path)
    character_tag = normalize_tag(str(data["character_tag"]))
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    try:
        ensure_owned_schema(con)
        validate_registered_character(con, character_tag, str(data["character_tag"]))
        validate_seed_profiles(character_tag, data["profiles"])
        con.execute("BEGIN")
        sources: dict[str, int] = {}
        for source in data["sources"]:
            if not isinstance(source, dict):
                raise ValueError("each source must be a JSON object")
            ref = source_ref(source)
            if not ref or ref in sources:
                raise ValueError(f"source ids must be unique and non-empty: {ref!r}")
            sources[ref] = upsert_source(con, source)

        profile_count = 0
        feature_count = 0
        link_count = 0
        conflict_count = 0
        for profile in data["profiles"]:
            if not isinstance(profile, dict):
                raise ValueError("each profile must be a JSON object")
            profile_key = upsert_profile(con, character_tag, profile)
            profile_count += 1
            features = profile.get("features", [])
            if not isinstance(features, list):
                raise ValueError(f"features must be a list for {profile_key}")
            if profile.get("replace_features", False):
                seed_tags = {
                    normalize_tag(str(feature.get("canonical_tag", "")))
                    for feature in features
                    if isinstance(feature, dict)
                }
                if not seed_tags:
                    raise ValueError(
                        f"replace_features requires at least one feature for {profile_key}"
                    )
                placeholders = ",".join("?" for _ in seed_tags)
                con.execute(
                    f"""UPDATE character_appearance_features
                        SET status='retired'
                        WHERE appearance_key=?
                          AND status<>'retired'
                          AND canonical_tag NOT IN ({placeholders})""",
                    [profile_key, *sorted(seed_tags)],
                )
            for feature in features:
                if not isinstance(feature, dict):
                    raise ValueError(f"feature must be an object for {profile_key}")
                canonical_tag = normalize_tag(str(feature.get("canonical_tag", "")))
                facet = normalize_tag(str(feature.get("facet", "")))
                source_refs = feature.get("source_refs", [])
                if not canonical_tag or not facet:
                    raise ValueError(f"feature requires facet and canonical_tag for {profile_key}")
                if not isinstance(source_refs, list) or not source_refs:
                    raise ValueError(f"published feature has no evidence: {profile_key}/{canonical_tag}")
                missing = sorted(set(str(ref) for ref in source_refs) - sources.keys())
                if missing:
                    raise ValueError(f"unknown source refs for {profile_key}/{canonical_tag}: {missing}")
                con.execute(
                    """INSERT INTO character_appearance_features(
                        appearance_key, facet, value, canonical_tag, role, status,
                        confidence, display_order
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(appearance_key, facet, canonical_tag) DO UPDATE SET
                        value=excluded.value,
                        role=excluded.role,
                        status=excluded.status,
                        confidence=excluded.confidence,
                        display_order=excluded.display_order""",
                    (
                        profile_key,
                        facet,
                        str(feature.get("value") or humanize_tag(canonical_tag)),
                        canonical_tag,
                        str(feature.get("role", "present")),
                        str(feature.get("status", "published")),
                        str(feature.get("confidence", "high")),
                        int(feature.get("display_order", 0)),
                    ),
                )
                feature_row = con.execute(
                    """SELECT feature_id FROM character_appearance_features
                       WHERE appearance_key=? AND facet=? AND canonical_tag=?""",
                    (profile_key, facet, canonical_tag),
                ).fetchone()
                if feature_row is None:
                    raise RuntimeError(f"could not retrieve feature {profile_key}/{canonical_tag}")
                feature_id = int(feature_row[0])
                feature_count += 1
                for ref in source_refs:
                    evidence = feature.get("evidence", {})
                    if not isinstance(evidence, dict):
                        evidence = {}
                    con.execute(
                        """INSERT INTO character_appearance_feature_sources(
                            feature_id, source_id, polarity, observed_tag,
                            support_count, sample_size, evidence_text, confidence
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(feature_id, source_id) DO UPDATE SET
                            polarity=excluded.polarity,
                            observed_tag=excluded.observed_tag,
                            support_count=excluded.support_count,
                            sample_size=excluded.sample_size,
                            evidence_text=excluded.evidence_text,
                            confidence=excluded.confidence""",
                        (
                            feature_id,
                            sources[str(ref)],
                            str(evidence.get("polarity", "supports")),
                            normalize_tag(str(evidence.get("observed_tag", canonical_tag))),
                            evidence.get("support_count"),
                            evidence.get("sample_size"),
                            str(evidence.get("text", "Reviewed from the cited source.")),
                            str(evidence.get("confidence", feature.get("confidence", "high"))),
                        ),
                    )
                    link_count += 1
            conflict_count += upsert_conflicts(
                con, profile_key, profile.get("conflicts", []), sources
            )
        con.execute(
            "INSERT OR REPLACE INTO appearance_schema_metadata(key, value) VALUES (?, ?)",
            ("last_promoted_seed", str(seed_path.resolve())),
        )
        con.execute(
            "INSERT OR REPLACE INTO appearance_schema_metadata(key, value) VALUES (?, ?)",
            ("last_promoted_at", datetime.now(timezone.utc).isoformat()),
        )
        con.commit()
        return {
            "profiles": profile_count,
            "features": feature_count,
            "evidence_links": link_count,
            "sources": len(sources),
            "conflicts": conflict_count,
        }
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    for key, value in promote(args.db, args.input).items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
