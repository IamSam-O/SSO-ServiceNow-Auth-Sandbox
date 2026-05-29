# sso-infrastructure

> **Disclaimer:** This project is provided as-is for educational and practice
> purposes only. It offers no warranties, guarantees, or protections of any kind.
> The authors accept no liability for any damage, data loss, security incidents,
> or other consequences arising from its use. Do not use any part of this project
> in a production environment or with real credentials, sensitive data, or
> live systems.

> **AI-assisted development:** Claude AI (Anthropic) was used as a development
> tool during the construction of this project. The developer was actively involved
> throughout, with Claude assisting in implementation, code generation, and
> documentation. All components were tested iteratively during development. As with
> any AI-assisted work, independent review of code and configuration is recommended
> before use.

Core identity provider stack for a self-contained, non-production SSO practice
environment. Authentik acts as the Identity Provider, backed by OpenLDAP as a
simulated Active Directory user store. SAML 2.0 and SCIM 2.0 are used to
integrate with a ServiceNow Personal Developer Instance.

This repository is one of three:

| Repository | Purpose |
|---|---|
| **sso-infrastructure** (this repo) | Authentik, OpenLDAP, LDIF Tool, scim-refresh |
| **sso-tunnel-cloudflare** | Cloudflare Tunnel connector — requires a domain you own |
| **sso-tunnel-ngrok** | ngrok tunnel connector — no domain required |

The tunnel repositories join the `sso-net` Docker network created by this stack
and expose Authentik publicly so ServiceNow can reach it.

---

## What it simulates

| Enterprise component | Simulated by |
|---|---|
| Active Directory / LDAP | OpenLDAP |
| Identity Provider (IdP) | Authentik |
| SSO protocol | SAML 2.0 |
| User provisioning protocol | SCIM 2.0 |
| ServiceNow instance | ServiceNow PDI (free developer instance) |
| Public IdP endpoint | Cloudflare Tunnel or ngrok (separate repo) |

---

## Stack

```
OpenLDAP ──(LDAP sync)──▶ Authentik ──(SCIM push)──▶ ServiceNow PDI
                               │
                         (SAML assertion)
                               │
              User ──▶ SSO URL ──▶ Authentik login ──▶ ServiceNow session
```

| Container | Image | Role |
|---|---|---|
| `openldap` | `osixia/openldap:1.3.0` | Simulated user/group directory |
| `phpldapadmin` | `osixia/phpldapadmin:0.9.0` | Browser UI for OpenLDAP (`localhost:8081`) |
| `authentik-server` | `ghcr.io/goauthentik/server:2026.5.2` | IdP — SAML flows and admin UI (`localhost:9000`) |
| `authentik-worker` | `ghcr.io/goauthentik/server:2026.5.2` | Background tasks — LDAP sync, SCIM push |
| `postgres` | `postgres:16` | Authentik database |
| `redis` | `redis:alpine` | Authentik task queue |
| `scim-refresh` | custom build | Keeps ServiceNow OAuth token current for SCIM |
| `ldif-tool` | custom build | Web UI for importing users into OpenLDAP (`localhost:5000`) |

---

## Prerequisites

- Docker Desktop
- A ServiceNow PDI — register free at [developer.servicenow.com](https://developer.servicenow.com)
- One of the tunnel repositories cloned alongside this one
- OpenSSL for generating `AUTHENTIK_SECRET_KEY`

---

## Quick start

1. Clone this repository and one tunnel repository
2. Copy `.env.example` to `.env` and fill in all values
3. Generate a secret key:
   ```bash
   openssl rand -base64 36
   ```
4. Start the infrastructure stack:
   ```bash
   docker compose up -d
   ```
5. In the tunnel repository, follow its README to expose Authentik publicly
6. Follow **CONFIGURATION.md** in order — each section depends on the previous one

The `data/` directory is gitignored and auto-created by Docker on first start.

---

## Networks

Two Docker networks are defined:

| Network | Internal | Purpose |
|---|---|---|
| `internal` | Yes | Container-to-container only — postgres, redis, openldap |
| `sso-net` | No | Host and tunnel access — Authentik, phpLDAPadmin, ldif-tool, scim-refresh |

Tunnel repositories join `sso-net` as an external network, allowing their
containers to reach `authentik-server` by name.

---

## Configuration

Full step-by-step setup instructions are in [CONFIGURATION.md](CONFIGURATION.md).

| Section | What it covers |
|---|---|
| 1 | Import LDAP users |
| 2 | Authentik initial setup, LDAP source, attribute mappings |
| 3 | Create the Authentik ServiceNow application and SAML provider |
| 4 | Configure ServiceNow Multi-Provider SSO |
| 5 | SCIM provisioning — users, groups, ETL fixes |
| 6 | Testing SSO login end-to-end |
| 7 | LDIF Tool — importing and managing LDAP users |
| 8 | Authentik application policy for automatic group coverage |
| 9 | Network segmentation |

---

## Known limitations

- LDAP group sync has a persistent `Group() got unexpected keyword arguments: 'path'`
  bug in Authentik that prevents group creation via sync. Groups must be pre-created
  via the LDIF Tool's Sync Groups button first.
- Authentik does not expose a programmatic LDAP sync endpoint — full syncs must be
  triggered manually in the admin UI.
- ServiceNow role assignments based on group membership are not yet implemented.

---

## Not for production

- Self-signed certificates
- Plaintext credentials in `.env`
- No HA, backups, or monitoring
- ServiceNow PDI has rate limits and resets periodically
- OpenLDAP is a stand-in — not a real AD with Kerberos, GPO, etc.
