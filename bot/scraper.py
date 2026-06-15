"""
scraper.py — TikTok scraper using tikwm.com
FPS is parsed from actual video file header (MP4 box parsing)
"""
import urllib.request
import urllib.parse
import json
import re
import struct
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
    p = min(width, height)
    if p >= 2160:   return "4K"
    elif p >= 1440: return "2K"
    elif p >= 1080: return "1080P"
    elif p >= 720:  return "720P"
    elif p >= 480:  return "480P"
    else:           return "360P"


def fetch_fps_from_video(video_url: str) -> int:
    """
    Download first 2MB of the MP4 and scan for the 'mvhd' or 'mdhd' box
    which contains the real timescale/duration to compute FPS,
    or find 'vmhd'/'stts' for frame count.
    We look for the tkhd/mdhd timescale approach.
    """
    try:
        req = urllib.request.Request(
            video_url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Range": "bytes=0-2097151",  # first 2MB
            }
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = resp.read()

        # Search for 'mdhd' box — contains timescale and duration for each track
        # mdhd structure: size(4) + 'mdhd'(4) + version(1) + flags(3) +
        #   if version==0: creation(4)+modification(4)+timescale(4)+duration(4)
        #   if version==1: creation(8)+modification(8)+timescale(4)+duration(8)
        fps_candidates = []
        i = 0
        while i < len(data) - 8:
            box_name = data[i+4:i+8]
            if box_name == b'mdhd':
                try:
                    version = data[i+8]
                    if version == 0:
                        timescale = struct.unpack('>I', data[i+20:i+24])[0]
                        duration  = struct.unpack('>I', data[i+24:i+28])[0]
                    else:
                        timescale = struct.unpack('>I', data[i+28:i+32])[0]
                        duration  = struct.unpack('>Q', data[i+32:i+40])[0]

                    if timescale and duration:
                        # timescale is ticks per second, duration is total ticks
                        # This gives us seconds, not FPS directly
                        # But video track mdhd timescale is often set to FPS * N
                        # We collect it and analyze
                        fps_candidates.append(timescale)
                except Exception:
                    pass
            i += 1

        # Also search for 'stts' (sample-to-time) box — most accurate
        # stts: size(4) + 'stts'(4) + version(1) + flags(3) +
        #       entry_count(4) + [sample_count(4) + sample_delta(4)] * entry_count
        # fps = timescale / sample_delta  (need mdhd timescale of video track)
        stts_fps = []
        i = 0
        while i < len(data) - 8:
            box_name = data[i+4:i+8]
            if box_name == b'stts':
                try:
                    entry_count = struct.unpack('>I', data[i+12:i+16])[0]
                    if entry_count > 0 and entry_count < 1000:
                        sample_delta = struct.unpack('>I', data[i+20:i+24])[0]
                        if sample_delta and sample_delta < 10000:
                            # fps = timescale / sample_delta
                            # Common: timescale=90000, delta=750 → 120fps
                            #         timescale=90000, delta=1500 → 60fps
                            #         timescale=90000, delta=3000 → 30fps
                            #         timescale=12800, delta=512  → 25fps
                            for ts in fps_candidates:
                                candidate = round(ts / sample_delta)
                                if 1 <= candidate <= 240:
                                    stts_fps.append(candidate)
                except Exception:
                    pass
            i += 1

        if stts_fps:
            return max(set(stts_fps), key=stts_fps.count)

        # Fallback: common timescales map
        for ts in fps_candidates:
            if ts in (12800, 90000, 180000):
                # can't determine without stts, return 0
                pass

        return 0

    except Exception:
        return 0


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

    # Resolution
    if width and height:
        resolution    = get_resolution(width, height)
        web_quality   = f"{resolution} • {width}x{height}"
        phone_quality = resolution
    else:
        resolution    = "—"
        web_quality   = "—"
        phone_quality = "—"

    # Get real FPS from video file
    video_url = d.get("hdplay") or d.get("play") or ""
    fps = 0
    if video_url:
        fps = fetch_fps_from_video(video_url)

    if fps:
        engine = "Zilem Optimized" if fps >= 60 else "Standard"
        fps_display = fps
    else:
        engine      = "—"
        fps_display = "—"

    file_size_mb = f"{size_bytes / 1024 / 1024:.1f}" if size_bytes else "—"

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
        "fps":            fps_display,
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
    
