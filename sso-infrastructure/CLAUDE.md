# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Local SSO practice environment for learning SAML 2.0 with ServiceNow. Authentik acts as the Identity Provider, backed by OpenLDAP as a simulated Active Directory user store. The stack is exposed publicly via a Cloudflare Tunnel so that a ServiceNow Personal Developer Instance (PDI) can communicate with it.

**User flow:**
```
OpenLDAP user (dept, title, groups)
    ↓  LDAP federation
Authentik maps attributes → SAML assertion
    ↓  SP-initiated SSO
ServiceNow JIT creates sys_user from assertion attributes
```

---

## Common Commands

```bash
# Start everything
docker compose up -d

# Watch cloudflared logs (shows auth URL on first run, tunnel status ongoing)
docker compose logs -f cloudflared

# Rebuild a custom service after editing its source
docker compose up -d --build cloudflared
docker compose up -d --build ldif-tool
docker compose up -d --build scim-refresh

# Stop without removing containers
docker compose stop

# Teardown — data in ./data/ survives (bind-mounted)
docker compose down

# Full reset — wipes ALL data including Authentik DB, LDAP, Redis, cloudflared credentials
docker compose down && Remove-Item -Recurse -Force ./data
```

```powershell
# Mirror LDAP groups into Authentik (superseded by ldif-tool /sync — kept as fallback)
.\create-ldap-groups.ps1
```

---

## Architecture

| Service | Role |
|---|---|
| **postgres** | Authentik database backend — healthchecked |
| **redis** | Authentik task queue/cache — healthchecked |
| **authentik-server** | IdP web server — federates with OpenLDAP, issues SAML assertions — port 9000 |
| **authentik-worker** | Background task runner — mounts `docker.sock` for outpost management |
| **openldap** | Simulated AD user store (`osixia/openldap:1.3.0`) — internal only |
| **phpldapadmin** | Web UI for OpenLDAP — port 8081 |
| **ldif-tool** | Flask web app — JSON→LDIF conversion and direct LDAP import — port 5000 |
| **scim-refresh** | Alpine/cron container — keeps ServiceNow SCIM token alive every 25 min |
| **cloudflared** | Custom container — exposes Authentik publicly via Cloudflare Tunnel |

`authentik-server` and `authentik-worker` use the same image (`ghcr.io/goauthentik/server`) with different `command` values. Both wait for postgres and redis healthchecks before starting.

**Data persistence:** All state lives in `./data/` bind-mounts — there are no named Docker volumes. `docker compose down -v` is effectively a no-op. The only way to fully reset is to delete `./data/`.

**Networks:** Two Docker networks — `internal` (no external routing, databases and LDAP) and `external` (bridge, for services that need outbound internet). `authentik-server` must be on `external` for `localhost:9000` and host-side API scripts to work; `phpldapadmin` must also be on `external` for `localhost:8081` — `internal: true` blocks host port mappings.

**Bootstrap caveat:** `AUTHENTIK_BOOTSTRAP_EMAIL` and `AUTHENTIK_BOOTSTRAP_PASSWORD` only apply once when `./data/postgres/` is empty. The compose file uses `env_file: .env` — these variables must be named exactly `AUTHENTIK_BOOTSTRAP_EMAIL` / `AUTHENTIK_BOOTSTRAP_PASSWORD` in `.env`. If the bootstrap ran before `.env` was configured, the default admin is `akadmin` / `root@example.com`.

**`cloudflared/entrypoint.sh`** state machine (runs on every container start):
1. **First run**: authenticates with Cloudflare (`cloudflared tunnel login`), creates the tunnel — cert and credentials saved to `./data/cloudflared/`
2. **Every start**: reads `routes.conf`, builds and validates a fresh ingress config, creates/overwrites DNS CNAMEs, starts the daemon by tunnel name
3. **Subsequent restarts**: skips auth and tunnel creation (credentials persist in `./data/cloudflared/`)

Handles Windows line endings in `routes.conf` and multiple JSON key formats in tunnel credentials.

---

## Configuration

**`.env`** — never commit; copy from `.env.example`. All services receive the full `.env` via `env_file: .env`.

| Variable | Purpose |
|---|---|
| `DOMAIN` | Drives Cloudflare route subdomains and OpenLDAP base DN (e.g. `soconnell.com` → `dc=soconnell,dc=com`) |
| `AUTHENTIK_SECRET_KEY` | Required — generate with `openssl rand -base64 36`. May contain `$` — handled safely by `env_file`, do not escape |
| `AUTHENTIK_BOOTSTRAP_EMAIL` / `AUTHENTIK_BOOTSTRAP_PASSWORD` | Admin credentials set on first start only — must use these exact names (not `AUTHENTIK_ADMIN_*`) |
| `AUTHENTIK_API_TOKEN` | Required for `ldif-tool`, `scim-refresh`, and `create-ldap-groups.ps1` — create under Directory → Tokens & App Passwords (Intent: API Token, assigned to a regular user — not an `ak-*` service account) |
| `AUTHENTIK_LDAP_SLUG` | Slug of the Authentik LDAP source — used by `ldif-tool` (default: `openldap`) |
| `POSTGRES_*` | PostgreSQL credentials — must match between postgres and authentik services |
| `LDAP_ADMIN_DN` | Full admin bind DN (e.g. `cn=admin,dc=soconnell,dc=com`) — used by `ldif-tool` |
| `LDAP_BASE_DN` | Base DN — used by `ldif-tool` to construct user/group paths |
| `LDAP_ADMIN_PASSWORD` | LDAP admin password |
| `SERVICENOW_INSTANCE` | ServiceNow PDI hostname — used by `scim-refresh` |
| `SERVICENOW_CLIENT_ID` / `SERVICENOW_CLIENT_SECRET` | OAuth app credentials from ServiceNow — special chars handled by `--data-urlencode`, do not escape |
| `SERVICENOW_SCIM_USER` / `SERVICENOW_SCIM_PASSWORD` | Account used by `scim-refresh` to authenticate to ServiceNow OAuth |

**`routes.conf`** — never commit; copy from `routes.conf.example`. Format: `- hostname:docker_service_name:port`. Only Authentik needs a public route (port 9000).

### Accessing services

| Service | URL |
|---|---|
| Authentik admin | `https://<DOMAIN>/if/admin/` (via tunnel) or `http://localhost:9000/if/admin/` |
| phpLDAPadmin | `http://localhost:8081` |
| ldif-tool | `http://localhost:5000` |

phpLDAPadmin login DN: `cn=admin,<LDAP_BASE_DN>`. Password: `LDAP_ADMIN_PASSWORD` from `.env`.

### Recovery when locked out of Authentik

```bash
docker compose exec authentik-worker ak create_recovery_key 1 akadmin
```

Prints a one-time login URL that bypasses the password stage.

---

## Setup Process

Complete `CONFIGURATION.md` sections in order. Critical non-obvious notes are captured here.

### Authentik Initial Setup (Section 2)

**First login** goes to `/if/flow/initial-setup/` — not the admin UI. Set credentials there; these are the credentials for all subsequent logins.

**API Token** must be assigned to a regular user account (e.g. `akadmin`). Authentik service accounts with the `ak-` prefix cannot authenticate to the API.

**LDAP Source** (`Directory → Federation and Social login → Create → LDAP Source`):

| Field | Value |
|---|---|
| Server URI | `ldap://openldap:389` |
| Enable StartTLS | Off |
| Bind CN | `cn=admin,dc=yourdomain,dc=com` |
| Base DN | `dc=yourdomain,dc=com` |
| Addition User DN | `ou=users` |
| Addition Group DN | `ou=groups` |
| User object filter | `(objectClass=inetOrgPerson)` |
| Group object filter | `(objectClass=groupOfNames)` |
| Group membership field | `member` |
| Object uniqueness field | `entryUUID` |
| UUID attribute | `entryUUID` |
| Username attribute | `uid` |

Remove all **Active Directory** mappings from both User and Group Property Mappings — keep only LDAP/OpenLDAP defaults.

**Custom attribute mapping** — to sync `title` and `departmentNumber`, create a single LDAP Source Property Mapping (`Customization → Property Mappings → Create → LDAP Source Property Mapping`). Expression must return a dict; `list_flatten` is NOT automatically applied inside `attributes` — call it explicitly:

```python
return {
    "attributes": {
        "title": list_flatten(ldap.get("title")),
        "departmentNumber": list_flatten(ldap.get("departmentNumber")),
    },
}
```

**Known bug — Authentik 2024.12.3:** LDAP group sync fails with `Group() got unexpected keyword arguments: 'path'`. Groups must be pre-created in Authentik with `ldap_uniq` set before sync will work. Use the ldif-tool's **Sync Groups to Authentik** button (or `create-ldap-groups.ps1`), then run the LDAP sync.

**Verify attributes synced:**
```powershell
docker compose exec postgres psql -U authentik -d authentik -c "SELECT attributes FROM authentik_core_user WHERE username = 'john.doe';"
```
Expected: `{"title": "...", "departmentNumber": "..."}`

**Application policy** — instead of binding individual groups to the ServiceNow app, use one expression policy that covers all LDAP users including future groups (`Customization → Policies → Create → Expression Policy`):
```python
return request.user.path.startswith("goauthentik.io/sources/")
```

### SAML Setup (Section 4)

The metadata exchange is bidirectional — order matters:

1. Create the ServiceNow IdP record in ServiceNow manually (not from metadata yet)
2. Click **Generate Metadata** on the IdP record — save the XML
3. In Authentik: **Applications → Providers → Create → SAML Provider from Metadata** — paste the ServiceNow XML
4. Set **NameID Property Mapping** to `authentik default SAML Mapping: Username` (sends `john.doe`, not email)
5. Sign assertions **On**, sign responses **Off**
6. Assign the provider to the ServiceNow application
7. Back in ServiceNow: **Import Identity Provider Metadata** on the IdP record — paste the Authentik metadata URL

### SCIM Setup (Section 5)

**ServiceNow prerequisites:**
- Install SCIM plugin: `com.snc.integration.scim2`
- Create service account `svc_authentik` with `admin` role (includes `scim_admin`)
- Create OAuth Application Registry using **Resource Owner Password Credentials Grant** (client credentials grant is enterprise-only on PDIs)

**Required custom property mappings** (`Customization → Property Mappings → Create → SCIM Provider Mapping`):

*Email — ServiceNow requires `type: work` on email objects:*
```python
return {
    "emails": [{"value": request.user.email, "type": "work", "primary": True}]
}
```

*Title and department — None guards required; sending `None` causes a 400 validation error:*
```python
result = {}
title = request.user.attributes.get("title")
if title:
    result["title"] = title
dept = request.user.attributes.get("departmentNumber")
if dept:
    result["urn:ietf:params:scim:schemas:extension:servicenow:2.0:User"] = {
        "department": {"name": dept}
    }
return result
```

*Groups:*
```python
return {"displayName": group.name, "externalId": group.attributes.get("ldap_uniq")}
```

On the SCIM provider, replace the default email mapping with `SCIM Email - work type` and replace the default group mapping with the custom group mapping.

**SCIM Group ETL fix** — Authentik includes `"id"` in PATCH bodies; ServiceNow rejects it as read-only. Fix in ServiceNow: `System SCIM → SCIM ETL Definitions → SCIM Group → group entity → Id field` — change **Coercion action** from `create` to `ignore`. Do not delete the field — ServiceNow needs it to return `sys_id` in responses.

**`akadmin` bypass** — `akadmin` is a superuser and bypasses all policy bindings, so Authentik always attempts to SCIM-sync it. If `akadmin`'s email conflicts with an existing ServiceNow user, every full sync produces a 409. Set `akadmin`'s email to `akadmin@authentik.local` to avoid this.

**SCIM token** — ServiceNow PDI OAuth tokens expire every ~30 minutes. The `scim-refresh` container fetches a fresh token and PATCHes it onto the SCIM provider automatically every 25 minutes.

### Testing SSO (Section 6)

Always test in an **incognito window** — testing in an active admin session redirects that session through the SAML flow.

To activate the IdP: use the **Test Connection** button on the ServiceNow IdP record. The `Active` field is read-only — it can only be set via the Activate button after a successful test.

---

## Custom Services

### ldif-tool (`ldif-tool/`)

Flask web app (Python/ldap3) with three endpoints:

- `POST /convert` — accepts a JSON file, returns a `.ldif` file download
- `POST /import` — writes users and groups directly to OpenLDAP, then automatically mirrors LDAP groups into Authentik (calls the same logic as `/sync`)
- `POST /sync` — queries OpenLDAP for all `groupOfNames` entries and creates matching groups in Authentik with `ldap_uniq` set to the LDAP `entryUUID`; supersedes `create-ldap-groups.ps1`

**Schema** is defined in `ldif-tool/schema.json` — controls field→attribute mapping, required fields, and which field auto-generates `groupOfNames` entries (currently `departmentNumber`, marked with `"generates_groups": true`). Only one field should have `generates_groups: true`. Rebuild after any schema change:
```powershell
docker compose up -d --build ldif-tool
```

Existing users are updated (not duplicated) on re-import via LDAP MODIFY_REPLACE.

**Note:** Authentik 2024.12.3 has no programmatic LDAP sync endpoint. After `/sync` or `/import`, a full LDAP sync (to pull users into Authentik) must still be triggered manually: **Directory → Federation and Social login → OpenLDAP → sync icon**.

### scim-refresh (`scim-refresh/`)

Solves ServiceNow PDI OAuth token expiry. On startup and every 25 minutes via cron:
1. Fetches a fresh access token from ServiceNow's OAuth endpoint (Resource Owner Password grant)
2. PATCHes it onto the first SCIM provider found in Authentik

Requires a ServiceNow OAuth Application Registry entry and `SERVICENOW_*` vars in `.env`.

### create-ldap-groups.ps1

Superseded by `ldif-tool`'s `POST /sync` endpoint. Kept as a standalone fallback if the ldif-tool container is not running.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Authentik won't start | Missing `AUTHENTIK_SECRET_KEY` | Generate with `openssl rand -base64 36` |
| LDAP sync returns 0 users | Wrong Base DN or filter | Verify `ou=users` exists in phpLDAPadmin |
| Groups missing after LDAP sync | Authentik 2024.12.3 `path` bug | Run ldif-tool `/sync` or `create-ldap-groups.ps1`, then sync again |
| SCIM 401 — user not authenticated | Token empty or expired | Check `docker compose logs scim-refresh`; paste a fresh token manually if needed |
| SCIM 400 — email error | Missing `type: work` | Ensure `SCIM Email - work type` mapping is selected on the SCIM provider |
| SCIM 400 — `Attribute id is read-only` | ETL `Id` coercion is `create` | Change `Id` field coercion to `ignore` on the `group` ETL entity |
| SCIM 409 conflict | `akadmin` email conflict or stale records | Set `akadmin` email to `akadmin@authentik.local`; delete conflicting ServiceNow records; clear tracking tables; re-sync |
| SCIM `missing or invalid 'id'` | `Id → sys_id` removed from ETL | Add it back with coercion `ignore` |
| SCIM 403 on Authentik API | Wrong token intent or `ak-*` account | Recreate token with Intent = API Token assigned to a regular user |
| SSO redirect never happens | IdP inactive, missing cert, plugin not enabled | Check in order: plugin enabled → cert present → IdP active → `sys_id` correct → check Authentik logs |
| Authentik login succeeds, redirected back to ServiceNow login | SAML assertion rejected | Verify ACS URL, signing cert, NameID mapping = Username, `user_name` field on IdP record |
| `localhost:9000` unreachable | `authentik-server` on `internal` only | Add `authentik-server` to `external` network |
| LDIF Tool `objectClassViolation` | Attribute not permitted by objectClasses | Remove field from `schema.json` or add required objectClass to `object_classes` |
