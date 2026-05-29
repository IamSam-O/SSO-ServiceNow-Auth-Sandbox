# sso-tunnel

Optional tunnel configurations for exposing `authentik-server` from
`sso-infrastructure` publicly so ServiceNow can reach it for SAML flows.

Two preconfigured options are provided — Cloudflare Tunnel and ngrok. Neither
is required if you already have an alternative way to expose a local service
publicly.

---

## Options

### Cloudflare Tunnel (`cloudflare/`)

Requires a domain you own with Cloudflare as the DNS provider. Provides a
stable, permanent public URL — configure ServiceNow once and never update it.
Cloudflare Tunnel is free.

### ngrok (`ngrok/`)

No domain required. Every free ngrok account is automatically assigned a
static dev domain on `ngrok-free.app` that persists across restarts — configure
ServiceNow once and it stays valid. No paid plan needed.

---

## Setup

1. `cd` into your chosen tunnel directory
2. Copy `.env.example` to `.env` and fill in the values
3. Start `sso-infrastructure` first, then start the tunnel:
   ```bash
   docker compose up -d
   ```

---

## Using a different tunnel

If you prefer to use a different tunnel solution (e.g. Tailscale Funnel,
Localtunnel, a self-hosted reverse proxy, or a VPS with port forwarding), the
only requirement is that your tunnel must be able to reach `authentik-server`
on port `9000`.

The simplest way to achieve this is to connect your tunnel container or process
to the `sso-net` Docker network, which is created by `sso-infrastructure` and
gives direct access to `authentik-server` by container name:

```yaml
networks:
  sso-net:
    external: true
    name: sso-net
```

If your tunnel runs outside Docker entirely (e.g. a native process on the host),
it can reach Authentik via `http://localhost:9000` since `authentik-server`
publishes port `9000` to the host.

---

## Not for production

This is a practice environment. Do not use with production credentials or systems.
