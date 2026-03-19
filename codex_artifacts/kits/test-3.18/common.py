#!/usr/bin/env python3

from __future__ import annotations

import os
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv


CODE_INTERPRETER_IMAGE = "e2bdev/code-interpreter:latest"
STARTUP_SOURCE = "/root/.jupyter/start-up.sh"
STARTUP_TARGET = "/usr/local/bin/code-interpreter-start.sh"
START_CMD = f"sudo bash {STARTUP_TARGET}"
READY_PORT = 49999
KIT_DIR = Path(__file__).resolve().parent
ENV_FILE = KIT_DIR / ".env.local"
ENV_ALIASES = {
    "E2B_DOMAIN": "TESTS_API_SERVER_URL",
    "E2B_API_KEY": "TESTS_E2B_API_KEY",
    "E2B_TEMPLATE_ID": "TESTS_SANDBOX_TEMPLATE_ID",
}


def load_local_env() -> None:
    load_dotenv(ENV_FILE)
    load_dotenv()


def required_env(name: str) -> str:
    value = resolve_env(name)
    if not value:
        raise RuntimeError(f"missing required env: {name}")
    return value


def optional_env(name: str) -> str | None:
    value = resolve_env(name)
    return value or None


def unique_alias(prefix: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{timestamp}_{uuid.uuid4().hex[:8]}"


def write_env_value(name: str, value: str) -> None:
    lines: list[str] = []
    if ENV_FILE.exists():
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines()

    updated = False
    output: list[str] = []
    for line in lines:
        if line.startswith(f"{name}="):
            output.append(f"{name}={value}")
            updated = True
        else:
            output.append(line)

    if not updated:
        output.append(f"{name}={value}")

    ENV_FILE.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")


def resolve_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if value:
        return value

    alias = ENV_ALIASES.get(name)
    if not alias:
        return ""

    alias_value = os.getenv(alias, "").strip()
    if not alias_value:
        return ""

    if name == "E2B_DOMAIN":
        parsed = urlparse(alias_value)
        return parsed.netloc or parsed.path

    return alias_value
