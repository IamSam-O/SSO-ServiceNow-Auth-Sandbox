# sso-tunnel — Cloudflare

Docker Compose project that exposes `authentik-server` from `sso-infrastructure`
publicly via a Cloudflare Tunnel so ServiceNow can reach it for SAML flows.

Requires a domain you own with Cloudflare as the DNS provider.

---

## Prerequisites

- `sso-infrastructure` running — start it first so `sso-net` exists
- A Cloudflare account
- A domain with Cloudflare DNS

---

## Setup

1. Copy `.env.example` to `.env` and fill in `DOMAIN` and `TUNNEL_NAME`
2. Copy `routes.conf.example` to `routes.conf` and set your subdomain
3. Start the tunnel:
   ```bash
   docker compose up -d
   ```
4. On first run the container prints a Cloudflare authentication URL — open it
   in a browser to authorise the tunnel. Credentials are saved to `./data/` and
   reused on subsequent starts.

---

## How it works

The container joins the `sso-net` Docker network created by `sso-infrastructure`
and reaches `authentik-server` by container name. On first run it authenticates
with Cloudflare, creates the named tunnel, and writes DNS CNAMEs for each route
in `routes.conf`. Subsequent restarts skip authentication and reuse saved credentials.

---

## Not for production

This is a practice environment. Do not use with production credentials or systems.
