#!/usr/bin/env python3
"""Promote several reviewed appearance seeds in one SQLite transaction."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.promote_appearance import promote_batch  # noqa: E402

DEFAULT_DB = ROOT / "tag_library.db"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument(
        "--input",
        dest="inputs",
        type=Path,
        action="append",
        required=True,
        help="reviewed appearance seed; repeat once per seed",
    )
    args = parser.parse_args()
    result: dict[str, Any] = promote_batch(args.db, args.inputs)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
