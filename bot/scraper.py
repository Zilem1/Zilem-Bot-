"""
scraper.py — TikTok scraper using tikwm.com
FPS parsed from MP4 boxes using proper box tree walking
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


def find_boxes(data, target_names):
    """
    Walk MP4 box tree and collect all boxes matching target_names.
    Returns dict of {name: [bytes, ...]}
    """
    results = {n: [] for n in target_names}

    def walk(buf, offset, end):
        while offset + 8 <= end:
            if offset + 4 > len(buf):
                break
            size = struct.unpack('>I', buf[offset:offset+4])[0]
            if size < 8:
                break
            name = buf[offset+4:offset+8]
            box_end = offset + size
            if box_end > len(buf):
                box_end = len(buf)

            name_str = name.decode('latin-1', errors='replace')
            if name_str in target_names:
                results[name_str].append(buf[offset:box_end])

            # Container boxes — walk into them
            if name in (b'moov', b'trak', b'mdia', b'minf', b'stbl'):
                walk(buf, offset + 8, box_end)

            offset += size
            if offset <= 0:
                break

    walk(data, 0, len(data))
    return results


def parse_fps_from_mp4(data: bytes) -> int:
    """
    Walk MP4 boxes to find mdhd (timescale) and stts (sample delta).
    FPS = timescale / sample_delta
    """
    boxes = find_boxes(data, ['moov', 'trak', 'mdia', 'minf', 'stbl', 'mdhd', 'stts'])

    timescales = []
    for box in boxes.get('mdhd', []):
        try:
            version = box[8]
            if version == 0:
                ts = struct.unpack('>I', box[20:24])[0]
            else:
                ts = struct.unpack('>I', box[28:32])[0]
            if ts > 0:
                timescales.append(ts)
        except Exception:
            pass

    fps_values = []
    for box in boxes.get('stts', []):
        try:
            entry_count = struct.unpack('>I', box[12:16])[0]
            if entry_count > 0:
                sample_delta = struct.unpack('>I', box[20:24])[0]
                if sample_delta > 0:
                    for ts in timescales:
                        fps = ts / sample_delta
                        if 1 <= fps <= 240:
                            fps_values.append(round(fps))
        except Exception:
            pass

    if fps_values:
        return max(set(fps_values), key=fps_values.count)
    return 0


def fetch_fps_from_video(video_url: str) -> int:
    """
    Download MP4 in chunks until we find moov box.
    Try first 512KB, then 2MB, then 8MB.
    """
    for chunk_size in [524288, 2097152, 8388608]:
        try:
            req = urllib.request.Request(
                video_url,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Range": f"bytes=0-{chunk_size-1}",
                }
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = resp.read()

            fps = parse_fps_from_mp4(data)
            if fps:
                return fps
        except Exception:
            continue
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

    # Get real FPS from video file
    video_url = d.get("hdplay") or d.get("play") or ""
    fps = fetch_fps_from_video(video_url) if video_url else 0

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
    
