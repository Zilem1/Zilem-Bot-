"""
scraper.py — TikTok video scraper using tikwm.com (free, no API key needed)
"""
import urllib.request
import urllib.parse
import json
import re
from datetime import datetime


API_URL = "https://www.tikwm.com/api/"


def _post(url: str) -> dict:
    payload = urllib.parse.urlencode({"url": url, "hd": 1}).encode()
    req = urllib.request.Request(
        API_URL,
        data=payload,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.tikwm.com/",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def fmt_num(n):
    if not n and n != 0:
        return "—"
    n = int(n)
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)


def fmt_duration(seconds):
    if not seconds:
        return "—"
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


async def scrape_tiktok(url: str) -> dict:
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _scrape_sync, url)


def _scrape_sync(url: str) -> dict:
    try:
        resp = _post(url)
    except Exception as e:
        raise Exception(f"Could not reach tikwm.com: {e}")

    if resp.get("code") != 0:
        msg = resp.get("msg", "Unknown error")
        raise Exception(f"tikwm.com error: {msg}")

    d = resp.get("data", {})
    if not d:
        raise Exception("No data returned from tikwm.com")

    author = d.get("author", {})

    # Video dimensions
    width  = int(d.get("width")  or 1080)
    height = int(d.get("height") or 1920)
    short_side = min(width, height)  # use short side for resolution (portrait videos)

    if short_side >= 2160:   resolution = "4K"
    elif short_side >= 1440: resolution = "2K"
    elif short_side >= 1080: resolution = "1080P"
    elif short_side >= 720:  resolution = "720P"
    else:                    resolution = "480P"

    quality_lbl   = "4K" if short_side >= 1080 else ("HD" if short_side >= 720 else "SD")
    web_quality   = f"{quality_lbl} • {width}x{height}"
    phone_quality = quality_lbl

    duration = int(d.get("duration") or 0)
    # Use actual FPS from API if available
    fps      = int(d.get("fps") or 0)
    if not fps:
        fps = 60 if d.get("bit_rate", 0) and int(d.get("bit_rate", 0)) > 3_000_000 else 30
    engine   = "HFR" if fps >= 60 else "Standard"

    # File size
    size_bytes = int(d.get("size") or d.get("wm_size") or 0)
    file_size_mb = f"{size_bytes / 1024 / 1024:.1f}" if size_bytes else "—"

    # Upload date
    create_time = d.get("create_time")
    if create_time:
        dt = datetime.utcfromtimestamp(int(create_time))
        uploaded_at = dt.strftime("%b %d, %Y, %I:%M %p")
    else:
        uploaded_at = "—"

    # Account status
    private = bool(author.get("is_private"))
    account_status = "private" if private else "safe"

    # Hashtags
    desc     = d.get("title") or ""
    hashtags = " ".join(re.findall(r"#\w+", desc))
    title    = re.sub(r"#\w+", "", desc).strip() or desc

    return {
        "author":         author.get("unique_id") or author.get("nickname") or "unknown",
        "verified":       bool(author.get("verified")),
        "region":         author.get("region") or d.get("region") or "Unknown",
        "account_status": account_status,
        "thumbnail":      d.get("cover") or d.get("origin_cover"),
        "title":          title,
        "hashtags":       hashtags,
        "video_id":       str(d.get("id") or "—"),
        "uploaded_at":    uploaded_at,
        "duration":       fmt_duration(duration),
        "resolution":     resolution,
        "fps":            fps,
        "web_quality":    web_quality,
        "phone_quality":  phone_quality,
        "engine":         engine,
        "file_size_mb":   file_size_mb,
        "views":          fmt_num(d.get("play_count")    or d.get("plays")     or 0),
        "likes":          fmt_num(d.get("digg_count")    or d.get("likes")     or 0),
        "comments":       fmt_num(d.get("comment_count") or d.get("comments")  or 0),
        "shares":         fmt_num(d.get("share_count")   or d.get("shares")    or 0),
        "bookmarks":      fmt_num(d.get("collect_count") or d.get("bookmarks") or 0),
        "downloads":      fmt_num(d.get("download_count") or 0),
    }
    
