import discord
from discord import app_commands
from discord.ext import commands
import sqlite3
import secrets
import string
import os
import asyncio
from datetime import datetime
from scraper import scrape_tiktok

# ── Config ────────────────────────────────────────────────────────────────────
BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
GUILD_ID   = int(os.getenv("DISCORD_GUILD_ID", "0"))
DB_PATH    = os.getenv("DB_PATH", "data/keys.db")

ROLE_TIER_MAP = {
    "admins":  "donor",
    "donor":   "donor",
    "booster": "booster",
    "helper":  "helper",
    "members": "member",
    "member":  "member",
}
TIER_INFO = {
    "donor":   {"label": "Donor",   "color": 0xa78bfa, "mb": 1024, "emoji": "💜", "code": "D"},
    "booster": {"label": "Booster", "color": 0xfbbf24, "mb": 750,  "emoji": "⭐", "code": "B"},
    "helper":  {"label": "Helper",  "color": 0x34d399, "mb": 500,  "emoji": "🟢", "code": "H"},
    "member":  {"label": "Member",  "color": 0x60a5fa, "mb": 150,  "emoji": "🔵", "code": "M"},
    "guest":   {"label": "Guest",   "color": 0x888888, "mb": 25,   "emoji": "⚪", "code": "G"},
}
TIER_PRIORITY = ["donor", "booster", "helper", "member", "guest"]

# ── Database ──────────────────────────────────────────────────────────────────
def init_db():
    os.makedirs(os.path.dirname(DB_PATH) if os.path.dirname(DB_PATH) else ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS keys (
            key          TEXT PRIMARY KEY,
            discord_id   TEXT NOT NULL UNIQUE,
            username     TEXT NOT NULL,
            display_name TEXT NOT NULL,
            avatar_url   TEXT,
            tier         TEXT NOT NULL,
            created_at   TEXT NOT NULL,
            last_seen    TEXT
        )
    """)
    conn.commit()
    conn.close()

def get_db():
    return sqlite3.connect(DB_PATH)

def upsert_key(discord_id, username, display_name, avatar_url, tier, key=None):
    conn = get_db()
    now = datetime.utcnow().isoformat()
    existing = conn.execute(
        "SELECT key, tier FROM keys WHERE discord_id = ?", (discord_id,)
    ).fetchone()
    if existing:
        existing_key, existing_tier = existing
        if existing_tier != tier:
            new_key = key or generate_key(tier)
            conn.execute("""
                UPDATE keys SET key=?, username=?, display_name=?, avatar_url=?, tier=?, last_seen=?
                WHERE discord_id=?
            """, (new_key, username, display_name, avatar_url, tier, now, discord_id))
            conn.commit(); conn.close()
            return new_key, False
        else:
            conn.execute("""
                UPDATE keys SET username=?, display_name=?, avatar_url=?, tier=?, last_seen=?
                WHERE discord_id=?
            """, (username, display_name, avatar_url, tier, now, discord_id))
            conn.commit(); conn.close()
            return existing_key, False
    else:
        new_key = key or generate_key(tier)
        conn.execute("""
            INSERT INTO keys (key, discord_id, username, display_name, avatar_url, tier, created_at)
            VALUES (?,?,?,?,?,?,?)
        """, (new_key, discord_id, username, display_name, avatar_url, tier, now))
        conn.commit(); conn.close()
        return new_key, True

def get_key_info(key):
    conn = get_db()
    row = conn.execute("SELECT * FROM keys WHERE key=?", (key,)).fetchone()
    conn.close()
    if row:
        return dict(zip(["key","discord_id","username","display_name","avatar_url","tier","created_at","last_seen"], row))
    return None

def get_user_key(discord_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM keys WHERE discord_id=?", (discord_id,)).fetchone()
    conn.close()
    if row:
        return dict(zip(["key","discord_id","username","display_name","avatar_url","tier","created_at","last_seen"], row))
    return None

def revoke_key(discord_id):
    conn = get_db()
    affected = conn.execute("DELETE FROM keys WHERE discord_id=?", (discord_id,)).rowcount
    conn.commit(); conn.close()
    return affected > 0

def list_all_keys():
    conn = get_db()
    rows = conn.execute("SELECT * FROM keys ORDER BY tier, created_at").fetchall()
    conn.close()
    return [dict(zip(["key","discord_id","username","display_name","avatar_url","tier","created_at","last_seen"], r)) for r in rows]

# ── Helpers ───────────────────────────────────────────────────────────────────
def generate_key(tier: str):
    code  = TIER_INFO.get(tier, TIER_INFO["guest"])["code"]
    chars = string.ascii_uppercase + string.digits
    segs  = [''.join(secrets.choice(chars) for _ in range(4)) for _ in range(2)]
    return f"ZILEM-{code}-{segs[0]}-{segs[1]}"

def get_user_tier(member: discord.Member) -> str:
    role_names = {r.name.lower() for r in member.roles}
    for tier in TIER_PRIORITY:
        if tier == "guest":
            continue
        if any(slug == tier for role, slug in ROLE_TIER_MAP.items() if role in role_names):
            return tier
    return "guest"

def tier_embed(key_info: dict, is_new: bool) -> discord.Embed:
    tier  = key_info["tier"]
    info  = TIER_INFO.get(tier, TIER_INFO["guest"])
    title = "✨ Key Generated!" if is_new else "🔑 Your Key"
    embed = discord.Embed(title=title, color=info["color"])
    embed.add_field(name="License Key", value=f"```{key_info['key']}```", inline=False)
    embed.add_field(name="Tier",        value=f"{info['emoji']} **{info['label']}**", inline=True)
    mb    = info["mb"]
    limit = f"{mb//1024} GB" if mb >= 1024 else f"{mb} MB"
    embed.add_field(name="File Limit",  value=limit, inline=True)
    embed.add_field(name="Activate at", value="[zilem.netlify.app/](https://zilem.netlify.app/)", inline=False)
    if key_info.get("avatar_url"):
        embed.set_thumbnail(url=key_info["avatar_url"])
    embed.set_footer(text=f"User: {key_info['username']} · ID: {key_info['discord_id']}")
    return embed

# ── Bot setup ─────────────────────────────────────────────────────────────────
intents        = discord.Intents.default()
intents.members = True
bot  = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

@bot.event
async def on_ready():
    init_db()
    guild = discord.Object(id=GUILD_ID)
    tree.copy_global_to(guild=guild)
    await tree.sync(guild=guild)
    print(f"✅ Logged in as {bot.user} | Guild synced: {GUILD_ID}")

# ── /getkey ───────────────────────────────────────────────────────────────────
@tree.command(name="getkey", description="Get your Zilem license key based on your Discord role")
async def getkey(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    member = interaction.guild.get_member(interaction.user.id)
    if not member:
        await interaction.followup.send("❌ Could not find you in this server.", ephemeral=True)
        return
    tier       = get_user_tier(member)
    username   = str(member)
    display    = member.display_name
    avatar     = str(member.display_avatar.url) if member.display_avatar else None
    prior      = get_user_key(str(member.id))
    prior_tier = prior["tier"] if prior else None
    key, is_new = upsert_key(member.id, username, display, avatar, tier)
    key_info   = get_user_key(str(member.id))
    embed      = tier_embed(key_info, is_new)
    if is_new:
        msg = "Your key is ready. Keep it safe!"
    elif prior_tier != tier:
        msg = f"Your role changed — here's your new key for the **{TIER_INFO[tier]['label']}** tier!"
    else:
        msg = "Here's your existing key — already up to date with your current tier!"
    await interaction.followup.send(content=msg, embed=embed, ephemeral=True)

# ── /mykey ────────────────────────────────────────────────────────────────────
@tree.command(name="mykey", description="View your current license key")
async def mykey(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    info = get_user_key(str(interaction.user.id))
    if not info:
        await interaction.followup.send("❌ You don't have a key yet. Use `/getkey` to generate one.", ephemeral=True)
        return
    embed = tier_embed(info, False)
    await interaction.followup.send(embed=embed, ephemeral=True)

# ── /check ────────────────────────────────────────────────────────────────────
@tree.command(name="check", description="Check a TikTok video metadata and stats")
@app_commands.describe(url="TikTok video URL")
async def check(interaction: discord.Interaction, url: str):
    await interaction.response.defer(ephemeral=True)

    if "tiktok.com" not in url:
        await interaction.followup.send("❌ Please provide a valid TikTok URL.", ephemeral=True)
        return

    try:
        d = await scrape_tiktok(url)
    except Exception as e:
        await interaction.followup.send(f"❌ {e}", ephemeral=True)
        return

    if d["account_status"] == "safe":
        status_str = "🟢 Safe *(Active)*"
    elif d["account_status"] == "private":
        status_str = "🔒 Private"
    else:
        status_str = "🔴 Banned"

    verified_mark = " ✓" if d["verified"] else ""

    embed = discord.Embed(
        title=f"🔍 {d['author']}{verified_mark} 😛 [{d['resolution']}{d['fps']}FPS]",
        url=url,
        description=d["hashtags"] or d["title"],
        color=0x1a1a2e,
    )
    embed.add_field(
        name="\u200b",
        value=f"@{d['author']} • 🌐 {d['region']}\n⏱️ Duration: {d['duration']} | 📅 Uploaded: {d['uploaded_at']}",
        inline=False,
    )
    embed.add_field(
        name="⚙️ TECHNICAL METADATA",
        value="\n".join([
            f"• Engine: `{d['engine']}`",
            f"• Web Quality: `{d['web_quality']}`",
            f"• Phone Quality: `{d['phone_quality']}`",
            f"• Framerate: `{d['fps']} FPS`",
            f"• File Size: `{d['file_size_mb']} MB`",
            f"• Account Status: {status_str}",
            f"• Video ID: `{d['video_id']}`",
        ]),
        inline=False,
    )
    embed.add_field(
        name="📊 ENGAGEMENT METRICS",
        value=f"👁️ {d['views']}  ❤️ {d['likes']}  💬 {d['comments']}  ⭐ {d['bookmarks']}  🔁 {d['shares']}  📥 {d['downloads']}",
        inline=False,
    )
    if d.get("thumbnail"):
        embed.set_thumbnail(url=d["thumbnail"])

    await interaction.channel.send(
        f"🔍 **@{interaction.user.name}** just checked a TikTok video using `/check`!"
    )
    await interaction.followup.send(embed=embed, ephemeral=True)

# ── /revokekey (admin) ────────────────────────────────────────────────────────
@tree.command(name="revokekey", description="[Admin] Revoke a user's license key")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(user="The user whose key to revoke")
async def revokekey(interaction: discord.Interaction, user: discord.Member):
    await interaction.response.defer(ephemeral=True)
    ok = revoke_key(str(user.id))
    if ok:
        await interaction.followup.send(f"✅ Revoked key for **{user.display_name}**.", ephemeral=True)
    else:
        await interaction.followup.send(f"⚠️ No key found for **{user.display_name}**.", ephemeral=True)

# ── /listkeys (admin) ─────────────────────────────────────────────────────────
@tree.command(name="listkeys", description="[Admin] List all active license keys")
@app_commands.checks.has_permissions(administrator=True)
async def listkeys(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    all_keys = list_all_keys()
    if not all_keys:
        await interaction.followup.send("No keys in the database yet.", ephemeral=True)
        return
    lines = []
    for k in all_keys[:25]:
        info = TIER_INFO.get(k["tier"], TIER_INFO["guest"])
        lines.append(f"{info['emoji']} `{k['key']}` — **{k['display_name']}** ({k['tier']})")
    embed = discord.Embed(title=f"🗝️ Active Keys ({len(all_keys)})", description="\n".join(lines), color=0x7c3aed)
    await interaction.followup.send(embed=embed, ephemeral=True)

# ── /synckey (admin) ──────────────────────────────────────────────────────────
@tree.command(name="synckey", description="[Admin] Sync all users' tiers with their current roles")
@app_commands.checks.has_permissions(administrator=True)
async def synckey(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    all_keys = list_all_keys()
    updated  = 0
    for k in all_keys:
        member = interaction.guild.get_member(int(k["discord_id"]))
        if member:
            new_tier = get_user_tier(member)
            avatar   = str(member.display_avatar.url) if member.display_avatar else None
            upsert_key(k["discord_id"], str(member), member.display_name, avatar, new_tier)
            updated += 1
    await interaction.followup.send(f"✅ Synced **{updated}** keys with current roles.", ephemeral=True)

# ── Error handler ─────────────────────────────────────────────────────────────
@tree.error
async def on_app_command_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("❌ You need administrator permission.", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ Error: {error}", ephemeral=True)

if __name__ == "__main__":
    bot.run(BOT_TOKEN)
                            
