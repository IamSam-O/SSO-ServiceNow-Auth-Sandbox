# SSO ServiceNow Auth Sandbox

A self-contained, non-production workspace for practising enterprise Single
Sign-On and SCIM provisioning with ServiceNow using SAML 2.0 and Authentik
as the Identity Provider.

---

## Structure

```
SSO ServiceNow Auth Sandbox/
├── sso-infrastructure/     Core IdP stack — start this first
└── sso-tunnel/
    ├── cloudflare/         Cloudflare Tunnel — requires a domain
    └── ngrok/              ngrok tunnel — no domain required
```

### `sso-infrastructure`

The main git repository. Contains Authentik, OpenLDAP, the LDIF Tool, and the
SCIM token refresh container. Defines the `sso-net` Docker network that tunnel
projects connect to.

### `sso-tunnel/cloudflare`

Docker Compose project that exposes Authentik publicly via a Cloudflare Tunnel.
Requires a domain you own with Cloudflare as the DNS provider. Provides a stable
URL — configure ServiceNow once and never update it.

### `sso-tunnel/ngrok`

Docker Compose project that exposes Authentik publicly via ngrok. No domain
required. On the free tier the public URL changes on every restart, which
requires updating the ServiceNow IdP metadata URL after each restart. A paid
ngrok plan with a static domain removes this limitation.

---

## Start order

Always start `sso-infrastructure` first — it creates the `sso-net` Docker
network that the tunnel projects depend on.

```bash
# 1 — start the core stack
cd sso-infrastructure
docker compose up -d

# 2 — start your chosen tunnel
cd ../sso-tunnel/cloudflare   # or ngrok
docker compose up -d
```

---

## Not for production

This workspace is for learning and practice only. It offers no warranties or
protections of any kind. Do not use real credentials, sensitive data, or connect
it to live systems.
