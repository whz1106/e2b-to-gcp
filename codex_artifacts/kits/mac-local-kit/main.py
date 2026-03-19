#!/usr/bin/env python3

from __future__ import annotations

import os

from dotenv import load_dotenv
from e2b_code_interpreter import Sandbox


def load_local_env() -> None:
    # Prefer a local file in this folder, then fall back to the default .env lookup.
    load_dotenv(".env.local")
    load_dotenv()


def optional_env(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return value or None


def main() -> int:
    load_local_env()

    create_kwargs: dict[str, str | int] = {}

    domain = optional_env("E2B_DOMAIN")
    api_key = optional_env("E2B_API_KEY")
    template_id = optional_env("E2B_TEMPLATE_ID")
    timeout = optional_env("E2B_TIMEOUT")

    if domain:
        create_kwargs["domain"] = domain
    if api_key:
        create_kwargs["api_key"] = api_key
    if template_id:
        create_kwargs["template"] = template_id
    if timeout:
        create_kwargs["timeout"] = int(timeout)

    with Sandbox.create(**create_kwargs) as sbx:
        print("sandbox_id:", sbx.sandbox_id)

        execution = sbx.run_code("print('hello world')")
        print("execution.logs:", execution.logs)

        files = sbx.files.list("/")
        print("files:", files)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
