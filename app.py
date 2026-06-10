"""
Quality Command Centre — Flask backend  (LOGIN + ROLES: admin / editor / viewer)
---------------------------------------------------------------------------------
Identity: the front-end logs into Supabase Auth (email+password) and sends the
returned JWT as  Authorization: Bearer <token>  on every request. This backend
verifies the token via Supabase /auth/v1/user and reads the user's email + role
(from app_metadata.role). Permissions are enforced HERE, not just in the UI.

Permission matrix:
  view all records / export ....... admin, editor, viewer
  add records ..................... admin, editor          (viewer -> 403)
  delete records .................. admin (any) | editor (own only) | viewer (none)

A user whose role is missing/invalid is treated as 'viewer' (least privilege).

Environment variables (set on Render):
  SUPABASE_URL            project URL (base only, no /rest/v1)
  SUPABASE_SERVICE_KEY    service-role key  (DB access)
  SUPABASE_ANON_KEY       anon (public) key (used to verify user tokens)   <-- NEW
  ALLOWED_ORIGINS         your front-end origin, e.g. https://garryii51.github.io
"""
import os
import requests
from functools import wraps
from flask import Flask, request, jsonify, g
from flask_cors import CORS

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SERVICE_KEY  = os.environ.get("SUPABASE_SERVICE_KEY", "")
ANON_KEY     = os.environ.get("SUPABASE_ANON_KEY", "")

_origins_raw = os.environ.get("ALLOWED_ORIGINS", "").strip()
ALLOWED_ORIGINS = [o.strip() for o in _origins_raw.split(",") if o.strip()] or ["*"]

REST     = f"{SUPABASE_URL}/rest/v1/records"
AUTH_URL = f"{SUPABASE_URL}/auth/v1/user"
HEADERS = {
    "apikey": SERVICE_KEY,
    "Authorization": f"Bearer {SERVICE_KEY}",
    "Content-Type": "application/json",
}

app = Flask(__name__)
CORS(app,
     resources={r"/api/*": {"origins": ALLOWED_ORIGINS}},
     methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
     allow_headers=["Content-Type", "Authorization"])

if not SUPABASE_URL or not SERVICE_KEY:
    app.logger.warning("SUPABASE_URL / SUPABASE_SERVICE_KEY not set.")
if not ANON_KEY:
    app.logger.warning("SUPABASE_ANON_KEY not set — login verification will fail until set.")
if ALLOWED_ORIGINS == ["*"]:
    app.logger.warning("ALLOWED_ORIGINS is '*' — set it to your front-end URL in production.")

VALID_ROLES = {"admin", "editor", "viewer", "approver"}


def verify_user(token):
    """Validate a Supabase JWT -> {'email':..., 'role':...} or None."""
    if not token or not ANON_KEY:
        return None
    try:
        r = requests.get(AUTH_URL, timeout=15, headers={
            "apikey": ANON_KEY, "Authorization": f"Bearer {token}",
        })
        if not r.ok:
            return None
        u = r.json()
        email = u.get("email")
        role = (u.get("app_metadata") or {}).get("role")
        if role not in VALID_ROLES:
            role = "viewer"   # least privilege by default
        return {"email": email, "role": role}
    except Exception:
        return None


def require_user(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        token = auth[7:] if auth.lower().startswith("bearer ") else ""
        user = verify_user(token)
        if not user or not user["email"]:
            return jsonify(error="unauthorized"), 401
        g.user = user
        return fn(*args, **kwargs)
    return wrapper


def _check_config():
    if not SUPABASE_URL or not SERVICE_KEY:
        return jsonify(error="Server not configured"), 500
    return None


@app.get("/api/health")
def health():
    return jsonify(ok=True, configured=bool(SUPABASE_URL and SERVICE_KEY),
                   auth_configured=bool(ANON_KEY))


@app.get("/api/me")
@require_user
def me():
    return jsonify(email=g.user["email"], role=g.user["role"])


@app.get("/api/records")
@require_user
def list_records():
    err = _check_config()
    if err:
        return err
    category = request.args.get("category")
    params = {"select": "*", "order": "created_at.desc"}
    if category:
        params["category"] = f"eq.{category}"
    r = requests.get(REST, headers=HEADERS, params=params, timeout=15)
    if not r.ok:
        return jsonify(error="supabase_error", detail=r.text), r.status_code
    return jsonify(r.json())


@app.post("/api/records")
@require_user
def create_record():
    err = _check_config()
    if err:
        return err
    if g.user["role"] == "viewer":
        return jsonify(error="forbidden: viewers cannot add records"), 403
    body = request.get_json(force=True, silent=True) or {}
    category = body.get("category")
    data = body.get("data", {})
    if not category:
        return jsonify(error="category is required"), 400
    sp = {"select": "serial_no", "category": f"eq.{category}",
          "order": "serial_no.desc", "limit": "1"}
    sr = requests.get(REST, headers=HEADERS, params=sp, timeout=15)
    rows = sr.json() if sr.ok else []
    serial_no = (rows[0]["serial_no"] + 1) if rows and rows[0].get("serial_no") else 1
    payload = {"category": category, "serial_no": serial_no,
               "data": data, "owner": g.user["email"]}
    headers = {**HEADERS, "Prefer": "return=representation"}
    r = requests.post(REST, headers=headers, json=payload, timeout=15)
    if not r.ok:
        return jsonify(error="supabase_error", detail=r.text), r.status_code
    created = r.json()
    return jsonify(created[0] if isinstance(created, list) else created), 201


@app.delete("/api/records/<rec_id>")
@require_user
def delete_record(rec_id):
    err = _check_config()
    if err:
        return err
    role = g.user["role"]
    if role == "viewer":
        return jsonify(error="forbidden: viewers cannot delete"), 403
    g1 = requests.get(REST, headers=HEADERS,
                      params={"select": "owner", "id": f"eq.{rec_id}"}, timeout=15)
    rows = g1.json() if g1.ok else []
    if not rows:
        return jsonify(error="not found"), 404
    owner = rows[0].get("owner")
    if role == "admin" or (role == "editor" and owner == g.user["email"]):
        r = requests.delete(REST, headers=HEADERS, params={"id": f"eq.{rec_id}"}, timeout=15)
        if not r.ok:
            return jsonify(error="supabase_error", detail=r.text), r.status_code
        return jsonify(deleted=True)
    return jsonify(error="forbidden: you can only delete your own records"), 403


@app.route("/api/records/<rec_id>", methods=["PATCH"])
@require_user
def update_record(rec_id):
    err = _check_config()
    if err:
        return err
    role = g.user["role"]
    if role == "viewer":
        return jsonify(error="forbidden: viewers cannot edit"), 403
    body = request.get_json(force=True, silent=True) or {}
    new_data = body.get("data")
    if new_data is None:
        return jsonify(error="data is required"), 400
    # fetch owner + existing data
    g1 = requests.get(REST, headers=HEADERS,
                      params={"select": "owner,data", "id": f"eq.{rec_id}"}, timeout=15)
    rows = g1.json() if g1.ok else []
    if not rows:
        return jsonify(error="not found"), 404
    owner = rows[0].get("owner")
    # admin: any. editor: own only.
    if not (role == "admin" or (role == "editor" and owner == g.user["email"])):
        return jsonify(error="forbidden: you can only edit your own records"), 403
    merged = {**(rows[0].get("data") or {}), **new_data}
    headers = {**HEADERS, "Prefer": "return=representation"}
    r = requests.patch(REST, headers=headers, params={"id": f"eq.{rec_id}"},
                       json={"data": merged}, timeout=15)
    if not r.ok:
        return jsonify(error="supabase_error", detail=r.text), r.status_code
    updated = r.json()
    return jsonify(updated[0] if isinstance(updated, list) else updated)


@app.route("/api/records/<rec_id>/approve", methods=["POST"])
@require_user
def approve_record(rec_id):
    err = _check_config()
    if err:
        return err
    role = g.user["role"]
    # only approver or admin may approve
    if role not in ("admin", "approver"):
        return jsonify(error="forbidden: only approver or admin can approve"), 403
    body = request.get_json(force=True, silent=True) or {}
    decision = body.get("decision")
    note = body.get("note", "")
    if decision not in ("Approved", "Rejected"):
        return jsonify(error="decision must be 'Approved' or 'Rejected'"), 400
    g1 = requests.get(REST, headers=HEADERS,
                      params={"select": "owner,data", "id": f"eq.{rec_id}"}, timeout=15)
    rows = g1.json() if g1.ok else []
    if not rows:
        return jsonify(error="not found"), 404
    owner = rows[0].get("owner")
    # cannot approve your own record (integrity) — applies even to admin
    if owner == g.user["email"]:
        return jsonify(error="forbidden: you cannot approve your own record"), 403
    data = rows[0].get("data") or {}
    data["approvalStatus"] = decision
    data["approvedBy"] = g.user["email"]
    data["approvalDate"] = __import__("datetime").datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    data["approvalNote"] = note
    data["status"] = "Closed" if decision == "Approved" else data.get("status", "Action")
    headers = {**HEADERS, "Prefer": "return=representation"}
    r = requests.patch(REST, headers=headers, params={"id": f"eq.{rec_id}"},
                       json={"data": data}, timeout=15)
    if not r.ok:
        return jsonify(error="supabase_error", detail=r.text), r.status_code
    out = r.json()
    return jsonify(out[0] if isinstance(out, list) else out)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
