#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import uuid

from dotenv import load_dotenv
from e2b import Template


def load_local_env() -> None:
    load_dotenv(".env.local")
    load_dotenv()


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"missing required env: {name}")
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a custom template on a self-hosted E2B cluster.",
    )
    parser.add_argument(
        "--alias",
        default="custom-code-interpreter",
        help="Template alias. A short random suffix is added automatically.",
    )
    parser.add_argument(
        "--cpu-count",
        type=int,
        default=2,
        help="CPU count for the built template.",
    )
    parser.add_argument(
        "--memory-mb",
        type=int,
        default=1024,
        help="Memory in MB for the built template.",
    )
    return parser.parse_args()


def main() -> int:
    load_local_env()
    args = parse_args()

    domain = required_env("E2B_DOMAIN")
    api_key = required_env("E2B_API_KEY")

    alias = f"{args.alias}-{uuid.uuid4().hex[:8]}"

    # Start from the official code interpreter image, then add your own tools.
    template = (
        Template()
        .from_image("e2bdev/code-interpreter:latest")
        .run_cmd("python3 --version")
        .run_cmd("pip install python-dotenv requests")
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

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
