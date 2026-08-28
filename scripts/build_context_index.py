"""Build the derived character/franchise context index used by the MCP searcher."""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "tag_library.db"
DEFAULT_OUTPUT = ROOT / "data" / "character_context.sqlite"
LINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")
WORD_RE = re.compile(r"[a-z0-9][a-z0-9:+!/-]{2,}", re.IGNORECASE)
COMMON_WORDS = {
    "about", "also", "and", "are", "from", "has", "into", "more", "not",
    "one", "that", "the", "their", "this", "with", "you",
}


def terms(value: str) -> set[str]:
    return {
        word for word in WORD_RE.findall((value or "").lower())
        if word not in COMMON_WORDS
    }


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


def build(source: Path, output: Path) -> tuple[int, int]:
    source = source.resolve()
    output = output.resolve()
    if source == output:
        raise ValueError("The context index must be separate from the source database")
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
        out.executescript(
            """
            PRAGMA journal_mode=DELETE;
            PRAGMA synchronous=NORMAL;
            CREATE TABLE character_context (
                tag TEXT NOT NULL,
                context TEXT NOT NULL,
                source TEXT NOT NULL,
                PRIMARY KEY(tag, context, source)
            );
            CREATE INDEX idx_character_context_context_tag
                ON character_context(context, tag);
            CREATE INDEX idx_character_context_tag ON character_context(tag);
            CREATE TABLE character_work_context (
                tag TEXT NOT NULL,
                work_tag TEXT NOT NULL,
                matched_terms TEXT NOT NULL,
                score INTEGER NOT NULL,
                source TEXT NOT NULL,
                PRIMARY KEY(tag, work_tag, source)
            );
            CREATE INDEX idx_character_work_context_tag_cover
                ON character_work_context(tag, score DESC, work_tag, matched_terms);
            CREATE INDEX idx_character_work_context_work ON character_work_context(work_tag);
            CREATE TABLE context_index_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )

        works: dict[str, set[str]] = {}
        works_by_term: dict[str, set[str]] = {}
        for row in src.execute(
            "SELECT name, aliases FROM tags WHERE category_name='copyright'"
        ):
            work = (row["name"] or "").lower()
            work_terms = terms(work) | terms(row["aliases"] or "")
            if not work_terms:
                continue
            works.setdefault(work, set()).update(work_terms)
        for work, work_terms in works.items():
            for word in work_terms:
                works_by_term.setdefault(word, set()).add(work)
        context_terms = set(works_by_term)

        src.execute(
            "CREATE TEMP TABLE character_names AS "
            "SELECT DISTINCT lower(name) AS name FROM tags "
            "WHERE category_name='character'"
        )
        src.execute("CREATE INDEX idx_temp_character_names ON character_names(name)")
        rows = src.execute(
            """
            SELECT w.title, w.body, w.other_names, w.site
            FROM wiki w JOIN character_names c ON lower(w.title)=c.name
            WHERE w.body IS NOT NULL AND trim(w.body) <> ''
            """
        )

        context_batch: list[tuple[str, str, str]] = []
        work_batch: list[tuple[str, str, str, int, str]] = []
        context_count = 0
        work_count = 0
        character_wiki_rows = 0
        for row in rows:
            character_wiki_rows += 1
            tag = row["title"].lower()
            text = " ".join((row["body"] or "", row["other_names"] or ""))
            links = LINK_RE.findall(text)
            text += " " + " ".join(links)
            words = terms(text)
            contexts = (words & context_terms) | {
                word for link in links for word in terms(link)
            }
            source_name = row["site"] or "wiki"
            for context in contexts:
                context_batch.append((tag, context, source_name))

            candidate_works: set[str] = set()
            for word in words:
                if word in works_by_term:
                    candidate_works.update(works_by_term[word])
            scored = []
            for work in candidate_works:
                matched = words & works[work]
                if matched:
                    scored.append((len(matched), work, matched))
            if scored:
                best_score = max(score for score, _, _ in scored)
                for score, work, matched in scored:
                    if score == best_score and (score >= 2 or len(scored) == 1):
                        work_batch.append((
                            tag, work, ",".join(sorted(matched)), score, source_name
                        ))

            if len(context_batch) >= 10000:
                out.executemany(
                    "INSERT OR IGNORE INTO character_context VALUES (?,?,?)",
                    context_batch,
                )
                context_count += len(context_batch)
                context_batch.clear()
            if len(work_batch) >= 5000:
                out.executemany(
                    "INSERT OR IGNORE INTO character_work_context VALUES (?,?,?,?,?)",
                    work_batch,
                )
                work_count += len(work_batch)
                work_batch.clear()

        if context_batch:
            out.executemany(
                "INSERT OR IGNORE INTO character_context VALUES (?,?,?)",
                context_batch,
            )
            context_count += len(context_batch)
        if work_batch:
            out.executemany(
                "INSERT OR IGNORE INTO character_work_context VALUES (?,?,?,?,?)",
                work_batch,
            )
            work_count += len(work_batch)

        stat = source.stat()
        metadata = {
            "schema_version": "3",
            "source_db": str(source),
            "source_size": str(stat.st_size),
            "source_sha256": source_hash,
            "source_wal_size": str(_sidecar_signature(source, "-wal")[0]),
            "source_wal_mtime_ns": str(_sidecar_signature(source, "-wal")[1]),
            "character_wiki_rows": str(character_wiki_rows),
            "context_rows": str(out.execute(
                "SELECT count(*) FROM character_context"
            ).fetchone()[0]),
            "work_rows": str(out.execute(
                "SELECT count(*) FROM character_work_context"
            ).fetchone()[0]),
        }
        out.executemany(
            "INSERT INTO context_index_metadata(key, value) VALUES (?,?)",
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

    os.replace(str(temporary), str(output))
    _remove_artifacts(output, include_main=False)
    return context_count, work_count


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    context_count, work_count = build(args.source, args.output)
    print(f"Inserted context rows: {context_count}")
    print(f"Inserted work relations: {work_count}")
