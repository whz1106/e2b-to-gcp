#!/usr/bin/env python3

from __future__ import annotations

from e2b import Template, wait_for_port

from common import (
    CODE_INTERPRETER_IMAGE,
    READY_PORT,
    STARTUP_SOURCE,
    STARTUP_TARGET,
    START_CMD,
    load_local_env,
    required_env,
    unique_alias,
    write_env_value,
)


def main() -> int:
    load_local_env()

    domain = required_env("E2B_DOMAIN")
    api_key = required_env("E2B_API_KEY")
    alias = unique_alias("test-3-18")

    template = (
        Template()
        .from_image(CODE_INTERPRETER_IMAGE)
        .run_cmd(
            f"sudo cp {STARTUP_SOURCE} {STARTUP_TARGET}"
            f" && sudo chmod 755 {STARTUP_TARGET}"
        )
        .set_start_cmd(START_CMD, wait_for_port(READY_PORT))
    )

    build = Template.build(
        template,
        alias=alias,
        cpu_count=2,
        memory_mb=2048,
        api_key=api_key,
        domain=domain,
        on_build_logs=lambda entry: print(f"[build] {entry.message}"),
    )

    write_env_value("E2B_TEMPLATE_ID", build.template_id)

    print("alias:", build.alias)
    print("template_id:", build.template_id)
    print("build_id:", build.build_id)
    print("saved_to_env:", "E2B_TEMPLATE_ID")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
