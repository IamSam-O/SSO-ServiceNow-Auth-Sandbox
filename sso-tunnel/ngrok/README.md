# sso-tunnel — ngrok

Docker Compose project that exposes `authentik-server` from `sso-infrastructure`
publicly via ngrok so ServiceNow can reach it for SAML flows. No domain required.

---

## Prerequisites

- `sso-infrastructure` running — start it first so `sso-net` exists
- A free ngrok account — register at [ngrok.com](https://ngrok.com)
- Your auth token from the ngrok dashboard

---

## Setup

1. Copy `.env.example` to `.env` and paste your `NGROK_AUTHTOKEN`
2. Start the tunnel:
   ```bash
   docker compose up -d
   ```
3. Get the public URL:
   ```bash
   docker compose logs ngrok
   ```

Update the Authentik metadata URL in the ServiceNow IdP record whenever the
URL changes (on every restart with the free tier).

---

## Static domain (optional)

On a paid ngrok plan, assign a static domain so the URL never changes:

1. Reserve a domain in the ngrok dashboard
2. Uncomment `NGROK_DOMAIN` in `.env`
3. Update the `command` in `docker-compose.yml`:
   ```yaml
   command: http authentik-server:9000 --domain=${NGROK_DOMAIN} --log stdout
   ```

---

## Free tier limitations

The public URL changes on every container restart. After each restart update
the Authentik metadata URL in the ServiceNow IdP record and re-import metadata.

Use the Cloudflare tunnel project instead if you own a domain.

---

## Not for production

This is a practice environment. Do not use with production credentials or systems.
