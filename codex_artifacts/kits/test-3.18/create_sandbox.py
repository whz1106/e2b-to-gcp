#!/usr/bin/env python3

from __future__ import annotations

import argparse

from e2b_code_interpreter import Sandbox

from common import load_local_env, optional_env, required_env, write_env_value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a sandbox from a template.")
    parser.add_argument("--template-id", help="Template ID to use. Falls back to E2B_TEMPLATE_ID.")
    parser.add_argument("--timeout", type=int, default=120, help="Sandbox timeout in seconds.")
    return parser.parse_args()


def main() -> int:
    load_local_env()
    args = parse_args()

    domain = required_env("E2B_DOMAIN")
    api_key = required_env("E2B_API_KEY")
    template_id = args.template_id or optional_env("E2B_TEMPLATE_ID")
    if not template_id:
        raise RuntimeError("missing template id: pass --template-id or set E2B_TEMPLATE_ID")

    sbx = Sandbox.create(
        domain=domain,
        api_key=api_key,
        template=template_id,
        timeout=args.timeout,
    )

    write_env_value("E2B_SANDBOX_ID", sbx.sandbox_id)

    print("sandbox_id:", sbx.sandbox_id)
    print("template_id:", template_id)
    print("timeout:", args.timeout)
    print("saved_to_env:", "E2B_SANDBOX_ID")
    print("note: this sandbox is still running until timeout or manual kill")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
