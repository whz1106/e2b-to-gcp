#!/usr/bin/env python3

from __future__ import annotations

import argparse

from e2b import Sandbox

from common import load_local_env, optional_env, required_env


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="List a directory inside an existing sandbox.")
    parser.add_argument("--sandbox-id", help="Sandbox ID. Falls back to E2B_SANDBOX_ID.")
    parser.add_argument("--path", default="/tmp/test-3.18", help="Directory path to list.")
    return parser.parse_args()


def main() -> int:
    load_local_env()
    args = parse_args()

    domain = required_env("E2B_DOMAIN")
    api_key = required_env("E2B_API_KEY")
    sandbox_id = args.sandbox_id or optional_env("E2B_SANDBOX_ID")
    if not sandbox_id:
        raise RuntimeError("missing sandbox id: pass --sandbox-id or set E2B_SANDBOX_ID")

    sbx = Sandbox.connect(
        sandbox_id=sandbox_id,
        domain=domain,
        api_key=api_key,
    )

    entries = sbx.files.list(args.path)
    print("sandbox_id:", sandbox_id)
    print("path:", args.path)
    print("entries:", [entry.name for entry in entries])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
