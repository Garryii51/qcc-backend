"""
Quality Command Centre — Flask backend
----------------------------------------
Holds the Supabase SERVICE-ROLE key server-side. The browser never sees it.
Exposes a small REST API the single-file HTML app calls with fetch().

Endpoints:
  GET    /api/health                 -> {"ok": true}
  GET    /api/records?category=copq  -> [ {id, category, serial_no, data, created_at}, ... ]
  GET    /api/records/next_serial?category=copq -> {"next": 7}
  POST   /api/records                -> create  (body: {category, data})  returns created row
  DELETE /api/records/<id>           -> delete   returns {"deleted": true}

Run locally:
  pip install -r requirements.txt
  set the env vars (see .env.example), then:  python app.py
"""
import os
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS

# ---- config (from environment, never hard-coded) ----
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SERVICE_KEY  = os.environ.get("SUPABASE_SERVICE_KEY", "")
# Comma-separated list of allowed front-end origins (your GitHub Pages URL, localhost, etc.)
# Default is empty -> CORS effectively closed until you set it. Use "*" only knowingly.
_origins_raw = os.environ.get("ALLOWED_ORIGINS", "").strip()
ALLOWED_ORIGINS = [o.strip() for o in _origins_raw.split(",") if o.strip()] or ["*"]

REST = f"{SUPABASE_URL}/rest/v1/records"
HEADERS = {
    "apikey": SERVICE_KEY,
    "Authorization": f"Bearer {SERVICE_KEY}",
    "Content-Type": "application/json",
}

app = Flask(__name__)
# Restrict CORS to the /api/* paths, only the configured origins, only the methods we use.
CORS(app,
     resources={r"/api/*": {"origins": ALLOWED_ORIGINS}},
     methods=["GET", "POST", "DELETE", "OPTIONS"],
     allow_headers=["Content-Type"])

# Loud startup warnings so misconfiguration is obvious in the Render logs.
if not SUPABASE_URL or not SERVICE_KEY:
    app.logger.warning("SUPABASE_URL / SUPABASE_SERVICE_KEY not set — API will return 500 until configured.")
if ALLOWED_ORIGINS == ["*"]:
    app.logger.warning("ALLOWED_ORIGINS is '*' (any site can call this API). Set it to your front-end URL in production.")


def _check_config():
    if not SUPABASE_URL or not SERVICE_KEY:
        return jsonify(error="Server not configured: set SUPABASE_URL and SUPABASE_SERVICE_KEY"), 500
    return None


@app.get("/api/health")
def health():
    return jsonify(ok=True, configured=bool(SUPABASE_URL and SERVICE_KEY))


@app.get("/api/records")
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


@app.get("/api/records/next_serial")
def next_serial():
    """Return the next sequential Sr. No. for a category (current max + 1)."""
    err = _check_config()
    if err:
        return err
    category = request.args.get("category", "")
    params = {
        "select": "serial_no",
        "category": f"eq.{category}",
        "order": "serial_no.desc",
        "limit": "1",
    }
    r = requests.get(REST, headers=HEADERS, params=params, timeout=15)
    if not r.ok:
        return jsonify(error="supabase_error", detail=r.text), r.status_code
    rows = r.json()
    nxt = (rows[0]["serial_no"] + 1) if rows and rows[0].get("serial_no") else 1
    return jsonify(next=nxt)


@app.post("/api/records")
def create_record():
    err = _check_config()
    if err:
        return err
    body = request.get_json(force=True, silent=True) or {}
    category = body.get("category")
    data = body.get("data", {})
    if not category:
        return jsonify(error="category is required"), 400

    # compute the next serial server-side so it can't be tampered with
    sp = {
        "select": "serial_no",
        "category": f"eq.{category}",
        "order": "serial_no.desc",
        "limit": "1",
    }
    sr = requests.get(REST, headers=HEADERS, params=sp, timeout=15)
    rows = sr.json() if sr.ok else []
    serial_no = (rows[0]["serial_no"] + 1) if rows and rows[0].get("serial_no") else 1

    payload = {"category": category, "serial_no": serial_no, "data": data}
    headers = {**HEADERS, "Prefer": "return=representation"}
    r = requests.post(REST, headers=headers, json=payload, timeout=15)
    if not r.ok:
        return jsonify(error="supabase_error", detail=r.text), r.status_code
    created = r.json()
    return jsonify(created[0] if isinstance(created, list) else created), 201


@app.delete("/api/records/<rec_id>")
def delete_record(rec_id):
    err = _check_config()
    if err:
        return err
    r = requests.delete(REST, headers=HEADERS, params={"id": f"eq.{rec_id}"}, timeout=15)
    if not r.ok:
        return jsonify(error="supabase_error", detail=r.text), r.status_code
    return jsonify(deleted=True)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    # debug stays OFF unless you explicitly set FLASK_DEBUG=1 for local work.
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
