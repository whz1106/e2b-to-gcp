#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/gcp-sync-secrets.sh [env]

Reads .env.<env> from the repository root and writes configured values into
GCP Secret Manager versions expected by the Terraform GCP deployment.

Required:
  GCP_PROJECT_ID
  PREFIX
  POSTGRES_CONNECTION_STRING

Optional:
  CLOUDFLARE_API_TOKEN
  SUPABASE_JWT_SECRETS
  POSTHOG_API_KEY
  LAUNCH_DARKLY_API_KEY
  ANALYTICS_COLLECTOR_HOST
  ANALYTICS_COLLECTOR_API_TOKEN
  GRAFANA_OTLP_URL
  GRAFANA_USERNAME
  GRAFANA_OTEL_COLLECTOR_TOKEN
  GRAFANA_LOGS_USER
  GRAFANA_LOGS_URL
  GRAFANA_LOGS_COLLECTOR_API_TOKEN
  REDIS_CLUSTER_URL
  REDIS_TLS_CA_BASE64
  ROUTING_DOMAINS_JSON
  SECURITY_NOTIFICATION_EMAIL
  DOCKERHUB_REMOTE_REPO_USERNAME
  DOCKERHUB_REMOTE_REPO_PASSWORD
EOF
}

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_NAME="${1:-$(cat "${ROOT_DIR}/.last_used_env" 2>/dev/null || echo dev)}"
ENV_FILE="${ROOT_DIR}/.env.${ENV_NAME}"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Environment file not found: ${ENV_FILE}" >&2
  usage
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

: "${GCP_PROJECT_ID:?GCP_PROJECT_ID must be set in ${ENV_FILE}}"
: "${PREFIX:?PREFIX must be set in ${ENV_FILE}}"
: "${POSTGRES_CONNECTION_STRING:?POSTGRES_CONNECTION_STRING must be set in ${ENV_FILE}}"

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

require_cmd gcloud

put_secret() {
  local secret_id="$1"
  local value="$2"

  if [[ -z "${value}" ]]; then
    echo "Skipping ${secret_id} (empty)"
    return 0
  fi

  printf '%s' "${value}" | gcloud secrets versions add "${secret_id}" \
    --project "${GCP_PROJECT_ID}" \
    --data-file=-

  echo "Updated ${secret_id}"
}

put_secret "${PREFIX}postgres-connection-string" "${POSTGRES_CONNECTION_STRING}"
put_secret "${PREFIX}cloudflare-api-token" "${CLOUDFLARE_API_TOKEN:-}"
put_secret "${PREFIX}supabase-jwt-secrets" "${SUPABASE_JWT_SECRETS:-}"
put_secret "${PREFIX}posthog-api-key" "${POSTHOG_API_KEY:-}"
put_secret "${PREFIX}launch-darkly-api-key" "${LAUNCH_DARKLY_API_KEY:-}"
put_secret "${PREFIX}analytics-collector-host" "${ANALYTICS_COLLECTOR_HOST:-}"
put_secret "${PREFIX}analytics-collector-api-token" "${ANALYTICS_COLLECTOR_API_TOKEN:-}"
put_secret "${PREFIX}grafana-otlp-url" "${GRAFANA_OTLP_URL:-}"
put_secret "${PREFIX}grafana-username" "${GRAFANA_USERNAME:-}"
put_secret "${PREFIX}grafana-otel-collector-token" "${GRAFANA_OTEL_COLLECTOR_TOKEN:-}"
put_secret "${PREFIX}grafana-logs-user" "${GRAFANA_LOGS_USER:-}"
put_secret "${PREFIX}grafana-logs-url" "${GRAFANA_LOGS_URL:-}"
put_secret "${PREFIX}grafana-api-key-logs-collector" "${GRAFANA_LOGS_COLLECTOR_API_TOKEN:-}"
put_secret "${PREFIX}redis-cluster-url" "${REDIS_CLUSTER_URL:-}"
put_secret "${PREFIX}redis-tls-ca-base64" "${REDIS_TLS_CA_BASE64:-}"
put_secret "${PREFIX}routing-domains" "${ROUTING_DOMAINS_JSON:-}"
put_secret "${PREFIX}security-notification-email" "${SECURITY_NOTIFICATION_EMAIL:-}"
put_secret "${PREFIX}dockerhub-remote-repo-username" "${DOCKERHUB_REMOTE_REPO_USERNAME:-}"
put_secret "${PREFIX}dockerhub-remote-repo-password" "${DOCKERHUB_REMOTE_REPO_PASSWORD:-}"
