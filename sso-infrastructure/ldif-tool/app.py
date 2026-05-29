import os
import json
from pathlib import Path
from flask import Flask, request, jsonify, send_file, render_template
from ldap3 import Server, Connection, ALL, MODIFY_REPLACE
from ldap3.core.exceptions import LDAPException, LDAPEntryAlreadyExistsResult
from dotenv import load_dotenv
import io
import requests

# Load .env from the project root (one level up from this file)
load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")

app = Flask(__name__)

LDAP_HOST     = os.environ.get("LDAP_HOST", "openldap")
LDAP_PORT     = int(os.environ.get("LDAP_PORT", 389))
LDAP_ADMIN_DN = os.environ.get("LDAP_ADMIN_DN", "")
LDAP_ADMIN_PW = os.environ.get("LDAP_ADMIN_PASSWORD", "")
LDAP_BASE_DN  = os.environ.get("LDAP_BASE_DN", "")
USERS_OU      = f"ou=users,{LDAP_BASE_DN}"
GROUPS_OU     = f"ou=groups,{LDAP_BASE_DN}"

AUTHENTIK_URL       = os.environ.get("AUTHENTIK_URL", "http://authentik-server:9000")
AUTHENTIK_API_TOKEN = os.environ.get("AUTHENTIK_API_TOKEN", "")
AUTHENTIK_LDAP_SLUG = os.environ.get("AUTHENTIK_LDAP_SLUG", "openldap")

# Load schema from schema.json
_schema_path = Path(__file__).resolve().parent / "schema.json"
with open(_schema_path) as _f:
    SCHEMA = json.load(_f)

OBJECT_CLASSES  = SCHEMA["object_classes"]
FIELDS          = SCHEMA["fields"]
ATTR_MAP        = {f["json_key"]: f["ldap_attr"] for f in FIELDS}
REQUIRED_FIELDS = {f["json_key"] for f in FIELDS if f.get("required")}
GROUP_FIELD     = next((f["json_key"] for f in FIELDS if f.get("generates_groups")), None)


def sync_groups_to_authentik():
    """Query OpenLDAP for groups and mirror them into Authentik with ldap_uniq set.

    Returns a result dict with:
      - status: 'ok' | 'warning' | 'error'
      - message: human-readable summary
      - total, created, updated, errors: counts
    """
    if not AUTHENTIK_API_TOKEN:
        return {
            "status": "warning",
            "message": "AUTHENTIK_API_TOKEN not configured — skipping Authentik sync. "
                       "Create an API token in Authentik and add it to .env, then use "
                       "the Sync Groups button to sync manually.",
            "total": 0,
            "created": 0,
            "updated": 0,
            "errors": 0,
        }

    headers = {
        "Authorization": f"Bearer {AUTHENTIK_API_TOKEN}",
        "Content-Type": "application/json",
    }

    # Query OpenLDAP for all groups and their entryUUIDs
    try:
        server = Server(LDAP_HOST, port=LDAP_PORT, get_info=ALL)
        conn = Connection(server, user=LDAP_ADMIN_DN, password=LDAP_ADMIN_PW, auto_bind=True)
    except LDAPException as e:
        return {
            "status": "error",
            "message": f"LDAP connection failed: {e}",
            "total": 0,
            "created": 0,
            "updated": 0,
            "errors": 0,
        }

    conn.search(
        GROUPS_OU,
        "(objectClass=posixGroup)",
        attributes=["cn", "entryUUID", "memberUid"],
    )
    groups = [
        {
            "name": str(entry.cn),
            "ldap_uniq": str(entry.entryUUID),
            "members": [str(m) for m in entry.memberUid] if entry.memberUid else [],
        }
        for entry in conn.entries
    ]
    conn.unbind()

    if not groups:
        return {
            "status": "warning",
            "message": "No groups found in LDAP",
            "total": 0,
            "created": 0,
            "updated": 0,
            "errors": 0,
        }

    # Build a uid → Authentik user ID lookup cache
    user_cache = {}
    try:
        page = 1
        while True:
            resp = requests.get(
                f"{AUTHENTIK_URL}/api/v3/core/users/?page_size=100&page={page}",
                headers=headers, timeout=10,
            )
            if resp.status_code != 200:
                break
            data = resp.json()
            for u in data.get("results", []):
                user_cache[u["username"]] = u["pk"]
            if not data.get("pagination", {}).get("next"):
                break
            page += 1
    except requests.RequestException:
        pass

    created = updated = errors = 0
    error_details = []

    for group in groups:
        member_ids = []
        for uid in group.get("members", []):
            if uid in user_cache:
                member_ids.append(user_cache[uid])

        body = {
            "name": group["name"],
            "attributes": {"ldap_uniq": group["ldap_uniq"]},
            "users": member_ids,
        }
        try:
            search = requests.get(
                f"{AUTHENTIK_URL}/api/v3/core/groups/?name={group['name']}",
                headers=headers, timeout=10,
            )
            existing = search.json().get("results", []) if search.status_code == 200 else []

            if existing:
                group_pk = existing[0]["pk"]
                resp = requests.patch(
                    f"{AUTHENTIK_URL}/api/v3/core/groups/{group_pk}/",
                    headers=headers, json=body, timeout=10,
                )
                if resp.status_code == 200:
                    updated += 1
                else:
                    errors += 1
                    error_details.append(f"{group['name']}: PATCH {resp.status_code} — {resp.text[:120]}")
            else:
                resp = requests.post(
                    f"{AUTHENTIK_URL}/api/v3/core/groups/",
                    headers=headers, json=body, timeout=10,
                )
                if resp.status_code == 201:
                    created += 1
                else:
                    errors += 1
                    error_details.append(f"{group['name']}: POST {resp.status_code} — {resp.text[:120]}")
        except requests.RequestException as e:
            errors += 1
            error_details.append(f"{group['name']}: {str(e)}")

    total = len(groups)
    if errors > 0 and created == 0 and updated == 0:
        status = "error"
    elif errors > 0:
        status = "warning"
    else:
        status = "ok"

    msg = f"{total} groups — {created} created, {updated} updated, {errors} errors"
    if error_details:
        msg += " | " + "; ".join(error_details[:3])
        if len(error_details) > 3:
            msg += f" (+{len(error_details) - 3} more)"

    return {
        "status": status,
        "message": msg,
        "total": total,
        "created": created,
        "updated": updated,
        "errors": errors,
    }


def parse_users(data):
    """Parse and validate incoming JSON list of users."""
    if not isinstance(data, list):
        raise ValueError("JSON must be an array of user objects.")
    known_keys = set(ATTR_MAP.keys()) | {"dn"}
    users = []
    for i, entry in enumerate(data):
        entry = {k: (v if v is not None else "") for k, v in entry.items()}
        for key in REQUIRED_FIELDS:
            if not str(entry.get(key, "")).strip():
                raise ValueError(f"Entry {i} is missing required field '{key}'.")
        filtered = {k: str(v).strip() for k, v in entry.items() if k in known_keys}
        users.append(filtered)
    return users


def build_ldif(users, include_groups=True):
    lines = []
    departments = {}
    if include_groups and GROUP_FIELD:
        for user in users:
            dept = user.get(GROUP_FIELD, "").strip()
            uid  = user.get("uid", "").strip()
            if dept:
                departments.setdefault(dept, []).append(uid)

    for user in users:
        uid = user.get("uid", "").strip()
        dn  = f"uid={uid},{USERS_OU}"
        lines.append(f"dn: {dn}")
        for oc in OBJECT_CLASSES:
            lines.append(f"objectClass: {oc}")
        for json_key, ldap_attr in ATTR_MAP.items():
            val = user.get(json_key, "").strip()
            if val:
                lines.append(f"{ldap_attr}: {val}")
        lines.append("")

    if include_groups:
        for gid_offset, (dept, members) in enumerate(departments.items()):
            group_cn = dept.lower().replace(" ", "-")
            dn = f"cn={group_cn},{GROUPS_OU}"
            lines.append(f"dn: {dn}")
            lines.append("objectClass: posixGroup")
            lines.append("objectClass: top")
            lines.append(f"cn: {group_cn}")
            lines.append(f"gidNumber: {10000 + gid_offset}")
            for uid in members:
                lines.append(f"memberUid: {uid}")
            lines.append("")

    return "\n".join(lines)


def import_to_ldap(users, include_groups=True):
    """Import users and groups into OpenLDAP. Returns LDAP results only."""
    results = []
    server = Server(LDAP_HOST, port=LDAP_PORT, get_info=ALL)

    try:
        conn = Connection(server, user=LDAP_ADMIN_DN, password=LDAP_ADMIN_PW, auto_bind=True)
    except LDAPException as e:
        return [{"status": "error", "message": f"Failed to connect to LDAP: {str(e)}"}]

    departments = {}

    for user in users:
        uid  = user.get("uid", "").strip()
        dn   = f"uid={uid},{USERS_OU}"
        attrs = {"objectClass": OBJECT_CLASSES}
        for json_key, ldap_attr in ATTR_MAP.items():
            if json_key == "uid":
                continue
            val = user.get(json_key, "").strip()
            if val:
                attrs[ldap_attr] = val

        if include_groups and GROUP_FIELD:
            dept = user.get(GROUP_FIELD, "").strip()
            if dept:
                departments.setdefault(dept, []).append(uid)

        try:
            success = conn.add(dn, attributes=attrs)
            if success:
                results.append({"dn": dn, "status": "created"})
            elif conn.result.get("description") == "entryAlreadyExists":
                changes = {
                    attr: [(MODIFY_REPLACE, [val])]
                    for attr, val in attrs.items()
                    if attr not in ("objectClass",)
                }
                mod_success = conn.modify(dn, changes)
                if mod_success:
                    results.append({"dn": dn, "status": "updated"})
                else:
                    desc = conn.result.get("description", "modify failed")
                    results.append({"dn": dn, "status": "error", "message": desc})
            else:
                desc = conn.result.get("description", "unknown error")
                results.append({"dn": dn, "status": "error", "message": desc})
        except LDAPException as e:
            results.append({"dn": dn, "status": "error", "message": str(e)})

    if include_groups:
        for gid_offset, (dept, members) in enumerate(departments.items()):
            group_cn = dept.lower().replace(" ", "-")
            dn = f"cn={group_cn},{GROUPS_OU}"
            attrs = {
                "objectClass": ["posixGroup", "top"],
                "cn": group_cn,
                "gidNumber": str(10000 + gid_offset),
                "memberUid": members,
            }
            try:
                success = conn.add(dn, attributes=attrs)
                if success:
                    results.append({"dn": dn, "status": "created"})
                elif conn.result.get("description") == "entryAlreadyExists":
                    changes = {
                        "memberUid": [(MODIFY_REPLACE, attrs["memberUid"])],
                    }
                    mod_success = conn.modify(dn, changes)
                    if mod_success:
                        results.append({"dn": dn, "status": "updated"})
                    else:
                        desc = conn.result.get("description", "modify failed")
                        results.append({"dn": dn, "status": "error", "message": desc})
                else:
                    desc = conn.result.get("description", "unknown error")
                    results.append({"dn": dn, "status": "error", "message": desc})
            except LDAPException as e:
                results.append({"dn": dn, "status": "error", "message": str(e)})

    conn.unbind()
    return results


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/schema")
def schema():
    return jsonify(SCHEMA)


@app.route("/sync", methods=["POST"])
def sync():
    result = sync_groups_to_authentik()
    return jsonify(result)


@app.route("/convert", methods=["POST"])
def convert():
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "No file uploaded."}), 400
    try:
        data  = json.load(file)
        users = parse_users(data)
        include_groups = request.form.get("include_groups", "true") == "true"
        ldif  = build_ldif(users, include_groups)
        buf   = io.BytesIO(ldif.encode("utf-8"))
        buf.seek(0)
        return send_file(buf, mimetype="text/plain",
                         as_attachment=True, download_name="users.ldif")
    except (ValueError, json.JSONDecodeError) as e:
        return jsonify({"error": str(e)}), 400


@app.route("/import", methods=["POST"])
def import_users():
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "No file uploaded."}), 400
    try:
        data  = json.load(file)
        users = parse_users(data)
        include_groups = request.form.get("include_groups", "true") == "true"

        # Step 1 — LDAP import
        ldap_results = import_to_ldap(users, include_groups)
        ldap_created = sum(1 for r in ldap_results if r["status"] == "created")
        ldap_updated = sum(1 for r in ldap_results if r["status"] == "updated")
        ldap_errors  = sum(1 for r in ldap_results if r["status"] == "error")

        # Step 2 — Authentik sync (independent of LDAP result)
        authentik_sync = sync_groups_to_authentik()

        return jsonify({
            "ldap": {
                "total":   len(ldap_results),
                "created": ldap_created,
                "updated": ldap_updated,
                "errors":  ldap_errors,
                "results": ldap_results,
            },
            "authentik": authentik_sync,
        })
    except (ValueError, json.JSONDecodeError) as e:
        return jsonify({"error": str(e)}), 400


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)