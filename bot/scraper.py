"""
scraper.py — TikTok scraper using tikwm.com
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


def get_resolution(width, height):
    """
    Use the smaller dimension as the resolution class.
    Portrait  1080x1920 → smaller = 1080 → 1080P ✅
    Landscape 1920x1080 → smaller = 1080 → 1080P ✅
    Portrait   720x1280 → smaller =  720 →  720P ✅
    Portrait  1440x2560 → smaller = 1440 →   2K ✅
    Portrait  2160x3840 → smaller = 2160 →   4K ✅
    """
    p = min(width, height)   # pixel count of shorter axis

    if p >= 2160:   return "4K"
    elif p >= 1440: return "2K"
    elif p >= 1080: return "1080P"
    elif p >= 720:  return "720P"
    elif p >= 480:  return "480P"
    else:           return "360P"


def get_fps_and_engine(size_bytes, duration):
    if size_bytes and duration:
        bitrate = (size_bytes * 8) / duration  # bps
    else:
        bitrate = 0

    if bitrate >= 15_000_000:
        return 120, "Zilem Optimized"
    elif bitrate >= 8_000_000:
        return 60, "Zilem Optimized"
    else:
        return 30, "Standard"


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
        raise Exception(f"tikwm error: {resp.get('msg', 'Unknown error')}")

    d = resp.get("data", {})
    if not d:
        raise Exception("No data returned")

    author     = d.get("author", {})
    width      = int(d.get("width")  or 0)
    height     = int(d.get("height") or 0)
    duration   = int(d.get("duration") or 0)
    size_bytes = int(d.get("size") or 0)

    resolution            = get_resolution(width, height) if width and height else "Unknown"
    fps, engine           = get_fps_and_engine(size_bytes, duration)
    web_quality           = f"{resolution} • {width}x{height}"
    phone_quality         = resolution
    file_size_mb          = f"{size_bytes / 1024 / 1024:.1f}" if size_bytes else "—"

    create_time = d.get("create_time")
    if create_time:
        dt = datetime.utcfromtimestamp(int(create_time))
        uploaded_at = dt.strftime("%b %d, %Y, %I:%M %p")
    else:
        uploaded_at = "—"

    private        = bool(author.get("is_private") or author.get("privateAccount"))
    account_status = "private" if private else "safe"

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
        "views":          fmt_num(d.get("play_count")    or 0),
        "likes":          fmt_num(d.get("digg_count")    or 0),
        "comments":       fmt_num(d.get("comment_count") or 0),
        "shares":         fmt_num(d.get("share_count")   or 0),
        "bookmarks":      fmt_num(d.get("collect_count") or 0),
        "downloads":      fmt_num(d.get("download_count") or 0),
    }
    
