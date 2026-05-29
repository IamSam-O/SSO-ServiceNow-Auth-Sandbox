# SSO Practice Environment — Configuration Guide

Complete these sections in order. Each section depends on the previous one.

---

## Prerequisites

**Tunnel**

Authentik must be publicly reachable for ServiceNow to initiate SAML flows.
Choose one tunnel repository alongside this one:

| | `sso-tunnel-cloudflare` | `sso-tunnel-ngrok` |
|---|---|---|
| **Requires** | Domain you own with Cloudflare DNS | ngrok account (free tier works) |
| **Public URL** | Stable — your own subdomain | Changes on every restart (free tier) |
| **ServiceNow reconfiguration** | Never after initial setup | Each restart on free tier |
| **Cost** | Free (Cloudflare Tunnel is free) | Free tier available; static domain requires paid plan |
| **First-run setup** | Browser auth step to link Cloudflare account | Paste authtoken from ngrok dashboard |

Use `sso-tunnel-cloudflare` if you own a domain — the stable URL means you
configure ServiceNow's IdP metadata URL once and never need to update it.

Use `sso-tunnel-ngrok` if you do not own a domain. On the free tier the public
URL changes each time the container restarts, which means updating the Authentik
metadata URL in ServiceNow after each restart. A paid ngrok plan with a static
domain removes this limitation.

Start the infrastructure stack first, then follow the chosen tunnel repository's
README to expose Authentik before proceeding with the ServiceNow configuration.

**ServiceNow**
- ServiceNow PDI activated at [developer.servicenow.com](https://developer.servicenow.com)
- Your PDI URL (e.g. `https://devXXXXXX.service-now.com`)

**Local environment**
- All containers running (`docker compose up`)
- Generate `AUTHENTIK_SECRET_KEY` before first startup:
  ```bash
  openssl rand -base64 36
  ```
  > **Windows:** OpenSSL is not installed by default. Install it via the Chocolatey
  > package manager:
  > ```powershell
  > choco install openssl
  > ```
  > If Chocolatey itself is not installed, follow the instructions at
  > [chocolatey.org/install](https://chocolatey.org/install).

  > **Note:** The secret key may contain `$` characters. This is handled automatically
  > by the `env_file` directive in `docker-compose.yml` — do not escape them.

---

## Section 1 — Provision LDAP Users

### 1.1 Import users

**Option A — LDIF Tool (recommended)**

Open `http://localhost:5000`, upload a JSON file matching the schema in
`ldif-tool/schema.json`, and click **Import to LDAP**. The tool upserts users
and groups, then automatically syncs groups to Authentik.

`ldif-tool/MOCK_DATA.json` contains sample users compatible with the schema.

**Option B — Direct ldapadd**

`sample-users.ldif` in this repository contains a small set of example users
and groups. Replace the placeholder base DN before importing:

```bash
docker compose cp sample-users.ldif openldap:/tmp/sample-users.ldif
docker compose exec openldap ldapadd -x \
  -D "cn=admin,dc=yourdomain,dc=com" \
  -w your_ldap_admin_password \
  -f /tmp/sample-users.ldif
```

### 1.2 Verify via phpLDAPadmin

- Open `http://localhost:8081`
- Login DN: `cn=admin,dc=yourdomain,dc=com`
- Password: `LDAP_ADMIN_PASSWORD`
- Confirm `ou=users` and `ou=groups` exist with entries

---

## Section 2 — Authentik Initial Setup

### 2.1 Initial setup and login

**First startup only:**
1. Navigate to `https://authentik.yourdomain.com/if/flow/initial-setup/`
2. Enter a username, email, and password of your choice
3. These credentials are used for all subsequent admin logins

**All subsequent logins:**
- Open `https://authentik.yourdomain.com/if/admin/`
- Log in with the credentials set during initial setup

### 2.2 Create an API Token

The API token is required by the `scim-refresh` container and the LDIF Tool.

1. **Directory → Tokens and App passwords → Create**
2. Fill in:

| Field | Value |
|---|---|
| Identifier | `api-admin` |
| User | a regular user account such as `akadmin` |
| Intent | **API Token** (not App password — app passwords do not work for API access) |

3. Save and copy the key into `.env` as `AUTHENTIK_API_TOKEN`

> **Important:** The token must be assigned to a regular user account, not a
> service account. Authentik service accounts (identifiable by the `ak-` prefix,
> e.g. `ak-outpost-*`) cannot be used for API token authentication. Use `akadmin`
> or any standard user with sufficient permissions.

### 2.3 Configure custom LDAP attribute mappings

Create all customisations before configuring any sources or providers so they
are available to assign immediately and active on the first sync.

---

#### LDAP Source Property Mapping

**Customization → Property Mappings → Create → LDAP Source Property Mapping**

| Field | Value |
|---|---|
| Name | `LDAP custom attributes` |

Expression — **must return a dictionary**, not a plain value:
```python
return {
    "attributes": {
        "title": list_flatten(ldap.get("title")),
        "departmentNumber": list_flatten(ldap.get("departmentNumber")),
    },
}
```

> **Important:** `list_flatten` is automatically applied to top-level properties
> but NOT to values inside `attributes` — you must call it explicitly.

---

#### SCIM Provider Mappings

**Customization → Property Mappings → Create → SCIM Provider Mapping**

Create the following three mappings:

**1. `SCIM Email - work type`**

ServiceNow's SCIM ETL requires `type: work` on the email object. Authentik's
default mapping omits this.

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

Sends job title and department to ServiceNow. None guards prevent null values
causing 400 errors for users without these attributes. When department data is
present, the ServiceNow extension namespace is declared in `schemas` — ServiceNow
requires all extension namespaces to be listed there or returns a 400
`invalidSyntax` error.

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

Sends the group name and LDAP UUID as `externalId` for stable coalescing in
ServiceNow.

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

This policy is used in Section 8 to automatically cover all LDAP-sourced users
on the ServiceNow application without needing to bind individual groups.

### 2.4 Configure LDAP Source

1. **Directory → Federation and Social login → Create → LDAP Source**
2. Fill in:

| Field | Value |
|---|---|
| Name | `OpenLDAP` |
| Slug | `openldap` |
| Server URI | `ldap://openldap:389` |
| Enable StartTLS | **Off** |
| Bind CN | `cn=admin,dc=yourdomain,dc=com` |
| Bind Password | your `LDAP_ADMIN_PASSWORD` |
| Base DN | `dc=yourdomain,dc=com` |
| Username attribute | `uid` |
| UUID attribute | `entryUUID` |

Scroll to **LDAP Attribute mapping** and remove all **Active Directory** mappings
from both User and Group Property Mappings. Keep only the LDAP and OpenLDAP
defaults. Add `LDAP custom attributes` to **User Property Mappings**.

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

> **Object uniqueness field and User membership attribute:** Both default to
> `objectSid` in a fresh Authentik install (Active Directory default). Change
> `Object uniqueness field` to `entryUUID` and `User membership attribute` to
> `uid` — leaving either as `objectSid` causes
> `LDAPAttributeError: invalid attribute type objectSid` on sync.

> **Why `posixGroup` with `memberUid` and `uid`:** `posixGroup` stores plain
> usernames in `memberUid` (e.g. `rkuhwald5`). The `User membership attribute`
> of `uid` matches exactly — both sides share the same value. This is the
> critical requirement for Authentik to resolve group membership. Using
> `groupOfNames` with full DNs in `member` caused membership sync to fail
> regardless of what `User membership attribute` was set to.

> **Lookup using user attribute:** Leave off — group membership is resolved via
> `memberUid` on the group, not a field on the user.

> **Outgoing sync trigger mode:** `Deferred until end` triggers the SCIM
> provider sync once after the full LDAP sync completes, rather than per-object
> (`Immediate`) or not at all (`None`). This is the recommended setting.

3. Click **Finish**
4. Run sync — **Directory → Federation and Social login → OpenLDAP → sync icon**

Verify custom attributes synced correctly:
```powershell
docker compose exec postgres psql -U authentik -d authentik -c "SELECT attributes FROM authentik_core_user WHERE username = 'john.doe';"
```
Expected: `{"title": "Senior Developer", "departmentNumber": "IT", ...}`

### 2.5 Sync groups and verify membership

**Step 1 — Create groups in Authentik**

Use the LDIF Tool's **Sync Groups to Authentik** button at `http://localhost:5000`.
This queries OpenLDAP for all `posixGroup` entries, creates them in Authentik
with `ldap_uniq` set, and populates membership directly via the Authentik API.

**Step 2 — Run LDAP sync**

Trigger sync from **Directory → Federation and Social login → OpenLDAP → sync icon**.
Authentik matches groups by name, links them to the LDAP source, and populates
member assignments.

> **Known bug:** Authentik has a persistent `Group() got unexpected keyword
> arguments: 'path'` error that prevents group CREATION via LDAP sync. Groups
> must be pre-created via the LDIF Tool first. Once they exist, the LDAP sync
> links them by name and membership populates correctly.

**Step 3 — Verify membership**

**Directory → Groups** — open any group and confirm members are listed. If
membership is missing, re-run the LDIF Tool sync then trigger LDAP sync again.

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

> **Note:** `Audience` was previously called `Issuer`. `SLS URL` is an optional
> Single Logout Service URL — leave blank for this environment.

Scroll down for advanced settings:

**Advanced flow settings**

| Field | Value |
|---|---|
| Authentication Flow | leave empty |
| Invalidation Flow | `default-provider-invalidation-flow` (default) |

**Advanced protocol settings**

| Field | Value |
|---|---|
| Signing Certificate | `authentik Self-signed Certificate` |
| Sign assertions | **On** |
| Sign responses | Off |
| Sign logout requests | Off |
| Sign logout response | Off |
| Verification Certificate | leave empty |
| Encryption Certificate | leave empty |

**Property mappings** — keep all 7 defaults selected.

| Field | Value |
|---|---|
| NameID Property Mapping | `authentik default SAML Mapping: Username` |
| AuthnContextClassRef Property Mapping | leave empty |
| Assertion valid not before | `minutes=-5` (default) |
| Assertion valid not on or after | `minutes=5` (default) |
| Session valid not on or after | `minutes=86400` (default) |

> **NameID Property Mapping:** This sends `john.doe` as the NameID which
> ServiceNow matches against `user_name`. Must be set explicitly — if left
> empty the NameID format from the incoming request is used instead.

### 3.2 Get the Authentik metadata URL

```
https://authentik.yourdomain.com/application/saml/service-now/metadata/
```

---

## Section 4 — ServiceNow Multi-Provider SSO

### 4.1 Activate the plugin

- **System Applications → All Available Applications**
- Search: `Multiple Provider Single Sign-On`
- Install: **Integration - Multiple Provider Single Sign-On Installer**

### 4.2 Import Authentik IdP metadata into ServiceNow

1. **Multi-Provider SSO → Identity Providers → New**
2. Select **Import Identity Provider Metadata**
3. Paste the Authentik metadata URL:
   ```
   https://authentik.yourdomain.com/application/saml/service-now/metadata/
   ```
4. Import — this populates the AuthnRequest URL, certificate, and issuer

### 4.3 Enable Multi-Provider SSO

1. **Multi-Provider SSO → Administration → Properties**
2. Enable the Multi-Provider SSO system property

Without this, SSO will not activate regardless of how the IdP record is configured.

### 4.4 Enable local recovery admin account

Before SSO will function, ServiceNow requires a local recovery admin account
to be designated. Without this, logins via SSO are silently redirected back to
the login page regardless of whether the SAML flow completes successfully.

1. **Multi-Provider SSO → Account Recovery → Properties**
2. Enable the local recovery admin account option
3. Set the designated recovery admin user (typically `admin`)

### 4.5 Configure the IdP record

| Field | Value |
|---|---|
| Name | `Authentik` |
| Active | false (activate after testing) |
| Default | false |
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

> **Field maps cannot be configured at this stage.** The field map picker
> relies on a transform map data source that does not exist until after the
> first SSO login attempt triggers ServiceNow to build it. Return to this tab
> after completing a successful test login and add the following field maps:

| SAML Attribute | ServiceNow Field |
|---|---|
| `user_name` | User Name |
| `email` | Email |
| `first_name` | First name |
| `last_name` | Last name |


---

## Section 5 — SCIM User Provisioning (Authentik → ServiceNow)

SCIM pushes users and groups from Authentik into ServiceNow automatically.
The `scim-refresh` container handles automatic OAuth token renewal.

### 5.1 Activate the SCIM plugin in ServiceNow

Navigate to **System Applications → All Available Applications** and install:
```
com.snc.integration.scim2
```
(SCIM v2 - ServiceNow Cross-domain Identity Management)

### 5.2 Create the service account in ServiceNow

1. **User Administration → Users → New**

| Field | Value |
|---|---|
| User ID | `svc_authentik` |
| First name | `Authentik` |
| Last name | `Service` |
| Email | `svc_authentik@yourdomain.com` |
| Active | true |
| Password | a strong password — store in `.env` as `SERVICENOW_SCIM_PASSWORD` |

2. Assign the **`admin`** role — this includes `scim_admin` which is required for
   SCIM API access

### 5.3 Locate the SCIM API OAuth Application Registry

When the SCIM plugin is installed, ServiceNow automatically creates an OAuth
Application Registry record called **SCIM API**. Use this instead of creating
a new one.

1. **System OAuth → Application Registry**
2. Find and open the **`SCIM API`** record
3. Set **OAuth application user** to `svc_authentik`
4. **Regenerate** the client secret — the default secret is unknown and must be
   regenerated before use
5. Note the **Client ID** and regenerated **Client secret** — store in `.env`

   > **Special characters in the client secret** (e.g. `+`, `[`, `]`, `(`, `)`)
   > are handled automatically by `--data-urlencode` in the scim-refresh container.
   > Do not escape them in `.env`.

### 5.4 SCIM property mappings

All three SCIM property mappings (`SCIM Email - work type`, `SCIM title and department`,
`SCIM Group - displayName`) were created in Section 2.3. Confirm they exist under
**Customization → Property Mappings** before proceeding.

### 5.5 Fix ServiceNow SCIM Group ETL — `id` read-only issue

Authentik includes `"id"` in PATCH request bodies when updating group membership.
ServiceNow's default SCIM Group ETL maps `id → sys_id` with coercion `create`,
which causes a 400 "Attribute id is read-only" error on every group membership sync.

Fix by changing the coercion action on the `Id` ETL entity field:

1. Navigate to **System SCIM → SCIM ETL Definitions → SCIM Group**
2. Open the **`group`** ETL entity (Table: `sys_user_group`)
3. Open the **`Id`** ETL entity field
4. Change **Coercion action** from `create` → **`ignore`**
5. Save

**Why this works:** With coercion `ignore`, ServiceNow still uses `sys_id` for
record coalescing and still returns it in SCIM responses (so Authentik gets the
external ID it needs), but it no longer attempts to write the incoming `id` value
to `sys_id`, eliminating the read-only conflict.

> **Do not remove the `Id` field entirely** — ServiceNow needs it to return `sys_id`
> in SCIM responses. Without it, Authentik throws `SCIM Response with missing or
> invalid 'id'` and cannot track the created group.

### 5.6 Create the SCIM Provider in Authentik

1. **Applications → Providers → Create → SCIM Provider**

| Field | Value |
|---|---|
| Name | `ServiceNow SCIM` |
| URL | `https://devXXXXXX.service-now.com/api/now/scim` |
| Token | ServiceNow OAuth token (managed by scim-refresh container) |

2. Scroll to **User Property Mappings** — add `SCIM Email - work type` and
   `SCIM title and department`. Remove any default email mapping.
3. Scroll to **Group Property Mappings** — add `SCIM Group - displayName`.
   Remove the default group mapping (`authentik default SCIM Mapping: Group`).

4. Assign the SCIM provider as a backchannel provider on the ServiceNow application:
   **Applications → ServiceNow → Edit → Backchannel Providers** → add `ServiceNow SCIM`

### 5.7 Configure policy/group bindings for SCIM sync

The policy binding controls which users Authentik syncs to ServiceNow.
Bind only your LDAP groups to avoid syncing system accounts.

1. **Applications → ServiceNow → Policy / Group Bindings**
2. Add bindings for: `it`, `hr`, `finance`, `servicenow-admins`

> **akadmin bypass:** `akadmin` is a superuser and bypasses all policy bindings
> regardless of group membership. Authentik will always attempt to sync it.
> Ensure `akadmin`'s email does not conflict with any existing ServiceNow user
> email — a conflict causes a 409 on every full sync. Set akadmin's email to
> something unique like `akadmin@authentik.local`.

### 5.8 Trigger initial sync

**Applications → Providers → ServiceNow SCIM → sync icon**

### 5.9 Troubleshooting SCIM sync errors

**401 Unauthorized — `User is not authenticated`**
The Bearer token in the SCIM provider is empty or expired. Either:
- The `scim-refresh` container hasn't run yet — check `docker compose logs scim-refresh`
- Manually get a token via Postman using the Resource Owner Password Credentials grant
  and paste it into the SCIM provider Token field

**400 Bad Request — `An email with type work is required`**
The email SCIM property mapping is missing or not selected. Ensure
`SCIM Email - work type` is in the selected mappings on the SCIM provider.
Also check that all synced users have emails set in Authentik.

**400 Bad Request — `Attribute id is read-only`**
The SCIM Group ETL `Id` field coercion is still set to `create`. Change it to
`ignore` per Section 5.5.

**409 Conflict — `ObjectExistsSyncException`**
Authentik is trying to create a record that already exists in ServiceNow but
doesn't have the external ID stored. Most commonly caused by:
- `akadmin`'s email conflicting with an existing ServiceNow user email
- Stale records left from a previous partial sync

Fix:
1. Check `akadmin`'s email in Authentik — change to `akadmin@authentik.local` if conflicting
2. Delete conflicting records from ServiceNow
3. Clear Authentik's SCIM tracking tables:
   ```powershell
   docker compose exec postgres psql -U authentik -d authentik -c "DELETE FROM authentik_providers_scim_scimprovideruser WHERE provider_id = <pk>;"
   docker compose exec postgres psql -U authentik -d authentik -c "DELETE FROM authentik_providers_scim_scimprovidergroup WHERE provider_id = <pk>;"
   ```
4. Trigger a fresh sync

**`SCIM Response with missing or invalid 'id'`**
The `Id → sys_id` field was removed from the SCIM Group ETL `group` entity.
ServiceNow needs this field to return `sys_id` in responses. Add it back with
coercion `ignore` (not `create` and not deleted).

---

## Section 6 — Testing

### 6.1 Pre-flight checks before testing SSO

**a) Verify Multi-Provider SSO is enabled at the plugin level**

Navigate to **Multi-Provider SSO → Properties** — confirm SSO is enabled globally.
This is separate from individual IdP records being active.

**b) Verify the signing certificate was imported**

Open the IdP record → **Encryption And Signing** tab — confirm Authentik's
signing certificate is populated. If the metadata import didn't bring it in,
ServiceNow will silently refuse to initiate the SSO flow.

**c) Activate the IdP record**

Use the **Test Connection** button on the IdP record. ServiceNow will initiate a
test SSO flow — run this in an incognito window to avoid losing your admin session.
Once the test completes successfully, click **Activate** to enable the IdP.

> The `Active` field is intentionally read-only. The Activate button is the correct
> and only supported method — it ensures the configuration has been validated before
> the IdP is put into service.

### 6.2 Test SSO login

Always test in an **incognito/private browser window** — testing in your active
admin session will redirect that session through the SAML flow and may log you out.

**Option A — Direct SSO URL**

Get the IdP `sys_id` from the URL when viewing the IdP record in ServiceNow, then navigate to:
```
https://devXXXXXX.service-now.com/login_with_sso.do?glide_sso_id=<sys_id>
```

**Option B — Login page button**

With `Show as Login option` checked on the IdP record, navigate to:
```
https://devXXXXXX.service-now.com/login.do
```
An **Authentik** SSO button should appear on the login page.

### 6.3 Expected flow

1. Browser redirects to Authentik login page at `authentik.yourdomain.com`
2. Log in with an LDAP user (e.g. `john.doe` / `Password1!`)
3. Authentik validates credentials against OpenLDAP
4. SAML assertion POSTed to ServiceNow ACS URL
5. ServiceNow matches assertion `NameID` against `user_name` field
6. User logged into ServiceNow as `john.doe`

### 6.4 Verify user record

**User Administration → Users** → search `john.doe` — record should exist
with `user_name`, `email`, `first_name`, `last_name` populated from SCIM.

### 6.5 Troubleshooting SSO redirect failures

**Brought to ServiceNow login page instead of Authentik**
ServiceNow is not initiating the SAML redirect. Check in order:
1. Multi-Provider SSO → Properties — plugin enabled globally?
2. IdP record → Encryption And Signing tab — certificate present?
3. IdP record — Active = true?
4. `sys_id` in the URL — matches the IdP record exactly?
5. Authentik logs — is any request arriving?

```powershell
docker compose logs authentik-server --since 5m | Select-String -Pattern "saml|SAML"
```

If nothing arrives at Authentik, the problem is entirely on the ServiceNow side.

**Authentik login succeeds but redirected back to ServiceNow login page**
The SAML assertion was rejected by ServiceNow. Check:
1. ACS URL in Authentik SAML provider matches `https://devXXXXXX.service-now.com/navpage.do`
2. Signing certificate on IdP record matches Authentik's current certificate
3. `NameID` mapping in Authentik is set to `authentik default SAML Mapping: Username`
4. `User Field` on ServiceNow IdP record is set to `user_name`
5. The user exists in ServiceNow (SCIM provisioned) with a matching `user_name`

---

## Section 7 — LDIF Tool

The LDIF Tool is a web interface at `http://localhost:5000` that replaces shell
and Docker scripts for LDAP user management.

### 7.1 Required .env values

`AUTHENTIK_URL`, `AUTHENTIK_LDAP_SLUG`, and `AUTHENTIK_API_TOKEN` are all
defined in `.env.example`. Ensure they are set in your `.env` before starting
the ldif-tool container. `AUTHENTIK_API_TOKEN` is created in Section 2.2.

### 7.2 JSON schema

Upload a JSON array matching the fields defined in `ldif-tool/schema.json`.
All fields except `uid`, `cn`, `givenname`, `sn`, `mail`, and `userpassword`
are optional. Fields present in the JSON but absent from the schema are silently
ignored. `null` values are treated as empty strings.

### 7.3 Import behaviour

The tool upserts — new entries are created, existing entries are updated with
the values from the JSON. Group membership is replaced with the current member
list on each import.

After a successful import the tool automatically runs **Sync Groups to Authentik**,
which queries OpenLDAP for all groups, retrieves their `entryUUID`, and creates
them in Authentik with `ldap_uniq` set. Groups that already exist in Authentik
are skipped.

### 7.4 Sync Groups to Authentik (manual)

The **Sync Groups to Authentik** button on the tool's home page runs the same
group sync without requiring a user import. Use it when:
- New groups were added to OpenLDAP outside of the tool
- The Authentik group records need to be refreshed after a clean environment rebuild

> **Note:** Authentik does not expose a programmatic LDAP sync endpoint.
> The sync button creates group records in Authentik with the correct `ldap_uniq` values.
> A full LDAP sync (to populate group members) still needs to be triggered manually
> from the Authentik admin UI: **Directory → Federation and Social login → OpenLDAP → sync icon**.

### 7.5 Extending the schema

To add a new LDAP attribute, add an entry to `ldif-tool/schema.json`:

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

Set `"preview": true` to show the field as a column in the preview table.
Set `"generates_groups": true` on the field that should drive group creation
(only one field should have this — currently `departmentnumber`).

Rebuild after any schema change:
```powershell
docker compose up -d --build ldif-tool
```

---

## Section 8 — Authentik Application Policy

Instead of binding individual LDAP groups to the ServiceNow application, use a
single expression policy that automatically covers all LDAP-sourced users —
including members of any new groups added in the future.

### 8.1 Bind the policy to the application

The `LDAP Users - All` expression policy was created in Section 2.3.

### 8.2 Bind to the application

1. **Applications → ServiceNow → Policy / Group Bindings**
2. Remove all individual group bindings
3. **Bind existing policy** → select `LDAP Users - All`

Any user synced from OpenLDAP has a path of
`goauthentik.io/sources/ldap/openldap/` — the policy matches all of them
regardless of group. New groups imported via the LDIF Tool are covered
automatically.

---

## Section 9 — Network Segmentation

By default Docker Compose containers can reach any external host. Restricting
outbound access to only what each container legitimately needs prevents unexpected
egress and limits blast radius if a container is compromised.

### 9.1 Network design

Two networks are defined:

| Network | `internal: true` | Purpose |
|---|---|---|
| `internal` | Yes | Container-to-container only — no internet access |
| `sso-net` | No | Host and tunnel access — named bridge, shared with tunnel repos |

Tunnel repositories (`sso-tunnel-cloudflare`, `sso-tunnel-ngrok`) join `sso-net`
as an external network, allowing their containers to reach `authentik-server` by
container name.

### 9.2 Container assignments

| Container | internal | sso-net | Reason |
|---|---|---|---|
| `postgres` | ✅ | ❌ | Only needs Authentik |
| `redis` | ✅ | ❌ | Only needs Authentik |
| `openldap` | ✅ | ❌ | Only needs Authentik |
| `phpldapadmin` | ✅ | ✅ | Needs OpenLDAP (internal) and host browser access |
| `authentik-server` | ✅ | ✅ | Host access on port 9000; tunnel containers reach it via sso-net |
| `authentik-worker` | ✅ | ✅ | Must reach ServiceNow for SCIM sync |
| `scim-refresh` | ✅ | ✅ | Reaches Authentik API internally, ServiceNow externally |
| `ldif-tool` | ✅ | ✅ | Host access on port 5000; reaches Authentik API internally |

### 9.3 docker-compose.yml network definition

The networks are already configured in `docker-compose.yml`. For reference:

```yaml
networks:
  internal:
    driver: bridge
    internal: true
  sso-net:
    driver: bridge
    name: sso-net
```

The `name: sso-net` directive gives the network a fixed name across Docker so
tunnel repositories can reference it as an external network regardless of which
directory they are run from.

> **Note:** `authentik-server` requires `sso-net` for host access on port 9000
> and for tunnel containers to reach it. Removing it from `sso-net` breaks
> `localhost:9000` access and prevents the tunnel from forwarding traffic.

> **Note:** `phpldapadmin` requires `sso-net` for the same reason — `internal: true`
> blocks host port mapping, so `localhost:8081` stops working without it.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Authentik won't start | Missing `AUTHENTIK_SECRET_KEY` | Generate with `openssl rand -base64 36` |
| LDAP sync returns 0 users | Wrong Base DN or filter | Verify in phpLDAPadmin that `ou=users` exists |
| Groups missing after LDAP sync | Authentik version-specific `path` bug | Use LDIF Tool **Sync Groups to Authentik** button then re-run LDAP sync |
| SCIM 401 all users | Token empty or expired | Check `docker compose logs scim-refresh` |
| SCIM 400 email error | Missing `type: work` on email | Add `SCIM Email - work type` property mapping |
| SCIM 400 group id read-only | ETL `Id` coercion is `create` | Change `Id` field coercion to `ignore` on the `group` ETL entity (Section 5.5) |
| SCIM 409 conflict | akadmin email conflict or stale records | Change akadmin email to `akadmin@authentik.local`, delete ServiceNow records, clear tracking tables, re-sync |
| SCIM `missing or invalid id` | `Id → sys_id` removed from ETL | Add it back with coercion `ignore`, not deleted |
| SCIM 403 on Authentik API | Wrong token intent | Recreate token with Intent = API Token |
| SSO redirect never happens | IdP not active, wrong sys_id, missing cert, or plugin not enabled | Check Section 6.5 in order |
| SSO has no effect after configuration | Multi-Provider SSO system property not enabled | **Multi-Provider SSO → Administration → Properties** — enable the system property |
| SSO completes but redirects to login page | Local recovery admin not configured | **Multi-Provider SSO → Account Recovery → Properties** — enable local recovery admin |
| ACS URL mismatch | SAML config error | Verify ACS URL matches exactly in SAML provider |
| Email notifications failing | No SMTP configured | Safe to ignore in practice environment |
| `$` variables in docker logs | Secret key has `$` chars | Handled by `env_file` in docker-compose.yml — no action needed |
| LDIF Tool `schema.json` not found | Missing `COPY schema.json` in Dockerfile | Rebuild with `docker compose up -d --build ldif-tool` |
| LDIF Tool `objectClassViolation` | Attribute not permitted by objectClasses | Remove the field from `schema.json` or add the required objectClass to `object_classes` |
| LDIF Tool sync not triggering | Authentik has no programmatic LDAP sync endpoint | Use **Sync Groups to Authentik** button instead; trigger full LDAP sync manually in Authentik UI |
| `localhost:9000` unreachable after network change | `authentik-server` on `internal` only | Add `authentik-server` to `sso-net` network in `docker-compose.yml` |
| `LDAPAttributeError: invalid attribute type objectSid` | User membership attribute or Object uniqueness field set to AD default | Change both to `entryUUID` in LDAP source Additional settings |