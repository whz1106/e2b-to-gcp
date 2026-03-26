#!/usr/bin/env python3

from __future__ import annotations

import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from run_concurrency_profile_test import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
