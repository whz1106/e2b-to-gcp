# GCP Self-Hosted E2B Smoke Tests

This folder contains a Python-based end-to-end smoke suite for the deployed GCP self-hosted E2B stack.

It verifies:

- public API health
- auth seed into Postgres for a temporary smoke-test team
- available template alias discovery from the deployed database
- sandbox creation against the live domain
- sandbox info fetch
- file write/read/list inside the sandbox
- foreground command execution
- outbound internet access from the sandbox
- background command start/list/kill
- sandbox teardown

## Usage

From the repo root:

```bash
codex_artifacts/kits/gcp-selfhost-smoke/run.sh
```

Or directly:

```bash
codex_artifacts/kits/gcp-selfhost-smoke/.venv/bin/python \
  codex_artifacts/kits/gcp-selfhost-smoke/run_smoke.py
```

## Required assumptions

- `.env.dev` contains a valid `POSTGRES_CONNECTION_STRING`
- `.env.dev` contains `DOMAIN_NAME`
- the deployed stack is reachable publicly
- at least one template alias exists in `env_aliases`
