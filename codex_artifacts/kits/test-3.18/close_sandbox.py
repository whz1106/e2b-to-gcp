#!/usr/bin/env python3

from __future__ import annotations

import argparse

from e2b import Sandbox

from common import ENV_FILE, load_local_env, optional_env, required_env, write_env_value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Destroy an existing sandbox.")
    parser.add_argument("--sandbox-id", help="Sandbox ID. Falls back to E2B_SANDBOX_ID.")
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
    sbx.kill()
    write_env_value("E2B_SANDBOX_ID", "")

    print("sandbox_id:", sandbox_id)
    print("status:", "destroyed")
    print("env_file:", str(ENV_FILE))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
