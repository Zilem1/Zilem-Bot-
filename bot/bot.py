import discord
from discord import app_commands
from discord.ext import commands
import sqlite3
import secrets
import string
import os
import asyncio
from datetime import datetime
from bot.scraper import scrape_tiktok

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
        status_str = "🟢 Active"
    elif d["account_status"] == "private":
        status_str = "🔒 Private"
    else:
        status_str = "🔴 Banned"

    verified_mark = " ✓" if d["verified"] else ""
    quality_tag = f"{d['resolution']} · {d['fps']}FPS" if d['fps'] != "—" else d['resolution']

    embed = discord.Embed(
        title=f"{d['author']}{verified_mark}",
        url=url,
        description=(
            f"```{quality_tag}```\n"
            + (d["hashtags"] if d["hashtags"] else "")
            + (f"\n{d['title']}" if d["title"] and d["title"] != d["hashtags"] else "")
        ).strip(),
        color=0x9D4EDD,
    )

    embed.add_field(name="🌐 Region", value=f"`{d['region']}`", inline=True)
    embed.add_field(name="⏱️ Duration", value=f"`{d['duration']}`", inline=True)
    embed.add_field(name="📅 Uploaded", value=f"`{d['uploaded_at']}`", inline=True)

    embed.add_field(
        name="⚙️ Technical Details",
        value=(
            f"```ansi\n"
            f"Engine        {d['engine']}\n"
            f"Web Quality   {d['web_quality']}\n"
            f"Phone Quality {d['phone_quality']}\n"
            f"Framerate     {d['fps']} FPS\n"
            f"File Size     {d['file_size_mb']} MB\n"
            f"Status        {d['account_status'].upper()}\n"
            f"```"
        ),
        inline=False,
    )

    embed.add_field(
        name="📊 Engagement",
        value=(
            f"👁️ **{d['views']}**   ❤️ **{d['likes']}**   💬 **{d['comments']}**\n"
            f"⭐ **{d['bookmarks']}**   🔁 **{d['shares']}**   📥 **{d['downloads']}**"
        ),
        inline=False,
    )

    embed.add_field(
        name="\u200b",
        value=f"🆔 `{d['video_id']}`  •  {status_str}",
        inline=False,
    )

    if d.get("thumbnail"):
        embed.set_thumbnail(url=d["thumbnail"])

    embed.set_author(name="Zilem Optimizer", icon_url=interaction.client.user.display_avatar.url if interaction.client.user.display_avatar else None)
    embed.set_footer(text=f"Requested by {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url if interaction.user.display_avatar else None)
    embed.timestamp = datetime.utcnow()

    view = discord.ui.View()
    view.add_item(discord.ui.Button(
        label="View on TikTok",
        style=discord.ButtonStyle.link,
        url=url,
        emoji="🔗",
    ))
    if d.get("video_url"):
        view.add_item(discord.ui.Button(
            label="Download Video",
            style=discord.ButtonStyle.link,
            url=d["video_url"],
            emoji="📥",
        ))

    await interaction.channel.send(
        f"🔍 {interaction.user.mention} just checked a TikTok video using `/check`!"
    )
    await interaction.followup.send(embed=embed, view=view, ephemeral=True)

# ── /checkffmpeg (diagnostic) ────────────────────────────────────────────────
@tree.command(name="checkffmpeg", description="[Diagnostic] Check if ffprobe/ffmpeg is installed on this server")
async def checkffmpeg(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    import subprocess
    try:
        result = subprocess.run(
            ["ffprobe", "-version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            first_line = result.stdout.splitlines()[0] if result.stdout else "ffprobe ran but gave no output"
            await interaction.followup.send(f"✅ ffprobe is installed:\n```{first_line}```", ephemeral=True)
        else:
            await interaction.followup.send(
                f"⚠️ ffprobe exists but exited with code {result.returncode}:\n```{result.stderr[:500]}```",
                ephemeral=True,
            )
    except FileNotFoundError:
        await interaction.followup.send(
            "❌ ffprobe NOT found on this system. The `ffmpeg` package is not installed — "
            "check that `\"ffmpeg\"` is listed in `nixPkgs` in `nixpacks.toml`, then redeploy.",
            ephemeral=True,
        )
    except subprocess.TimeoutExpired:
        await interaction.followup.send("⚠️ ffprobe found but timed out responding.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ Unexpected error checking ffprobe: `{e}`", ephemeral=True)

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
    # ── /announcement (admin) ─────────────────────────────────────────────────────
@tree.command(name="announcement", description="Send an announcement embed to a channel")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(
    message = "The announcement text",
    title   = "Embed title (optional)",
    channel = "Channel to send to (defaults to current)",
    ping    = "Who to ping"
)
@app_commands.choices(ping=[
    app_commands.Choice(name="@everyone", value="everyone"),
    app_commands.Choice(name="@here",     value="here"),
    app_commands.Choice(name="None",      value="none"),
])
async def announcement(
    interaction: discord.Interaction,
    message: str,
    title:   str = "📢 Announcement",
    channel: discord.TextChannel = None,
    ping:    str = "none"
):
    await interaction.response.defer(ephemeral=True)
    target = channel or interaction.channel

    embed = discord.Embed(
        title       = title,
        description = message,
        color       = 0x7c3aed
    )
    embed.set_footer(text=f"Announced by {interaction.user.display_name} • Zilem Method")
    embed.timestamp = datetime.utcnow()

    ping_text = f"@{ping}" if ping != "none" else None

    try:
        await target.send(content=ping_text, embed=embed)
        await interaction.followup.send(
            f"✅ Announcement sent to {target.mention}", ephemeral=True
        )
    except discord.Forbidden:
        await interaction.followup.send(
            "❌ I don't have permission to post in that channel.", ephemeral=True
        )
    except Exception as e:
        await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)

# ── Error handler ─────────────────────────────────────────────────────────────
@tree.error
async def on_app_command_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("❌ You need administrator permission.", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ Error: {error}", ephemeral=True)

if __name__ == "__main__":
    bot.run(BOT_TOKEN)
