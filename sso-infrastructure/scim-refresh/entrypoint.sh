#!/bin/bash
set -e

log_info()  { echo "[INFO]  $(date '+%Y-%m-%d %H:%M:%S') $*"; }

log_info "Waiting for Authentik to be ready..."
until curl -sf "${AUTHENTIK_URL:-http://authentik-server:9000}/-/health/ready/" >/dev/null 2>&1; do
  sleep 5
done
log_info "Authentik is ready."

log_info "Running initial token refresh..."
/refresh.sh || log_info "Initial refresh failed — will retry on next cron run."

# Export env vars for cron
{
  for var in SERVICENOW_INSTANCE SERVICENOW_CLIENT_ID SERVICENOW_CLIENT_SECRET SERVICENOW_SCIM_USER SERVICENOW_SCIM_PASSWORD AUTHENTIK_API_TOKEN AUTHENTIK_URL; do
    printf '%s=%q\n' "$var" "${!var:-}"
  done
} > /etc/environment

# Schedule every 25 minutes
echo "*/25 * * * * /refresh.sh >> /var/log/scim-refresh.log 2>&1" | crontab -
log_info "Cron scheduled every 25 minutes."

crond -f
