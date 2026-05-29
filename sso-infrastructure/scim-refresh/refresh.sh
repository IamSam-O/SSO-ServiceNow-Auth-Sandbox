#!/bin/bash
set -euo pipefail

# Source env vars when called from cron (not inherited from shell)
[ -f /etc/environment ] && source /etc/environment

log_info()  { echo "[INFO]  $(date '+%Y-%m-%d %H:%M:%S') $*"; }
log_error() { echo "[ERROR] $(date '+%Y-%m-%d %H:%M:%S') $*"; exit 1; }

INSTANCE=$(echo "${SERVICENOW_INSTANCE}" | sed 's|^https://||;s|^http://||;s|/$||')

log_info "Requesting token from ServiceNow (${INSTANCE})..."
TOKEN_RESPONSE=$(curl -s -X POST "https://${INSTANCE}/oauth_token.do" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "grant_type=password" \
  --data-urlencode "client_id=${SERVICENOW_CLIENT_ID}" \
  --data-urlencode "client_secret=${SERVICENOW_CLIENT_SECRET}" \
  --data-urlencode "username=${SERVICENOW_SCIM_USER}" \
  --data-urlencode "password=${SERVICENOW_SCIM_PASSWORD}")

ACCESS_TOKEN=$(echo "$TOKEN_RESPONSE" | jq -r '.access_token // empty')
if [[ -z "$ACCESS_TOKEN" ]]; then
  log_error "Failed to get token. Response: $TOKEN_RESPONSE"
fi
log_info "Token received."

log_info "Looking up Authentik SCIM provider..."
PROVIDER_RESPONSE=$(curl -s "${AUTHENTIK_URL}/api/v3/providers/scim/" \
  -H "Authorization: Bearer ${AUTHENTIK_API_TOKEN}")
PROVIDER_ID=$(echo "$PROVIDER_RESPONSE" | jq -r '.results[0].pk // empty')
if [[ -z "$PROVIDER_ID" ]]; then
  log_error "No SCIM provider found. Create one in Authentik under Applications → Providers."
fi
log_info "Found SCIM provider ID: ${PROVIDER_ID}. Updating token..."

HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X PATCH \
  "${AUTHENTIK_URL}/api/v3/providers/scim/${PROVIDER_ID}/" \
  -H "Authorization: Bearer ${AUTHENTIK_API_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"token\": \"${ACCESS_TOKEN}\"}")

if [[ "$HTTP_STATUS" == "200" ]]; then
  log_info "Token updated successfully."
else
  log_error "Failed to update token. HTTP status: ${HTTP_STATUS}"
fi
