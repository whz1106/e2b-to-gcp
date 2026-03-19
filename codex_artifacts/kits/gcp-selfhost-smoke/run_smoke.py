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


ROOT_DIR = Path(__file__).resolve().parents[3]
ENV_FILE = ROOT_DIR / ".env.dev"
GENERATED_ENV_FILE = Path(__file__).resolve().parent / ".env.generated"


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


def main() -> int:
    load_env_file(ENV_FILE)

    domain_name = required_env("DOMAIN_NAME")
    postgres_connection_string = required_env("POSTGRES_CONNECTION_STRING")

    api_key = f"e2b_{secrets.token_hex(16)}"
    access_token = f"sk_e2b_{secrets.token_hex(16)}"
    team_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())

    config = SmokeConfig(
        domain_name=domain_name,
        api_url=f"https://api.{domain_name}",
        postgres_connection_string=postgres_connection_string,
        api_key=api_key,
        access_token=access_token,
        team_id=team_id,
        user_id=user_id,
        template_id="",
    )

    write_generated_env(config)

    try:
        with psycopg.connect(
            config.postgres_connection_string,
            autocommit=True,
        ) as conn:
            seed_auth(conn, config)
            available_templates = list_templates(conn)
            config.template_id = choose_template(available_templates)

        log_step("Public API health check")
        assert_health(config)

        if not config.template_id:
            config.template_id = build_smoke_template(config)
        else:
            log_step(f"Selected existing template alias: {config.template_id}")

        sandbox = create_sandbox(config)
        try:
            exercise_sandbox(config, sandbox)
        finally:
            log_step(f"Destroying sandbox: {sandbox.sandbox_id}")
            sandbox.kill()

        print("\nSmoke test suite completed successfully.")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"\nSmoke test suite failed: {exc}", file=sys.stderr)
        return 1


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


def write_generated_env(config: SmokeConfig) -> None:
    GENERATED_ENV_FILE.write_text(
        "\n".join(
            [
                f"TESTS_API_SERVER_URL={config.api_url}",
                f"TESTS_E2B_API_KEY={config.api_key}",
                f"TESTS_E2B_ACCESS_TOKEN={config.access_token}",
                f"TESTS_SANDBOX_TEAM_ID={config.team_id}",
                f"TESTS_SANDBOX_USER_ID={config.user_id}",
                f"POSTGRES_CONNECTION_STRING={config.postgres_connection_string}",
                f"DOMAIN_NAME={config.domain_name}",
            ]
        )
        + "\n"
    )


def log_step(message: str) -> None:
    print(f"\n==> {message}")


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
    log_step("Seeding temporary auth data into Postgres")

    user_email = f"gcp-smoke-{config.user_id}@e2b.dev"
    team_slug = f"gcp-smoke-{config.team_id[:12]}"

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
            (
                config.team_id,
                user_email,
                "GCP Smoke Team",
                "base_v1",
                False,
                team_slug,
            ),
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
                "GCP self-host smoke access token",
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
                "GCP self-host smoke api key",
            ),
        )


def list_templates(conn: psycopg.Connection[Any]) -> list[tuple[str, str]]:
    log_step("Listing deployed template aliases")

    with conn.cursor() as cur:
        cur.execute(
            """
            select alias, env_id
            from env_aliases
            order by alias
            """
        )
        rows = [(row[0], str(row[1])) for row in cur.fetchall()]

    if rows:
        print("Available template aliases:")
        for alias, env_id in rows:
            print(f"  - {alias} -> {env_id}")
    else:
        print("No template aliases found in env_aliases.")

    return rows


def choose_template(aliases: list[tuple[str, str]]) -> str:
    preferred = os.getenv("TESTS_SANDBOX_TEMPLATE_ID", "").strip()
    if preferred:
        preferred_match = next((env_id for alias, env_id in aliases if alias == preferred), None)
        if preferred_match is None:
            print(
                f"Configured TESTS_SANDBOX_TEMPLATE_ID={preferred!r} not found in env_aliases, "
                "falling back to discovered aliases or auto-build."
            )
        else:
            return preferred_match

    # Existing aliases may belong to different teams and can return 403 for a newly
    # generated temporary smoke-test team. When there is no explicit usable template
    # configured, we prefer building a fresh temporary template for the current team.
    return ""


def build_smoke_template(config: SmokeConfig) -> str:
    build_name = f"gcp-smoke-{uuid.uuid4().hex[:12]}"

    log_step(f"Building temporary smoke template: {build_name}")

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
        "Built template successfully:",
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


def assert_health(config: SmokeConfig) -> None:
    response = requests.get(f"{config.api_url}/health", timeout=20)
    if response.status_code != 200:
        raise SmokeFailure(
            f"health check failed: status={response.status_code} body={response.text}"
        )

    print(f"Health OK: {response.text}")


def create_sandbox(config: SmokeConfig) -> Sandbox:
    log_step("Creating sandbox via Python SDK")
    sandbox = Sandbox.create(
        template=config.template_id,
        timeout=120,
        api_key=config.api_key,
        domain=config.domain_name,
    )
    print(f"Created sandbox: {sandbox.sandbox_id}")
    return sandbox


def exercise_sandbox(config: SmokeConfig, sandbox: Sandbox) -> None:
    log_step("Fetching sandbox info")
    info = sandbox.get_info()
    print(json.dumps(to_jsonable(info), indent=2, default=str))

    log_step("Checking envd health through SDK")
    if not sandbox.is_running():
        raise SmokeFailure("sandbox is not running according to envd health")

    log_step("Writing and reading files inside sandbox")
    sandbox.files.write("/tmp/gcp-smoke/hello.txt", "hello from python smoke\n")
    read_back = sandbox.files.read("/tmp/gcp-smoke/hello.txt")
    if "hello from python smoke" not in read_back:
        raise SmokeFailure(f"unexpected file content: {read_back!r}")

    entries = sandbox.files.list("/tmp/gcp-smoke")
    names = [entry.name for entry in entries]
    if "hello.txt" not in names:
        raise SmokeFailure(f"uploaded file not found in listing: {names}")
    print(f"Filesystem OK: entries={names}")

    log_step("Running foreground command")
    result = sandbox.commands.run("python3 -c \"print('sandbox-ok')\"")
    if result.exit_code != 0 or "sandbox-ok" not in result.stdout:
        raise SmokeFailure(
            f"foreground command failed: exit={result.exit_code} stdout={result.stdout!r} stderr={result.stderr!r}"
        )
    print(f"Foreground command OK: {result.stdout.strip()}")

    log_step("Testing outbound internet access from sandbox")
    network_result = sandbox.commands.run(
        "python3 - <<'PY'\n"
        "import urllib.request\n"
        "print(urllib.request.urlopen('https://example.com', timeout=10).status)\n"
        "PY"
    )
    if network_result.exit_code != 0 or "200" not in network_result.stdout:
        raise SmokeFailure(
            f"internet access test failed: exit={network_result.exit_code} stdout={network_result.stdout!r} stderr={network_result.stderr!r}"
        )
    print(f"Internet access OK: {network_result.stdout.strip()}")

    log_step("Starting background command")
    handle = sandbox.commands.run("sleep 120", background=True)
    time.sleep(2)

    processes = sandbox.commands.list()
    pids = [proc.pid for proc in processes]
    if handle.pid not in pids:
        raise SmokeFailure(f"background process pid {handle.pid} not found in {pids}")
    print(f"Background command visible in process list: pid={handle.pid}")

    log_step("Killing background command")
    sandbox.commands.kill(handle.pid)
    time.sleep(1)

    remaining = sandbox.commands.list()
    remaining_pids = [proc.pid for proc in remaining]
    if handle.pid in remaining_pids:
        raise SmokeFailure(
            f"background process pid {handle.pid} still running after kill: {remaining_pids}"
        )
    print("Background command kill OK")


if __name__ == "__main__":
    raise SystemExit(main())
