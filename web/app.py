
from flask import Flask, jsonify, request, render_template, abort
import sqlite3
import os
from datetime import datetime

app = Flask(__name__)

@app.after_request
def add_cors_headers(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Admin-Secret"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
    return resp

DB_PATH    = os.getenv("DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "keys.db"))
API_SECRET = os.getenv("API_SECRET", "change-me-secret")  # For admin endpoints

TIER_INFO = {
    "donor":    {"label": "Donor",     "color": "#a78bfa", "mb": 1024, "emoji": "💎", "max_res": "4K",    "max_fps": None, "patches": None},
    "first100": {"label": "First 100", "color": "#e879f9", "mb": 500,  "emoji": "🏅", "max_res": "4K",    "max_fps": None, "patches": 5   },
    "booster":  {"label": "Booster",   "color": "#fbbf24", "mb": 750,  "emoji": "🚀", "max_res": "4K",    "max_fps": 120,  "patches": 7   },
    "helper":   {"label": "Helper",    "color": "#34d399", "mb": 500,  "emoji": "🛠️","max_res": "4K",    "max_fps": None, "patches": None},
    "member":   {"label": "Member",    "color": "#60a5fa", "mb": 150,  "emoji": "👥", "max_res": "1080p", "max_fps": 60,   "patches": 5   },
    "guest":    {"label": "Guest",     "color": "#888888", "mb": 25,   "emoji": "👤", "max_res": "1080p", "max_fps": 60,   "patches": None},
}

def get_week_start():
    from datetime import timedelta
    today = datetime.utcnow().date()
    monday = today - timedelta(days=today.weekday())
    return monday.isoformat()

def get_usage_count(discord_id: str) -> int:
    try:
        conn = get_db()
        week = get_week_start()
        row = conn.execute(
            "SELECT week_start, patch_count FROM usage WHERE discord_id=?", (str(discord_id),)
        ).fetchone()
        conn.close()
        if not row or row[0] != week:
            return 0
        return row[1]
    except Exception:
        return 0

def get_db():
    return sqlite3.connect(DB_PATH)

def row_to_dict(row):
    if not row:
        return None
    return dict(zip(["key","discord_id","username","display_name","avatar_url","tier","created_at","last_seen"], row))

# ── Public: Validate a key ─────────────────────────────────────────────────────
@app.route("/api/validate", methods=["POST", "OPTIONS"])
def validate():
    """Called by the Zilem website to validate a key. Always server-authoritative."""
    # CORS preflight
    if request.method == "OPTIONS":
        r = jsonify({}); r.headers["Access-Control-Allow-Origin"] = "*"
        r.headers["Access-Control-Allow-Headers"] = "Content-Type"
        r.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        return r, 204

    body = request.get_json(silent=True) or {}
    key  = body.get("key", "").strip().upper()
    if not key:
        return _cors(jsonify({"valid": False, "error": "No key provided"}), 400)

    conn = get_db()
    row  = conn.execute("SELECT * FROM keys WHERE key=?", (key,)).fetchone()
    if row:
        conn.execute("UPDATE keys SET last_seen=? WHERE key=?",
                     (datetime.utcnow().isoformat(), key))
        conn.commit()
    conn.close()

    if not row:
        return _cors(jsonify({"valid": False, "error": "Invalid key"}), 401)

    info = row_to_dict(row)
    tier = info["tier"]

    # Defensive: guest tier is not issuable and should never authenticate
    if tier == "guest":
        return _cors(jsonify({"valid": False, "error": "Key tier no longer valid"}), 401)

    ti   = TIER_INFO.get(tier, TIER_INFO["guest"])

    patches_limit = ti.get("patches")
    # Track usage for everyone, even unlimited tiers, so the site can show
    # "N used" against an infinity symbol instead of always showing 0.
    patches_used  = get_usage_count(info["discord_id"])

    return _cors(jsonify({
        "valid":          True,
        "tier":           tier,
        "tier_label":     ti["label"],
        "tier_emoji":     ti["emoji"],
        "limit_mb":       ti["mb"],
        "max_res":        ti.get("max_res", "1080p"),
        "max_fps":        ti.get("max_fps"),
        "patches_limit":  patches_limit,
        "patches_used":   patches_used,
        "discord_id":     info["discord_id"],
        "username":       info["username"],
        "display_name":   info["display_name"],
        "avatar_url":     info["avatar_url"],
    }))


def get_db_immediate():
    # Separate connection in autocommit mode so we can issue our own
    # BEGIN IMMEDIATE below. That grabs SQLite's write lock right away
    # (not lazily on first write), so two /api/use requests for the same
    # key arriving at the same instant can't both read "0 used" before
    # either one commits — the second has to wait for the first to finish.
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.isolation_level = None
    return conn

# ── Public: Record one patch use (server-authoritative, atomic) ───────────────
@app.route("/api/use", methods=["POST", "OPTIONS"])
def use_patch():
    """Called once per completed patch. This is the real enforcement point —
    checks the weekly count and increments it in the same locked transaction,
    so there's nothing left on the client (refresh, re-entering the key,
    editing sessionStorage, calling the JS directly) that can affect the
    outcome. Everything relevant is looked up server-side from the key."""
    if request.method == "OPTIONS":
        r = jsonify({}); r.headers["Access-Control-Allow-Origin"] = "*"
        r.headers["Access-Control-Allow-Headers"] = "Content-Type"
        r.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        return r, 204

    body = request.get_json(silent=True) or {}
    key  = body.get("key", "").strip().upper()
    if not key:
        return _cors(jsonify({"ok": False, "error": "No key provided"}), 400)

    conn = get_db_immediate()
    try:
        conn.execute("BEGIN IMMEDIATE")

        row = conn.execute("SELECT discord_id, tier FROM keys WHERE key=?", (key,)).fetchone()
        if not row:
            conn.execute("ROLLBACK")
            return _cors(jsonify({"ok": False, "error": "Invalid key"}), 401)

        discord_id, tier = row
        if tier == "guest":
            conn.execute("ROLLBACK")
            return _cors(jsonify({"ok": False, "error": "Key tier no longer valid"}), 401)

        ti = TIER_INFO.get(tier, TIER_INFO["guest"])
        patches_limit = ti.get("patches")

        week = get_week_start()
        urow = conn.execute(
            "SELECT week_start, patch_count FROM usage WHERE discord_id=?", (discord_id,)
        ).fetchone()
        current = urow[1] if (urow and urow[0] == week) else 0

        # Only capped tiers get rejected at the limit. Unlimited tiers
        # (patches_limit is None) skip straight to incrementing below —
        # they still get counted, just never blocked.
        if patches_limit is not None and current >= patches_limit:
            conn.execute("ROLLBACK")
            return _cors(jsonify({
                "ok": False, "error": "limit_reached",
                "patches_used": current, "patches_limit": patches_limit
            }), 403)

        new_count = current + 1
        conn.execute("""
            INSERT INTO usage (discord_id, week_start, patch_count) VALUES (?,?,?)
            ON CONFLICT(discord_id) DO UPDATE SET week_start=excluded.week_start, patch_count=excluded.patch_count
        """, (discord_id, week, new_count))
        conn.execute("UPDATE keys SET last_seen=? WHERE key=?",
                     (datetime.utcnow().isoformat(), key))
        conn.execute("COMMIT")

        return _cors(jsonify({"ok": True, "patches_used": new_count, "patches_limit": patches_limit}))
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        conn.close()


def _cors(response, status=200):
    """Add CORS header so the frontend can reach the API."""
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.status_code = status
    return response

# ── Public: User profile card (for activate page) ─────────────────────────────
@app.route("/api/profile/<key>", methods=["GET"])
def profile(key):
    key  = key.strip().upper()
    conn = get_db()
    row  = conn.execute("SELECT * FROM keys WHERE key=?", (key,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "Key not found"}), 404
    info = row_to_dict(row)
    tier = info["tier"]
    ti   = TIER_INFO.get(tier, TIER_INFO["guest"])
    return jsonify({
        "display_name": info["display_name"],
        "username":     info["username"],
        "avatar_url":   info["avatar_url"],
        "tier":         tier,
        "tier_label":   ti["label"],
        "tier_color":   ti["color"],
        "tier_emoji":   ti["emoji"],
        "limit_mb":     ti["mb"],
    })

# ── Admin: list all keys (protected) ─────────────────────────────────────────
@app.route("/api/admin/keys", methods=["GET"])
def admin_keys():
    secret = request.headers.get("X-Admin-Secret", "")
    if secret != API_SECRET:
        abort(401)
    conn = get_db()
    rows = conn.execute("SELECT * FROM keys ORDER BY tier, created_at").fetchall()
    conn.close()
    return jsonify([row_to_dict(r) for r in rows])

# ── Admin: revoke a key ────────────────────────────────────────────────────────
@app.route("/api/admin/revoke/<discord_id>", methods=["DELETE"])
def admin_revoke(discord_id):
    secret = request.headers.get("X-Admin-Secret", "")
    if secret != API_SECRET:
        abort(401)
    conn = get_db()
    affected = conn.execute("DELETE FROM keys WHERE discord_id=?", (discord_id,)).rowcount
    conn.commit()
    conn.close()
    return jsonify({"revoked": affected > 0})

# ── Dashboard (web UI) ────────────────────────────────────────────────────────
@app.route("/")
def dashboard():
    conn = get_db()
    rows = conn.execute("SELECT * FROM keys ORDER BY created_at DESC").fetchall()
    conn.close()
    keys = [row_to_dict(r) for r in rows]
    for k in keys:
        ti = TIER_INFO.get(k["tier"], TIER_INFO["guest"])
        k["tier_label"] = ti["label"]
        k["tier_color"] = ti["color"]
        k["tier_emoji"] = ti["emoji"]
        k["limit_mb"]   = ti["mb"]
    stats = {t: sum(1 for k in keys if k["tier"]==t) for t in TIER_INFO}
    return render_template("dashboard.html", keys=keys, stats=stats, tier_info=TIER_INFO)

@app.route("/activate")
def activate():
    return render_template("activate.html")

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
