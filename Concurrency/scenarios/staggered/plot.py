#!/usr/bin/env python3

from __future__ import annotations

import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

DEFAULT_INPUT_DIR = ROOT_DIR / "results" / "test-3.24"
DEFAULT_OUTPUT_DIR = ROOT_DIR / "plots" / "test-3.24"

from plot_results import main  # noqa: E402


if __name__ == "__main__":
    if len(sys.argv) == 1:
        sys.argv.extend(
            [
                "--input-dir",
                str(DEFAULT_INPUT_DIR),
                "--output-dir",
                str(DEFAULT_OUTPUT_DIR),
            ]
        )
    raise SystemExit(main())
