#!/usr/bin/env python3

from __future__ import annotations

import argparse
from pathlib import Path

from e2b import Sandbox

from common import load_local_env, optional_env, required_env


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download a file from an existing sandbox.")
    parser.add_argument("--sandbox-id", help="Sandbox ID. Falls back to E2B_SANDBOX_ID.")
    parser.add_argument(
        "--remote-path",
        default="/tmp/test-3.18/sample_upload.txt",
        help="Remote sandbox file to read.",
    )
    parser.add_argument(
        "--local-path",
        default="/home/ubuntu/whz/infra/codex_artifacts/kits/test-3.18/downloaded_sample.txt",
        help="Local file path to save to.",
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

    sbx = Sandbox.connect(
        sandbox_id=sandbox_id,
        domain=domain,
        api_key=api_key,
    )

    content = sbx.files.read(args.remote_path)
    local_path = Path(args.local_path).expanduser().resolve()
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_text(content, encoding="utf-8")

    print("sandbox_id:", sandbox_id)
    print("remote_path:", args.remote_path)
    print("local_path:", str(local_path))
    print("bytes_downloaded:", len(content.encode("utf-8")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
