"""
scraper.py — TikTok scraper.

Engagement stats (views/likes/comments/etc) come from tikwm — that data
genuinely only exists on TikTok's servers and tikwm proxies it.

Technical metadata (resolution, fps, file size) comes from ffprobe run
directly against the actual video file. This is the authoritative source:
ffprobe reads real container/codec metadata, not a third party's summary
of it. tikwm's width/height/size fields are unreliable (sometimes 0,
sometimes wrong) so they are not trusted for technical metadata.
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
# tikwm — used ONLY for engagement stats, author info, description.
# Never trusted for width/height/fps/size since those are unreliable.
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
# Formatting helpers
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
# ffprobe — single authoritative source for ALL technical video metadata.
# Returns width, height, fps, and file size, all read directly from the
# actual video stream. One subprocess call instead of three.
# ---------------------------------------------------------------------------

def probe_video(video_url: str) -> dict:
    """
    Returns {"width": int, "height": int, "fps": int, "size": int} —
    any field that could not be determined is 0, and the caller must
    display "—" for that field rather than guessing.
    """
    result_data = {"width": 0, "height": 0, "fps": 0, "size": 0}

    if not video_url:
        print("[ffprobe] no video_url available")
        return result_data

    try:
        proc = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height,r_frame_rate",
                "-show_entries", "format=size",
                "-of", "json",
                "-user_agent", USER_AGENT,
                video_url,
            ],
            capture_output=True,
            text=True,
            timeout=25,
        )
    except FileNotFoundError:
        print("[ffprobe] binary not found — ensure 'ffmpeg' is in nixpacks.toml nixPkgs")
        return result_data
    except subprocess.TimeoutExpired:
        print("[ffprobe] timed out probing video stream")
        return result_data
    except Exception as e:
        print(f"[ffprobe] unexpected error launching process: {e}")
        return result_data

    if proc.returncode != 0:
        print(f"[ffprobe] exited with error: {proc.stderr.strip()[:400]}")
        return result_data

    if not proc.stdout.strip():
        print(f"[ffprobe] empty stdout. stderr: {proc.stderr.strip()[:400]}")
        return result_data

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        print(f"[ffprobe] output not valid JSON: {proc.stdout[:400]}")
        return result_data

    streams = data.get("streams", [])
    if streams:
        stream = streams[0]
        w = stream.get("width")
        h = stream.get("height")
        if w:
            result_data["width"] = int(w)
        if h:
            result_data["height"] = int(h)

        r_frame_rate = stream.get("r_frame_rate")
        if r_frame_rate and "/" in r_frame_rate:
            try:
                num_str, den_str = r_frame_rate.split("/")
                num, den = int(num_str), int(den_str)
                if den != 0:
                    fps = round(num / den)
                    if 1 <= fps <= 240:
                        result_data["fps"] = fps
                    else:
                        print(f"[ffprobe] fps {fps} out of plausible range, discarding")
                else:
                    print("[ffprobe] r_frame_rate denominator was zero")
            except ValueError as e:
                print(f"[ffprobe] could not parse r_frame_rate '{r_frame_rate}': {e}")
        else:
            print(f"[ffprobe] r_frame_rate missing or malformed: {r_frame_rate!r}")
    else:
        print("[ffprobe] no video stream found in probe output")

    fmt = data.get("format", {})
    size = fmt.get("size")
    if size:
        result_data["size"] = int(size)

    return result_data


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

    # --- Technical metadata: authoritative via ffprobe on the real file ---
    video_url = d.get("hdplay") or d.get("play") or ""
    probe = probe_video(video_url)

    width, height = probe["width"], probe["height"]
    has_dimensions = width > 0 and height > 0

    if has_dimensions:
        resolution    = classify_resolution(width, height)
        web_quality   = f"{resolution} • {width}x{height}"
        phone_quality = resolution
    else:
        resolution    = "—"
        web_quality   = "—"
        phone_quality = "—"

    fps_value = probe["fps"]
    if fps_value:
        fps    = fps_value
        engine = "Zilem Optimized" if fps_value >= 60 else "Standard"
    else:
        fps    = "—"
        engine = "—"

    # File size — prefer ffprobe's real measured size; fall back to tikwm's
    # reported size only if ffprobe couldn't determine it.
    size_bytes = probe["size"] or int(d.get("size") or 0)
    file_size_mb = f"{size_bytes / 1024 / 1024:.1f}" if size_bytes else "—"

    # --- Duration (tikwm-reported, used only for display, not derivation) ---
    duration = int(d.get("duration") or 0)

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

    # --- Engagement stats (genuinely only available from TikTok via tikwm) ---
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
    
