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
        return {"min": 0.0, "max": 0.0, "avg": 0.0}
    return {
        "min": round(min(values), 2),
        "max": round(max(values), 2),
        "avg": round(sum(values) / len(values), 2),
    }


def build_profile_command(profile: str, hold_seconds: int, network_url: str, io_mb: int, memory_mb: int) -> str:
    if profile == "light":
        return 'python3 -c "print(\\"concurrency-ok\\")"'

    if profile == "cpu":
        return (
            "python3 - <<'PY'\n"
            "import time\n"
            "end = time.time() + 60\n"
            "total = 0\n"
            "while time.time() < end:\n"
            "    for i in range(200000):\n"
            "        total += i * i\n"
            "print(total)\n"
            "PY"
        )

    if profile == "memory":
        return (
            "python3 - <<'PY'\n"
            f"size = {memory_mb} * 1024 * 1024\n"
            "data = bytearray(size)\n"
            "for i in range(0, len(data), 4096):\n"
            "    data[i] = 1\n"
            "print(len(data))\n"
            f"import time; time.sleep({hold_seconds})\n"
            "PY"
        )

    if profile == "io":
        return (
            "python3 - <<'PY'\n"
            "from pathlib import Path\n"
            f"size = {io_mb} * 1024 * 1024\n"
            "path = Path('/tmp/concurrency-io.bin')\n"
            "chunk = b'a' * (1024 * 1024)\n"
            "with path.open('wb') as fh:\n"
            "    for _ in range(size // len(chunk)):\n"
            "        fh.write(chunk)\n"
            "data = path.read_bytes()\n"
            "print(len(data))\n"
            "path.unlink(missing_ok=True)\n"
            "PY"
        )

    if profile == "network":
        return (
            "python3 - <<'PY'\n"
            "import urllib.request\n"
            "statuses = []\n"
            f"url = {network_url!r}\n"
            "for _ in range(10):\n"
            "    with urllib.request.urlopen(url, timeout=15) as response:\n"
            "        statuses.append(response.status)\n"
            "print(','.join(map(str, statuses)))\n"
            "PY"
        )

    if profile == "mixed":
        return (
            "python3 - <<'PY'\n"
            "import time\n"
            "import urllib.request\n"
            "from pathlib import Path\n"
            "total = 0\n"
            "for i in range(500000):\n"
            "    total += i * i\n"
            f"data = bytearray({memory_mb} * 1024 * 1024)\n"
            "for i in range(0, len(data), 4096):\n"
            "    data[i] = 1\n"
            "path = Path('/tmp/concurrency-mixed.bin')\n"
            "path.write_bytes(b'x' * (10 * 1024 * 1024))\n"
            f"with urllib.request.urlopen({network_url!r}, timeout=15) as response:\n"
            "    status = response.status\n"
            "print(f'cpu={total} memory={len(data)} network={status}')\n"
            "path.unlink(missing_ok=True)\n"
            f"time.sleep({hold_seconds})\n"
            "PY"
        )

    raise RuntimeError(f"unsupported profile: {profile}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create concurrent sandboxes with heavier workload profiles."
    )
    parser.add_argument("--concurrency", type=int, required=True, help="Number of concurrent sandboxes.")
    parser.add_argument("--profile", choices=["light", "cpu", "memory", "io", "network", "mixed"], required=True)
    parser.add_argument("--hold-seconds", type=int, default=120, help="How long to keep the sandbox after command completion.")
    parser.add_argument("--timeout", type=int, default=300, help="Sandbox timeout in seconds.")
    parser.add_argument("--template-id", help="Template ID or alias. Falls back to E2B_TEMPLATE_ID.")
    parser.add_argument("--domain", help="E2B domain. Falls back to E2B_DOMAIN.")
    parser.add_argument("--api-key", help="E2B API key. Falls back to E2B_API_KEY.")
    parser.add_argument("--network-url", default="https://example.com", help="URL used by network and mixed profiles.")
    parser.add_argument("--io-mb", type=int, default=100, help="Data size in MB for io profile.")
    parser.add_argument("--memory-mb", type=int, default=256, help="Memory size in MB for memory and mixed profiles.")
    parser.add_argument("--no-cleanup", action="store_true", help="Do not kill successful sandboxes at the end.")
    parser.add_argument("--output-json", help="Optional path to write the full JSON result.")
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
        f"[{status}] worker={result.index} sandbox_id={sandbox_id} "
        f"create={result.create_seconds:.2f}s command={result.command_seconds:.2f}s"
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
        "total_duration_seconds": round(time.perf_counter() - started, 2),
        "create_seconds_stats": seconds_stats([item.create_seconds for item in results]),
        "command_seconds_stats": seconds_stats([item.command_seconds for item in results]),
        "error_summary": error_summary,
    }


def main() -> int:
    load_env_file(DEFAULT_ENV_FILE)
    load_env_file(LOCAL_ENV_FILE)
    args = parse_args()

    domain = (args.domain or os.getenv("E2B_DOMAIN", "")).strip() or required_env("E2B_DOMAIN")
    api_key = (args.api_key or os.getenv("E2B_API_KEY", "")).strip() or required_env("E2B_API_KEY")
    template_id = (args.template_id or os.getenv("E2B_TEMPLATE_ID", "")).strip() or required_env("E2B_TEMPLATE_ID")
    cleanup = not args.no_cleanup

    command = build_profile_command(
        profile=args.profile,
        hold_seconds=args.hold_seconds,
        network_url=args.network_url,
        io_mb=args.io_mb,
        memory_mb=args.memory_mb,
    )

    test_time = datetime.now(UTC).isoformat()
    test_id = f"profile-{args.profile}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{args.concurrency}"
    environment = detect_environment()

    print("Concurrency profile test started")
    print(f"profile: {args.profile}")
    print(f"domain: {domain}")
    print(f"template_id: {template_id}")
    print(f"concurrency: {args.concurrency}")
    print(f"hold_seconds: {args.hold_seconds}")
    print(f"timeout: {args.timeout}")
    print(f"cleanup: {cleanup}")
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
                command,
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
            "profile": args.profile,
            "concurrency": args.concurrency,
            "hold_seconds": args.hold_seconds,
            "timeout": args.timeout,
            "cleanup": cleanup,
            "network_url": args.network_url,
            "io_mb": args.io_mb,
            "memory_mb": args.memory_mb,
            "command": command,
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
