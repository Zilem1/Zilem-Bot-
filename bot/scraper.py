"""
scraper.py — TikTok scraper using tikwm.com + ffprobe for real FPS
"""
import urllib.request
import urllib.parse
import json
import re
import subprocess
import tempfile
import os
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


def fetch_fps_ffprobe(video_url: str) -> int:
    """
    Use ffprobe to get exact FPS from the video stream.
    """
    if not video_url:
        print("[FPS] No video_url provided")
        return 0

    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=r_frame_rate",
                "-of", "json",
                "-user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                video_url
            ],
            capture_output=True,
            text=True,
            timeout=20
        )

        if result.returncode != 0:
            print(f"[FPS] ffprobe failed (code {result.returncode}): {result.stderr.strip()[:300]}")
            return 0

        if not result.stdout.strip():
            print(f"[FPS] ffprobe returned empty stdout. stderr: {result.stderr.strip()[:300]}")
            return 0

        data = json.loads(result.stdout)
        streams = data.get("streams", [])
        if not streams:
            print("[FPS] No video streams found in ffprobe output")
            return 0

        r_frame_rate = streams[0].get("r_frame_rate", "0/1")
        num, den = r_frame_rate.split("/")
        fps = round(int(num) / int(den))
        if 1 <= fps <= 240:
            return fps
        print(f"[FPS] Computed fps out of range: {fps}")
        return 0

    except FileNotFoundError:
        print("[FPS] ffprobe binary not found on PATH")
        return 0
    except subprocess.TimeoutExpired:
        print("[FPS] ffprobe timed out")
        return 0
    except Exception as e:
        print(f"[FPS] ffprobe unexpected error: {e}")
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

    if width and height:
        resolution    = get_resolution(width, height)
        web_quality   = f"{resolution} • {width}x{height}"
        phone_quality = resolution
    else:
        resolution    = "1080P"
        web_quality   = "1080P"
        phone_quality = "1080P"

    video_url = d.get("hdplay") or d.get("play") or ""
    fps = fetch_fps_ffprobe(video_url) if video_url else 0

    if fps:
        engine = "Zilem Optimized" if fps >= 60 else "Standard"
    else:
        fps    = "—"
        engine = "—"

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
    
