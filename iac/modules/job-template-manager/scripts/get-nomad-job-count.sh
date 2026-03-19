#!/bin/bash
# Get current job count from Nomad API to preserve autoscaler-managed values.
# This prevents Terraform from resetting count on job updates.
#
# IMPORTANT: Under normal operation this should fail on Nomad API errors
# (network, auth, TLS) to prevent accidental scale-downs. However during
# teardown the Nomad endpoint may already be gone. In that case we safely
# fall back to min_count so Terraform destroy can continue cleaning up.
#
# Based on: https://registry.terraform.io/providers/hashicorp/external/latest/docs/data-sources/external#processing-json-in-shell-scripts

set -euo pipefail

# Extract arguments from the input into shell variables.
eval "$(jq -r '@sh "ADDR=\(.nomad_addr) TOKEN=\(.nomad_token) JOB=\(.job_name) MIN=\(.min_count)"')"

# Fetch job info and capture HTTP status code
set +e
RESPONSE=$(curl -s -w "\n---HTTP_STATUS:%{http_code}" -H "X-Nomad-Token: $TOKEN" \
  "$ADDR/v1/job/$JOB" 2>&1)
CURL_EXIT=$?
set -e

# Extract HTTP code and body
HTTP_CODE=$(echo "$RESPONSE" | grep '^---HTTP_STATUS:' | sed 's/---HTTP_STATUS://')
BODY=$(echo "$RESPONSE" | grep -v '^---HTTP_STATUS:')

# Handle curl-level failures (network, TLS, DNS, etc.)
if [ $CURL_EXIT -ne 0 ]; then
  COUNT="$MIN"
  jq -n --arg count "$COUNT" '{"count":$count}'
  exit 0
fi

# Handle HTTP error responses
if [ -z "$HTTP_CODE" ]; then
  echo "ERROR: Could not determine HTTP status code from Nomad API response" >&2
  exit 1
fi

if [ "$HTTP_CODE" = "404" ]; then
  # Job doesn't exist yet - use minimum count
  COUNT="$MIN"
elif [ "$HTTP_CODE" -ge 200 ] && [ "$HTTP_CODE" -lt 300 ]; then
  # Success - parse the count from response
  COUNT=$(echo "$BODY" | jq -r '.TaskGroups[0].Count // empty' 2>/dev/null)
  if ! [[ "$COUNT" =~ ^[0-9]+$ ]]; then
    echo "ERROR: Failed to parse job count from Nomad API response" >&2
    echo "Response body: $BODY" >&2
    exit 1
  fi
else
  # During teardown the endpoint may still resolve but return an upstream
  # error while the control plane is being removed. Fall back to min_count.
  COUNT="$MIN"
fi

# Ensure COUNT is at least MIN
if [ "$COUNT" -lt "$MIN" ]; then
  COUNT="$MIN"
fi

# Safely produce a JSON object containing the result value.
jq -n --arg count "$COUNT" '{"count":$count}'
