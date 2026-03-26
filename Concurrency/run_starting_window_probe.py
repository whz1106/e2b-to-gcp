#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from e2b import Sandbox

from run_concurrency_test import (
    DEFAULT_COMMAND,
    DEFAULT_ENV_FILE,
    LOCAL_ENV_FILE,
    classify_error,
    detect_environment,
    load_env_file,
    required_env,
    seconds_stats,
    wait_for_clean_environment,
)


@dataclass
class ProbeResult:
    index: int
    success: bool
    sandbox_id: str | None
    create_seconds: float
    command_seconds: float
    hold_seconds: int
    exit_code: int | None
    stdout: str
    stderr: str
    error_type: str | None
    error_message: str | None
    fast_failure: bool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Probe whether a single client hits the starting-sandbox window during burst creation."
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=6,
        help="How many Sandbox.create() requests to fire concurrently. Default: 6.",
    )
    parser.add_argument(
        "--hold-seconds",
        type=int,
        default=120,
        help="How long to keep successful sandboxes alive before cleanup.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=180,
        help="Sandbox timeout in seconds passed to Sandbox.create().",
    )
    parser.add_argument(
        "--command",
        default=DEFAULT_COMMAND,
        help="Lightweight command to run inside each sandbox.",
    )
    parser.add_argument("--template-id", help="Template ID or alias. Falls back to E2B_TEMPLATE_ID.")
    parser.add_argument("--domain", help="E2B domain. Falls back to E2B_DOMAIN.")
    parser.add_argument("--api-key", help="E2B API key. Falls back to E2B_API_KEY.")
    parser.add_argument(
        "--fast-failure-seconds",
        type=float,
        default=3.0,
        help="Create failures faster than this are treated as fast placement failures.",
    )
    parser.add_argument("--no-cleanup", action="store_true", help="Do not kill successful sandboxes at the end.")
    parser.add_argument("--output-json", help="Optional path to write the full JSON result.")
    parser.add_argument(
        "--wait-for-clean-seconds",
        type=int,
        default=240,
        help="Wait up to this many seconds for existing sandboxes to disappear before starting the test.",
    )
    parser.add_argument(
        "--precheck-poll-seconds",
        type=int,
        default=10,
        help="Polling interval in seconds while waiting for a clean environment.",
    )
    parser.add_argument(
        "--force-cleanup-before-start",
        action="store_true",
        help="Try to kill existing running sandboxes for this team before starting the test.",
    )
    return parser.parse_args()


def run_probe_worker(
    index: int,
    domain: str,
    api_key: str,
    template_id: str,
    timeout: int,
    command: str,
    hold_seconds: int,
    cleanup: bool,
    fast_failure_seconds: float,
) -> ProbeResult:
    sandbox: Sandbox | None = None
    create_started = time.perf_counter()
    command_seconds = 0.0

    try:
        sandbox = Sandbox.create(
            template=template_id,
            timeout=timeout,
            api_key=api_key,
            domain=domain,
        )
        create_seconds = time.perf_counter() - create_started

        command_started = time.perf_counter()
        result = sandbox.commands.run(command)
        command_seconds = time.perf_counter() - command_started

        if result.exit_code != 0:
            return ProbeResult(
                index=index,
                success=False,
                sandbox_id=sandbox.sandbox_id,
                create_seconds=create_seconds,
                command_seconds=command_seconds,
                hold_seconds=hold_seconds,
                exit_code=result.exit_code,
                stdout=result.stdout.strip(),
                stderr=result.stderr.strip(),
                error_type="command_failed",
                error_message="command_failed",
                fast_failure=False,
            )

        if hold_seconds > 0:
            time.sleep(hold_seconds)

        return ProbeResult(
            index=index,
            success=True,
            sandbox_id=sandbox.sandbox_id,
            create_seconds=create_seconds,
            command_seconds=command_seconds,
            hold_seconds=hold_seconds,
            exit_code=result.exit_code,
            stdout=result.stdout.strip(),
            stderr=result.stderr.strip(),
            error_type=None,
            error_message=None,
            fast_failure=False,
        )
    except Exception as exc:  # noqa: BLE001
        error_message = str(exc)
        create_seconds = time.perf_counter() - create_started
        return ProbeResult(
            index=index,
            success=False,
            sandbox_id=sandbox.sandbox_id if sandbox else None,
            create_seconds=create_seconds,
            command_seconds=command_seconds,
            hold_seconds=hold_seconds,
            exit_code=None,
            stdout="",
            stderr="",
            error_type=classify_error(error_message),
            error_message=error_message,
            fast_failure=create_seconds <= fast_failure_seconds,
        )
    finally:
        if sandbox is not None and cleanup:
            try:
                sandbox.kill()
            except Exception:
                pass


def print_result(result: ProbeResult) -> None:
    status = "OK" if result.success else "FAIL"
    sandbox_id = result.sandbox_id or "-"
    print(
        f"[{status}] worker={result.index} sandbox_id={sandbox_id} "
        f"create={result.create_seconds:.2f}s command={result.command_seconds:.2f}s"
    )
    if result.error_type:
        print(f"  error_type: {result.error_type}")
    if result.fast_failure:
        print("  fast_failure: true")
    if result.error_message:
        print(f"  error_message: {result.error_message}")


def summarize(results: list[ProbeResult], started: float, cleanup: bool, fast_failure_seconds: float) -> dict:
    success_results = [item for item in results if item.success]
    failed_results = [item for item in results if not item.success]
    placement_failed = [item for item in failed_results if item.error_type == "placement_failed"]
    fast_placement_failed = [item for item in placement_failed if item.fast_failure]
    timeout_failures = [item for item in failed_results if item.error_type == "timeout"]
    total_duration = time.perf_counter() - started

    inferred_starting_window_pressure = bool(fast_placement_failed)
    inferred_starting_window_size = len(success_results) if inferred_starting_window_pressure else None

    return {
        "total": len(results),
        "success": len(success_results),
        "failed": len(failed_results),
        "success_rate": round((len(success_results) / len(results)) * 100, 2) if results else 0.0,
        "cleanup_enabled": cleanup,
        "total_duration_seconds": round(total_duration, 2),
        "fast_failure_seconds": fast_failure_seconds,
        "create_seconds_stats": seconds_stats([item.create_seconds for item in results]),
        "command_seconds_stats": seconds_stats([item.command_seconds for item in results]),
        "placement_failed_count": len(placement_failed),
        "fast_placement_failed_count": len(fast_placement_failed),
        "timeout_count": len(timeout_failures),
        "inferred_starting_window_pressure": inferred_starting_window_pressure,
        "inferred_starting_window_size": inferred_starting_window_size,
        "note": (
            "Fast placement_failed results usually mean the single client had no free starting slots. "
            "This probes burst create pressure, not the final running sandbox capacity."
        ),
    }


def main() -> int:
    load_env_file(DEFAULT_ENV_FILE)
    load_env_file(LOCAL_ENV_FILE)
    args = parse_args()

    if args.concurrency <= 0:
        raise RuntimeError("--concurrency must be greater than 0")
    if args.hold_seconds < 0:
        raise RuntimeError("--hold-seconds must be >= 0")
    if args.fast_failure_seconds <= 0:
        raise RuntimeError("--fast-failure-seconds must be > 0")

    domain = (args.domain or "").strip() or required_env("E2B_DOMAIN")
    api_key = (args.api_key or "").strip() or required_env("E2B_API_KEY")
    template_id = (args.template_id or "").strip() or required_env("E2B_TEMPLATE_ID")
    cleanup = not args.no_cleanup

    wait_for_clean_environment(
        domain=domain,
        api_key=api_key,
        max_wait_seconds=args.wait_for_clean_seconds,
        poll_interval_seconds=args.precheck_poll_seconds,
        force_cleanup=args.force_cleanup_before_start,
    )

    test_time = datetime.now(UTC).isoformat()
    test_id = f"starting-window-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{args.concurrency}"
    environment = detect_environment()

    print("Starting-window probe started")
    print(f"domain: {domain}")
    print(f"template_id: {template_id}")
    print(f"concurrency: {args.concurrency}")
    print(f"hold_seconds: {args.hold_seconds}")
    print(f"timeout: {args.timeout}")
    print(f"fast_failure_seconds: {args.fast_failure_seconds}")
    print(f"cleanup: {cleanup}")
    print("")

    started = time.perf_counter()
    results: list[ProbeResult] = []

    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [
            executor.submit(
                run_probe_worker,
                index,
                domain,
                api_key,
                template_id,
                args.timeout,
                args.command,
                args.hold_seconds,
                cleanup,
                args.fast_failure_seconds,
            )
            for index in range(1, args.concurrency + 1)
        ]

        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print_result(result)

    results.sort(key=lambda item: item.index)
    summary = summarize(results, started, cleanup, args.fast_failure_seconds)

    payload = {
        "meta": {
            "test_id": test_id,
            "test_time": test_time,
            "environment": environment,
            "domain": domain,
            "template_id": template_id,
            "concurrency": args.concurrency,
            "hold_seconds": args.hold_seconds,
            "timeout": args.timeout,
            "fast_failure_seconds": args.fast_failure_seconds,
            "cleanup": cleanup,
            "command": args.command,
        },
        "summary": summary,
        "results": [asdict(item) for item in results],
    }

    print("")
    print("Summary")
    print(json.dumps(summary, indent=2))

    if args.output_json:
        output_path = Path(args.output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"json_report: {output_path}")

    return 1 if summary["failed"] > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
