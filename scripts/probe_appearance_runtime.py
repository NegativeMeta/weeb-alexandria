#!/usr/bin/env python3
"""Read-only smoke probe for the owned appearance runtime."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=ROOT / "tag_library.db")
    parser.add_argument("--character", action="append", required=True)
    args = parser.parse_args()
    os.environ["TAGLIB_DB"] = str(args.db.resolve())

    from weeb_alexandria_mcp.appearance_runtime import get_appearance_payload
    from weeb_alexandria_mcp.server import _db

    connection = _db()
    try:
        payloads: dict[str, dict[str, Any]] = {}
        for character in args.character:
            payload = get_appearance_payload(connection, character, include_evidence=True)
            if not isinstance(payload, dict):
                raise RuntimeError(f"runtime returned a non-object payload for {character}")
            if "profiles" not in payload or "found" not in payload:
                raise RuntimeError(f"runtime payload is incomplete for {character}")
            payloads[character] = {
                "found": bool(payload["found"]),
                "profile_count": int(payload.get("profile_count", 0)),
            }
    finally:
        connection.close()

    print(json.dumps({
        "status": "ok",
        "characters": payloads,
    }, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
