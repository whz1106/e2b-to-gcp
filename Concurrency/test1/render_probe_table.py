#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render a single running-capacity probe JSON file into a markdown table."
    )
    parser.add_argument(
        "input_json",
        help="Path to a single probe JSON file, for example results/test1/013.json.",
    )
    parser.add_argument(
        "--output",
        help="Optional output markdown path. Defaults to <input_stem>_table.md next to the JSON file.",
    )
    return parser.parse_args()


def build_table(results: list[dict]) -> str:
    headers = [
        "index",
        "phase",
        "success",
        "sandbox_id",
        "started_s",
        "ready_s",
        "finished_s",
        "create_s",
        "command_s",
        "run_window_s",
        "exit_code",
        "error_type",
        "error_message",
    ]

    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]

    for item in results:
        started = float(item.get("started_offset_seconds", 0) or 0)
        create_s = float(item.get("create_seconds", 0) or 0)
        command_s = float(item.get("command_seconds", 0) or 0)
        finished = float(item.get("finished_offset_seconds", 0) or 0)
        ready = round(started + create_s + command_s, 2)
        run_window = round(finished - started, 2)
        error_message = str(item.get("error_message") or "-").replace("\n", " ")

        row = [
            str(item.get("index", "")),
            str(item.get("phase", "")),
            "Y" if item.get("success") else "N",
            str(item.get("sandbox_id") or "-"),
            f"{started:.2f}",
            f"{ready:.2f}",
            f"{finished:.2f}",
            f"{create_s:.2f}",
            f"{command_s:.2f}",
            f"{run_window:.2f}",
            str(item.get("exit_code") if item.get("exit_code") is not None else "-"),
            str(item.get("error_type") or "-"),
            error_message,
        ]
        lines.append("| " + " | ".join(row) + " |")

    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    input_path = Path(args.input_json).resolve()
    if not input_path.exists():
        raise RuntimeError(f"input JSON does not exist: {input_path}")

    payload = json.loads(input_path.read_text(encoding="utf-8"))
    results = payload.get("results")
    if not isinstance(results, list) or not results:
        raise RuntimeError(f"results list is missing or empty in: {input_path}")

    output_path = (
        Path(args.output).resolve()
        if args.output
        else input_path.with_name(f"{input_path.stem}_table.md")
    )
    output_path.write_text(build_table(results), encoding="utf-8")

    print(f"input_json: {input_path}")
    print(f"output_md: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
