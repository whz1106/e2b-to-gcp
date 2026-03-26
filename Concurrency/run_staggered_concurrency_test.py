#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
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
    create_attempts: int
    create_retries: int
    retry_on_create_failure: bool
    retry_interval_seconds: int
    retry_max_seconds: int
    first_failure_running_count: int | None
    last_observed_running_count_before_success: int | None
    retry_running_count_min: int | None
    retry_running_count_max: int | None
    success_after_running_count_drop: bool
    retry_observations: list[dict[str, Any]]
    create_error_retriable: bool | None
    exit_code: int | None
    stdout: str
    stderr: str
    error_type: str | None
    error_message: str | None


class SchedulingPauseController:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled
        self._lock = threading.Lock()
        self._active_failed_workers: set[int] = set()
        self._clear_event = threading.Event()
        self._clear_event.set()

    def signal_create_failure(self, worker_index: int) -> bool:
        if not self.enabled:
            return False

        with self._lock:
            if worker_index in self._active_failed_workers:
                return False
            self._active_failed_workers.add(worker_index)
            self._clear_event.clear()
            return True

    def worker_finished(self, worker_index: int) -> None:
        if not self.enabled:
            return

        with self._lock:
            if worker_index not in self._active_failed_workers:
                return
            self._active_failed_workers.remove(worker_index)
            if not self._active_failed_workers:
                self._clear_event.set()

    def wait_until_clear(self, next_worker_index: int) -> None:
        if not self.enabled:
            return

        announced = False
        while True:
            if self._clear_event.is_set():
                if announced:
                    print(f"[scheduler] resumed before submitting worker={next_worker_index}")
                return

            if not announced:
                with self._lock:
                    active_workers = sorted(self._active_failed_workers)
                print(
                    "[scheduler] paused before submitting worker="
                    f"{next_worker_index} due to active create failure(s): {active_workers}"
                )
                announced = True

            self._clear_event.wait(timeout=0.5)


class SchedulingStopController:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled
        self._stop_event = threading.Event()
        self._reason: str | None = None
        self._worker_index: int | None = None

    def signal_terminal_create_error(self, worker_index: int, reason: str) -> bool:
        if not self.enabled or self._stop_event.is_set():
            return False
        self._worker_index = worker_index
        self._reason = reason
        self._stop_event.set()
        return True

    def should_stop(self) -> bool:
        return self._stop_event.is_set()

    def reason(self) -> str | None:
        return self._reason

    def worker_index(self) -> int | None:
        return self._worker_index


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


RETRIABLE_CREATE_ERROR_TYPES = {"api_limit", "placement_failed", "timeout", "server_error", "connection_closed"}


def is_retriable_create_error(error_type: str) -> bool:
    return error_type in RETRIABLE_CREATE_ERROR_TYPES


def seconds_stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {"min": 0.0, "max": 0.0, "avg": 0.0}
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


def count_running_sandboxes(domain: str, api_key: str) -> int | None:
    try:
        return len(list_running_sandboxes(domain, api_key))
    except Exception as exc:  # noqa: BLE001
        print(f"  retry_observation_error: failed to count running sandboxes: {exc}")
        return None


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
        description="Create sandboxes at a fixed interval and run a lightweight command."
    )
    parser.add_argument("--count", type=int, required=True, help="Number of sandboxes to create.")
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=10,
        help="Seconds to wait between starting each sandbox create request.",
    )
    parser.add_argument(
        "--hold-seconds",
        type=int,
        default=180,
        help="How long to keep each successful sandbox alive before cleanup.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=200,
        help="Sandbox timeout in seconds passed to Sandbox.create().",
    )
    parser.add_argument(
        "--command",
        default=DEFAULT_COMMAND,
        help="Lightweight command to run inside each sandbox.",
    )
    parser.add_argument("--template-id", help="Template ID to use. Falls back to E2B_TEMPLATE_ID.")
    parser.add_argument("--domain", help="E2B domain. Falls back to E2B_DOMAIN.")
    parser.add_argument("--api-key", help="E2B API key. Falls back to E2B_API_KEY.")
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
    parser.add_argument(
        "--retry-on-create-failure",
        action="store_true",
        help="Retry sandbox create failures until success or the retry limit is reached.",
    )
    parser.add_argument(
        "--retry-interval-seconds",
        type=int,
        default=2,
        help="Seconds to wait between create retry attempts.",
    )
    parser.add_argument(
        "--retry-max-seconds",
        type=int,
        default=0,
        help="Maximum total seconds spent retrying create failures. 0 means unlimited.",
    )
    parser.add_argument(
        "--pause-scheduling-on-create-failure",
        action="store_true",
        help="Pause submitting later workers while any worker is retrying create failures.",
    )
    parser.add_argument(
        "--stop-scheduling-on-terminal-create-error",
        action="store_true",
        help="Stop submitting later workers after a non-retriable create error such as not_found.",
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
    retry_on_create_failure: bool,
    retry_interval_seconds: int,
    retry_max_seconds: int,
    pause_controller: SchedulingPauseController,
    stop_controller: SchedulingStopController,
) -> WorkerResult:
    sandbox: Sandbox | None = None
    create_started = time.perf_counter()
    command_seconds = 0.0
    create_attempts = 0
    retry_count = 0
    observed_running_counts: list[int] = []
    retry_observations: list[dict[str, Any]] = []
    first_failure_running_count: int | None = None
    last_observed_running_count_before_success: int | None = None
    create_error_type: str | None = None
    create_error_message: str | None = None
    scheduling_pause_signaled = False

    try:
        while True:
            create_attempts += 1
            if retry_on_create_failure and create_attempts > 1:
                running_count_before_retry = count_running_sandboxes(domain, api_key)
                if running_count_before_retry is not None:
                    observed_running_counts.append(running_count_before_retry)
                    last_observed_running_count_before_success = running_count_before_retry
                retry_observations.append(
                    {
                        "stage": "before_retry_attempt",
                        "attempt": create_attempts,
                        "elapsed_seconds": round(time.perf_counter() - create_started, 2),
                        "running_sandbox_count": running_count_before_retry,
                        "error_type": None,
                        "error_message": None,
                    }
                )
            try:
                sandbox = Sandbox.create(
                    template=template_id,
                    timeout=timeout,
                    api_key=api_key,
                    domain=domain,
                )
                create_seconds = time.perf_counter() - create_started
                break
            except Exception as exc:  # noqa: BLE001
                sandbox = None
                create_error_message = str(exc)
                create_error_type = classify_error(create_error_message)
                create_error_retriable = is_retriable_create_error(create_error_type)

                if not scheduling_pause_signaled:
                    scheduling_pause_signaled = pause_controller.signal_create_failure(index)

                if not create_error_retriable:
                    stop_controller.signal_terminal_create_error(index, f"{create_error_type}: {create_error_message}")

                if not retry_on_create_failure or not create_error_retriable:
                    return WorkerResult(
                        index=index,
                        success=False,
                        sandbox_id=None,
                        create_seconds=time.perf_counter() - create_started,
                        command_seconds=command_seconds,
                        hold_seconds=hold_seconds,
                        create_attempts=create_attempts,
                        create_retries=0,
                        retry_on_create_failure=retry_on_create_failure,
                        retry_interval_seconds=retry_interval_seconds,
                        retry_max_seconds=retry_max_seconds,
                        first_failure_running_count=None,
                        last_observed_running_count_before_success=None,
                        retry_running_count_min=None,
                        retry_running_count_max=None,
                        success_after_running_count_drop=False,
                        retry_observations=[],
                        create_error_retriable=create_error_retriable,
                        exit_code=None,
                        stdout="",
                        stderr="",
                        error_type=create_error_type,
                        error_message=create_error_message,
                    )

                running_count = count_running_sandboxes(domain, api_key)
                if running_count is not None:
                    observed_running_counts.append(running_count)
                    if first_failure_running_count is None:
                        first_failure_running_count = running_count
                    last_observed_running_count_before_success = running_count
                retry_observations.append(
                    {
                        "stage": "after_failure",
                        "attempt": create_attempts,
                        "elapsed_seconds": round(time.perf_counter() - create_started, 2),
                        "running_sandbox_count": running_count,
                        "error_type": create_error_type,
                        "error_message": create_error_message,
                    }
                )

                retry_count = create_attempts - 1
                elapsed_seconds = time.perf_counter() - create_started
                retry_line = (
                    f"[RETRY] worker={index} "
                    f"attempt={create_attempts} "
                    f"running_count={running_count if running_count is not None else '-'} "
                    f"elapsed={elapsed_seconds:.2f}s"
                )

                if retry_max_seconds > 0 and elapsed_seconds >= retry_max_seconds:
                    print(f"{retry_line} retry_limit_reached=True")
                    return WorkerResult(
                        index=index,
                        success=False,
                        sandbox_id=None,
                        create_seconds=elapsed_seconds,
                        command_seconds=command_seconds,
                        hold_seconds=hold_seconds,
                        create_attempts=create_attempts,
                        create_retries=retry_count,
                        retry_on_create_failure=retry_on_create_failure,
                        retry_interval_seconds=retry_interval_seconds,
                        retry_max_seconds=retry_max_seconds,
                        first_failure_running_count=first_failure_running_count,
                        last_observed_running_count_before_success=last_observed_running_count_before_success,
                        retry_running_count_min=min(observed_running_counts) if observed_running_counts else None,
                        retry_running_count_max=max(observed_running_counts) if observed_running_counts else None,
                        success_after_running_count_drop=(
                            first_failure_running_count is not None
                            and any(count < first_failure_running_count for count in observed_running_counts)
                        ),
                        retry_observations=retry_observations,
                        create_error_retriable=create_error_retriable,
                        exit_code=None,
                        stdout="",
                        stderr="",
                        error_type=create_error_type,
                        error_message=create_error_message,
                    )

                print(f"{retry_line} retrying_in={retry_interval_seconds}s")
                time.sleep(retry_interval_seconds)
                continue

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
                create_attempts=create_attempts,
                create_retries=retry_count,
                retry_on_create_failure=retry_on_create_failure,
                retry_interval_seconds=retry_interval_seconds,
                retry_max_seconds=retry_max_seconds,
                first_failure_running_count=first_failure_running_count,
                last_observed_running_count_before_success=last_observed_running_count_before_success,
                retry_running_count_min=min(observed_running_counts) if observed_running_counts else None,
                retry_running_count_max=max(observed_running_counts) if observed_running_counts else None,
                success_after_running_count_drop=(
                    first_failure_running_count is not None
                    and any(count < first_failure_running_count for count in observed_running_counts)
                ),
                retry_observations=retry_observations,
                create_error_retriable=None,
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
            create_attempts=create_attempts,
            create_retries=retry_count,
            retry_on_create_failure=retry_on_create_failure,
            retry_interval_seconds=retry_interval_seconds,
            retry_max_seconds=retry_max_seconds,
            first_failure_running_count=first_failure_running_count,
            last_observed_running_count_before_success=last_observed_running_count_before_success,
            retry_running_count_min=min(observed_running_counts) if observed_running_counts else None,
            retry_running_count_max=max(observed_running_counts) if observed_running_counts else None,
            success_after_running_count_drop=(
                first_failure_running_count is not None
                and any(count < first_failure_running_count for count in observed_running_counts)
            ),
            retry_observations=retry_observations,
            create_error_retriable=None,
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
            create_attempts=create_attempts,
            create_retries=retry_count,
            retry_on_create_failure=retry_on_create_failure,
            retry_interval_seconds=retry_interval_seconds,
            retry_max_seconds=retry_max_seconds,
            first_failure_running_count=first_failure_running_count,
            last_observed_running_count_before_success=last_observed_running_count_before_success,
            retry_running_count_min=min(observed_running_counts) if observed_running_counts else None,
            retry_running_count_max=max(observed_running_counts) if observed_running_counts else None,
            success_after_running_count_drop=(
                first_failure_running_count is not None
                and any(count < first_failure_running_count for count in observed_running_counts)
            ),
            retry_observations=retry_observations,
            create_error_retriable=None if sandbox else is_retriable_create_error(classify_error(error_message)),
            exit_code=None,
            stdout="",
            stderr="",
            error_type=classify_error(error_message),
            error_message=error_message,
        )
    finally:
        if scheduling_pause_signaled:
            pause_controller.worker_finished(index)
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
        f"attempts={result.create_attempts} "
        f"retries={result.create_retries} "
        f"drop_after_retry={result.success_after_running_count_drop} "
        f"create={result.create_seconds:.2f}s "
        f"command={result.command_seconds:.2f}s"
    )

    if result.stdout:
        print(f"  stdout: {result.stdout}")
    if result.stderr:
        print(f"  stderr: {result.stderr}")
    if result.retry_observations:
        last_observation = result.retry_observations[-1]
        print(
            "  retry_window: "
            f"first_running={result.first_failure_running_count} "
            f"last_running={result.last_observed_running_count_before_success} "
            f"min={result.retry_running_count_min} "
            f"max={result.retry_running_count_max} "
            f"last_attempt={last_observation['attempt']}"
        )
    if result.error_type:
        print(f"  error_type: {result.error_type}")
    if result.create_error_retriable is not None:
        print(f"  create_error_retriable: {result.create_error_retriable}")
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

    return {
        "total": len(results),
        "success": len(success_results),
        "failed": len(failed_results),
        "success_rate": round((len(success_results) / len(results)) * 100, 2) if results else 0.0,
        "cleanup_enabled": cleanup,
        "total_duration_seconds": round(total_duration, 2),
        "create_seconds_stats": seconds_stats([item.create_seconds for item in results]),
        "command_seconds_stats": seconds_stats([item.command_seconds for item in results]),
        "retry_enabled_workers": sum(1 for item in results if item.retry_on_create_failure),
        "workers_with_create_retries": sum(1 for item in results if item.create_retries > 0),
        "workers_success_after_running_count_drop": sum(
            1 for item in success_results if item.success_after_running_count_drop
        ),
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


def main() -> int:
    load_env_file(DEFAULT_ENV_FILE)
    load_env_file(LOCAL_ENV_FILE)
    args = parse_args()

    if args.count <= 0:
        raise RuntimeError("--count must be greater than 0")
    if args.interval_seconds < 0:
        raise RuntimeError("--interval-seconds must be >= 0")
    if args.hold_seconds < 0:
        raise RuntimeError("--hold-seconds must be >= 0")
    if args.retry_interval_seconds <= 0:
        raise RuntimeError("--retry-interval-seconds must be > 0")
    if args.retry_max_seconds < 0:
        raise RuntimeError("--retry-max-seconds must be >= 0")

    domain = (args.domain or os.getenv("E2B_DOMAIN", "")).strip() or required_env("E2B_DOMAIN")
    api_key = (args.api_key or os.getenv("E2B_API_KEY", "")).strip() or required_env("E2B_API_KEY")
    template_id = (args.template_id or os.getenv("E2B_TEMPLATE_ID", "")).strip() or required_env("E2B_TEMPLATE_ID")

    cleanup = not args.no_cleanup
    wait_for_clean_environment(
        domain=domain,
        api_key=api_key,
        max_wait_seconds=args.wait_for_clean_seconds,
        poll_interval_seconds=args.precheck_poll_seconds,
        force_cleanup=args.force_cleanup_before_start,
    )
    test_time = datetime.now(UTC).isoformat()
    test_id = f"staggered-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{args.count}"
    environment = detect_environment()

    print("Staggered concurrency test started")
    print(f"domain: {domain}")
    print(f"template_id: {template_id}")
    print(f"count: {args.count}")
    print(f"interval_seconds: {args.interval_seconds}")
    print(f"hold_seconds: {args.hold_seconds}")
    print(f"timeout: {args.timeout}")
    print(f"cleanup: {cleanup}")
    print(f"retry_on_create_failure: {args.retry_on_create_failure}")
    print(f"retry_interval_seconds: {args.retry_interval_seconds}")
    print(f"retry_max_seconds: {args.retry_max_seconds}")
    print(f"pause_scheduling_on_create_failure: {args.pause_scheduling_on_create_failure}")
    print(f"stop_scheduling_on_terminal_create_error: {args.stop_scheduling_on_terminal_create_error}")
    print(f"command: {args.command}")
    print("")

    started = time.perf_counter()
    results: list[WorkerResult] = []
    results_lock = threading.Lock()
    futures_map: dict[Future[WorkerResult], int] = {}
    pause_controller = SchedulingPauseController(args.pause_scheduling_on_create_failure)
    stop_controller = SchedulingStopController(args.stop_scheduling_on_terminal_create_error)

    with ThreadPoolExecutor(max_workers=args.count) as executor:
        for index in range(1, args.count + 1):
            if stop_controller.should_stop():
                print(
                    "[scheduler] stopped before submitting worker="
                    f"{index} due to terminal create error from worker={stop_controller.worker_index()}: "
                    f"{stop_controller.reason()}"
                )
                break
            pause_controller.wait_until_clear(index)
            if stop_controller.should_stop():
                print(
                    "[scheduler] stopped before submitting worker="
                    f"{index} due to terminal create error from worker={stop_controller.worker_index()}: "
                    f"{stop_controller.reason()}"
                )
                break
            future = executor.submit(
                run_worker,
                index,
                domain,
                api_key,
                template_id,
                args.timeout,
                args.command,
                args.hold_seconds,
                cleanup,
                args.retry_on_create_failure,
                args.retry_interval_seconds,
                args.retry_max_seconds,
                pause_controller,
                stop_controller,
            )
            futures_map[future] = index

            if index < args.count and args.interval_seconds > 0:
                time.sleep(args.interval_seconds)

        for future in as_completed(futures_map):
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
            "count": args.count,
            "interval_seconds": args.interval_seconds,
            "hold_seconds": args.hold_seconds,
            "timeout": args.timeout,
            "cleanup": cleanup,
            "retry_on_create_failure": args.retry_on_create_failure,
            "retry_interval_seconds": args.retry_interval_seconds,
            "retry_max_seconds": args.retry_max_seconds,
            "pause_scheduling_on_create_failure": args.pause_scheduling_on_create_failure,
            "stop_scheduling_on_terminal_create_error": args.stop_scheduling_on_terminal_create_error,
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
