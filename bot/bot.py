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
    "admins":     "helper",
    "zilem":      "helper",
    "wick":       "helper",
    "donor":      "donor",
    "booster":    "booster",
    "helper":     "helper",
    "first 100":  "first100",
    "first100":   "first100",
    "members":    "member",
    "member":     "member",
    "tickety":    "guest",
}
# mb        = file size limit in MB
# max_res   = label shown in embeds
# max_fps   = FPS cap
# patches   = weekly patch limit (None = unlimited)
TIER_INFO = {
    "donor":    {"label": "Donor",     "color": 0xa78bfa, "mb": 1024, "emoji": "💎", "code": "D", "max_res": "4K",    "max_fps": None,  "patches": None},
    "first100": {"label": "First 100", "color": 0xe879f9, "mb": 500,  "emoji": "🏅", "code": "F", "max_res": "4K",    "max_fps": None,  "patches": 5},
    "booster":  {"label": "Booster",   "color": 0xfbbf24, "mb": 750,  "emoji": "🚀", "code": "B", "max_res": "4K",    "max_fps": 120,   "patches": 7},
    "helper":   {"label": "Helper",    "color": 0x34d399, "mb": 500,  "emoji": "🛠️", "code": "H", "max_res": "1440p", "max_fps": None,  "patches": None},
    "member":   {"label": "Member",    "color": 0x60a5fa, "mb": 150,  "emoji": "👥", "code": "M", "max_res": "1080p", "max_fps": 60,    "patches": 5},
    "guest":    {"label": "Guest",     "color": 0x888888, "mb": 25,   "emoji": "👤", "code": "G", "max_res": "1080p", "max_fps": 60,    "patches": None},
}
TIER_PRIORITY = ["donor", "first100", "booster", "helper", "member", "guest"]

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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS usage (
            discord_id   TEXT PRIMARY KEY,
            week_start   TEXT NOT NULL,
            patch_count  INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()

def get_week_start() -> str:
    from datetime import timedelta
    today = datetime.utcnow().date()
    monday = today - timedelta(days=today.weekday())
    return monday.isoformat()

def get_usage(discord_id: str) -> int:
    conn = get_db()
    week = get_week_start()
    row = conn.execute("SELECT week_start, patch_count FROM usage WHERE discord_id=?", (str(discord_id),)).fetchone()
    conn.close()
    if not row or row[0] != week:
        return 0
    return row[1]

def increment_usage(discord_id: str) -> int:
    conn = get_db()
    week = get_week_start()
    row = conn.execute("SELECT week_start, patch_count FROM usage WHERE discord_id=?", (str(discord_id),)).fetchone()
    if not row or row[0] != week:
        conn.execute("INSERT OR REPLACE INTO usage (discord_id, week_start, patch_count) VALUES (?,?,1)", (str(discord_id), week))
        count = 1
    else:
        count = row[1] + 1
        conn.execute("UPDATE usage SET patch_count=? WHERE discord_id=?", (count, str(discord_id)))
    conn.commit()
    conn.close()
    return count

def reset_usage(discord_id: str):
    conn = get_db()
    week = get_week_start()
    conn.execute("INSERT OR REPLACE INTO usage (discord_id, week_start, patch_count) VALUES (?,?,0)", (str(discord_id), week))
    conn.commit()
    conn.close()

def reset_all_usage():
    conn = get_db()
    week = get_week_start()
    conn.execute("UPDATE usage SET week_start=?, patch_count=0", (week,))
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
    res   = info.get("max_res", "1080p")
    fps   = f"{info['max_fps']} FPS" if info.get("max_fps") else "Unlimited FPS"
    embed.add_field(name="Max Quality", value=f"{res} · {fps}", inline=True)
    patches = info.get("patches")
    patch_str = f"{patches}/week" if patches else "Unlimited"
    embed.add_field(name="Weekly Patches", value=patch_str, inline=True)
    embed.add_field(name="Activate at", value="[zilem.netlify.app/](https://zilem.netlify.app/)", inline=False)
    if key_info.get("avatar_url"):
        embed.set_thumbnail(url=key_info["avatar_url"])
    embed.set_footer(text=f"User: {key_info['username']} · ID: {key_info['discord_id']}")
    return embed

# ── Bot setup ─────────────────────────────────────────────────────────────────
intents         = discord.Intents.default()
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
    tier = get_user_tier(member)
    if tier == "guest":
        await interaction.followup.send(
            "❌ You don't have a role that qualifies for a key. "
            "Get Member, Booster, or Donor to unlock the patcher.",
            ephemeral=True
        )
        return
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

    embed.add_field(name="🌐 Region",   value=f"`{d['region']}`",      inline=True)
    embed.add_field(name="⏱️ Duration", value=f"`{d['duration']}`",    inline=True)
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

    embed.set_author(
        name="Zilem Optimizer",
        icon_url=interaction.client.user.display_avatar.url if interaction.client.user.display_avatar else None
    )
    embed.set_footer(
        text=f"Requested by {interaction.user.display_name}",
        icon_url=interaction.user.display_avatar.url if interaction.user.display_avatar else None
    )
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

# ── /checkffmpeg (diagnostic) ─────────────────────────────────────────────────
@tree.command(name="checkffmpeg", description="[Diagnostic] Check if ffprobe/ffmpeg is installed on this server")
async def checkffmpeg(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    import subprocess
    try:
        result = subprocess.run(
            ["ffprobe", "-version"],
            capture_output=True, text=True, timeout=5,
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

# ── /announcement (admin) ─────────────────────────────────────────────────────
#
#  Supports TWO modes:
#
#  1. SIMPLE  — just title + message, quick one-liner announcement
#  2. RICH    — multi-section formatted announcement like the screenshot:
#               use \n in message to separate paragraphs
#               use [SECTION: Title] to start a new bold section header
#               use [ITEM: 01 | Label] to add a numbered item header
#               use [DIVIDER] to add a --- line
#               use [BUTTON: Label | URL] to add a link button at the bottom
#
#  Example rich message (paste into Discord slash command):
#  🔥 The engine just got better!\n[DIVIDER]\n[SECTION: ✨ NEW FEATURES]\n[ITEM: 01 | Native Video Preview]\nYou can now preview videos instantly.\n[DIVIDER]\n[BUTTON: Go to Tickets | https://discord.com/channels/...]
#
# ─────────────────────────────────────────────────────────────────────────────

def parse_announcement(raw: str):
    """
    Parses the raw message string into a structured list of blocks.
    Returns (embed_description, buttons)
    """
    import re
    lines   = raw.replace("\\n", "\n").split("\n")
    parts   = []
    buttons = []

    for line in lines:
        line = line.strip()
        if not line:
            parts.append("")
            continue

        # [DIVIDER] → horizontal rule
        if line.upper() == "[DIVIDER]":
            parts.append("─" * 35)
            continue

        # [SECTION: Title] → bold large header
        m = re.match(r"\[SECTION:\s*(.+?)\]", line, re.IGNORECASE)
        if m:
            parts.append(f"\n**{m.group(1).strip()}**")
            continue

        # [ITEM: 01 | Label] → numbered item header
        m = re.match(r"\[ITEM:\s*(.+?)\]", line, re.IGNORECASE)
        if m:
            parts.append(f"\n**{m.group(1).strip()}**")
            continue

        # [BUTTON: Label | URL] → link button (collected separately)
        m = re.match(r"\[BUTTON:\s*(.+?)\s*\|\s*(.+?)\]", line, re.IGNORECASE)
        if m:
            buttons.append((m.group(1).strip(), m.group(2).strip()))
            continue

        # Plain text
        parts.append(line)

    description = "\n".join(parts).strip()
    return description, buttons


@tree.command(name="announcement", description="[Admin] Send a rich formatted announcement")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(
    message = "Announcement text. Use \\n for newlines, [SECTION:], [ITEM:], [DIVIDER], [BUTTON: Label | URL]",
    title   = "Main title shown at top of embed",
    channel = "Channel to post in (defaults to current)",
    ping    = "Who to ping",
    color   = "Embed accent color",
    image   = "Banner image URL (shown at bottom of embed)",
    thumbnail = "Small icon image URL (top right of embed)",
    footer  = "Custom footer text (defaults to your name)",
)
@app_commands.choices(
    ping=[
        app_commands.Choice(name="@everyone", value="everyone"),
        app_commands.Choice(name="@here",     value="here"),
        app_commands.Choice(name="None",      value="none"),
    ],
    color=[
        app_commands.Choice(name="Purple (default)", value="purple"),
        app_commands.Choice(name="Green",            value="green"),
        app_commands.Choice(name="Blue",             value="blue"),
        app_commands.Choice(name="Gold",             value="gold"),
        app_commands.Choice(name="Red",              value="red"),
        app_commands.Choice(name="White",            value="white"),
    ],
)
async def announcement(
    interaction : discord.Interaction,
    message     : str,
    title       : str                 = "📢 Announcement",
    channel     : discord.TextChannel = None,
    ping        : str                 = "none",
    color       : str                 = "purple",
    image       : str                 = None,
    thumbnail   : str                 = None,
    footer      : str                 = None,
):
    await interaction.response.defer(ephemeral=True)

    target = channel or interaction.channel

    color_map = {
        "purple": 0x7c3aed,
        "green":  0x34d399,
        "blue":   0x60a5fa,
        "gold":   0xfbbf24,
        "red":    0xf87171,
        "white":  0xeeeeee,
    }
    embed_color = color_map.get(color, 0x7c3aed)

    # Parse rich formatting
    description, buttons = parse_announcement(message)

    embed = discord.Embed(
        title       = title,
        description = description,
        color       = embed_color,
    )

    footer_text = footer or f"Zilem Method  •  {interaction.user.display_name}"
    embed.set_footer(
        text     = footer_text,
        icon_url = interaction.user.display_avatar.url if interaction.user.display_avatar else None,
    )
    embed.timestamp = datetime.utcnow()

    if image:
        embed.set_image(url=image)

    if thumbnail:
        embed.set_thumbnail(url=thumbnail)

    # Build view with any [BUTTON:] tags
    view = None
    if buttons:
        view = discord.ui.View()
        for label, url in buttons[:5]:   # Discord max 5 buttons per row
            view.add_item(discord.ui.Button(
                label = label,
                url   = url,
                style = discord.ButtonStyle.link,
            ))

    ping_text = f"@{ping}" if ping != "none" else None

    try:
        await target.send(content=ping_text, embed=embed, view=view)
        await interaction.followup.send(
            f"✅ Announcement sent to {target.mention}", ephemeral=True
        )
    except discord.Forbidden:
        await interaction.followup.send(
            "❌ I don't have permission to post in that channel.", ephemeral=True
        )
    except Exception as e:
        await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)


@tree.command(name="announce_help", description="[Admin] Show how to format rich announcements")
@app_commands.checks.has_permissions(administrator=True)
async def announce_help(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    embed = discord.Embed(
        title       = "📋 Announcement Formatting Guide",
        description = (
            "Use these tags inside your `/announcement message:` to build rich posts.\n"
            "Separate lines with **\\n** (backslash n).\n"
        ),
        color = 0x7c3aed,
    )
    embed.add_field(
        name  = "Tags",
        value = (
            "`[SECTION: Title]` → Bold section header\n"
            "`[ITEM: 01 | Label]` → Numbered item header\n"
            "`[DIVIDER]` → Horizontal line ─────\n"
            "`[BUTTON: Label | URL]` → Link button below embed\n"
            "`\\n` → New line\n"
        ),
        inline=False,
    )
    embed.add_field(
        name  = "Example message",
        value = (
            "```"
            "🔥 Big update is here!\\n"
            "[DIVIDER]\\n"
            "[SECTION: ✨ What's New]\\n"
            "[ITEM: 01 | Faster Patching]\\n"
            "We rewrote the core engine.\\n"
            "[DIVIDER]\\n"
            "[SECTION: II. How to Update]\\n"
            "[ITEM: 02 | Re-download]\\n"
            "Just refresh the site.\\n"
            "[BUTTON: Open Site | https://zilem.netlify.app]"
            "```"
        ),
        inline=False,
    )
    embed.set_footer(text="Only admins can use /announcement")
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
    embed = discord.Embed(
        title       = f"🗝️ Active Keys ({len(all_keys)})",
        description = "\n".join(lines),
        color       = 0x7c3aed,
    )
    await interaction.followup.send(embed=embed, ephemeral=True)

# ── /synckey (admin) ──────────────────────────────────────────────────────────
@tree.command(name="synckey", description="[Admin] Sync all users' tiers with their current roles")
@app_commands.checks.has_permissions(administrator=True)
async def synckey(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    all_keys = list_all_keys()
    updated  = 0
    revoked  = 0
    for k in all_keys:
        member = interaction.guild.get_member(int(k["discord_id"]))
        if not member:
            # User left the server — revoke their key entirely
            revoke_key(k["discord_id"])
            revoked += 1
            continue
        new_tier = get_user_tier(member)
        if new_tier == "guest":
            # Lost their qualifying role — key is revoked, not downgraded
            revoke_key(k["discord_id"])
            revoked += 1
            continue
        avatar = str(member.display_avatar.url) if member.display_avatar else None
        upsert_key(k["discord_id"], str(member), member.display_name, avatar, new_tier)
        updated += 1
    await interaction.followup.send(
        f"✅ Synced **{updated}** keys with current roles. Revoked **{revoked}** (no qualifying role).",
        ephemeral=True
    )

# ── Error handler ─────────────────────────────────────────────────────────────
@tree.error
async def on_app_command_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        try:
            await interaction.response.send_message("❌ You need administrator permission.", ephemeral=True)
        except discord.InteractionResponded:
            await interaction.followup.send("❌ You need administrator permission.", ephemeral=True)
    else:
        try:
            await interaction.response.send_message(f"❌ Error: {error}", ephemeral=True)
        except discord.InteractionResponded:
            await interaction.followup.send(f"❌ Error: {error}", ephemeral=True)

if __name__ == "__main__":
    bot.run(BOT_TOKEN)

# ── /myusage ──────────────────────────────────────────────────────────────────
@tree.command(name="myusage", description="Check how many patches you've used this week")
async def myusage(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    info = get_user_key(str(interaction.user.id))
    if not info:
        await interaction.followup.send("❌ You don't have a key yet. Use `/getkey` to generate one.", ephemeral=True)
        return
    tier     = info["tier"]
    tier_inf = TIER_INFO.get(tier, TIER_INFO["guest"])
    used     = get_usage(str(interaction.user.id))
    limit    = tier_inf.get("patches")
    limit_str = str(limit) if limit else "∞"

    from datetime import timedelta, date
    today   = datetime.utcnow().date()
    monday  = today - timedelta(days=today.weekday())
    next_monday = monday + timedelta(days=7)
    days_left = (next_monday - today).days

    embed = discord.Embed(title="📊 Your Weekly Usage", color=tier_inf["color"])
    embed.add_field(name="Tier",         value=f"{tier_inf['emoji']} {tier_inf['label']}", inline=True)
    embed.add_field(name="Patches Used", value=f"{used} / {limit_str}", inline=True)
    embed.add_field(name="Resets In",    value=f"{days_left} day(s)", inline=True)
    embed.set_footer(text=f"Week resets every Monday · {interaction.user.display_name}")
    await interaction.followup.send(embed=embed, ephemeral=True)


# ── /resetusage (admin) ───────────────────────────────────────────────────────
@tree.command(name="resetusage", description="[Admin] Reset weekly patch usage — one user or everyone")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(
    user="The user to reset (leave blank to reset ALL users)",
)
async def resetusage(interaction: discord.Interaction, user: discord.Member = None):
    await interaction.response.defer(ephemeral=True)
    if user:
        reset_usage(str(user.id))
        await interaction.followup.send(f"✅ Reset weekly usage for **{user.display_name}** back to 0.", ephemeral=True)
    else:
        reset_all_usage()
        await interaction.followup.send("✅ Reset weekly patch usage for **all users** back to 0.", ephemeral=True)
