"""
scraper.py — TikTok video scraper (no API key needed)
Fetches real data directly from TikTok page HTML.
"""
import urllib.request
import urllib.parse
import urllib.error
import json
import re
import gzip
import zlib
import random
from datetime import datetime

# ── User agents ───────────────────────────────────────────────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]

def _random_ua():
    return random.choice(USER_AGENTS)

def _build_headers():
    return {
        "User-Agent": _random_ua(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
    }

# ── HTTP fetch with redirect + decompression ──────────────────────────────────
def _fetch(url, redirect_count=0):
    if redirect_count > 5:
        raise Exception("Too many redirects")

    req = urllib.request.Request(url, headers=_build_headers())

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
            final_url = resp.url
            encoding = resp.headers.get("Content-Encoding", "")

            # Decompress
            if encoding == "gzip":
                body = gzip.decompress(raw).decode("utf-8", errors="replace")
            elif encoding == "br":
                try:
                    import brotli
                    body = brotli.decompress(raw).decode("utf-8", errors="replace")
                except ImportError:
                    body = raw.decode("utf-8", errors="replace")
            elif encoding == "deflate":
                try:
                    body = zlib.decompress(raw).decode("utf-8", errors="replace")
                except Exception:
                    body = zlib.decompress(raw, -zlib.MAX_WBITS).decode("utf-8", errors="replace")
            else:
                body = raw.decode("utf-8", errors="replace")

            return body, final_url

    except urllib.error.HTTPError as e:
        raise Exception(f"HTTP {e.code}: {e.reason}")

# ── Extract data from TikTok HTML ─────────────────────────────────────────────
def _extract_data(html):
    # Method 1: __UNIVERSAL_DATA_FOR_REHYDRATION__ (current TikTok)
    m = re.search(r'<script[^>]*id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(1))
            item = (data
                    .get("__DEFAULT_SCOPE__", {})
                    .get("webapp.video-detail", {})
                    .get("itemInfo", {})
                    .get("itemStruct"))
            if item:
                return _parse_item(item)
        except Exception:
            pass

    # Method 2: __NEXT_DATA__
    m = re.search(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(1))
            item = (data
                    .get("props", {})
                    .get("pageProps", {})
                    .get("itemInfo", {})
                    .get("itemStruct"))
            if item:
                return _parse_item(item)
        except Exception:
            pass

    # Method 3: Bare stats regex fallback
    m = re.search(r'"playCount":(\d+).*?"diggCount":(\d+).*?"commentCount":(\d+).*?"shareCount":(\d+)', html, re.DOTALL)
    if m:
        return {
            "views": int(m.group(1)), "likes": int(m.group(2)),
            "comments": int(m.group(3)), "shares": int(m.group(4)),
            "bookmarks": 0, "downloads": 0, "partial": True,
            "username": "unknown", "region": "Unknown",
            "verified": False, "account_status": "safe",
            "thumbnail": None, "title": "", "hashtags": "",
            "video_id": "", "uploaded_at": "—", "duration": 0,
            "resolution": "1080P", "fps": 60, "file_size_mb": "—",
            "web_quality": "4K • 1080x1920", "phone_quality": "4K",
            "engine": "HFR",
        }

    return None

def _parse_item(item):
    stats  = item.get("stats") or item.get("statsV2") or {}
    video  = item.get("video") or {}
    author = item.get("author") or {}

    # Stats
    views     = int(stats.get("playCount")    or stats.get("vvCount")      or 0)
    likes     = int(stats.get("diggCount")    or 0)
    comments  = int(stats.get("commentCount") or 0)
    shares    = int(stats.get("shareCount")   or 0)
    bookmarks = int(stats.get("collectCount") or stats.get("bookmarkCount") or 0)
    downloads = int(stats.get("downloadCount") or 0)

    # Video
    duration  = int(video.get("duration") or 0)
    width     = int(video.get("width")    or 1080)
    height    = int(video.get("height")   or 1920)
    bitrate   = int(video.get("bitrate")  or 0)
    fps       = int(video.get("fps")      or 0) or (60 if bitrate > 3_000_000 else 30)
    thumbnail = video.get("cover") or video.get("originCover")

    # Resolution
    long_side = max(width, height)
    if long_side >= 2160:   resolution = "4K"
    elif long_side >= 1440: resolution = "2K"
    elif long_side >= 1080: resolution = "1080P"
    elif long_side >= 720:  resolution = "720P"
    else:                   resolution = "480P"

    quality_lbl  = "4K" if long_side >= 1080 else ("HD" if long_side >= 720 else "SD")
    web_quality  = f"{quality_lbl} • {width}x{height}"
    phone_quality = quality_lbl
    engine        = "HFR" if fps >= 60 else "Standard"

    # File size estimate (bitrate bps × duration s → bytes → MB)
    if bitrate and duration:
        file_size_mb = f"{(bitrate * duration / 8 / 1024 / 1024):.1f}"
    else:
        file_size_mb = "—"

    # Author
    username   = author.get("uniqueId") or author.get("username") or "unknown"
    verified   = bool(author.get("verified"))
    region     = author.get("region") or item.get("locationCreated") or "Unknown"
    private    = bool(author.get("privateAccount"))
    banned     = bool(author.get("secret"))
    account_status = "banned" if banned else ("private" if private else "safe")

    # Upload date
    create_time = item.get("createTime")
    if create_time:
        dt = datetime.utcfromtimestamp(int(create_time))
        uploaded_at = dt.strftime("%b %-d, %Y, %I:%M %p")
    else:
        uploaded_at = "—"

    # Description / hashtags
    desc     = item.get("desc") or ""
    hashtags = " ".join(re.findall(r"#\w+", desc))
    title    = re.sub(r"#\w+", "", desc).strip() or desc

    video_id = item.get("id") or ""

    return {
        "views": views, "likes": likes, "comments": comments,
        "shares": shares, "bookmarks": bookmarks, "downloads": downloads,
        "username": username, "verified": verified, "region": region,
        "account_status": account_status, "thumbnail": thumbnail,
        "title": title, "hashtags": hashtags, "video_id": video_id,
        "uploaded_at": uploaded_at, "duration": duration,
        "resolution": resolution, "fps": fps, "file_size_mb": file_size_mb,
        "web_quality": web_quality, "phone_quality": phone_quality,
        "engine": engine,
    }

# ── Number formatter ──────────────────────────────────────────────────────────
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

# ── Main entry point ──────────────────────────────────────────────────────────
async def scrape_tiktok(url: str) -> dict:
    """
    Call this from your bot. Returns a dict with all video info.
    Raises Exception with a human-readable message on failure.
    """
    import asyncio

    # Run blocking HTTP in thread so bot doesn't freeze
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _scrape_sync, url)
    return result

def _scrape_sync(url: str) -> dict:
    # Resolve short URLs
    final_url = url
    if any(x in url for x in ["vm.tiktok", "vt.tiktok", "/t/"]):
        try:
            _, final_url = _fetch(url)
        except Exception as e:
            raise Exception(f"Could not resolve short URL: {e}")

    # Fetch page
    try:
        html, final_url = _fetch(final_url)
    except Exception as e:
        raise Exception(f"Could not fetch TikTok page: {e}")

    # Check if blocked
    if "verifyChallenge" in html or "tiktok.com/login" in html or len(html) < 5000:
        raise Exception("TikTok blocked the request — please try again in a moment")

    # Extract
    data = _extract_data(html)
    if not data:
        raise Exception("Could not extract video data — TikTok may have changed their page structure")

    # Fill video ID / username from URL if missing
    if not data.get("video_id"):
        m = re.search(r"/video/(\d+)", final_url)
        data["video_id"] = m.group(1) if m else "—"

    if not data.get("username") or data["username"] == "unknown":
        m = re.search(r"@([\w.]+)/", final_url)
        if m:
            data["username"] = m.group(1)

    # Return formatted version
    return {
        "author":         data["username"],
        "verified":       data["verified"],
        "region":         data.get("region") or "Unknown",
        "account_status": data["account_status"],
        "thumbnail":      data.get("thumbnail"),
        "title":          data.get("title", ""),
        "hashtags":       data.get("hashtags", ""),
        "video_id":       data["video_id"],
        "uploaded_at":    data.get("uploaded_at", "—"),
        "duration":       fmt_duration(data.get("duration")),
        "resolution":     data["resolution"],
        "fps":            data["fps"],
        "web_quality":    data["web_quality"],
        "phone_quality":  data["phone_quality"],
        "engine":         data["engine"],
        "file_size_mb":   data.get("file_size_mb", "—"),
        # Formatted stats
        "views":          fmt_num(data["views"]),
        "likes":          fmt_num(data["likes"]),
        "comments":       fmt_num(data["comments"]),
        "shares":         fmt_num(data["shares"]),
        "bookmarks":      fmt_num(data["bookmarks"]),
        "downloads":      fmt_num(data["downloads"]),
    }
