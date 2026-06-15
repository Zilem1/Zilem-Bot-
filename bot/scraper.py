"""
scraper.py — TikTok scraper using yt-dlp for accurate metadata
"""
import re
import asyncio
from datetime import datetime


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
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _scrape_sync, url)


def _scrape_sync(url: str) -> dict:
    try:
        import yt_dlp
    except ImportError:
        raise Exception("yt-dlp is not installed")

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extractor_args": {"tiktok": {"webpage_download": True}},
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
        except Exception as e:
            raise Exception(f"yt-dlp could not fetch video: {e}")

    if not info:
        raise Exception("No data returned from yt-dlp")

    # --- FPS & resolution from best format ---
    fps        = 0
    width      = 0
    height     = 0
    file_size  = 0

    formats = info.get("formats") or []
    # pick best video format (highest tbr)
    best = None
    for f in formats:
        if f.get("vcodec") and f["vcodec"] != "none":
            if best is None or (f.get("tbr") or 0) > (best.get("tbr") or 0):
                best = f

    if best:
        fps       = int(best.get("fps") or 0)
        width     = int(best.get("width") or 0)
        height    = int(best.get("height") or 0)
        file_size = int(best.get("filesize") or best.get("filesize_approx") or 0)

    # fallback to top-level
    if not fps:    fps    = int(info.get("fps") or 30)
    if not width:  width  = int(info.get("width") or 1080)
    if not height: height = int(info.get("height") or 1920)

    short_side = min(width, height)
    if short_side >= 2160:
        resolution = "4K";    quality_lbl = "4K"
    elif short_side >= 1440:
        resolution = "2K";    quality_lbl = "2K"
    elif short_side >= 1080:
        resolution = "1080P"; quality_lbl = "1080P"
    elif short_side >= 720:
        resolution = "720P";  quality_lbl = "HD"
    else:
        resolution = "480P";  quality_lbl = "SD"
    web_quality   = f"{quality_lbl} • {width}x{height}"
    phone_quality = quality_lbl
    engine        = "HFR" if fps >= 60 else "Standard"

    file_size_mb = f"{file_size / 1024 / 1024:.1f}" if file_size else "—"

    # --- Author ---
    uploader    = info.get("uploader_id") or info.get("uploader") or "unknown"
    if uploader.startswith("@"):
        uploader = uploader[1:]
    verified    = bool(info.get("channel_is_verified"))
    region      = info.get("region") or "Unknown"

    # --- Upload date ---
    upload_date = info.get("upload_date")  # YYYYMMDD
    if upload_date:
        dt = datetime.strptime(upload_date, "%Y%m%d")
        uploaded_at = dt.strftime("%b %d, %Y")
    else:
        uploaded_at = "—"

    # --- Stats ---
    views     = info.get("view_count")    or 0
    likes     = info.get("like_count")    or 0
    comments  = info.get("comment_count") or 0
    shares    = info.get("repost_count")  or 0
    bookmarks = info.get("bookmark_count") or 0

    # --- Description / hashtags ---
    desc     = info.get("description") or info.get("title") or ""
    hashtags = " ".join(re.findall(r"#\w+", desc))
    title    = re.sub(r"#\w+", "", desc).strip() or desc

    # --- Account status ---
    account_status = "safe"

    return {
        "author":         uploader,
        "verified":       verified,
        "region":         region,
        "account_status": account_status,
        "thumbnail":      info.get("thumbnail"),
        "title":          title,
        "hashtags":       hashtags,
        "video_id":       str(info.get("id") or "—"),
        "uploaded_at":    uploaded_at,
        "duration":       fmt_duration(info.get("duration")),
        "resolution":     resolution,
        "fps":            fps,
        "web_quality":    web_quality,
        "phone_quality":  phone_quality,
        "engine":         engine,
        "file_size_mb":   file_size_mb,
        "views":          fmt_num(views),
        "likes":          fmt_num(likes),
        "comments":       fmt_num(comments),
        "shares":         fmt_num(shares),
        "bookmarks":      fmt_num(bookmarks),
        "downloads":      "—",
    }
    
