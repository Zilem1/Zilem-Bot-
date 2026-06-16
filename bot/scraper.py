"""
scraper.py — TikTok scraper.
Every field is either read from a real source or explicitly marked unknown ("—").
No value is invented or assumed.
"""
import urllib.request
import urllib.parse
import urllib.error
import json
import re
import subprocess
from datetime import datetime

API_URL = "https://www.tikwm.com/api/"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


# ---------------------------------------------------------------------------
# URL resolution
# ---------------------------------------------------------------------------

def _resolve_short_url(url: str) -> str:
    """
    vt.tiktok.com / vm.tiktok.com short links must be resolved to the
    canonical tiktok.com/@user/video/<id> URL before lookup.
    Manually walks every redirect hop (301/302/303/307/308), max 5 hops.
    If resolution fails at any point, returns the last known URL — the
    caller is responsible for treating a parse failure as a real error,
    not papering over it.
    """
    if "vt.tiktok.com" not in url and "vm.tiktok.com" not in url:
        return url

    current_url = url
    headers = {"User-Agent": USER_AGENT}

    for _ in range(5):
        req = urllib.request.Request(current_url, headers=headers, method="HEAD")
        opener = urllib.request.build_opener()
        try:
            resp = opener.open(req, timeout=10)
            return resp.geturl() or current_url
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308):
                location = e.headers.get("Location")
                if not location:
                    return current_url
                if location.startswith("/"):
                    location = urllib.parse.urljoin(current_url, location)
                current_url = location
                continue
            return current_url
        except Exception:
            return current_url

    return current_url


# ---------------------------------------------------------------------------
# tikwm lookup
# ---------------------------------------------------------------------------

def _fetch_metadata(url: str) -> dict:
    resolved_url = _resolve_short_url(url)
    payload = urllib.parse.urlencode({"url": resolved_url, "hd": 1}).encode()
    req = urllib.request.Request(
        API_URL,
        data=payload,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": USER_AGENT,
            "Referer": "https://www.tikwm.com/",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


# ---------------------------------------------------------------------------
# Formatting helpers — these only format, they never invent data
# ---------------------------------------------------------------------------

def fmt_num(n):
    if n is None:
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


def classify_resolution(width: int, height: int) -> str:
    """
    Resolution class based on the SHORT side of the frame, which is
    correct regardless of portrait or landscape orientation:
      portrait  1080x1920 -> short=1080 -> 1080P
      landscape 1920x1080 -> short=1080 -> 1080P
      portrait  1440x2560 -> short=1440 -> 2K
    Requires width and height > 0. Caller must check this before calling.
    """
    short_side = min(width, height)
    if short_side >= 2160:
        return "4K"
    if short_side >= 1440:
        return "2K"
    if short_side >= 1080:
        return "1080P"
    if short_side >= 720:
        return "720P"
    if short_side >= 480:
        return "480P"
    return "360P"


# ---------------------------------------------------------------------------
# FPS — read from the real video stream via ffprobe. Never guessed.
# ---------------------------------------------------------------------------

def fetch_fps_ffprobe(video_url: str) -> int:
    """
    Returns real FPS read from the video's r_frame_rate stream metadata,
    or 0 if it genuinely could not be determined (caller must show "—").
    """
    if not video_url:
        print("[FPS] no video_url available from metadata source")
        return 0

    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=r_frame_rate",
                "-of", "json",
                "-user_agent", USER_AGENT,
                video_url,
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except FileNotFoundError:
        print("[FPS] ffprobe binary not found — is ffmpeg installed in nixpacks.toml?")
        return 0
    except subprocess.TimeoutExpired:
        print("[FPS] ffprobe timed out fetching stream info")
        return 0
    except Exception as e:
        print(f"[FPS] unexpected error launching ffprobe: {e}")
        return 0

    if result.returncode != 0:
        print(f"[FPS] ffprobe exited with error: {result.stderr.strip()[:300]}")
        return 0

    if not result.stdout.strip():
        print(f"[FPS] ffprobe produced no output. stderr: {result.stderr.strip()[:300]}")
        return 0

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"[FPS] ffprobe output was not valid JSON: {result.stdout[:300]}")
        return 0

    streams = data.get("streams", [])
    if not streams:
        print("[FPS] ffprobe found no video stream")
        return 0

    r_frame_rate = streams[0].get("r_frame_rate")
    if not r_frame_rate or "/" not in r_frame_rate:
        print(f"[FPS] r_frame_rate missing or malformed: {r_frame_rate!r}")
        return 0

    try:
        num_str, den_str = r_frame_rate.split("/")
        num, den = int(num_str), int(den_str)
        if den == 0:
            print("[FPS] r_frame_rate denominator was zero")
            return 0
        fps = round(num / den)
    except (ValueError, ZeroDivisionError) as e:
        print(f"[FPS] could not parse r_frame_rate '{r_frame_rate}': {e}")
        return 0

    if not (1 <= fps <= 240):
        print(f"[FPS] computed fps {fps} outside plausible range, discarding")
        return 0

    return fps


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def scrape_tiktok(url: str) -> dict:
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _scrape_sync, url)


def _scrape_sync(url: str) -> dict:
    try:
        resp = _fetch_metadata(url)
    except Exception as e:
        raise Exception(f"Could not reach Zilem Optimizer: {e}")

    if resp.get("code") != 0:
        raise Exception(f"Zilem Optimizer error: {resp.get('msg', 'Unknown error')}")

    d = resp.get("data") or {}
    if not d:
        raise Exception("Zilem Optimizer returned no data for this video")

    author = d.get("author") or {}

    # --- Dimensions: read raw, do not assume a default ---
    raw_width  = d.get("width")
    raw_height = d.get("height")
    width  = int(raw_width)  if raw_width  else 0
    height = int(raw_height) if raw_height else 0
    has_dimensions = width > 0 and height > 0

    if has_dimensions:
        resolution    = classify_resolution(width, height)
        web_quality   = f"{resolution} • {width}x{height}"
        phone_quality = resolution
    else:
        # Honest about not knowing — no fabricated "1080P" default
        print(f"[Resolution] width/height missing from metadata (raw: {raw_width}x{raw_height})")
        resolution    = "—"
        web_quality   = "—"
        phone_quality = "—"

    # --- Duration & size: read raw ---
    duration   = int(d.get("duration") or 0)
    size_bytes = int(d.get("size") or 0)
    file_size_mb = f"{size_bytes / 1024 / 1024:.1f}" if size_bytes else "—"

    # --- FPS: real measurement only ---
    video_url = d.get("hdplay") or d.get("play") or ""
    fps_value = fetch_fps_ffprobe(video_url)

    if fps_value:
        fps    = fps_value
        engine = "Zilem Optimized" if fps_value >= 60 else "Standard"
    else:
        fps    = "—"
        engine = "—"

    # --- Upload date ---
    create_time = d.get("create_time")
    if create_time:
        dt = datetime.utcfromtimestamp(int(create_time))
        uploaded_at = dt.strftime("%b %d, %Y, %I:%M %p")
    else:
        uploaded_at = "—"

    # --- Account status ---
    is_private = bool(author.get("is_private") or author.get("privateAccount"))
    account_status = "private" if is_private else "safe"

    # --- Description / hashtags ---
    desc     = d.get("title") or ""
    hashtags = " ".join(re.findall(r"#\w+", desc))
    title    = re.sub(r"#\w+", "", desc).strip() or desc

    # --- Engagement stats: read raw, format for display ---
    views     = d.get("play_count")
    likes     = d.get("digg_count")
    comments  = d.get("comment_count")
    shares    = d.get("share_count")
    bookmarks = d.get("collect_count")
    downloads = d.get("download_count")

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
        "views":          fmt_num(views),
        "likes":          fmt_num(likes),
        "comments":       fmt_num(comments),
        "shares":         fmt_num(shares),
        "bookmarks":      fmt_num(bookmarks),
        "downloads":      fmt_num(downloads),
        }
    
