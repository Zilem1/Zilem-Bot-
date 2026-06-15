"""
main.py — Runs Flask web server + Discord bot in the same process.
Railway will call: python main.py
"""
import threading
import os
import sys

# Ensure the app root is always on the Python path regardless of CWD
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Ensure data dir exists
os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)

# Point DB at an absolute path so both bot and web share the same file
os.environ.setdefault("DB_PATH", os.path.join(ROOT, "data", "keys.db"))

def run_web():
    from web.app import app
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

def run_bot():
    from bot.bot import bot, BOT_TOKEN
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌  DISCORD_BOT_TOKEN not set — bot will not start")
        return
    bot.run(BOT_TOKEN)

if __name__ == "__main__":
    # Run web server in background thread
    web_thread = threading.Thread(target=run_web, daemon=True)
    web_thread.start()
    print("✅ Web server started")

    # Run Discord bot in main thread (blocking)
    run_bot()
