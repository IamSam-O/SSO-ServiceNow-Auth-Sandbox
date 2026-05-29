# sso-tunnel — ngrok

Docker Compose project that exposes `authentik-server` from `sso-infrastructure`
publicly via ngrok so ServiceNow can reach it for SAML flows. No domain required.

---

## Prerequisites

- `sso-infrastructure` running — start it first so `sso-net` exists
- A free ngrok account — register at [ngrok.com](https://ngrok.com)
- Your auth token and static dev domain from the ngrok dashboard

---

## Static dev domain (free)

Every ngrok account is automatically assigned a free static dev domain on
`ngrok-free.app` (e.g. `abc123xyz.ngrok-free.app`). This domain is permanently
assigned to your account and does not change between restarts — configure
ServiceNow once and it stays valid.

To find your domain: **ngrok dashboard → Universal Gateway → Domains**

---

## Setup

1. Copy `.env.example` to `.env`
2. Set `NGROK_AUTHTOKEN` from the ngrok dashboard
3. Set `NGROK_DOMAIN` to your static dev domain
4. Start `sso-infrastructure` first, then start the tunnel:
   ```bash
   docker compose up -d
   ```

---

## Interstitial page note

On the free plan, ngrok displays a browser warning page before forwarding
traffic to your app. This only affects browser navigation — programmatic HTTP
requests (such as ServiceNow fetching Authentik's SAML metadata URL) are not
affected.

---

## Not for production

This is a practice environment. Do not use with production credentials or systems.