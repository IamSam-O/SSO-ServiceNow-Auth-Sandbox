# SSO ServiceNow Auth Sandbox — Configuration Guide

Complete these sections in order. Each section depends on the previous one.

> **Note:** This guide is a best-effort reference based on the tested configuration
> of this environment. It is not a guaranteed step-by-step walkthrough — some steps
> may behave differently depending on software versions, PDI state, or environment
> differences. Use it as a reference and apply judgement accordingly.

---

## Contents

- [Prerequisites](#prerequisites)
  - [Accounts and services](#accounts-and-services)
  - [Install ServiceNow plugins](#install-servicenow-plugins)
  - [Generate a secret key](#generate-a-secret-key)
  - [Configure sso-infrastructure](#configure-sso-infrastructure)
  - [Start sso-infrastructure](#start-sso-infrastructure)
- [Tunnel Setup — choose one](#tunnel-setup--choose-one)
  - [Option A — ngrok](#option-a--ngrok)
  - [Option B — Cloudflare Tunnel](#option-b--cloudflare-tunnel)
- [Section 1 — Provision LDAP Users](#section-1--provision-ldap-users)
  - [1.1 Create organisational units](#11-create-organisational-units)
  - [1.2 Import users](#12-import-users)
  - [1.3 Verify via phpLDAPadmin](#13-verify-via-phpldapadmin)
- [Section 2 — Authentik Initial Setup](#section-2--authentik-initial-setup)
  - [2.1 Initial setup and login](#21-initial-setup-and-login)
  - [2.2 Create an API Token](#22-create-an-api-token)
  - [2.3 Configure custom property mappings](#23-configure-custom-property-mappings)
  - [2.4 Configure LDAP Source](#24-configure-ldap-source)
  - [2.5 Sync groups and verify membership](#25-sync-groups-and-verify-membership)
- [Section 3 — Authentik Application and SAML Provider](#section-3--authentik-application-and-saml-provider)
  - [3.1 Create the application and SAML provider](#31-create-the-application-and-saml-provider)
  - [3.2 Create the SCIM Provider](#32-create-the-scim-provider)
  - [3.3 Assign the SCIM provider as a backchannel provider](#33-assign-the-scim-provider-as-a-backchannel-provider)
  - [3.4 Bind the policy to the application](#34-bind-the-policy-to-the-application)
  - [3.5 Get the Authentik metadata URL](#35-get-the-authentik-metadata-url)
- [Section 4 — ServiceNow Multi-Provider SSO](#section-4--servicenow-multi-provider-sso)
  - [4.1 Import Authentik metadata into ServiceNow](#41-import-authentik-metadata-into-servicenow)
  - [4.2 Enable Multi-Provider SSO](#42-enable-multi-provider-sso)
  - [4.3 Enable local recovery admin account](#43-enable-local-recovery-admin-account)
  - [4.4 Configure the IdP record](#44-configure-the-idp-record)
  - [4.5 Enable JIT provisioning](#45-enable-jit-provisioning)
- [Section 5 — SCIM User Provisioning](#section-5--scim-user-provisioning)
  - [5.1 Create the service account](#51-create-the-service-account)
  - [5.2 Locate the SCIM API OAuth Application Registry](#52-locate-the-scim-api-oauth-application-registry)
  - [5.3 Fix ServiceNow SCIM Group ETL — id read-only issue](#53-fix-servicenow-scim-group-etl--id-read-only-issue)
  - [5.4 Configure policy bindings for SCIM sync](#54-configure-policy-bindings-for-scim-sync)
  - [5.5 Trigger initial sync](#55-trigger-initial-sync)
  - [5.6 Configure akadmin in ServiceNow](#56-configure-akadmin-in-servicenow)
- [Section 6 — SSO Configuration](#section-6--sso-configuration)
  - [6.1 Configure akadmin in ServiceNow](#61-configure-akadmin-in-servicenow)
  - [6.2 First login and MFA setup](#62-first-login-and-mfa-setup)
  - [6.3 Enable account recovery](#63-enable-account-recovery)
  - [6.4 Enable Multi-Provider SSO](#64-enable-multi-provider-sso)
- [Section 7 — Testing](#section-7--testing)
  - [7.1 Initial test using the Test Connection button](#71-initial-test-using-the-test-connection-button)
  - [7.2 Subsequent SSO testing](#72-subsequent-sso-testing)
  - [7.3 Expected flow](#73-expected-flow)
  - [7.4 Verify user record](#74-verify-user-record)
- [Section 8 — LDIF Tool](#section-8--ldif-tool)
  - [8.1 JSON schema](#81-json-schema)
  - [8.2 Import behaviour](#82-import-behaviour)
  - [8.3 Extending the schema](#83-extending-the-schema)
- [Section 9 — Authentik Application Policy](#section-9--authentik-application-policy)
- [Troubleshooting](#troubleshooting)
  - [Infrastructure](#infrastructure)
  - [ngrok tunnel](#ngrok-tunnel)
  - [Cloudflare tunnel](#cloudflare-tunnel)
- [Not for production](#not-for-production)

---

## Prerequisites

### Accounts and services

- Docker Desktop installed and running
- A ServiceNow PDI — register free at [developer.servicenow.com](https://developer.servicenow.com)
- Your PDI URL (e.g. `https://devXXXXXX.service-now.com`)
- One of the following for public tunnel access:
  - A free ngrok account at [ngrok.com](https://ngrok.com) — no domain required
  - A Cloudflare account with a domain you own using Cloudflare DNS

### Install ServiceNow plugins

Plugin installs on a PDI can take several minutes. Start both installs now so
they complete in the background while you work through the rest of the setup.

Log into your PDI and navigate to **System Applications → All Available
Applications** for each of the following:

**Multi-Provider SSO**

- Search: `Multiple Provider Single Sign-On`
- Install: **Integration - Multiple Provider Single Sign-On Installer**

**SCIM**

- Search: `SCIM`
- Install: **SCIM v2 - ServiceNow Cross-domain Identity Management**
  (`com.snc.integration.scim2`)

You do not need to wait for either install to finish before continuing. Return
to Sections 4 and 5 once they have completed.

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

> **Running both tunnels simultaneously:** There is no technical limitation
> preventing both tunnel containers from running at the same time — each
> independently joins `sso-net` and forwards traffic to `authentik-server:9000`.
> This can be useful for testing one tunnel option then the other without
> tearing down the infrastructure. ServiceNow supports multiple IdP records,
> so you can configure one for each tunnel URL and simply change which one is
> set as the default to switch between them — no reconfiguration needed.

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
| Verification Certificate | leave empty |
| Encryption Certificate | leave empty |
| Property mappings | no change |
| NameID Property Mapping | `authentik default SAML Mapping: Username` |

> **NameID Property Mapping:** Sends `jane.doe` as the NameID which ServiceNow
> matches against `user_name`. Must be set explicitly.

### 3.2 Create the SCIM Provider

1. **Applications → Providers → Create → SCIM Provider**

| Field | Value |
|---|---|
| Name | `ServiceNow SCIM` |
| URL | `https://devXXXXXX.service-now.com/api/now/scim` |
| Token | enter a placeholder value for now — see note below |

> **Token field behaviour:** The token field cannot be left empty — Authentik
> requires a value to save the provider. However, the field may not allow
> pasting on first entry. Enter any random string as a placeholder to create
> the provider, then edit it immediately after saving and you will be able to
> paste the real token. The `scim-refresh` container will overwrite this value
> automatically every 25 minutes once it is running, so the placeholder will
> not persist.

> **URL naming convention:** The SCIM endpoint URL above uses your PDI hostname
> directly. If your instance URL follows a different pattern, update the hostname
> to match — the path `/api/now/scim` remains constant.

2. **User Property Mappings** — the selected mappings should be:

| Mapping | Purpose |
|---|---|
| `authentik default SCIM Mapping: User` | Core user attributes — keep this |
| `SCIM Email - work type` | Adds `type: work` to email — required by ServiceNow |
| `SCIM title and department` | Sends job title and department |

3. **Group Property Mappings** — the selected mappings should be:

| Mapping | Purpose |
|---|---|
| `authentik default SCIM Mapping: Group` | Core group attributes — keep this |
| `SCIM Group - displayName` | Sends group name and LDAP UUID as `externalId` |

### 3.3 Assign the SCIM provider as a backchannel provider

1. **Applications → ServiceNow → Edit**
2. Under **Backchannel Providers** add `ServiceNow SCIM`
3. Save

> **Why backchannel:** A backchannel provider runs silently alongside the main
> SAML flow. Assigning the SCIM provider here means Authentik will push user and
> group changes to ServiceNow automatically whenever the LDAP sync runs, without
> requiring a separate trigger.

### 3.4 Bind the policy to the application

1. **Applications → ServiceNow → Policy / Group Bindings**
2. Select **Bind existing policy/group/user**
3. Fill in:

| Field | Value |
|---|---|
| Policy | `LDAP Users - All` |
| Enabled | True |
| Negate Result | False |
| Order | 0 |
| Timeout | 30 |
| Failure Result | Don't Pass |

4. Save Binding

5. Select **Bind existing policy/group/user** again
6. Fill in:

| Field | Value |
|---|---|
| User | `akadmin` |
| Enabled | True |
| Negate Result | False |
| Order | 1 |
| Timeout | 30 |
| Failure Result | Don't Pass |

7. Save Binding

> **Why bind akadmin directly:** `akadmin` is the local Authentik admin account
> and is not sourced from OpenLDAP, so it is not covered by the `LDAP Users - All`
> policy. Binding it as a user directly ensures it always has access to the
> ServiceNow application and can be used for local admin and recovery purposes
> independent of the LDAP source.

### 3.5 Get the Authentik metadata URL

```
https://your-public-authentik-url/application/saml/service-now/metadata/
```

---

## Section 4 — ServiceNow Multi-Provider SSO

> **Plugin required:** The Multi-Provider SSO plugin must be installed before
> proceeding. This was started in the Prerequisites section. Confirm the install
> has completed before continuing.

### 4.1 Import Authentik metadata into ServiceNow

1. **Multi-Provider SSO → Identity Providers → New**
2. Select **Import Identity Provider Metadata**
3. Paste the Authentik metadata URL:
   ```
   https://your-public-authentik-url/application/saml/service-now/metadata/
   ```
4. After the record is saved, scroll to the **Encryption And Signing** related
   list and confirm the Authentik signing certificate is present. If it is
   missing the metadata import did not bring it in — re-import before continuing.

### 4.2 Enable Multi-Provider SSO

**Multi-Provider SSO → Administration → Properties** — enable the system property.

Without this, SSO will not activate regardless of IdP configuration.

### 4.3 Enable local recovery admin account

**Multi-Provider SSO → Account Recovery → Properties** — enable the local
recovery admin account option and set the designated recovery admin user
(typically `admin`).

Without this, SSO logins are silently redirected back to the login page
regardless of whether the SAML flow completes successfully.

### 4.4 Configure the IdP record

| Field | Value |
|---|---|
| Name | `Authentik` |
| Active | false (activate after testing) |
| NameID Policy | `urn:oasis:names:tc:SAML:1.1:nameid-format:unspecified` |
| User Field | `user_name` |
| Sign AuthnRequest | false |
| Show as Login option | true |

### 4.5 Enable JIT provisioning

**User Provisioning** tab:

| Field | Value |
|---|---|
| Auto Provisioning User | true |
| Update User Record Upon Each Login | true |

> **Role assignment:** There is no default role field in the User Provisioning
> tab. Roles are assigned to provisioned users via **User groups applied to
> provisioned users** — lock icon on the right. Add any groups whose roles you
> want automatically applied to users on first login. This is not required for
> basic SSO to function.

---

## Section 5 — SCIM User Provisioning

> **Plugin required:** The SCIM plugin (`com.snc.integration.scim2`) must be
> installed before proceeding. This was started in the Prerequisites section.
> Confirm the install has completed before continuing.

### 5.1 Create the service account

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

### 5.2 Locate the SCIM API OAuth Application Registry

1. **System OAuth → Application Registry**
2. Find and open the **`SCIM API`** record
3. Set **OAuth application user** to `svc_authentik`
4. **Regenerate** the client secret
5. Copy the **Client ID** and **Client secret** into `sso-infrastructure/.env`

> Do not create a new OAuth record — use the one ServiceNow auto-creates when
> the SCIM plugin is installed.

### 5.3 Fix ServiceNow SCIM Group ETL — id read-only issue

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

### 5.4 Configure policy bindings for SCIM sync

1. **Applications → ServiceNow → Policy / Group Bindings**
2. Confirm the `LDAP Users - All` expression policy binding from Section 3.4 is present

> **akadmin bypass:** `akadmin` is a superuser that bypasses all policy bindings.
> Set `akadmin`'s email to `akadmin@authentik.local` to prevent 409 conflicts
> on every full sync.

### 5.5 Trigger initial sync

**Applications → Providers → ServiceNow SCIM → sync icon**

Restart the `scim-refresh` container to run the initial token refresh:

```powershell
docker compose restart scim-refresh
```

---

## Section 6 — SSO Configuration

This section must be completed while logged in as `akadmin` in ServiceNow
before SSO is activated. Once SSO goes live, local logins are blocked except
for ACR users — completing this section first ensures `akadmin` remains
accessible as a recovery account.

### 6.1 Configure akadmin in ServiceNow

Once the initial SCIM sync completes, `akadmin` will exist as a user record in
ServiceNow. Before it can be used as a local admin account it needs roles
assigned and a password set.

**Assign roles**

1. **User Administration → Users** → search for `akadmin`
2. Open the user record
3. Scroll to the **Roles** tab and assign the following:

| Role | Purpose |
|---|---|
| `admin` | Full system administration access |
| `acl_admin` | Required to manage ACL rules and security policies |

**Set a password**

The `akadmin` record is synced from Authentik without a ServiceNow password.
A password must be set before the account can log in locally:

1. On the `akadmin` user record click **Set Password**
2. Set a strong password and note it securely — this is your ServiceNow local
   admin password, independent of the Authentik credentials

### 6.2 First login and MFA setup

Before enabling account recovery, `akadmin` must have completed a first login
so ServiceNow can register the account for ACR in the next step.

1. Open an incognito window and navigate to your PDI login page
2. Log in with `akadmin` and the password you set in section 6.1
3. ServiceNow will prompt you to change the password on first login
4. After the password change, follow the prompts to set up MFA

> Keep the `akadmin` credentials stored securely outside the lab environment.

### 6.3 Enable account recovery

Account recovery (ACR) allows `akadmin` to log in locally even when SSO is
active. This must be configured before enabling SSO — once SSO is live, local
logins are blocked for all non-ACR users.

> **You must be logged in as `akadmin` for this step.** The account recovery
> setup links to your current session in Step 2. If you complete this as the
> wrong user, that user becomes the ACR account instead.

1. Navigate to **Multi-Provider SSO → Account Recovery → Properties**
2. Check **Enable account recovery**
3. Click the **here** link in Step 2 to set up account recovery for your
   account — this registers `akadmin` as the ACR user
4. Click **Save**

**Disable the SSO enforcement system property**

By default the system property `glide.sso.acr.enabled` blocks all local logins
even when ACR is configured. This must be set to `false` to allow `akadmin` to
log in locally.

1. Search for `sys_properties.list` in the filter navigator
2. Find and open the `glide.sso.acr.enabled` property
3. Set the **Value** to `false`
4. Save

> With `glide.sso.acr.enabled` set to `false` and account recovery enabled,
> `akadmin` can log in locally via the standard login page while all other
> users are directed through SSO.

### 6.4 Enable Multi-Provider SSO

1. Navigate to **Multi-Provider SSO → Administration → Properties**
2. Enable the **Enable multiple provider SSO** system property
3. Save

Without this, SSO will not activate regardless of how the IdP record is
configured.

---

## Section 7 — Testing

> **Before testing:** Log out of Authentik completely. If an active Authentik
> session exists when the SAML flow triggers, ServiceNow may be redirected using
> that session rather than prompting for credentials, which skips the login step
> and makes it difficult to verify the flow is working correctly.

### 7.1 Initial test using the Test Connection button

The first SSO test must be done using the **Test Connection** button on the IdP
record. This validates the SAML configuration and if successful enables the
**Activate** button to make the IdP live.

> **Which user to test with:** LDAP-imported users do not have roles or a
> ServiceNow password — their LDAP password is not synced. For initial testing
> use `akadmin`, which has roles assigned and a password set from Section 6.
> If you want to test with an imported user, assign them roles in ServiceNow
> first via **User Administration → Users**.

1. Log out of Authentik
2. Open the IdP record in ServiceNow
3. Open an **incognito window** before clicking Test Connection — testing in
   your active admin session will redirect that session through the SAML flow
4. Click **Test Connection** on the IdP record
5. Log in with `akadmin` (or an imported user with roles assigned) in the
   incognito window
6. Once the test completes successfully, return to the IdP record and click **Activate**

> The `Active` field is read-only. The Activate button is the only supported
> method — it ensures the configuration has been validated before the IdP is
> put into service.

### 7.2 Subsequent SSO testing

After the IdP is active, test a full SSO login via the login page or direct URL.
Always use an **incognito/private browser window** and ensure you are logged out
of Authentik first.

> **Imported users and roles:** LDAP-imported users will authenticate
> successfully via SSO but will land in ServiceNow with no roles unless they
> have been assigned manually. Assign roles via **User Administration → Users**
> before testing with a specific imported user if access beyond the default
> self-service portal is needed.

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

### 7.3 Expected flow

1. Browser redirects to Authentik login at your public URL
2. Log in with an LDAP user (e.g. `jane.doe` / `Password1!`)
3. Authentik validates credentials against OpenLDAP
4. SAML assertion POSTed to ServiceNow ACS URL (`/navpage.do`)
5. ServiceNow matches NameID against `user_name`
6. User logged into ServiceNow

### 7.4 Verify user record

**User Administration → Users** → search `jane.doe` — record should exist with
`user_name`, `email`, `first_name`, `last_name` populated from SCIM.

---

## Section 8 — LDIF Tool

### 8.1 JSON schema

Upload a JSON array matching the fields in `sso-infrastructure/ldif-tool/schema.json`.
Required fields: `uid`, `cn`, `givenname`, `sn`, `mail`, `userpassword`, `title`,
`departmentnumber`. Fields present in JSON but absent from the schema are silently
ignored. `null` values are treated as empty strings.

### 8.2 Import behaviour

The tool upserts — new entries are created, existing entries updated. Group
membership is replaced with the current member list on each import. After a
successful import the tool automatically runs Sync Groups to Authentik.

### 8.3 Extending the schema

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

## Section 9 — Authentik Application Policy

The `LDAP Users - All` expression policy was created in Section 2.3 and bound
to the ServiceNow application in Section 3.4.

Any user synced from OpenLDAP has a path starting with
`goauthentik.io/sources/ldap/openldap/` — the policy covers all of them
automatically including members of any new groups added in future.

If you need to add or adjust bindings:

1. **Applications → ServiceNow → Policy / Group Bindings**
2. Remove any individual group bindings
3. **Bind existing policy** → select `LDAP Users - All`

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
| SCIM 400 group id read-only | ETL `Id` coercion is `create` | Change coercion to `ignore` (Section 5.3) |
| SCIM 409 conflict | akadmin email conflict or stale records | Set akadmin email to `akadmin@authentik.local`, delete ServiceNow records, clear tracking tables, re-sync |
| SCIM `missing or invalid id` | `Id → sys_id` removed from ETL | Add it back with coercion `ignore` |
| SCIM 403 on Authentik API | Wrong token intent or `ak-*` account | Recreate token with Intent = API Token on a regular user |
| SSO redirect never happens | IdP not active, missing cert, or plugin not enabled | Verify cert in IdP related list, confirm SSO enabled in Section 6.4, check IdP is active |
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