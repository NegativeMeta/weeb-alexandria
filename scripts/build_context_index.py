"""Build the derived character-context index used by the MCP searcher."""
from __future__ import annotations

import argparse
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "tag_library.db"
DEFAULT_OUTPUT = ROOT / "data" / "character_context.sqlite"
LINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")
WORD_RE = re.compile(r"[a-z0-9][a-z0-9:+!/-]{2,}", re.IGNORECASE)


def normalize(value: str) -> str:
    return " ".join(WORD_RE.findall((value or "").lower()))


def build(source: Path, output: Path) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()
    out = sqlite3.connect(output)
    out.executescript(
        """
        PRAGMA journal_mode=WAL;
        CREATE TABLE character_context (
            tag TEXT NOT NULL,
            context TEXT NOT NULL,
            source TEXT NOT NULL,
            PRIMARY KEY(tag, context, source)
        );
        CREATE INDEX idx_character_context_context ON character_context(context);
        CREATE INDEX idx_character_context_tag ON character_context(tag);
        """
    )
    src = sqlite3.connect(source)
    src.row_factory = sqlite3.Row
    context_terms = set()
    for row in src.execute(
        "SELECT name, aliases FROM tags WHERE category_name='copyright'"
    ):
        context_terms.update(WORD_RE.findall((row["name"] or "").lower()))
        context_terms.update(WORD_RE.findall((row["aliases"] or "").lower()))
    src.execute("CREATE TEMP TABLE character_names AS SELECT DISTINCT lower(name) AS name FROM tags WHERE category_name='character'")
    src.execute("CREATE INDEX idx_temp_character_names ON character_names(name)")
    rows = src.execute(
        """
        SELECT w.title, w.body, w.other_names, w.site
        FROM wiki w JOIN character_names c ON lower(w.title)=c.name
        WHERE w.body IS NOT NULL AND trim(w.body) <> ''
        """
    )
    batch = []
    count = 0
    for row in rows:
        tag = row["title"].lower()
        text = " ".join((row["body"] or "", row["other_names"] or ""))
        links = LINK_RE.findall(text)
        text += " " + " ".join(links)
        words = set(WORD_RE.findall(text.lower()))
        contexts = (words & context_terms) | {
            word for link in links for word in WORD_RE.findall(link.lower())
        }
        for context in contexts:
            batch.append((tag, context, row["site"] or "wiki"))
        if len(batch) >= 10000:
            out.executemany("INSERT OR IGNORE INTO character_context VALUES (?,?,?)", batch)
            count += len(batch)
            batch.clear()
    if batch:
        out.executemany("INSERT OR IGNORE INTO character_context VALUES (?,?,?)", batch)
        count += len(batch)
    out.commit()
    src.close()
    out.close()
    return count


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(f"Inserted context rows: {build(args.source, args.output)}")
