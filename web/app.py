
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
    "donor":   {"label": "Donor",   "color": "#a78bfa", "mb": 1024, "emoji": "💜"},
    "booster": {"label": "Booster", "color": "#fbbf24", "mb": 750,  "emoji": "⭐"},
    "helper":  {"label": "Helper",  "color": "#34d399", "mb": 500,  "emoji": "🟢"},
    "member":  {"label": "Member",  "color": "#60a5fa", "mb": 150,  "emoji": "🔵"},
    "guest":   {"label": "Guest",   "color": "#888888", "mb": 25,   "emoji": "⚪"},
}

def get_db():
    return sqlite3.connect(DB_PATH)

def row_to_dict(row):
    if not row:
        return None
    return dict(zip(["key","discord_id","username","display_name","avatar_url","tier","created_at","last_seen"], row))

# ── Public: Validate a key ─────────────────────────────────────────────────────
@app.route("/api/validate", methods=["GET"])
def validate():
    """Called by your Zilem website to validate a key."""
    key = request.args.get("key", "").strip().upper()
    if not key:
        return jsonify({"valid": False, "error": "No key provided"}), 400

    conn = get_db()
    row  = conn.execute("SELECT * FROM keys WHERE key=?", (key,)).fetchone()
    # Update last_seen
    if row:
        conn.execute("UPDATE keys SET last_seen=? WHERE key=?", (datetime.utcnow().isoformat(), key))
        conn.commit()
    conn.close()

    if not row:
        return jsonify({"valid": False, "error": "Key not found"}), 404

    info = row_to_dict(row)
    tier = info["tier"]
    ti   = TIER_INFO.get(tier, TIER_INFO["guest"])

    return jsonify({
        "valid":        True,
        "key":          info["key"],
        "tier":         tier,
        "tier_label":   ti["label"],
        "tier_color":   ti["color"],
        "tier_emoji":   ti["emoji"],
        "limit_mb":     ti["mb"],
        "discord_id":   info["discord_id"],
        "username":     info["username"],
        "display_name": info["display_name"],
        "avatar_url":   info["avatar_url"],
        "created_at":   info["created_at"],
        "last_seen":    info["last_seen"],
    })

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
