#!/usr/bin/env python3
"""Promote the batch-42 seeds (two passes for idempotence)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROMOTE = ROOT / "scripts" / "promote_appearance.py"
SEEDS = ROOT / "seeds" / "appearance"

SEED_FILES = [
    "bea_(pokemon).json",
    "fischl_(genshin_impact).json",
    "hifumi_(blue_archive).json",
    "ultimate_madoka.json",
    "robin_(honkai_fullwidth_colon_star_rail).json",
    "kishin_sagume.json",
]


def run(seed: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(PROMOTE), "--input", str(SEEDS / seed)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )


def main() -> int:
    overall_fail = False
    for pass_i in (1, 2):
        print(f"\n=== PROMOTION PASS {pass_i} ===")
        any_fail = False
        for seed in SEED_FILES:
            r = run(seed)
            status = "OK" if r.returncode == 0 else "FAIL"
            if r.returncode != 0:
                any_fail = True
            print(f"[{status}] {seed}")
            if r.stdout.strip():
                print("  stdout:", r.stdout.strip().replace("\n", " | "))
            if r.stderr.strip():
                print("  stderr:", r.stderr.strip().replace("\n", " | "))
        if any_fail:
            overall_fail = True
            print(f"pass {pass_i} had failures")
    return 1 if overall_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
