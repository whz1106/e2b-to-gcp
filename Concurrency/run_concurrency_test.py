#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from e2b import Sandbox


ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_ENV_FILE = ROOT_DIR / ".env"
LOCAL_ENV_FILE = ROOT_DIR / ".env.local"
REPO_ROOT = ROOT_DIR.parent
DEFAULT_COMMAND = 'python3 -c "print(\\"concurrency-ok\\")"'


@dataclass
class WorkerResult:
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


def load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for line in path.read_text(encoding="utf-8").splitlines():
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
        raise RuntimeError(f"missing required env: {name}")
    return value


def detect_environment() -> str:
    env = os.getenv("TERRAFORM_ENVIRONMENT", "").strip()
    if env:
        return env

    last_used_env = REPO_ROOT / ".last_used_env"
    if last_used_env.exists():
        value = last_used_env.read_text(encoding="utf-8").strip()
        if value:
            return value

    return "unknown"


def classify_error(message: str) -> str:
    lowered = message.lower()
    if "429" in lowered:
        return "api_limit"
    if "failed to place sandbox" in lowered:
        return "placement_failed"
    if "404" in lowered:
        return "not_found"
    if "500" in lowered:
        return "server_error"
    if "timed out" in lowered or "timeout" in lowered:
        return "timeout"
    if "peer closed connection" in lowered or "incomplete chunked read" in lowered:
        return "connection_closed"
    return "unknown"


def seconds_stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {
            "min": 0.0,
            "max": 0.0,
            "avg": 0.0,
        }
    return {
        "min": round(min(values), 2),
        "max": round(max(values), 2),
        "avg": round(sum(values) / len(values), 2),
    }


def list_running_sandboxes(domain: str, api_key: str) -> list[Any]:
    paginator = Sandbox.list(api_key=api_key, domain=domain, limit=100)
    sandboxes: list[Any] = []

    while True:
        sandboxes.extend(paginator.next_items())
        if not paginator.has_next:
            break

    return sandboxes


def wait_for_clean_environment(
    domain: str,
    api_key: str,
    max_wait_seconds: int,
    poll_interval_seconds: int,
    force_cleanup: bool,
) -> None:
    deadline = time.monotonic() + max_wait_seconds
    cleaned_ids: set[str] = set()

    while True:
        sandboxes = list_running_sandboxes(domain, api_key)
        sandbox_ids = [getattr(item, "sandbox_id", "") for item in sandboxes if getattr(item, "sandbox_id", "")]

        if not sandbox_ids:
            print("precheck: environment is clean")
            return

        print(f"precheck: detected {len(sandbox_ids)} running sandbox(es): {', '.join(sandbox_ids)}")

        if force_cleanup:
            for sandbox_id in sandbox_ids:
                if sandbox_id in cleaned_ids:
                    continue
                try:
                    Sandbox.connect(sandbox_id=sandbox_id, api_key=api_key, domain=domain).kill()
                    cleaned_ids.add(sandbox_id)
                    print(f"precheck: cleanup requested for sandbox_id={sandbox_id}")
                except Exception as exc:  # noqa: BLE001
                    print(f"precheck: failed to cleanup sandbox_id={sandbox_id}: {exc}")

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError(
                f"environment not clean after waiting {max_wait_seconds}s; "
                f"still running: {', '.join(sandbox_ids)}"
            )

        time.sleep(min(poll_interval_seconds, max(1, int(remaining))))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create multiple sandboxes concurrently and run a lightweight command."
    )
    parser.add_argument("--concurrency", type=int, required=True, help="Number of concurrent sandboxes.")
    parser.add_argument(
        "--hold-seconds",
        type=int,
        default=120,
        help="How long to keep each successful sandbox alive before cleanup.",
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
    parser.add_argument(
        "--template-id",
        help="Template ID to use. Falls back to E2B_TEMPLATE_ID.",
    )
    parser.add_argument(
        "--domain",
        help="E2B domain. Falls back to E2B_DOMAIN.",
    )
    parser.add_argument(
        "--api-key",
        help="E2B API key. Falls back to E2B_API_KEY.",
    )
    parser.add_argument(
        "--no-cleanup",
        action="store_true",
        help="Do not kill successful sandboxes at the end.",
    )
    parser.add_argument(
        "--output-json",
        help="Optional path to write the full JSON result.",
    )
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


def run_worker(
    index: int,
    domain: str,
    api_key: str,
    template_id: str,
    timeout: int,
    command: str,
    hold_seconds: int,
    cleanup: bool,
) -> WorkerResult:
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
            return WorkerResult(
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
            )

        if hold_seconds > 0:
            time.sleep(hold_seconds)

        return WorkerResult(
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
        )
    except Exception as exc:  # noqa: BLE001
        error_message = str(exc)
        return WorkerResult(
            index=index,
            success=False,
            sandbox_id=sandbox.sandbox_id if sandbox else None,
            create_seconds=time.perf_counter() - create_started,
            command_seconds=command_seconds,
            hold_seconds=hold_seconds,
            exit_code=None,
            stdout="",
            stderr="",
            error_type=classify_error(error_message),
            error_message=error_message,
        )
    finally:
        if sandbox is not None and cleanup:
            try:
                sandbox.kill()
            except Exception:
                pass


def print_result(result: WorkerResult) -> None:
    status = "OK" if result.success else "FAIL"
    sandbox_id = result.sandbox_id or "-"
    print(
        f"[{status}] "
        f"worker={result.index} "
        f"sandbox_id={sandbox_id} "
        f"create={result.create_seconds:.2f}s "
        f"command={result.command_seconds:.2f}s"
    )

    if result.stdout:
        print(f"  stdout: {result.stdout}")
    if result.stderr:
        print(f"  stderr: {result.stderr}")
    if result.error_type:
        print(f"  error_type: {result.error_type}")
    if result.error_message:
        print(f"  error_message: {result.error_message}")


def summarize(results: list[WorkerResult], started: float, cleanup: bool) -> dict[str, Any]:
    success_results = [item for item in results if item.success]
    failed_results = [item for item in results if not item.success]
    total_duration = time.perf_counter() - started
    error_summary: dict[str, int] = {}
    for item in failed_results:
        key = item.error_type or "unknown"
        error_summary[key] = error_summary.get(key, 0) + 1

    summary = {
        "total": len(results),
        "success": len(success_results),
        "failed": len(failed_results),
        "success_rate": round((len(success_results) / len(results)) * 100, 2) if results else 0.0,
        "cleanup_enabled": cleanup,
        "total_duration_seconds": round(total_duration, 2),
        "create_seconds_stats": seconds_stats([item.create_seconds for item in results]),
        "command_seconds_stats": seconds_stats([item.command_seconds for item in results]),
        "error_summary": error_summary,
        "successful_sandbox_ids": [item.sandbox_id for item in success_results if item.sandbox_id],
        "failed_workers": [
            {
                "index": item.index,
                "sandbox_id": item.sandbox_id,
                "error_type": item.error_type,
                "error_message": item.error_message,
                "exit_code": item.exit_code,
            }
            for item in failed_results
        ],
    }
    return summary


def main() -> int:
    load_env_file(DEFAULT_ENV_FILE)
    load_env_file(LOCAL_ENV_FILE)
    args = parse_args()

    if args.concurrency <= 0:
        raise RuntimeError("--concurrency must be greater than 0")
    if args.hold_seconds < 0:
        raise RuntimeError("--hold-seconds must be >= 0")

    domain = (args.domain or os.getenv("E2B_DOMAIN", "")).strip()
    api_key = (args.api_key or os.getenv("E2B_API_KEY", "")).strip()
    template_id = (args.template_id or os.getenv("E2B_TEMPLATE_ID", "")).strip()

    if not domain:
        domain = required_env("E2B_DOMAIN")
    if not api_key:
        api_key = required_env("E2B_API_KEY")
    if not template_id:
        template_id = required_env("E2B_TEMPLATE_ID")

    cleanup = not args.no_cleanup
    wait_for_clean_environment(
        domain=domain,
        api_key=api_key,
        max_wait_seconds=args.wait_for_clean_seconds,
        poll_interval_seconds=args.precheck_poll_seconds,
        force_cleanup=args.force_cleanup_before_start,
    )
    test_time = datetime.now(UTC).isoformat()
    test_id = f"concurrency-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{args.concurrency}"
    environment = detect_environment()

    print("Concurrency test started")
    print(f"domain: {domain}")
    print(f"template_id: {template_id}")
    print(f"concurrency: {args.concurrency}")
    print(f"hold_seconds: {args.hold_seconds}")
    print(f"timeout: {args.timeout}")
    print(f"cleanup: {cleanup}")
    print(f"command: {args.command}")
    print("")

    started = time.perf_counter()
    results: list[WorkerResult] = []
    results_lock = threading.Lock()

    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [
            executor.submit(
                run_worker,
                index,
                domain,
                api_key,
                template_id,
                args.timeout,
                args.command,
                args.hold_seconds,
                cleanup,
            )
            for index in range(1, args.concurrency + 1)
        ]

        for future in as_completed(futures):
            result = future.result()
            with results_lock:
                results.append(result)
            print_result(result)

    results.sort(key=lambda item: item.index)
    summary = summarize(results, started, cleanup)

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

    if summary["failed"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
