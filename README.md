# SSO ServiceNow Auth Sandbox

A self-contained, non-production workspace for practising enterprise Single
Sign-On and SCIM provisioning with ServiceNow using SAML 2.0 and Authentik
as the Identity Provider.

---

> **Disclaimer:** This project is provided as-is for educational and practice
> purposes only. It offers no warranties, guarantees, or protections of any kind.
> The authors accept no liability for any damage, data loss, security incidents,
> or other consequences arising from its use. Do not use any part of this project
> in a production environment or with real credentials, sensitive data, or live
> systems.

> **AI-assisted development:** Claude AI (Anthropic) was used as a development
> tool during the construction of this project. The developer was actively involved
> throughout, with Claude assisting in implementation, code generation, and
> documentation. All components were tested iteratively during development. As with
> any AI-assisted work, independent review of code and configuration is recommended
> before use.

---

## Project structure

```
SSO ServiceNow Auth Sandbox/
├── CONFIGURATION.md            ← Start here after cloning
├── README.md
├── .gitignore
├── .gitattributes
│
├── sso-infrastructure/         ← Core identity provider stack
│   ├── docker-compose.yml
│   ├── .env.example
│   ├── .env                    ← Created by you, gitignored
│   ├── sample-users.ldif
│   ├── CLAUDE.md
│   ├── data/                   ← Auto-created by Docker on first run, gitignored
│   │   ├── authentik/
│   │   ├── ldap/
│   │   ├── postgres/
│   │   └── redis/
│   ├── ldif-tool/              ← Flask app for importing users into OpenLDAP
│   │   ├── app.py
│   │   ├── schema.json
│   │   ├── requirements.txt
│   │   ├── Dockerfile
│   │   ├── MOCK_DATA.json
│   │   └── templates/
│   │       └── index.html
│   └── scim-refresh/           ← Alpine/cron container for SCIM token renewal
│       ├── Dockerfile
│       ├── entrypoint.sh
│       └── refresh.sh
│
└── sso-tunnel/                 ← Tunnel connectors — choose one
    ├── cloudflare/             ← Cloudflare Tunnel (requires a domain you own)
    │   ├── docker-compose.yml
    │   ├── .env.example
    │   ├── .env                ← Created by you, gitignored
    │   ├── routes.conf.example
    │   ├── routes.conf         ← Created by you, gitignored
    │   └── cloudflared/
    │       ├── Dockerfile
    │       └── entrypoint.sh
    └── ngrok/                  ← ngrok tunnel (no domain required)
        ├── docker-compose.yml
        ├── .env.example
        ├── .env                ← Created by you, gitignored
        ├── ngrok.yml.example
        └── ngrok.yml           ← Created by you, gitignored
```

### Directories that do not exist until after first run

`sso-infrastructure/data/` is created automatically by Docker the first time
`docker compose up` is run. It holds all persistent state for Authentik,
OpenLDAP, PostgreSQL, and Redis as bind-mounted volumes. Its subdirectories are
tracked in git via `.gitkeep` files but their contents are gitignored.

`sso-tunnel/cloudflare/data/` is created on the first run of the Cloudflare
tunnel container. It holds the Cloudflare certificate and tunnel credentials.
Do not delete this directory between restarts — it is required for the tunnel
to reconnect without re-authenticating.

---

## Stack

| Container | Image | Role |
|---|---|---|
| `authentik-server` | `ghcr.io/goauthentik/server:2026.5.2` | Identity Provider — SAML flows, admin UI (`localhost:9000`) |
| `authentik-worker` | `ghcr.io/goauthentik/server:2026.5.2` | Background tasks — LDAP sync, SCIM push |
| `openldap` | `osixia/openldap:1.5.0` | Simulated user and group directory |
| `phpldapadmin` | `osixia/phpldapadmin:0.9.0` | Browser UI for OpenLDAP (`localhost:8081`) |
| `postgres` | `postgres:16` | Authentik database |
| `redis` | `redis:alpine` | Authentik task queue and cache |
| `ldif-tool` | custom build | Web UI for importing users into OpenLDAP (`localhost:5000`) |
| `scim-refresh` | custom build | Renews ServiceNow OAuth token for SCIM every 25 minutes |
| `cloudflared` | custom build | Cloudflare Tunnel connector (optional) |
| `ngrok` | `ngrok/ngrok:latest` | ngrok tunnel connector (optional) |

---

## Quick start

```powershell
# 1 — configure the infrastructure environment
Copy-Item sso-infrastructure\.env.example sso-infrastructure\.env
# fill in sso-infrastructure\.env before proceeding

# 2 — start the core stack
cd sso-infrastructure
docker compose up -d

# 3 — start your chosen tunnel
cd ..\sso-tunnel\ngrok        # or cloudflare
docker compose up -d
```

Then follow **CONFIGURATION.md** from the beginning. The configuration guide
walks through the full setup in order — do not skip sections.

> **`AUTHENTIK_API_TOKEN` cannot be filled in before first run.** Leave it blank
> in `.env` when starting the stack for the first time. The token is created
> inside the Authentik UI after it is running — Section 2.2 of the configuration
> guide covers this.

---

## Networks

`sso-infrastructure` creates two Docker networks:

| Network | Internal | Purpose |
|---|---|---|
| `internal` | Yes | Container-to-container only — postgres, redis, openldap |
| `sso-net` | No | Host and tunnel access — Authentik, phpLDAPadmin, ldif-tool, scim-refresh |

The tunnel projects join `sso-net` as an external network. `sso-infrastructure`
must be started first — the tunnel containers will fail if `sso-net` does not
exist.

---

## Known limitations

- Authentik has a persistent bug (`Group() got unexpected keyword arguments: 'path'`)
  that prevents group creation via LDAP sync. Groups must be pre-created via the
  LDIF Tool's Sync Groups button before running an LDAP sync.
- Authentik does not expose a programmatic LDAP sync endpoint — full syncs must
  be triggered manually in the admin UI.
- ServiceNow role assignments based on group membership are not yet implemented.
- ServiceNow PDI instances reset periodically and have rate limits — this is a
  ServiceNow platform constraint, not a limitation of this project.

---

## Not for production

- Self-signed certificates
- Plaintext credentials in `.env`
- No HA, backups, or monitoring
- OpenLDAP is a stand-in — not a real AD with Kerberos, GPO, or domain trust