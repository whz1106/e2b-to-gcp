#!/usr/bin/env python3

from __future__ import annotations

import argparse
from pathlib import Path

from e2b import Sandbox

from common import load_local_env, optional_env, required_env


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Upload a local file into an existing sandbox.")
    parser.add_argument("--sandbox-id", help="Sandbox ID. Falls back to E2B_SANDBOX_ID.")
    parser.add_argument(
        "--local-path",
        default="/home/ubuntu/whz/infra/codex_artifacts/kits/test-3.18/sample_upload.txt",
        help="Local file to upload.",
    )
    parser.add_argument(
        "--remote-path",
        default="/tmp/test-3.18/sample_upload.txt",
        help="Remote sandbox path to write to.",
    )
    return parser.parse_args()


def main() -> int:
    load_local_env()
    args = parse_args()

    domain = required_env("E2B_DOMAIN")
    api_key = required_env("E2B_API_KEY")
    sandbox_id = args.sandbox_id or optional_env("E2B_SANDBOX_ID")
    if not sandbox_id:
        raise RuntimeError("missing sandbox id: pass --sandbox-id or set E2B_SANDBOX_ID")

    local_path = Path(args.local_path).expanduser().resolve()
    if not local_path.is_file():
        raise FileNotFoundError(f"local file not found: {local_path}")

    sbx = Sandbox.connect(
        sandbox_id=sandbox_id,
        domain=domain,
        api_key=api_key,
    )

    content = local_path.read_text(encoding="utf-8")
    sbx.files.write(args.remote_path, content)

    print("sandbox_id:", sandbox_id)
    print("local_path:", str(local_path))
    print("remote_path:", args.remote_path)
    print("bytes_uploaded:", len(content.encode("utf-8")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
