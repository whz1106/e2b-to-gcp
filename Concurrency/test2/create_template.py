#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

from e2b import Template


DEFAULT_ALIAS_PREFIX = "test4"
DEFAULT_CPU_COUNT = 1
DEFAULT_MEMORY_MB = 4096
EXPECTED_TEAM_DISK_MB = 10240
BASE_IMAGE = "e2bdev/code-interpreter:latest"


def load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        os.environ.setdefault(key, value)


def load_local_env() -> None:
    root = Path(__file__).resolve().parents[1]
    load_env_file(root / ".env")
    load_env_file(root / ".env.local")


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"missing required env: {name}")
    return value


def unique_alias(prefix: str) -> str:
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{ts}_{uuid.uuid4().hex[:8]}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a test2 template for self-hosted E2B concurrency tests.",
    )
    parser.add_argument(
        "--alias-prefix",
        default=DEFAULT_ALIAS_PREFIX,
        help="Template alias prefix. A unique suffix will be appended automatically.",
    )
    parser.add_argument(
        "--alias",
        help="Exact template alias. If provided, --alias-prefix is ignored.",
    )
    parser.add_argument(
        "--cpu-count",
        type=int,
        default=DEFAULT_CPU_COUNT,
        help="Requested template CPU count. Default: 1.",
    )
    parser.add_argument(
        "--memory-mb",
        type=int,
        default=DEFAULT_MEMORY_MB,
        help="Requested template memory in MB. Default: 1024.",
    )
    parser.add_argument(
        "--expected-disk-mb",
        type=int,
        default=EXPECTED_TEAM_DISK_MB,
        help=(
            "Expected disk size inherited from the current team tier. "
            "This is informational only. Default: 10240."
        ),
    )
    return parser.parse_args()


def main() -> int:
    load_local_env()
    args = parse_args()

    domain = required_env("E2B_DOMAIN")
    api_key = required_env("E2B_API_KEY")
    alias = args.alias.strip() if args.alias else unique_alias(args.alias_prefix)

    template = (
        Template()
        .from_image(BASE_IMAGE)
        .run_cmd("python3 --version")
        .run_cmd("pip install python-dotenv requests", user="root")
    )

    build = Template.build(
        template,
        alias=alias,
        cpu_count=args.cpu_count,
        memory_mb=args.memory_mb,
        api_key=api_key,
        domain=domain,
        on_build_logs=lambda entry: print(f"[build] {entry.message}"),
    )

    print("alias:", build.alias)
    print("template_id:", build.template_id)
    print("build_id:", build.build_id)
    print("cpu_count:", args.cpu_count)
    print("memory_mb:", args.memory_mb)
    print("disk_mb:", args.expected_disk_mb, "(inherited from current team limit)")
    print("base_image:", BASE_IMAGE)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
