"""Build the optional derived FTS5 index used by the MCP tag search."""
from __future__ import annotations

import argparse
import hashlib
import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "tag_library.db"
DEFAULT_OUTPUT = ROOT / "data" / "tag_search.sqlite"
BATCH_SIZE = 10_000


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _remove_artifacts(path: Path, include_main: bool = True) -> None:
    suffixes = ("", "-wal", "-shm") if include_main else ("-wal", "-shm")
    for suffix in suffixes:
        candidate = Path(str(path) + suffix)
        if not candidate.exists():
            continue
        if candidate.is_dir():
            raise IsADirectoryError(candidate)
        candidate.unlink()


def _sidecar_signature(path: Path, suffix: str) -> tuple[int, int]:
    try:
        stat = Path(str(path) + suffix).stat()
    except OSError:
        return (-1, -1)
    return stat.st_size, stat.st_mtime_ns


def build(source: Path, output: Path) -> tuple[int, str]:
    """Build a standalone FTS5 index from the source tag table."""
    source = source.resolve()
    output = output.resolve()
    if source == output:
        raise ValueError("The FTS5 index must be separate from the source database")
    if not source.exists():
        raise FileNotFoundError(source)
    if output.is_dir():
        raise IsADirectoryError(output)

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(str(output) + ".tmp")
    _remove_artifacts(temporary)

    source_hash = sha256(source)
    src = sqlite3.connect(str(source))
    src.row_factory = sqlite3.Row
    out: sqlite3.Connection | None = None
    try:
        out = sqlite3.connect(str(temporary))
        total = 0
        out.execute("PRAGMA journal_mode=DELETE")
        out.execute("PRAGMA synchronous=NORMAL")
        out.executescript(
            """
            PRAGMA user_version = 1;
            CREATE TABLE tag_search_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE tag_search USING fts5(
                site UNINDEXED,
                name,
                category_name UNINDEXED,
                post_count UNINDEXED,
                aliases,
                nsfw UNINDEXED,
                tokenize='unicode61'
            );
            """
        )
        rows = src.execute(
            "SELECT site, name, category_name, post_count, aliases, nsfw "
            "FROM tags ORDER BY site, name"
        )
        batch: list[tuple[object, ...]] = []
        for row in rows:
            batch.append(tuple(row))
            if len(batch) >= BATCH_SIZE:
                out.executemany(
                    "INSERT INTO tag_search "
                    "(site, name, category_name, post_count, aliases, nsfw) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    batch,
                )
                total += len(batch)
                batch.clear()
        if batch:
            out.executemany(
                "INSERT INTO tag_search "
                "(site, name, category_name, post_count, aliases, nsfw) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                batch,
            )
            total += len(batch)

        metadata = {
            "schema_version": "1",
            "source_db": str(source),
            "source_size": str(source.stat().st_size),
            "source_sha256": source_hash,
            "source_wal_size": str(_sidecar_signature(source, "-wal")[0]),
            "source_wal_mtime_ns": str(_sidecar_signature(source, "-wal")[1]),
            "indexed_rows": str(total),
        }
        out.executemany(
            "INSERT INTO tag_search_metadata(key, value) VALUES (?, ?)",
            metadata.items(),
        )
        out.commit()
    except BaseException:
        if out is not None:
            out.close()
        src.close()
        try:
            _remove_artifacts(temporary)
        except OSError:
            pass
        raise
    else:
        if out is not None:
            out.close()
        src.close()

    # os.replace/Path.replace is atomic on one filesystem. If it fails, the
    # previous output remains intact and the temporary can be inspected/retried.
    temporary.replace(output)
    _remove_artifacts(output, include_main=False)
    return total, source_hash


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    indexed_rows, source_hash = build(args.source, args.output)
    print(f"Indexed tag rows: {indexed_rows}")
    print(f"Source SHA-256: {source_hash}")
    print(f"Index -> {args.output.resolve()}")
