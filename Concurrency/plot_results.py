#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT_DIR = ROOT_DIR / "results" / "test_base"
DEFAULT_OUTPUT_DIR = ROOT_DIR / "plots" / "test_base"


def sort_key_for_file(name: str) -> tuple[int, str]:
    stem = Path(name).stem
    if stem.isdigit():
        return (0, f"{int(stem):09d}")
    return (1, name)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plot sandbox concurrency JSON results into charts and summary tables."
    )
    parser.add_argument(
        "--input-dir",
        default=str(DEFAULT_INPUT_DIR),
        help="Directory containing JSON result files, or a single JSON result file.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory for generated summary markdown.",
    )
    return parser.parse_args()


def load_results(input_dir: Path) -> list[dict]:
    rows: list[dict] = []
    if input_dir.is_file():
        paths = [input_dir]
        relative_root = input_dir.parent
    else:
        paths = sorted(input_dir.rglob("*.json"))
        relative_root = input_dir

    for path in paths:
        with path.open(encoding="utf-8") as fh:
            payload = json.load(fh)

        meta = payload.get("meta", {})
        summary = payload.get("summary", {})
        row = {
            "file": path.name,
            "test_id": meta.get("test_id", ""),
            "profile": meta.get("profile", "light"),
            "concurrency": meta.get("concurrency", 0),
            "count": meta.get("count", 0),
            "interval_seconds": meta.get("interval_seconds", 0),
            "hold_seconds": meta.get("hold_seconds", 0),
            "timeout": meta.get("timeout", 0),
            "success": summary.get("success", 0),
            "failed": summary.get("failed", 0),
            "total": summary.get("total", 0),
            "success_rate": summary.get("success_rate", 0.0),
            "total_duration_seconds": summary.get("total_duration_seconds", 0.0),
            "create_avg": summary.get("create_seconds_stats", {}).get("avg", 0.0),
            "create_min": summary.get("create_seconds_stats", {}).get("min", 0.0),
            "create_max": summary.get("create_seconds_stats", {}).get("max", 0.0),
            "command_avg": summary.get("command_seconds_stats", {}).get("avg", 0.0),
            "command_min": summary.get("command_seconds_stats", {}).get("min", 0.0),
            "command_max": summary.get("command_seconds_stats", {}).get("max", 0.0),
            "error_summary": summary.get("error_summary", {}),
        }
        rows.append(row)

    rows.sort(key=lambda item: sort_key_for_file(item["file"]))
    return rows


def write_markdown(rows: list[dict], output_path: Path) -> None:
    headers = [
        "file",
        "count",
        "interval",
        "hold",
        "timeout",
        "success",
        "failed",
        "success_rate",
        "create_avg",
        "command_avg",
        "errors",
    ]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]

    for row in sorted(rows, key=lambda item: sort_key_for_file(item["file"])):
        errors = ", ".join(f"{k}:{v}" for k, v in sorted(row["error_summary"].items())) or "-"
        lines.append(
            "| "
            + " | ".join(
                [
                    row["file"],
                    str(row["count"] or row["concurrency"]),
                    f'{row["interval_seconds"]}s' if row["interval_seconds"] else "-",
                    f'{row["hold_seconds"]}s',
                    f'{row["timeout"]}s',
                    str(row["success"]),
                    str(row["failed"]),
                    f'{row["success_rate"]:.2f}%',
                    f'{row["create_avg"]:.2f}s',
                    f'{row["command_avg"]:.2f}s',
                    errors,
                ]
            )
            + " |"
        )

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)

    if not input_dir.exists():
        raise RuntimeError(f"input dir does not exist: {input_dir}")

    rows = load_results(input_dir)
    if not rows:
        raise RuntimeError(f"no JSON files found in: {input_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)

    write_markdown(rows, output_dir / "summary.md")
    for name in [
        "summary.csv",
        "success_rate.png",
        "durations.png",
        "failures.png",
        "error_types.png",
    ]:
        (output_dir / name).unlink(missing_ok=True)

    print(f"input_dir: {input_dir}")
    print(f"output_dir: {output_dir}")
    print("generated:")
    print(f"  - {output_dir / 'summary.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
