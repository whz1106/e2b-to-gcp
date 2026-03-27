#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from e2b import Sandbox

ROOT_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT_DIR.parent
DEFAULT_ENV_FILE = ROOT_DIR / ".env"
LOCAL_ENV_FILE = ROOT_DIR / ".env.local"


@dataclass
class ProbeResult:
    index: int
    success: bool
    sandbox_id: str | None
    create_seconds: float
    command_seconds: float
    sandbox_timeout: int
    exit_code: int | None
    stdout: str
    stderr: str
    error_type: str | None
    error_message: str | None
    phase: str
    started_offset_seconds: float
    finished_offset_seconds: float

    @property
    def ready_offset_seconds(self) -> float:
        # ready 表示 create 完成后，连同保活命令也已启动完成的时刻。
        return round(self.started_offset_seconds + self.create_seconds + self.command_seconds, 2)


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
        # 测试前先清空当前 team 下的残留 sandbox，避免把上一轮结果混进来。
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


def build_loop_command(sandbox_timeout: int) -> str:
    return (
        "sh -lc '"
        "nohup python3 -c \"import time; time.sleep("
        f"{sandbox_timeout}"
        ")\" "
        ">/tmp/running_capacity_probe_sleep.log 2>&1 & "
        "echo sleep-started'"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Probe the stable running sandbox capacity of a single client with staggered creates."
    )
    parser.add_argument("--max-sandboxes", type=int, default=20, help="Upper bound of create attempts.")
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=10,
        help="Seconds to wait between create attempts. Default: 10.",
    )
    parser.add_argument(
        "--sandbox-timeout",
        type=int,
        default=200,
        help="Sandbox lifetime timeout in seconds passed to Sandbox.create(). Default: 200.",
    )
    parser.add_argument(
        "--timeout",
        dest="sandbox_timeout_legacy",
        type=int,
        help="Deprecated alias for --sandbox-timeout.",
    )
    parser.add_argument(
        "--create-request-timeout",
        type=float,
        default=0,
        help="HTTP request timeout for Sandbox.create() in seconds. 0 disables the request timeout. Default: 0.",
    )
    parser.add_argument(
        "--command",
        default="",
        help="Optional custom background keepalive command. Defaults to a background sleep launcher.",
    )
    parser.add_argument(
        "--retry-after-release-seconds",
        type=int,
        default=5,
        help="After the earliest successful sandbox finishes, wait this many seconds before one retry create.",
    )
    parser.add_argument(
        "--command-timeout",
        type=float,
        default=30,
        help="Timeout for the keepalive start command request in seconds. Default: 30.",
    )
    parser.add_argument("--template-id", help="Template ID or alias. Falls back to E2B_TEMPLATE_ID.")
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
    return parser.parse_args()


def run_worker(
    test_started_monotonic: float,
    index: int,
    domain: str,
    api_key: str,
    template_id: str,
    sandbox_timeout: int,
    create_request_timeout: float,
    keepalive_command: str,
    command_timeout: float,
    cleanup: bool,
    phase: str,
) -> ProbeResult:
    sandbox: Sandbox | None = None
    # started 是 worker 进入本次 create 流程的相对时间。
    started_offset_seconds = time.perf_counter() - test_started_monotonic
    create_started = time.perf_counter()
    create_seconds = 0.0
    command_seconds = 0.0

    try:
        sandbox = Sandbox.create(
            template=template_id,
            timeout=sandbox_timeout,
            request_timeout=create_request_timeout,
            api_key=api_key,
            domain=domain,
        )
        create_seconds = time.perf_counter() - create_started

        # 先在 sandbox 内启动一个后台 keepalive，再把整个生命周期占满到 sandbox_timeout。
        started_holding = time.perf_counter()
        result = sandbox.commands.run(keepalive_command, timeout=command_timeout)
        command_seconds += time.perf_counter() - started_holding

        if result.exit_code != 0:
            return ProbeResult(
                index=index,
                success=False,
                sandbox_id=sandbox.sandbox_id,
                create_seconds=create_seconds,
                command_seconds=command_seconds,
                sandbox_timeout=sandbox_timeout,
                exit_code=result.exit_code,
                stdout=result.stdout.strip(),
                stderr=result.stderr.strip(),
                error_type="command_failed",
                error_message="initial_health_check_failed",
                phase=f"{phase}:keepalive_start",
                started_offset_seconds=round(started_offset_seconds, 2),
                finished_offset_seconds=round(time.perf_counter() - test_started_monotonic, 2),
            )

        # 这里的 timeout 从 create 发起时开始算，不是从 ready 时刻重新计时。
        lifecycle_deadline = create_started + sandbox_timeout
        remaining_lifetime = lifecycle_deadline - time.perf_counter()
        if remaining_lifetime > 0:
            time.sleep(remaining_lifetime)

        return ProbeResult(
            index=index,
            success=True,
            sandbox_id=sandbox.sandbox_id,
            create_seconds=create_seconds,
            command_seconds=command_seconds,
            sandbox_timeout=sandbox_timeout,
            exit_code=result.exit_code,
            stdout=result.stdout.strip(),
            stderr=result.stderr.strip(),
            error_type=None,
            error_message=None,
            phase=phase,
            started_offset_seconds=round(started_offset_seconds, 2),
            finished_offset_seconds=round(time.perf_counter() - test_started_monotonic, 2),
        )
    except Exception as exc:  # noqa: BLE001
        error_message = str(exc)
        error_type = classify_error(error_message)
        failure_phase = f"{phase}:create"
        if sandbox is not None:
            failure_phase = f"{phase}:runtime"
        return ProbeResult(
            index=index,
            success=False,
            sandbox_id=sandbox.sandbox_id if sandbox else None,
            create_seconds=create_seconds if create_seconds > 0 else time.perf_counter() - create_started,
            command_seconds=command_seconds,
            sandbox_timeout=sandbox_timeout,
            exit_code=None,
            stdout="",
            stderr="",
            error_type=error_type,
            error_message=error_message,
            phase=failure_phase,
            started_offset_seconds=round(started_offset_seconds, 2),
            finished_offset_seconds=round(time.perf_counter() - test_started_monotonic, 2),
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
        f"[{status}] phase={result.phase} worker={result.index} sandbox_id={sandbox_id} "
        f"create={result.create_seconds:.2f}s command={result.command_seconds:.2f}s"
    )
    print(
        "  timeline: "
        f"started={result.started_offset_seconds:.2f}s "
        f"ready={result.ready_offset_seconds:.2f}s "
        f"finished={result.finished_offset_seconds:.2f}s"
    )
    if result.error_type:
        print(f"  error_type: {result.error_type}")
    if result.error_message:
        print(f"  error_message: {result.error_message}")
    if result.stdout:
        lines = result.stdout.splitlines()
        print(f"  stdout_last: {lines[-1]}")


def print_first_failure(result: ProbeResult) -> None:
    print(
        "[FIRST_FAILURE] "
        f"worker={result.index} "
        f"phase={result.phase} "
        f"error_type={result.error_type or '-'} "
        f"started={result.started_offset_seconds:.2f}s "
        f"finished={result.finished_offset_seconds:.2f}s "
        f"create={result.create_seconds:.2f}s"
    )


def print_waiting_for_release(result: ProbeResult, retry_after_release_seconds: int) -> None:
    sandbox_id = result.sandbox_id or "-"
    print(
        "[WAIT_RELEASE] "
        f"worker={result.index} "
        f"sandbox_id={sandbox_id} "
        f"finished={result.finished_offset_seconds:.2f}s "
        f"retrying_in={retry_after_release_seconds}s"
    )


def print_submit(index: int, phase: str, offset_seconds: float) -> None:
    print(
        "[SUBMIT] "
        f"worker={index} "
        f"phase={phase} "
        f"started={offset_seconds:.2f}s"
    )


def print_waiting_candidate(index: int, now_offset_seconds: float) -> None:
    print(
        "[WAITING] "
        f"candidate_worker={index} "
        f"at={now_offset_seconds:.2f}s "
        "waiting_for_finish=true"
    )


def print_running_count(label: str, domain: str, api_key: str, offset_seconds: float) -> int | None:
    try:
        sandboxes = list_running_sandboxes(domain, api_key)
        sandbox_ids = [getattr(item, "sandbox_id", "") for item in sandboxes if getattr(item, "sandbox_id", "")]
        joined = ", ".join(sandbox_ids) if sandbox_ids else "-"
        print(
            "[RUNNING] "
            f"label={label} "
            f"at={offset_seconds:.2f}s "
            f"count={len(sandbox_ids)} "
            f"sandboxes={joined}"
        )
        return len(sandbox_ids)
    except Exception as exc:  # noqa: BLE001
        print(
            "[RUNNING] "
            f"label={label} "
            f"at={offset_seconds:.2f}s "
            f"error={exc}"
        )
        return None


def summarize(
    results: list[ProbeResult],
    started: float,
    cleanup: bool,
    first_failure_index: int | None,
    first_failure_error: str | None,
    initial_success_count: int,
    retry_attempted: bool,
    retry_success: bool | None,
    earliest_successful_index: int | None,
    retry_results: list[ProbeResult],
) -> dict:
    success_results = [item for item in results if item.success]
    failed_results = [item for item in results if not item.success]
    total_duration = time.perf_counter() - started
    initial_results = [item for item in results if item.phase.startswith("initial")]
    successes_before_failure = [
        item
        for item in initial_results
        if item.success and (first_failure_index is None or item.index < first_failure_index)
    ]
    placement_failures = [
        item for item in initial_results if item.error_type == "placement_failed"
    ]
    runtime_failures = [
        item for item in initial_results if item.phase.endswith(":runtime")
    ]
    final_retry_result = retry_results[-1] if retry_results else None
    retry_create_seconds = final_retry_result.create_seconds if final_retry_result is not None else None
    retry_started_offset = final_retry_result.started_offset_seconds if final_retry_result is not None else None
    retry_finished_offset = final_retry_result.finished_offset_seconds if final_retry_result is not None else None

    return {
        "total_results": len(results),
        "success": len(success_results),
        "failed": len(failed_results),
        "cleanup_enabled": cleanup,
        "total_duration_seconds": round(total_duration, 2),
        "create_seconds_stats": seconds_stats([item.create_seconds for item in results]),
        "command_seconds_stats": seconds_stats([item.command_seconds for item in results]),
        "first_failure_index": first_failure_index,
        "first_failure_error": first_failure_error,
        "initial_success_count_before_failure": len(successes_before_failure),
        "max_simultaneous_running_estimate": len(successes_before_failure),
        "stable_running_capacity_estimate": len(successes_before_failure),
        "earliest_successful_index": earliest_successful_index,
        "first_runtime_failure_index": runtime_failures[0].index if runtime_failures else None,
        "first_placement_failure_index": placement_failures[0].index if placement_failures else None,
        "retry_attempted_after_first_release": retry_attempted,
        "retry_success_after_first_release": retry_success,
        "retry_attempt_count_after_first_release": len(retry_results),
        "retry_create_seconds_after_first_release": round(retry_create_seconds, 2) if retry_create_seconds is not None else None,
        "retry_started_offset_seconds": retry_started_offset,
        "retry_finished_offset_seconds": retry_finished_offset,
        "timeline": [
            {
                "index": item.index,
                "phase": item.phase,
                "success": item.success,
                "sandbox_id": item.sandbox_id,
                "started_offset_seconds": item.started_offset_seconds,
                "ready_offset_seconds": item.ready_offset_seconds,
                "finished_offset_seconds": item.finished_offset_seconds,
                "create_seconds": round(item.create_seconds, 2),
            }
            for item in sorted(initial_results + retry_results, key=lambda item: (item.started_offset_seconds, item.index, item.phase))
        ],
        "note": (
            "This probe estimates how many sandboxes can stay running at once by creating one every few seconds, "
            "then retrying after the earliest sandbox finishes."
        ),
    }


def main() -> int:
    load_env_file(DEFAULT_ENV_FILE)
    load_env_file(LOCAL_ENV_FILE)
    args = parse_args()

    if args.sandbox_timeout_legacy is not None:
        args.sandbox_timeout = args.sandbox_timeout_legacy

    if args.max_sandboxes <= 0:
        raise RuntimeError("--max-sandboxes must be greater than 0")
    if args.interval_seconds < 0:
        raise RuntimeError("--interval-seconds must be >= 0")
    if args.retry_after_release_seconds < 0:
        raise RuntimeError("--retry-after-release-seconds must be >= 0")
    if args.command_timeout <= 0:
        raise RuntimeError("--command-timeout must be greater than 0")
    if args.create_request_timeout < 0:
        raise RuntimeError("--create-request-timeout must be >= 0")
    if args.sandbox_timeout <= 0:
        raise RuntimeError("--sandbox-timeout must be greater than 0")

    domain = (args.domain or "").strip() or required_env("E2B_DOMAIN")
    api_key = (args.api_key or "").strip() or required_env("E2B_API_KEY")
    template_id = (args.template_id or "").strip() or required_env("E2B_TEMPLATE_ID")
    cleanup = not args.no_cleanup
    keepalive_command = args.command.strip() or build_loop_command(args.sandbox_timeout)

    wait_for_clean_environment(
        domain=domain,
        api_key=api_key,
        max_wait_seconds=args.wait_for_clean_seconds,
        poll_interval_seconds=args.precheck_poll_seconds,
        force_cleanup=args.force_cleanup_before_start,
    )

    test_time = datetime.now(UTC).isoformat()
    test_id = f"running-capacity-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{args.max_sandboxes}"
    environment = detect_environment()

    print("Running-capacity probe started")
    print(f"domain: {domain}")
    print(f"template_id: {template_id}")
    print(f"max_sandboxes: {args.max_sandboxes}")
    print(f"interval_seconds: {args.interval_seconds}")
    print(f"sandbox_timeout: {args.sandbox_timeout}")
    print(f"create_request_timeout: {args.create_request_timeout}")
    print(f"command_timeout: {args.command_timeout}")
    print(f"retry_after_release_seconds: {args.retry_after_release_seconds}")
    print(f"cleanup: {cleanup}")
    print("")

    started = time.perf_counter()
    results: list[ProbeResult] = []
    first_failure_index: int | None = None
    first_failure_error: str | None = None
    retry_attempted = False
    retry_success: bool | None = None
    earliest_successful_index: int | None = None
    retry_results: list[ProbeResult] = []

    with ThreadPoolExecutor(max_workers=args.max_sandboxes + 1) as executor:
        futures: list[Future[ProbeResult]] = []
        future_by_index: dict[int, Future[ProbeResult]] = {}
        collected_indexes: set[tuple[int, str]] = set()

        def collect_ready_futures(stop_on_first_failure: bool) -> bool:
            nonlocal first_failure_index, first_failure_error, earliest_successful_index

            saw_failure = False
            # 只收集已经结束的 worker，避免阻塞后续 submit 的节奏。
            for future in futures:
                if not future.done():
                    continue
                result = future.result()
                key = (result.index, result.phase)
                if key in collected_indexes:
                    continue
                collected_indexes.add(key)
                results.append(result)
                print_result(result)

                if result.success and earliest_successful_index is None:
                    earliest_successful_index = result.index

                if not result.success and first_failure_index is None:
                    first_failure_index = result.index
                    first_failure_error = result.error_type or result.error_message
                    print_first_failure(result)
                    saw_failure = True
                    if stop_on_first_failure:
                        break

            return saw_failure

        for index in range(1, args.max_sandboxes + 1):
            # 初始阶段按固定间隔提交，用来观察容量边界出现在哪个 worker。
            print_submit(index, "initial", time.perf_counter() - started)
            future = executor.submit(
                run_worker,
                started,
                index,
                domain,
                api_key,
                template_id,
                args.sandbox_timeout,
                args.create_request_timeout,
                keepalive_command,
                args.command_timeout,
                cleanup,
                "initial",
            )
            futures.append(future)
            future_by_index[index] = future

            if collect_ready_futures(stop_on_first_failure=True):
                break

            if index < args.max_sandboxes:
                time.sleep(args.interval_seconds)
                if collect_ready_futures(stop_on_first_failure=True):
                    break

        if first_failure_index is None:
            for future in futures:
                result = future.result()
                key = (result.index, result.phase)
                if key in collected_indexes:
                    continue
                collected_indexes.add(key)
                results.append(result)
                print_result(result)
                if result.success and earliest_successful_index is None:
                    earliest_successful_index = result.index
                if not result.success and first_failure_index is None:
                    first_failure_index = result.index
                    first_failure_error = result.error_type or result.error_message

        initial_success_count = len([item for item in results if item.success and item.phase == "initial"])

        if first_failure_index is not None:
            earliest_successful_result: ProbeResult | None = None
            upper_bound = first_failure_index - 1
            for index in range(1, upper_bound + 1):
                future = future_by_index.get(index)
                if future is None:
                    continue
                if not future.done():
                    print_waiting_candidate(index, time.perf_counter() - started)
                result = future.result()
                key = (result.index, result.phase)
                if key not in collected_indexes:
                    collected_indexes.add(key)
                    results.append(result)
                    print_result(result)
                if result.success:
                    earliest_successful_index = result.index
                    earliest_successful_result = result
                    break

            if earliest_successful_result is not None:
                retry_attempted = True
                retry_attempt_number = 0
                while True:
                    # 首次失败后，只等最早成功的 sandbox 释放，再按固定间隔补位。
                    print_waiting_for_release(earliest_successful_result, args.retry_after_release_seconds)
                    if args.retry_after_release_seconds > 0:
                        time.sleep(args.retry_after_release_seconds)
                    retry_attempt_number += 1
                    print(
                        f"[RETRY] worker={first_failure_index} attempt={retry_attempt_number} "
                        f"retrying_after={args.retry_after_release_seconds}s"
                    )
                    retry_result = run_worker(
                        started,
                        first_failure_index,
                        domain,
                        api_key,
                        template_id,
                        args.sandbox_timeout,
                        args.create_request_timeout,
                        keepalive_command,
                        args.command_timeout,
                        cleanup,
                        f"retry_after_first_release:{retry_attempt_number}",
                    )
                    retry_results.append(retry_result)
                    results.append(retry_result)
                    print_result(retry_result)
                    # retry 成功后再查一次当前 running 数量，避免把查询延迟算进 retry 起点。
                    print_running_count(
                        f"retry_after_attempt_{retry_attempt_number}",
                        domain,
                        api_key,
                        time.perf_counter() - started,
                    )
                    if retry_result.success:
                        release_gap = round(
                            retry_result.ready_offset_seconds - earliest_successful_result.finished_offset_seconds,
                            2,
                        )
                        print(
                            "[RETRY_SUCCESS] "
                            f"worker={first_failure_index} "
                            f"attempt={retry_attempt_number} "
                            f"release_to_ready={release_gap}s "
                            f"create={retry_result.create_seconds:.2f}s"
                        )
                    if retry_result.success:
                        retry_success = True
                        break
                    if retry_result.error_type != "placement_failed":
                        print(
                            "[RETRY_STOP] "
                            f"worker={first_failure_index} "
                            f"attempt={retry_attempt_number} "
                            f"error_type={retry_result.error_type or '-'}"
                        )
                        retry_success = False
                        break

        for future in futures:
            result = future.result()
            key = (result.index, result.phase)
            if key in collected_indexes:
                continue
            collected_indexes.add(key)
            results.append(result)
            print_result(result)

    results.sort(key=lambda item: (item.index, item.phase))
    # summary 里保留容量估计、首次失败点和 retry 结果，方便后续直接读 JSON。
    summary = summarize(
        results=results,
        started=started,
        cleanup=cleanup,
        first_failure_index=first_failure_index,
        first_failure_error=first_failure_error,
        initial_success_count=initial_success_count,
        retry_attempted=retry_attempted,
        retry_success=retry_success,
        earliest_successful_index=earliest_successful_index,
        retry_results=retry_results,
    )

    payload = {
        "meta": {
            "test_id": test_id,
            "test_time": test_time,
            "environment": environment,
            "domain": domain,
            "template_id": template_id,
            "max_sandboxes": args.max_sandboxes,
            "interval_seconds": args.interval_seconds,
            "sandbox_timeout": args.sandbox_timeout,
            "create_request_timeout": args.create_request_timeout,
            "command_timeout": args.command_timeout,
            "retry_after_release_seconds": args.retry_after_release_seconds,
            "cleanup": cleanup,
            "keepalive_command": keepalive_command,
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

    return 1 if first_failure_index is not None else 0


if __name__ == "__main__":
    raise SystemExit(main())
