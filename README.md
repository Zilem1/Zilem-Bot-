# Zilem Bot — Complete Setup Guide

## What This Does

One Railway deployment runs two things in the same process:
- **Discord Bot** — `/getkey` `/mykey` `/revokekey` `/listkeys` `/synckey`
- **Web Dashboard** — `yourapp.railway.app/` (admin key list) + `/activate` (user key page)

---

## Why It Was Crashing

Three bugs in the original code:

**1. Missing `__init__.py`**
Python couldn't find `bot/` and `web/` as packages.
Fix: added empty `bot/__init__.py` and `web/__init__.py`.

**2. Wrong `sys.path`**
Railway doesn't run from `/app` — the imports `from bot.bot import` and `from web.app import` 
failed because Python didn't know where to look.
Fix: `main.py` now inserts its own directory into `sys.path` at startup.

**3. Relative DB path**
`web/app.py` had `DB_PATH = "../data/keys.db"` — relative path that breaks on Railway.
Fix: now uses an absolute path built from `__file__`, set via env var so both bot and web 
share the exact same database.

---

## Step 1 — Create the Discord Bot

1. Go to https://discord.com/developers/applications
2. Click **New Application** → name it "Zilem"
3. Left sidebar → **Bot**
   - Click **Add Bot** → confirm
   - Under **Token** → click **Reset Token** → **copy it** (this is your `DISCORD_BOT_TOKEN`)
   - Scroll down to **Privileged Gateway Intents**
   - Turn ON: **Server Members Intent** (required so bot can see roles)
   - Turn ON: **Message Content Intent**
   - Click **Save Changes**

4. Left sidebar → **OAuth2** → **URL Generator**
   - Scopes: check `bot` and `applications.commands`
   - Bot Permissions: check:
     - Send Messages
     - Send Messages in Threads
     - Use Slash Commands
     - Read Message History
   - Copy the generated URL → open in browser → add bot to your server

5. Get your Server ID:
   - In Discord: Settings → Advanced → Enable Developer Mode
   - Right-click your server icon → **Copy Server ID**
   - This is your `DISCORD_GUILD_ID`

---

## Step 2 — Deploy to Railway

1. Go to https://railway.app → New Project → Deploy from GitHub repo
   (or: New Project → Empty Project → upload files)

2. Add all the project files (this zip extracted)

3. Click your service → **Variables** tab → add these:

```
DISCORD_BOT_TOKEN    = (paste the token from Step 1)
DISCORD_GUILD_ID     = (paste your server ID from Step 1)
API_SECRET           = (make up any random string, e.g. mySecretKey123)
PORT                 = 5000
```

That's it. Do NOT set DB_PATH — Railway handles it automatically.

4. Railway will auto-detect `railway.toml` and run `python main.py`

5. After deploy, check logs — you should see:
   ```
   ✅ Web server started
   ✅ Logged in as Zilem#1234 | Guild synced: 123456789
   ```

---

## Step 3 — Test It

In your Discord server, type `/getkey` — bot should reply with a key embed (ephemeral/private).

Open your Railway URL:
- `https://yourapp.railway.app/` → admin dashboard (all keys)
- `https://yourapp.railway.app/activate` → user key activation page

---

## Environment Variables — Full Reference

| Variable | Where to get it | Example |
|---|---|---|
| `DISCORD_BOT_TOKEN` | Discord Dev Portal → Bot → Reset Token | `MTIzNDU2Nz...` |
| `DISCORD_GUILD_ID` | Right-click server → Copy Server ID | `1234567890123` |
| `API_SECRET` | Make it up — used for `/api/admin/*` | `mySecret42!` |
| `PORT` | Set to `5000` on Railway | `5000` |

---

## Tier / Role Setup

Edit `bot/bot.py` lines 17-22 to match your actual Discord role names (case-insensitive):

```python
ROLE_TIER_MAP = {
    "donor":   "donor",     # Role named "Donor" → donor tier (unlimited)
    "booster": "booster",   # Role named "Booster" → booster tier (unlimited)
    "helper":  "helper",    # Role named "Helper" → helper tier (unlimited)
    "member":  "member",    # Role named "Member" → member tier (200 MB)
}
# Anyone without a matching role gets "guest" tier (50 MB)
```

Tier limits are in `TIER_INFO` in both `bot/bot.py` and `web/app.py`.

---

## Bot Commands

| Command | Who | What |
|---|---|---|
| `/getkey` | Everyone | Generates (or retrieves) your license key based on your roles |
| `/mykey` | Everyone | Shows your current key again |
| `/revokekey @user` | Admins only | Deletes a user's key |
| `/listkeys` | Admins only | Shows all keys (up to 25) |
| `/synckey` | Admins only | Re-scans all users' roles and updates tiers |

---

## API Endpoints

| Endpoint | Auth | What |
|---|---|---|
| `GET /api/validate?key=XXXX-XXXX-XXXX-XXXX` | None | Validate a key (used by your website) |
| `GET /api/profile/<key>` | None | Get user profile for a key (used by /activate page) |
| `GET /api/admin/keys` | Header: `X-Admin-Secret: <API_SECRET>` | List all keys as JSON |
| `DELETE /api/admin/revoke/<discord_id>` | Header: `X-Admin-Secret: <API_SECRET>` | Revoke a key |

---

## Logs

In Railway → your service → **Deployments** → click latest → **View Logs**

Good startup looks like:
```
✅ Web server started
✅ Logged in as YourBot#1234 | Guild synced: 1234567890
```

Common errors:
- `DISCORD_BOT_TOKEN not set` → check your Railway env variables
- `Privileged intent error` → go to Discord Dev Portal → Bot → enable Server Members Intent
- `Guild not found` → double check DISCORD_GUILD_ID is correct

