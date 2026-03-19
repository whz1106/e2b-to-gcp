#!/usr/bin/env python3

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import sys
import time
import uuid
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any

import psycopg
import requests
from e2b import Sandbox, Template


ENV_FILE = Path(".env.local")


class SmokeFailure(RuntimeError):
    pass


@dataclass
class SmokeConfig:
    domain_name: str
    api_url: str
    postgres_connection_string: str
    api_key: str
    access_token: str
    team_id: str
    user_id: str
    template_id: str


def load_env_file(path: Path) -> None:
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value.startswith(("'", '"')) and value.endswith(("'", '"')):
            value = value[1:-1]
        os.environ.setdefault(key, value)


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SmokeFailure(f"required env {name} is missing")
    return value


def to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return {key: to_jsonable(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    return value


def hash_key(raw_hex_value: str) -> str:
    digest = hashlib.sha256(bytes.fromhex(raw_hex_value)).digest()
    return "$sha256$" + base64.b64encode(digest).decode().rstrip("=")


def seed_auth(conn: psycopg.Connection[Any], config: SmokeConfig) -> None:
    user_email = f"mac-smoke-{config.user_id}@e2b.dev"
    team_slug = f"mac-smoke-{config.team_id[:12]}"

    api_key_value = config.api_key[len("e2b_") :]
    access_token_value = config.access_token[len("sk_e2b_") :]

    with conn.cursor() as cur:
        cur.execute(
            """
            insert into auth.users (id, email)
            values (%s, %s)
            on conflict (id) do nothing
            """,
            (config.user_id, user_email),
        )
        cur.execute(
            """
            insert into teams (id, email, name, tier, is_blocked, slug)
            values (%s, %s, %s, %s, %s, %s)
            on conflict (id) do nothing
            """,
            (config.team_id, user_email, "Mac Smoke Team", "base_v1", False, team_slug),
        )
        cur.execute(
            """
            insert into users_teams (user_id, team_id, is_default)
            values (%s, %s, %s)
            on conflict do nothing
            """,
            (config.user_id, config.team_id, True),
        )
        cur.execute(
            """
            insert into access_tokens (
                id,
                user_id,
                access_token_hash,
                access_token_prefix,
                access_token_length,
                access_token_mask_prefix,
                access_token_mask_suffix,
                name,
                created_at
            ) values (%s, %s, %s, %s, %s, %s, %s, %s, now())
            """,
            (
                str(uuid.uuid4()),
                config.user_id,
                hash_key(access_token_value),
                "sk_e2b_",
                len(access_token_value),
                access_token_value[:2],
                access_token_value[-4:],
                "Mac smoke access token",
            ),
        )
        cur.execute(
            """
            insert into team_api_keys (
                team_id,
                created_by,
                updated_at,
                api_key_hash,
                api_key_prefix,
                api_key_length,
                api_key_mask_prefix,
                api_key_mask_suffix,
                name,
                created_at
            ) values (%s, %s, now(), %s, %s, %s, %s, %s, %s, now())
            """,
            (
                config.team_id,
                config.user_id,
                hash_key(api_key_value),
                "e2b_",
                len(api_key_value),
                api_key_value[:2],
                api_key_value[-4:],
                "Mac smoke api key",
            ),
        )


def build_template(config: SmokeConfig) -> str:
    build_name = f"mac-smoke-{uuid.uuid4().hex[:12]}"

    template = (
        Template()
        .from_ubuntu_image("22.04")
        .apt_install(["python3", "curl"])
        .set_start_cmd("sleep infinity", "python3 --version")
    )

    build_info = Template.build(
        template,
        name=build_name,
        api_key=config.api_key,
        domain=config.domain_name,
        cpu_count=2,
        memory_mb=1024,
        on_build_logs=lambda entry: print(f"[build] {entry.message}"),
    )

    print(
        "build:",
        json.dumps(
            {
                "template_id": build_info.template_id,
                "build_id": build_info.build_id,
                "name": build_info.name,
            },
            indent=2,
        ),
    )

    return build_info.template_id


def main() -> int:
    load_env_file(ENV_FILE)

    domain_name = required_env("DOMAIN_NAME")
    postgres_connection_string = required_env("POSTGRES_CONNECTION_STRING")

    config = SmokeConfig(
        domain_name=domain_name,
        api_url=f"https://api.{domain_name}",
        postgres_connection_string=postgres_connection_string,
        api_key=f"e2b_{secrets.token_hex(16)}",
        access_token=f"sk_e2b_{secrets.token_hex(16)}",
        team_id=str(uuid.uuid4()),
        user_id=str(uuid.uuid4()),
        template_id="",
    )

    try:
        with psycopg.connect(config.postgres_connection_string, autocommit=True) as conn:
            seed_auth(conn, config)

        health = requests.get(f"{config.api_url}/health", timeout=20)
        print("health:", health.status_code, health.text)
        health.raise_for_status()

        config.template_id = build_template(config)

        sandbox = Sandbox.create(
            template=config.template_id,
            timeout=120,
            api_key=config.api_key,
            domain=config.domain_name,
        )
        print("sandbox_id:", sandbox.sandbox_id)

        try:
            info = sandbox.get_info()
            print(json.dumps(to_jsonable(info), indent=2, default=str))

            if not sandbox.is_running():
                raise SmokeFailure("sandbox is not running")

            sandbox.files.write("/tmp/mac-full/hello.txt", "hello from mac full smoke\n")
            print("read:", repr(sandbox.files.read("/tmp/mac-full/hello.txt")))
            print("files:", [entry.name for entry in sandbox.files.list("/tmp/mac-full")])

            command = sandbox.commands.run("python3 -c \"print('sandbox-ok')\"")
            print("foreground:", command.exit_code, command.stdout.strip(), command.stderr.strip())

            network = sandbox.commands.run(
                "python3 - <<'PY'\n"
                "import urllib.request\n"
                "print(urllib.request.urlopen('https://example.com', timeout=10).status)\n"
                "PY"
            )
            print("internet:", network.exit_code, network.stdout.strip(), network.stderr.strip())

            background = sandbox.commands.run("sleep 60", background=True)
            time.sleep(2)
            print("pids:", [proc.pid for proc in sandbox.commands.list()])
            sandbox.commands.kill(background.pid)
            print("killed pid:", background.pid)
        finally:
            sandbox.kill()
            print("sandbox destroyed")

        return 0
    except Exception as exc:  # noqa: BLE001
        print("FAILED:", exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
