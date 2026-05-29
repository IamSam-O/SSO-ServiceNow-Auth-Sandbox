#!/bin/bash
set -e

DATA_PATH="/data"
CONFIG_FILE="/tmp/config.json"
ROUTES_FILE="/etc/cloudflared/routes.conf"

log_info()  { echo "[INFO] $*"; }
log_error() { echo "[ERROR] $*"; exit 1; }

# --- Certificate ---

hasCertificate() { [[ -f "${DATA_PATH}/cert.pem" ]]; }

createCertificate() {
  log_info "No certificate found. Open the URL below in your browser to authenticate with Cloudflare:"
  cloudflared tunnel login 2>&1
  [[ -f "/root/.cloudflared/cert.pem" ]] && mv /root/.cloudflared/cert.pem "${DATA_PATH}/cert.pem"
  hasCertificate || log_error "Certificate creation failed."
  log_info "Certificate saved."
}

# --- Tunnel ---

hasTunnel() {
  if [[ -f "${DATA_PATH}/tunnel.json" ]]; then
    TUNNEL_UUID=$(jq -r '.TunnelID // .tunnelID // .id // .tunnel_id // empty' "${DATA_PATH}/tunnel.json" 2>/dev/null)
    [[ -n "$TUNNEL_UUID" ]] && { log_info "Existing tunnel: $TUNNEL_UUID"; return 0; }
  fi
  return 1
}

createTunnel() {
  log_info "Creating tunnel: $TUNNEL_NAME"
  cloudflared tunnel \
    --origincert="${DATA_PATH}/cert.pem" \
    create \
    --cred-file="${DATA_PATH}/tunnel.json" \
    "$TUNNEL_NAME" || log_error "Tunnel creation failed. Delete any existing tunnel named '$TUNNEL_NAME' from the Cloudflare dashboard first."
  hasTunnel || log_error "Could not read tunnel credentials after creation."
  log_info "Tunnel created: $TUNNEL_UUID"
}

# --- Config ---

createConfig() {
  log_info "Building ingress config..."
  local ingress="[]"

  while IFS= read -r line || [[ -n "$line" ]]; do
    route=$(echo "$line" | sed 's/^[[:space:]]*-[[:space:]]*//' | tr -d '\r')
    [[ -z "$route" || "$route" == \#* ]] && continue
    HOSTNAME=$(echo "$route" | cut -d: -f1)
    HOST=$(echo "$route" | cut -d: -f2)
    PORT=$(echo "$route" | cut -d: -f3)
    SERVICE="http://${HOST}:${PORT}"
    log_info "Route: $HOSTNAME -> $SERVICE"
    ingress=$(echo "$ingress" | jq \
      --arg h "$HOSTNAME" --arg s "$SERVICE" \
      '. + [{"hostname": $h, "service": $s, "originRequest": {"noTLSVerify": true}}]')
  done < "$ROUTES_FILE"

  ingress=$(echo "$ingress" | jq '. + [{"service": "http_status:404"}]')

  jq -n \
    --arg tunnel "$TUNNEL_UUID" \
    --arg creds "${DATA_PATH}/tunnel.json" \
    --argjson ingress "$ingress" \
    '{"tunnel": $tunnel, "credentials-file": $creds, "ingress": $ingress}' \
    > "$CONFIG_FILE"

  log_info "Validating config..."
  cloudflared tunnel \
    --origincert="${DATA_PATH}/cert.pem" \
    --config="$CONFIG_FILE" \
    ingress validate || log_error "Config validation failed."
}

# --- DNS ---

createDNS() {
  while IFS= read -r line || [[ -n "$line" ]]; do
    route=$(echo "$line" | sed 's/^[[:space:]]*-[[:space:]]*//' | tr -d '\r')
    [[ -z "$route" || "$route" == \#* ]] && continue
    HOSTNAME=$(echo "$route" | cut -d: -f1)
    log_info "Creating DNS record: $HOSTNAME"
    cloudflared tunnel \
      --origincert="${DATA_PATH}/cert.pem" \
      route dns -f "$TUNNEL_UUID" "$HOSTNAME" || log_error "DNS creation failed for $HOSTNAME"
  done < "$ROUTES_FILE"
}

# --- Main ---

mkdir -p "$DATA_PATH"
TUNNEL_NAME="${TUNNEL_NAME:-homelab}"

hasCertificate  || createCertificate
hasTunnel       || createTunnel
createConfig
createDNS

log_info "Starting cloudflared..."
exec cloudflared tunnel \
  --no-autoupdate \
  --origincert="${DATA_PATH}/cert.pem" \
  --config="$CONFIG_FILE" \
  --loglevel=info \
  run "$TUNNEL_NAME"
