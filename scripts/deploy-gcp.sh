#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_NAME="${1:-$(cat "${ROOT_DIR}/.last_used_env" 2>/dev/null || echo dev)}"
ENV_FILE="${ROOT_DIR}/.env.${ENV_NAME}"
SKIP_BUILD="${SKIP_BUILD:-false}"
SKIP_PUBLIC_BUILDS="${SKIP_PUBLIC_BUILDS:-false}"
SKIP_SECRET_SYNC="${SKIP_SECRET_SYNC:-false}"

usage() {
  cat <<EOF
Usage: scripts/deploy-gcp.sh [env]

Runs the documented GCP deployment flow:
  1. switch env
  2. provider login
  3. init
  4. sync GCP secrets from ${ENV_FILE}
  5. build and upload images
  6. copy public Firecracker builds
  7. terraform apply without Nomad jobs
  8. terraform apply with Nomad jobs

Flags are controlled via env vars:
  SKIP_SECRET_SYNC=true
  SKIP_BUILD=true
  SKIP_PUBLIC_BUILDS=true
EOF
}

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Environment file not found: ${ENV_FILE}" >&2
  usage
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

if [[ "${PROVIDER:-gcp}" != "gcp" ]]; then
  echo "This script only supports PROVIDER=gcp" >&2
  exit 1
fi

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

require_cmd make
require_cmd gcloud
require_cmd terraform
require_cmd packer

if [[ "${SKIP_BUILD}" != "true" ]]; then
  require_cmd docker
  require_cmd go
fi

if [[ "${SKIP_PUBLIC_BUILDS}" != "true" ]]; then
  require_cmd gsutil
fi

cd "${ROOT_DIR}"

make switch-env ENV="${ENV_NAME}"
make provider-login
make init

if [[ "${SKIP_SECRET_SYNC}" != "true" ]]; then
  "${ROOT_DIR}/scripts/gcp-sync-secrets.sh" "${ENV_NAME}"
fi

if [[ "${SKIP_BUILD}" != "true" ]]; then
  make build-and-upload
fi

if [[ "${SKIP_PUBLIC_BUILDS}" != "true" ]]; then
  make copy-public-builds
fi

make plan-without-jobs
make apply
make plan
make apply
