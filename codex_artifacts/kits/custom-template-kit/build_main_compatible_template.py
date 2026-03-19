#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import uuid
from datetime import datetime

from dotenv import load_dotenv
from e2b import Template, wait_for_port


DEFAULT_ALIAS = "main-code-interpreter"
CODE_INTERPRETER_IMAGE = "e2bdev/code-interpreter:latest"
CODE_INTERPRETER_SOURCE_CMD = "/root/.jupyter/start-up.sh"
CODE_INTERPRETER_START_CMD = "sudo bash /usr/local/bin/code-interpreter-start.sh"
CODE_INTERPRETER_PORT = 49999


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
        description="Build a template intended to run e2b_code_interpreter Sandbox.run_code().",
    )
    parser.add_argument("--alias", default=DEFAULT_ALIAS, help="Template alias prefix.")
    parser.add_argument("--cpu-count", type=int, default=2, help="CPU count for the template.")
    parser.add_argument(
        "--memory-mb",
        type=int,
        default=2048,
        help="Memory in MB for the template.",
    )
    return parser.parse_args()


def with_suffix(alias: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{alias}_{timestamp}_{uuid.uuid4().hex[:8]}"


def main() -> int:
    load_local_env()
    args = parse_args()

    domain = required_env("E2B_DOMAIN")
    api_key = required_env("E2B_API_KEY")
    alias = with_suffix(args.alias)

    # Code interpreter needs its own startup script; using only the base image is not enough.
    template = (
        Template()
        .from_image(CODE_INTERPRETER_IMAGE)
        .run_cmd(
            "sudo cp /root/.jupyter/start-up.sh /usr/local/bin/code-interpreter-start.sh"
            " && sudo chmod 755 /usr/local/bin/code-interpreter-start.sh"
        )
        .set_start_cmd(
        CODE_INTERPRETER_START_CMD,
        wait_for_port(CODE_INTERPRETER_PORT),
        )
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
    print("base_image:", CODE_INTERPRETER_IMAGE)
    print("source_start_cmd:", CODE_INTERPRETER_SOURCE_CMD)
    print("start_cmd:", CODE_INTERPRETER_START_CMD)
    print("ready_port:", CODE_INTERPRETER_PORT)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
