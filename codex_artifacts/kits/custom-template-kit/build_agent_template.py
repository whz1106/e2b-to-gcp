#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import uuid
from datetime import datetime

from dotenv import load_dotenv
from e2b import Template


DEFAULT_ALIAS = "dynamic_agent_sandbox"


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
        description="Build a custom self-hosted E2B template from business code.",
    )
    parser.add_argument(
        "--alias",
        default=DEFAULT_ALIAS,
        help="Template alias prefix.",
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
        default=2048,
        help="Memory in MB for the built template.",
    )
    parser.add_argument(
        "--with-playwright",
        action="store_true",
        help="Install Playwright and Chromium during template build.",
    )
    return parser.parse_args()


def with_suffix(alias: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{alias}_{timestamp}_{uuid.uuid4().hex[:8]}"


def build_template(*, alias: str, cpu_count: int, memory_mb: int, with_playwright: bool) -> None:
    domain = required_env("E2B_DOMAIN")
    api_key = required_env("E2B_API_KEY")

    # Start from the code interpreter image so run_code() capable workloads have the right base.
    template = (
        Template()
        .from_image("e2bdev/code-interpreter:latest")
        .run_cmd("python3 --version")
        .run_cmd("pip install python-dotenv requests pandas")
        .run_cmd("npm install -g npm@latest", user="root")
    )

    if with_playwright:
        template = template.run_cmd(
            "npx playwright install chromium --with-deps",
            user="root",
        )

    build = Template.build(
        template,
        alias=alias,
        cpu_count=cpu_count,
        memory_mb=memory_mb,
        api_key=api_key,
        domain=domain,
        on_build_logs=lambda entry: print(f"[build] {entry.message}"),
    )

    print("alias:", build.alias)
    print("template_id:", build.template_id)
    print("build_id:", build.build_id)
    print("cpu_count:", cpu_count)
    print("memory_mb:", memory_mb)
    print("base_image:", "e2bdev/code-interpreter:latest")


def main() -> None:
    load_local_env()
    args = parse_args()
    alias = with_suffix(args.alias)
    build_template(
        alias=alias,
        cpu_count=args.cpu_count,
        memory_mb=args.memory_mb,
        with_playwright=args.with_playwright,
    )


if __name__ == "__main__":
    main()
