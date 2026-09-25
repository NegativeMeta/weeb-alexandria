"""Normalize category labels in an existing combined-source snapshot.

Run without --apply to preview. Applying creates a SQLite backup first.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "tag_library.db"
DEFAULT_BACKUP_DIR = ROOT / "data" / "backups"
sys.path.insert(0, str(ROOT))

from weeb_alexandria_mcp.tag_categories import CATEGORY_NAMES_BY_SOURCE  # noqa: E402


def _changes(con: sqlite3.Connection) -> list[tuple[int, str, int]]:
    mapping = CATEGORY_NAMES_BY_SOURCE["combined"]
    changes = []
    for category, desired_name in mapping.items():
        if category_name_is_numeric(category):
            category_id = int(category)
            count = con.execute(
                "SELECT count(*) FROM tags WHERE site='combined' AND category=? "
                "AND category_name IS NOT ?",
                (category_id, desired_name),
            ).fetchone()[0]
            if count:
                changes.append((category_id, desired_name, int(count)))
    return changes


def category_name_is_numeric(value: str) -> bool:
    return value.isdigit()


def _backup(source: sqlite3.Connection, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = backup_dir / f"tag_library_before_category_normalization_{stamp}.sqlite"
    suffix = 1
    while backup.exists():
        backup = backup_dir / (
            f"tag_library_before_category_normalization_{stamp}_{suffix}.sqlite"
        )
        suffix += 1
    destination = sqlite3.connect(str(backup))
    try:
        source.backup(destination)
        destination.commit()
    finally:
        destination.close()
    return backup


def normalize(db_path: Path, backup_dir: Path, apply: bool) -> tuple[int, int]:
    db_path = db_path.resolve()
    if not db_path.is_file():
        raise FileNotFoundError(db_path)

    read_uri = f"file:{db_path.as_posix()}?mode=ro"
    preview = sqlite3.connect(read_uri, uri=True)
    try:
        changes = _changes(preview)
        for category_id, desired, count in changes:
            current = preview.execute(
                "SELECT DISTINCT category_name FROM tags "
                "WHERE site='combined' AND category=? AND category_name IS NOT ? "
                "ORDER BY category_name LIMIT 3",
                (category_id, desired),
            ).fetchall()
            labels = ", ".join(repr(row[0]) for row in current)
            print(f"combined category {category_id}: {labels} -> {desired} ({count} tags)")
        if not changes:
            print("No combined-source category labels need normalization.")
            return 0, 0
        if not apply:
            print("Preview only. Re-run with --apply to write the changes.")
            return 0, 0

        backup = _backup(preview, backup_dir)
        print(f"Backup created: {backup}")
    finally:
        preview.close()

    updated_tags = 0
    updated_wiki = 0
    mapping = CATEGORY_NAMES_BY_SOURCE["combined"]
    with sqlite3.connect(str(db_path), timeout=30) as con:
        try:
            con.execute("BEGIN IMMEDIATE")
            for category, desired_name in mapping.items():
                if not category_name_is_numeric(category):
                    continue
                cursor = con.execute(
                    "UPDATE tags SET category_name=? WHERE site='combined' "
                    "AND category=? AND category_name IS NOT ?",
                    (desired_name, int(category), desired_name),
                )
                updated_tags += cursor.rowcount
            cursor = con.execute(
                "UPDATE wiki SET category_name=("
                "SELECT t.category_name FROM tags t "
                "WHERE t.site='combined' AND t.name=wiki.title) "
                "WHERE site='combined' AND EXISTS ("
                "SELECT 1 FROM tags t WHERE t.site='combined' "
                "AND t.name=wiki.title AND t.category_name IS NOT wiki.category_name)"
            )
            updated_wiki = cursor.rowcount
            con.commit()
        except BaseException:
            con.rollback()
            raise
    print(f"Normalized {updated_tags} combined tag rows and {updated_wiki} wiki rows.")
    return updated_tags, updated_wiki


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    parser.add_argument("--apply", action="store_true", help="back up and apply the changes")
    args = parser.parse_args()
    normalize(args.db, args.backup_dir, args.apply)


if __name__ == "__main__":
    main()
