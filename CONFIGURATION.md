# SSO ServiceNow Auth Sandbox — Configuration Guide

Complete these sections in order. Each section depends on the previous one.

> **Note:** This guide is a best-effort reference based on the tested configuration
> of this environment. It is not a guaranteed step-by-step walkthrough — some steps
> may behave differently depending on software versions, PDI state, or environment
> differences. Use it as a reference and apply judgement accordingly.

---

## Prerequisites

### Accounts and services

- Docker Desktop installed and running
- A ServiceNow PDI — register free at [developer.servicenow.com](https://developer.servicenow.com)
- Your PDI URL (e.g. `https://devXXXXXX.service-now.com`)
- One of the following for public tunnel access:
  - A free ngrok account at [ngrok.com](https://ngrok.com) — no domain required
  - A Cloudflare account with a domain you own using Cloudflare DNS

### Generate a secret key

Generate `AUTHENTIK_SECRET_KEY` before first startup:

```bash
openssl rand -base64 36
```

> **Windows:** OpenSSL is not installed by default. Install via Chocolatey:
> ```powershell
> choco install openssl
> ```
> If Chocolatey is not installed, follow the instructions at
> [chocolatey.org/install](https://chocolatey.org/install).

> The secret key may contain `$` characters. This is handled automatically
> by the `env_file` directive in `docker-compose.yml` — do not escape them.

### Configure sso-infrastructure

1. Copy `sso-infrastructure/.env.example` to `sso-infrastructure/.env`
2. Fill in all values — refer to the inline comments in `.env.example`
3. Set `DOMAIN=sso.local` — this is your LDAP domain, not your tunnel URL
4. Set `LDAP_BASE_DN=dc=sso,dc=local` and `LDAP_ADMIN_DN=cn=admin,dc=sso,dc=local`
5. Set `SERVICENOW_INSTANCE` to your PDI hostname (e.g. `devXXXXXX.service-now.com`)

> **`AUTHENTIK_API_TOKEN` cannot be filled in yet.** The token is created inside
> the Authentik UI after the stack is running — see Section 2.2. Leave it blank
> for now. The `scim-refresh` container and LDIF Tool will not function until it
> is added and the stack is restarted, but nothing else depends on it at this stage.

### Start sso-infrastructure

```powershell
cd sso-infrastructure
docker compose up -d
```

Wait for all containers to reach a healthy state before proceeding:

```powershell
docker compose ps
```

All services should show `running` or `healthy`. The `authentik-server` and
`authentik-worker` containers wait for postgres and redis healthchecks before
starting — allow 30-60 seconds on first run.

---

## Tunnel Setup — choose one

### Option A — ngrok

#### A.1 Prerequisites

- Your authtoken from [dashboard.ngrok.com/get-started/your-authtoken](https://dashboard.ngrok.com/get-started/your-authtoken)
- Your static dev domain from [dashboard.ngrok.com/domains](https://dashboard.ngrok.com/domains)

Every free ngrok account is automatically assigned a static dev domain on
`ngrok-free.app` (e.g. `abc123xyz.ngrok-free.app`). This domain persists
across container restarts.

#### A.2 Configure .env

Copy `sso-tunnel/ngrok/.env.example` to `sso-tunnel/ngrok/.env` and fill in:

```
NGROK_AUTHTOKEN=your_authtoken_here
```

#### A.3 Configure ngrok.yml

Copy `sso-tunnel/ngrok/ngrok.yml.example` to `sso-tunnel/ngrok/ngrok.yml` and
set your static domain:

```yaml
version: 3

endpoints:
  - name: authentik
    url: https://your-static-domain.ngrok-free.app
    upstream:
      url: http://authentik-server:9000
```

> **Important — agent endpoint vs cloud endpoint:** The Docker container creates
> an agent endpoint, which only exists while the container is running. If you
> previously created a cloud endpoint for the same domain via the ngrok dashboard,
> it will block the agent from starting with `ERR_NGROK_334`. Go to
> `dashboard.ngrok.com/endpoints`, find the endpoint, and delete it before
> starting the container.

#### A.4 Start the tunnel

```powershell
cd sso-tunnel\ngrok
docker compose up -d
```

Verify the tunnel is online:

```powershell
docker compose logs ngrok
```

Your public Authentik URL is:
```
https://your-static-domain.ngrok-free.app
```

Use this URL wherever the guide references the Authentik public URL.

---

### Option B — Cloudflare Tunnel

#### B.1 Prerequisites

- A Cloudflare account
- A domain you own with Cloudflare as the DNS provider

#### B.2 Configure .env

Copy `sso-tunnel/cloudflare/.env.example` to `sso-tunnel/cloudflare/.env` and fill in:

```
DOMAIN=yourdomain.com
TUNNEL_NAME=sso-lab
```

`TUNNEL_NAME` must not already exist in your Cloudflare account — the container
creates it on first run.

#### B.3 Configure routes.conf

Copy `sso-tunnel/cloudflare/routes.conf.example` to
`sso-tunnel/cloudflare/routes.conf` and set your subdomain:

```
- authentik.yourdomain.com:authentik-server:9000
```

#### B.4 First run — authenticate with Cloudflare

Run without `-d` on first start so you can see the authentication URL:

```powershell
cd sso-tunnel\cloudflare
docker compose up
```

The container will print a Cloudflare authentication URL:

```
[INFO] No certificate found. Open the URL below in your browser to authenticate with Cloudflare:
https://dash.cloudflare.com/argotunnel?...
```

Open that URL in your browser and authorise the tunnel. The container will then
create the tunnel, write DNS CNAMEs, validate the config, and start the daemon.
Subsequent restarts skip authentication and reuse saved credentials from `./data/`.

Your public Authentik URL is:
```
https://authentik.yourdomain.com
```

Use this URL wherever the guide references the Authentik public URL.

---

## Section 1 — Provision LDAP Users

### 1.1 Create organisational units

Before any users or groups can be created, the LDAP directory tree needs two
organisational units (OUs) to act as containers — one for users and one for
groups. In LDAP, every entry must have a parent that already exists. Attempting
to create a user under `ou=users` before that OU exists will fail with an
`objectNotFound` or `noSuchObject` error.

**What is an organisational unit?**

An LDAP directory is a tree of entries, each identified by a Distinguished Name
(DN) — a comma-separated path from the entry back to the root. An OU is a
structural container entry, analogous to a folder. Every user and group entry
in this environment lives inside one:

```
dc=sso,dc=local                  ← root (base DN)
├── ou=users,dc=sso,dc=local     ← container for all user accounts
└── ou=groups,dc=sso,dc=local    ← container for all groups
```

**Creating the OUs via phpLDAPadmin**

Open `http://localhost:8081` and log in:

- Login DN: `cn=admin,dc=sso,dc=local`
- Password: `LDAP_ADMIN_PASSWORD` from `.env`

Create `ou=users`:

1. Click the base DN (`dc=sso,dc=local`) in the left tree to select it
2. Click **Create a child entry**
3. Select **Generic: Organisational Unit**
4. Fill in the following attributes:

| Attribute | Value | Explanation |
|---|---|---|
| `objectClass` | `organizationalUnit` | Declares this entry as an OU — required by the LDAP schema |
| `objectClass` | `top` | Every LDAP entry must include `top` in its objectClass chain |
| `ou` | `users` | The name of this organisational unit — becomes part of the DN |

5. Click **Create Object**, then **Commit**

The DN of the new entry will be `ou=users,dc=sso,dc=local`.

Repeat the same steps to create `ou=groups`, setting `ou` to `groups`.

**Understanding the properties**

`objectClass` defines what type of entry this is and which attributes it is
allowed or required to have. LDAP is schema-driven — every entry must conform
to at least one structural objectClass. `organizationalUnit` is the standard
structural class for containers. `top` is the abstract root class that all
objectClasses ultimately inherit from and must always be present.

`ou` (organisational unit name) is the naming attribute for this entry — the
part that appears at the left of the DN. It is both a required attribute of
`organizationalUnit` and the RDN (Relative Distinguished Name) that uniquely
identifies the entry within its parent.

`dn` (Distinguished Name) is not an attribute you set directly — it is
constructed from the RDN plus the parent DN. For `ou=users` created under
`dc=sso,dc=local`, the full DN becomes `ou=users,dc=sso,dc=local`. This is
the path Authentik and the LDIF Tool will use when searching for users and groups.

### 1.2 Import users

**Option A — LDIF Tool (recommended)**

Open `http://localhost:5000`, upload a JSON file matching the schema in
`sso-infrastructure/ldif-tool/schema.json`, and click **Import to LDAP**. The
tool upserts users and groups into OpenLDAP. If an Authentik API token is
configured the tool will also attempt to sync groups to Authentik automatically
— results are shown separately. If the token is not yet configured the LDAP
import will still succeed and you can sync groups manually later using the
**Sync Groups to Authentik** button.

`sso-infrastructure/ldif-tool/MOCK_DATA.json` contains sample users compatible
with the schema.

**Option B — Direct ldapadd**

`sso-infrastructure/sample-users.ldif` contains a small set of example users
and groups. Import with:

```powershell
docker compose cp sample-users.ldif openldap:/tmp/sample-users.ldif
docker compose exec openldap ldapadd -x `
  -D "cn=admin,dc=sso,dc=local" `
  -w your_ldap_admin_password `
  -f /tmp/sample-users.ldif
```

### 1.3 Verify via phpLDAPadmin

- Open `http://localhost:8081`
- Login DN: `cn=admin,dc=sso,dc=local`
- Password: `LDAP_ADMIN_PASSWORD` from `.env`
- Confirm `ou=users` and `ou=groups` exist with entries

---

## Section 2 — Authentik Initial Setup

### 2.1 Initial setup and login

**First startup only:**

1. Navigate to `https://your-public-authentik-url/if/flow/initial-setup/`
2. Enter a username, email, and password of your choice
3. These credentials are used for all subsequent admin logins

**All subsequent logins:**

Open `https://your-public-authentik-url/if/admin/`

### 2.2 Create an API Token

The API token is required by the `scim-refresh` container and the LDIF Tool's
Sync Groups to Authentik function. This is the first point in the setup where
it can be created — Authentik must be running before the token exists.

1. **Directory → Tokens and App passwords → Create**
2. Fill in:

| Field | Value |
|---|---|
| Identifier | `api-admin` |
| User | `akadmin` |
| Intent | **API Token** |

3. Copy the token key — it is only shown once
4. Add it to `sso-infrastructure/.env` as `AUTHENTIK_API_TOKEN`
5. Restart the stack to pick up the new value:
   ```powershell
   docker compose restart
   ```

> **Important:** The token must be assigned to a regular user account, not a
> service account. Authentik service accounts (identifiable by the `ak-` prefix,
> e.g. `ak-outpost-*`) cannot authenticate to the API.

> **LDIF Tool behaviour before the token is set:** The LDIF Tool will import
> users into OpenLDAP successfully but the Authentik sync step will show a
> warning rather than an error. This is expected — return to the LDIF Tool
> after completing this step and use the **Sync Groups to Authentik** button
> to run the sync manually.

### 2.3 Configure custom property mappings

Create all mappings before configuring sources or providers so they are
available to assign immediately and active on the first sync.

---

#### LDAP Source Property Mapping

**Customization → Property Mappings → Create → LDAP Source Property Mapping**

| Field | Value |
|---|---|
| Name | `LDAP custom attributes` |

Expression:

```python
return {
    "attributes": {
        "title": list_flatten(ldap.get("title")),
        "departmentNumber": list_flatten(ldap.get("departmentNumber")),
    },
}
```

> `list_flatten` is automatically applied to top-level properties but NOT to
> values inside `attributes` — call it explicitly here.

---

#### SCIM Provider Mappings

**Customization → Property Mappings → Create → SCIM Provider Mapping**

Create the following three mappings:

**1. `SCIM Email - work type`**

```python
return {
    "emails": [
        {
            "value": request.user.email,
            "type": "work",
            "primary": True,
        }
    ]
}
```

**2. `SCIM title and department`**

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
    result["schemas"] = [
        "urn:ietf:params:scim:schemas:core:2.0:User",
        "urn:ietf:params:scim:schemas:extension:servicenow:2.0:User",
    ]

return result
```

**3. `SCIM Group - displayName`**

```python
return {
    "displayName": group.name,
    "externalId": group.attributes.get("ldap_uniq"),
}
```

---

#### Expression Policy

**Customization → Policies → Create → Expression Policy**

| Field | Value |
|---|---|
| Name | `LDAP Users - All` |

```python
return request.user.path.startswith("goauthentik.io/sources/")
```

### 2.4 Configure LDAP Source

1. **Directory → Federation and Social login → Create → LDAP Source**
2. Fill in:

| Field | Value |
|---|---|
| Name | `OpenLDAP` |
| Slug | `openldap` |
| Server URI | `ldap://openldap:389` |
| Enable StartTLS | **Off** |
| Bind CN | `cn=admin,dc=sso,dc=local` |
| Bind Password | your `LDAP_ADMIN_PASSWORD` |
| Base DN | `dc=sso,dc=local` |
| Username attribute | `uid` |
| UUID attribute | `entryUUID` |

Remove all **Active Directory** mappings from both User and Group Property
Mappings. Keep only the LDAP and OpenLDAP defaults. Add `LDAP custom attributes`
to **User Property Mappings**.

Scroll to **Additional settings**:

| Field | Value |
|---|---|
| Addition User DN | `ou=users` |
| Addition Group DN | `ou=groups` |
| User object filter | `(objectClass=inetOrgPerson)` |
| Group object filter | `(objectClass=posixGroup)` |
| Group membership field | `memberUid` |
| User membership attribute | `uid` |
| Lookup using user attribute | Off |
| Object uniqueness field | `entryUUID` |
| Outgoing sync trigger mode | `Deferred until end` |

> **Object uniqueness field and User membership attribute** both default to
> `objectSid` in a fresh Authentik install. Change both — leaving either as
> `objectSid` causes `LDAPAttributeError: invalid attribute type objectSid` on sync.

3. Click **Finish**
4. Run sync — **Directory → Federation and Social login → OpenLDAP → sync icon**

Verify custom attributes synced:

```powershell
docker compose exec postgres psql -U authentik -d authentik -c `
  "SELECT attributes FROM authentik_core_user WHERE username = 'jane.doe';"
```

Expected: `{"title": "IT Manager", "departmentNumber": "it", ...}`

### 2.5 Sync groups and verify membership

**Step 1 — Create groups in Authentik**

Use the LDIF Tool's **Sync Groups to Authentik** button at `http://localhost:5000`.
This queries OpenLDAP for all `posixGroup` entries, creates them in Authentik
with `ldap_uniq` set, and populates membership via the Authentik API.

**Step 2 — Run LDAP sync**

**Directory → Federation and Social login → OpenLDAP → sync icon**

> **Known bug:** Authentik has a persistent `Group() got unexpected keyword
> arguments: 'path'` error that prevents group creation via LDAP sync. Groups
> must be pre-created via the LDIF Tool first. Once they exist the LDAP sync
> links them by name and membership populates correctly.

**Step 3 — Verify**

**Directory → Groups** — open any group and confirm members are listed.

---

## Section 3 — Authentik Application and SAML Provider

### 3.1 Create the application and SAML provider

1. **Applications → Applications → Create**

**Application**

| Field | Value |
|---|---|
| Name | `ServiceNow` |
| Slug | `servicenow` |

**SAML Provider**

| Field | Value |
|---|---|
| Name | `Provider for ServiceNow` |
| Authorization flow | `default-provider-authorization-implicit-consent` |
| ACS URL | `https://devXXXXXX.service-now.com/navpage.do` |
| Audience | `https://devXXXXXX.service-now.com` |
| SLS URL | leave empty |

**Advanced protocol settings**

| Field | Value |
|---|---|
| Signing Certificate | `authentik Self-signed Certificate` |
| Sign assertions | **On** |
| Sign responses | Off |
| Sign logout requests | Off |
| Sign logout response | Off |
| Verification Certificate | Empty |
| Encryption Certificate | Empty |
| Property mappings | no change |
| NameID Property Mapping | `authentik default SAML Mapping: Username` |
| NameID Property Mapping | Empty |
> **NameID Property Mapping:** Sends `jane.doe` as the NameID which ServiceNow
> matches against `user_name`. Must be set explicitly.

**Create a Policy/User/Group Binding**

### 3.2 Get the Authentik metadata URL
Do the following for each Policy listed belowe
> Select **Bind existing policy/group/user**
> **Policy**

| Policy | Enabled | Negate Result | Order | Timeout | Failure Result |
|-------|-------|---------|---------------|-------|--------------|
| LDAP Users - All | True | False | 0 | 30 | Don't Pass |

**Save Binding**

```
https://your-public-authentik-url/application/saml/service-now/metadata/
```

---

## Section 4 — ServiceNow Multi-Provider SSO

### 4.1 Activate the plugin

- **System Applications → All Available Applications**
- Search: `Multiple Provider Single Sign-On`
- Install: **Integration - Multiple Provider Single Sign-On Installer**

### 4.2 Import Authentik metadata into ServiceNow

1. **Multi-Provider SSO → Identity Providers → New**
2. Select **Import Identity Provider Metadata**
3. Paste the Authentik metadata URL:
   ```
   https://your-public-authentik-url/application/saml/service-now/metadata/
   ```

### 4.3 Enable Multi-Provider SSO

**Multi-Provider SSO → Administration → Properties** — enable the system property.

Without this, SSO will not activate regardless of IdP configuration.

### 4.4 Enable local recovery admin account

**Multi-Provider SSO → Account Recovery → Properties** — enable the local
recovery admin account option and set the designated recovery admin user
(typically `admin`).

Without this, SSO logins are silently redirected back to the login page
regardless of whether the SAML flow completes successfully.

### 4.5 Configure the IdP record

| Field | Value |
|---|---|
| Name | `Authentik` |
| Active | false (activate after testing) |
| NameID Policy | `urn:oasis:names:tc:SAML:1.1:nameid-format:unspecified` |
| User Field | `user_name` |
| Sign AuthnRequest | false |
| Show as Login option | true |

### 4.6 Enable JIT provisioning

**User Provisioning** tab:

| Field | Value |
|---|---|
| Auto-provisioning user | true |
| Default role | `itil` |

> **Field maps cannot be configured yet.** The transform map data source does
> not exist until after the first SSO login attempt. Return to this tab after
> completing a successful test login and add:

| SAML Attribute | ServiceNow Field |
|---|---|
| `user_name` | User Name |
| `email` | Email |
| `first_name` | First name |
| `last_name` | Last name |

---

## Section 5 — SCIM User Provisioning

### 5.1 Activate the SCIM plugin

**System Applications → All Available Applications** — install:
```
com.snc.integration.scim2
```

### 5.2 Create the service account

**User Administration → Users → New**

| Field | Value |
|---|---|
| User ID | `svc_authentik` |
| First name | `Authentik` |
| Last name | `Service` |
| Email | `svc_authentik@sso.local` |
| Active | true |
| Password | strong password — store in `.env` as `SERVICENOW_SCIM_PASSWORD` |

Assign the **`admin`** role — this includes `scim_admin`.

### 5.3 Locate the SCIM API OAuth Application Registry

1. **System OAuth → Application Registry**
2. Find and open the **`SCIM API`** record
3. Set **OAuth application user** to `svc_authentik`
4. **Regenerate** the client secret
5. Copy the **Client ID** and **Client secret** into `sso-infrastructure/.env`

> Do not create a new OAuth record — use the one ServiceNow auto-creates when
> the SCIM plugin is installed.

### 5.4 Fix ServiceNow SCIM Group ETL — id read-only issue

Authentik includes `"id"` in PATCH request bodies. ServiceNow's default ETL
maps this as read-only and returns a 400 on every group membership sync.

1. **System SCIM → SCIM ETL Definitions → SCIM Group**
2. Open the **`group`** ETL entity (Table: `sys_user_group`)
3. Open the **`Id`** ETL entity field
4. Change **Coercion action** from `create` → **`ignore`**
5. Save

> Do not remove the `Id` field entirely — ServiceNow needs it to return `sys_id`
> in SCIM responses. Without it Authentik throws
> `SCIM Response with missing or invalid 'id'`.

### 5.5 Create the SCIM Provider in Authentik

1. **Applications → Providers → Create → SCIM Provider**

| Field | Value |
|---|---|
| Name | `ServiceNow SCIM` |
| URL | `https://devXXXXXX.service-now.com/api/now/scim` |
| Token | leave empty — `scim-refresh` manages this automatically |

2. **User Property Mappings** — add `SCIM Email - work type` and
   `SCIM title and department`. Remove the default email mapping.
3. **Group Property Mappings** — add `SCIM Group - displayName`.
   Remove `authentik default SCIM Mapping: Group`.
4. Assign as a backchannel provider on the ServiceNow application:
   **Applications → ServiceNow → Edit → Backchannel Providers** → add `ServiceNow SCIM`

### 5.6 Configure policy bindings for SCIM sync

1. **Applications → ServiceNow → Policy / Group Bindings**
2. Bind the `LDAP Users - All` expression policy created in Section 2.3

> **akadmin bypass:** `akadmin` is a superuser that bypasses all policy bindings.
> Set `akadmin`'s email to `akadmin@authentik.local` to prevent 409 conflicts
> on every full sync.

### 5.7 Trigger initial sync

**Applications → Providers → ServiceNow SCIM → sync icon**

Restart the `scim-refresh` container to run the initial token refresh:

```powershell
docker compose restart scim-refresh
```

---

## Section 6 — Testing

### 6.1 Pre-flight checks

**a) Multi-Provider SSO enabled globally**

**Multi-Provider SSO → Properties** — confirm SSO is enabled.

**b) Signing certificate imported**

IdP record → **Encryption And Signing** tab — confirm Authentik's signing
certificate is present.

**c) Activate the IdP record**

Use the **Test Connection** button on the IdP record — run this in an incognito
window to avoid losing your admin session. Once the test completes successfully
click **Activate**.

> The `Active` field is read-only. The Activate button is the only supported
> method — it validates the configuration before putting the IdP into service.

### 6.2 Test SSO login

Always test in an **incognito/private browser window**.

**Option A — Direct SSO URL**

Get the IdP `sys_id` from the URL when viewing the IdP record, then navigate to:
```
https://devXXXXXX.service-now.com/login_with_sso.do?glide_sso_id=<sys_id>
```

**Option B — Login page button**

```
https://devXXXXXX.service-now.com/login.do
```

An **Authentik** button should appear on the login page.

### 6.3 Expected flow

1. Browser redirects to Authentik login at your public URL
2. Log in with an LDAP user (e.g. `jane.doe` / `Password1!`)
3. Authentik validates credentials against OpenLDAP
4. SAML assertion POSTed to ServiceNow ACS URL (`/navpage.do`)
5. ServiceNow matches NameID against `user_name`
6. User logged into ServiceNow

### 6.4 Verify user record

**User Administration → Users** → search `jane.doe` — record should exist with
`user_name`, `email`, `first_name`, `last_name` populated from SCIM.

---

## Section 7 — LDIF Tool

### 7.1 JSON schema

Upload a JSON array matching the fields in `sso-infrastructure/ldif-tool/schema.json`.
Required fields: `uid`, `cn`, `givenname`, `sn`, `mail`, `userpassword`, `title`,
`departmentnumber`. Fields present in JSON but absent from the schema are silently
ignored. `null` values are treated as empty strings.

### 7.2 Import behaviour

The tool upserts — new entries are created, existing entries updated. Group
membership is replaced with the current member list on each import. After a
successful import the tool automatically runs Sync Groups to Authentik.

### 7.3 Extending the schema

Add an entry to `ldif-tool/schema.json`:

```json
{
  "json_key": "mobile",
  "ldap_attr": "mobile",
  "label": "Mobile Phone",
  "group": "job",
  "required": false,
  "preview": false
}
```

Rebuild after any schema change:

```powershell
docker compose up -d --build ldif-tool
```

---

## Section 8 — Authentik Application Policy

### 8.1 Bind the policy to the application

The `LDAP Users - All` expression policy was created in Section 2.3.

1. **Applications → ServiceNow → Policy / Group Bindings**
2. Remove any individual group bindings
3. **Bind existing policy** → select `LDAP Users - All`

Any user synced from OpenLDAP has a path starting with
`goauthentik.io/sources/ldap/openldap/` — the policy covers all of them
automatically including members of any new groups added in future.

---

## Troubleshooting

### Infrastructure

| Symptom | Cause | Fix |
|---|---|---|
| Authentik won't start | Missing `AUTHENTIK_SECRET_KEY` | Generate with `openssl rand -base64 36` |
| LDAP sync returns 0 users | Wrong Base DN or filter | Verify `ou=users` exists in phpLDAPadmin |
| Groups missing after LDAP sync | Authentik `path` bug | Use LDIF Tool Sync Groups button then re-run LDAP sync |
| SCIM 401 all users | Token empty or expired | `docker compose logs scim-refresh` |
| SCIM 400 email error | Missing `type: work` | Add `SCIM Email - work type` mapping to SCIM provider |
| SCIM 400 group id read-only | ETL `Id` coercion is `create` | Change coercion to `ignore` (Section 5.4) |
| SCIM 409 conflict | akadmin email conflict or stale records | Set akadmin email to `akadmin@authentik.local`, delete ServiceNow records, clear tracking tables, re-sync |
| SCIM `missing or invalid id` | `Id → sys_id` removed from ETL | Add it back with coercion `ignore` |
| SCIM 403 on Authentik API | Wrong token intent or `ak-*` account | Recreate token with Intent = API Token on a regular user |
| SSO redirect never happens | IdP not active, missing cert, or plugin not enabled | Check Section 6.1 in order |
| SSO completes but redirects to login page | Multi-Provider SSO system property not enabled | **Multi-Provider SSO → Administration → Properties** |
| SSO has no effect after login | Local recovery admin not configured | **Multi-Provider SSO → Account Recovery → Properties** |
| `LDAPAttributeError: invalid attribute type objectSid` | Object uniqueness field or User membership attribute set to AD default | Change both to `entryUUID` and `uid` in LDAP source Additional settings |

### ngrok tunnel

| Symptom | Cause | Fix |
|---|---|---|
| `network sso-net could not be found` | `sso-infrastructure` not running | Start infrastructure first |
| `ERR_NGROK_105` — authtoken invalid | `NGROK_AUTHTOKEN` not set in `.env` | Fill in `.env` and restart |
| `ERR_NGROK_334` — endpoint already online | Cloud endpoint exists for same domain | Go to `dashboard.ngrok.com/endpoints`, delete the endpoint, restart container |
| Container restart loop | Previous session still held by ngrok | Wait 2-3 minutes for session to expire, then `docker compose up` |

### Cloudflare tunnel

| Symptom | Cause | Fix |
|---|---|---|
| `network sso-net could not be found` | `sso-infrastructure` not running | Start infrastructure first |
| Container exits after printing auth URL | Waiting for browser auth | Open the URL in logs and authorise |
| `Tunnel creation failed` | Tunnel name already exists in Cloudflare | Delete from Cloudflare dashboard — Zero Trust → Networks → Tunnels |
| `Config validation failed` | Malformed `routes.conf` | Check format `- hostname:service:port`, ensure trailing newline |
| Authentik unreachable after tunnel starts | `routes.conf` not read on Windows | Ensure `routes.conf` has a trailing newline |
| Credentials lost | `data/` deleted | Do not delete `data/` between restarts — only delete for a full reset |

---

## Not for production

- Self-signed certificates
- Plaintext credentials in `.env`
- No HA, backups, or monitoring
- ServiceNow PDI has rate limits and resets periodically
- OpenLDAP is a stand-in — not a real AD with Kerberos, GPO, etc.