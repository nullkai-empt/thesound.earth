"""NASA SVS discovery, metadata parsing and ephemeral visual frame analysis."""
from __future__ import annotations
from .ssl_config import configure_global_ssl, get_ssl_context
configure_global_ssl()

import html
import json
import re
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlparse, urlunparse
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from PIL import Image, ImageFilter, ImageStat
import numpy as np

NASA_HOST = "svs.gsfc.nasa.gov"
API_ROOT = "https://svs.gsfc.nasa.gov/api/"
MAX_FRAME_BYTES = 40 * 1024 * 1024
MAX_LISTING_BYTES = 8 * 1024 * 1024
MAX_FRAMES = 240
ANALYSIS_SIZE = (256, 256)
SVS_CACHE_TTL_SECONDS = 900  # 15 minutes auto-expiry TTL


def cleanup_abandoned_temp(max_age_seconds: int = 24 * 60 * 60) -> int:
    """Remove only stale THESOUND.EARTH-owned scratch directories from a prior crash."""
    root = Path(tempfile.gettempdir()).resolve()
    now = time.time()
    removed = 0
    for entry in root.iterdir():
        if not entry.is_dir() or not entry.name.startswith(("thesound-earth-svs-", "thesound-earth-exr-", "earthsonic-svs-", "earthsonic-exr-")):
            continue
        try:
            if now - entry.stat().st_mtime > max_age_seconds and entry.resolve().parent == root:
                shutil.rmtree(entry)
                removed += 1
        except OSError:
            continue
    return removed


def trusted_nasa_url(value: str) -> str:
    """Validate an SVS URL and normalize the API's legacy http links to https."""
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or parsed.hostname != NASA_HOST or parsed.port not in {None, 80, 443}:
        raise ValueError("NASA media URL is outside the trusted SVS host.")
    return urlunparse(("https", NASA_HOST, parsed.path, "", parsed.query, ""))


class _SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        trusted_nasa_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = build_opener(_SafeRedirect(), HTTPSHandler(context=get_ssl_context()))


def _get(url: str, *, timeout: float = 15, limit: int = MAX_LISTING_BYTES) -> bytes:
    url = trusted_nasa_url(url)
    req = Request(url, headers={"User-Agent": "THESOUND.EARTH/1.0 (NASA SVS visual sonification)"})
    for attempt in range(3):
        try:
            with _opener.open(req, timeout=timeout) as response:
                chunks, size = [], 0
                while True:
                    part = response.read(min(256 * 1024, limit + 1 - size))
                    if not part:
                        break
                    chunks.append(part)
                    size += len(part)
                    if size > limit:
                        raise ValueError("NASA media response exceeds the configured size limit.")
            return b"".join(chunks)
        except HTTPError as exc:
            if exc.code not in {408, 429, 500, 502, 503, 504} or attempt == 2:
                raise RuntimeError(f"NASA SVS returned HTTP {exc.code}.") from exc
        except (URLError, TimeoutError) as exc:
            if attempt == 2:
                raise RuntimeError(f"Could not reach NASA SVS: {exc}") from exc
        time.sleep(0.25 * (attempt + 1))
    raise RuntimeError("NASA SVS request failed after retries.")


def search_svs(query: str = "", offset: int = 0, limit: int = 24, eic_only: bool = True) -> dict:
    if offset < 0 or not 1 <= limit <= 100:
        raise ValueError("Invalid NASA SVS pagination values.")
    params = {"limit": limit, "offset": offset, "studio": "SVS"}
    if eic_only:
        params["made_for"] = "EIC"
    if query.strip():
        params["search"] = query.strip()[:160]
    url = API_ROOT + "search/?" + urlencode(params)
    payload = json.loads(_get(url).decode("utf-8"))
    results = payload.get("results")
    if not isinstance(results, list):
        raise ValueError("NASA SVS search response has no results list.")
    return {
        "count": int(payload.get("count", len(results))),
        "next_offset": offset + limit if payload.get("next") else None,
        "previous_offset": max(0, offset - limit) if payload.get("previous") else None,
        "results": [{k: item.get(k) for k in ("id", "url", "result_type", "release_date", "title", "description")} for item in results],
    }


def _walk_media(value):
    if isinstance(value, dict):
        if isinstance(value.get("instance"), dict):
            yield value["instance"]
        for child in value.values():
            yield from _walk_media(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_media(child)


def get_visualization(visualization_id: int) -> dict:
    if not 1 <= visualization_id <= 999999:
        raise ValueError("Invalid NASA visualization ID.")

    page = None
    last_err = None

    # Try JSON API endpoints: /api/{id}/ and /api/vis/{id}/
    for endpoint in (f"https://{NASA_HOST}/api/{visualization_id}/", f"https://{NASA_HOST}/api/vis/{visualization_id}/"):
        try:
            raw = _get(endpoint)
            page = json.loads(raw.decode("utf-8"))
            if isinstance(page, dict) and page.get("id"):
                break
        except Exception as exc:
            last_err = exc
            page = None

    # Fallback to scraping HTML if API returned 404 or unexpected payload
    if not page or not isinstance(page, dict):
        try:
            html_raw = _get(f"https://{NASA_HOST}/{visualization_id}/").decode("utf-8", "replace")
            title_m = re.search(r"<title>(.*?)</title>", html_raw, re.I)
            t_str = title_m.group(1).replace("NASA SVS |", "").strip() if title_m else f"NASA SVS {visualization_id}"
            desc_m = re.search(r'<meta\s+name=["\']description["\']\s+content=["\'](.*?)["\']', html_raw, re.I)
            d_str = desc_m.group(1).strip() if desc_m else ""

            media_items = []
            seen_urls = set()
            # Extract MP4 links
            for mp4_href in re.findall(r'href=["\']([^"\']+\.mp4)["\']', html_raw, re.I):
                full_url = f"https://{NASA_HOST}{mp4_href}" if mp4_href.startswith("/") else mp4_href
                try:
                    full_url = trusted_nasa_url(full_url)
                except ValueError:
                    continue
                if full_url in seen_urls:
                    continue
                seen_urls.add(full_url)
                dim = re.search(r"(\d{3,5})x(\d{3,5})", full_url)
                w = int(dim.group(1)) if dim else None
                h = int(dim.group(2)) if dim else None
                media_items.append({
                    "url": full_url,
                    "filename": Path(urlparse(full_url).path).name,
                    "format": "mp4",
                    "type": "Movie",
                    "width": w,
                    "height": h,
                    "alt_text": t_str,
                })

            return {
                "id": visualization_id,
                "url": f"https://{NASA_HOST}/{visualization_id}/",
                "title": t_str,
                "description": d_str,
                "release_date": None,
                "update_date": None,
                "datasets": [],
                "credits": {},
                "studio": "svs",
                "made_for": None,
                "media": media_items,
            }
        except Exception as exc:
            raise RuntimeError(f"Could not load NASA visualization {visualization_id}: {last_err or exc}") from exc

    media, seen = [], set()
    for item in _walk_media(page.get("media_groups", [])):
        url = item.get("url")
        kind = str(item.get("media_type", "")).lower()
        if not url or kind not in {"frames", "movie", "image", "video"}:
            continue
        url = trusted_nasa_url(url)
        key = (kind, url)
        if key in seen:
            continue
        seen.add(key)
        dimensions = re.search(r"(\d{3,5})x(\d{3,5})", urlparse(url).path)
        width = item.get("width") or (int(dimensions.group(1)) if dimensions else None)
        height = item.get("height") or (int(dimensions.group(2)) if dimensions else None)
        media.append({
            "url": url,
            "filename": item.get("filename"),
            "format": Path(urlparse(url).path).suffix.lower().lstrip("."),
            "type": item.get("media_type"),
            "width": width,
            "height": height,
            "alt_text": item.get("alt_text"),
        })
    return {
        "id": visualization_id,
        "url": trusted_nasa_url(page.get("url", f"https://{NASA_HOST}/{visualization_id}/")),
        "title": page.get("title", "Untitled NASA visualization"),
        "description": page.get("description", ""),
        "release_date": page.get("release_date"),
        "update_date": page.get("update_date"),
        "datasets": page.get("datasets", []),
        "credits": page.get("credits", page.get("main_credits", {})),
        "studio": page.get("studio"),
        "made_for": page.get("made_for"),
        "media": media,
    }


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.hrefs.append(html.unescape(href))


def _frame_urls(directory_url: str) -> list[str]:
    body = _get(directory_url).decode("utf-8", "replace")
    parser = _Links()
    parser.feed(body)
    names = [urljoin(directory_url, link) for link in parser.hrefs if re.search(r"\.(?:png|jpe?g|tiff?|exr)$", link, re.I)]
    def order(url: str):
        match = re.search(r"(\d+)(?=\.[^.]+$)", urlparse(url).path)
        return (0, int(match.group(1)), url) if match else (1, 0, url)
    return sorted((trusted_nasa_url(x) for x in names), key=order)


def _frame_id(url: str, fallback: int) -> int:
    match = re.search(r"(\d+)(?=\.[^.]+$)", urlparse(url).path)
    return int(match.group(1)) if match else fallback


def _media_size(asset: dict) -> int:
    try:
        width, height = int(asset.get("width")), int(asset.get("height"))
        if width > 0 and height > 0:
            return width * height
    except (TypeError, ValueError):
        pass
    return 2**63 - 1


@dataclass(frozen=True)
class VisualFeatures:
    frame_number: int
    timestamp_seconds: float | None
    brightness: float
    saturation: float
    edge_density: float
    color_rgb: tuple[float, float, float]
    motion: float


def _features(image: Image.Image, frame_number: int, timestamp: float | None, previous: Image.Image | None) -> tuple[VisualFeatures, Image.Image]:
    image.thumbnail(ANALYSIS_SIZE)
    rgb = image.convert("RGB")
    stats = ImageStat.Stat(rgb)
    brightness = ImageStat.Stat(rgb.convert("L")).mean[0] / 255
    hsv = rgb.convert("HSV")
    saturation = ImageStat.Stat(hsv).mean[1] / 255
    edges = rgb.convert("L").filter(ImageFilter.FIND_EDGES)
    edge_density = float(np.count_nonzero(np.asarray(edges) > 48)) / (edges.width * edges.height)
    motion = 0.0
    if previous is not None:
        before = previous.convert("L")
        after = rgb.convert("L")
        import PIL.ImageChops
        diff = PIL.ImageChops.difference(before, after)
        motion = min(1.0, ImageStat.Stat(diff).mean[0] / 96)
    feature = VisualFeatures(frame_number, timestamp, brightness, saturation, edge_density, tuple(x / 255 for x in stats.mean), motion)
    return feature, rgb.copy()


def _decode_frame(data: bytes, source_url: str = "") -> Image.Image:
    from io import BytesIO
    try:
        image = Image.open(BytesIO(data))
        if image.width * image.height > 100_000_000:
            image.close()
            raise ValueError("NASA frame exceeds the pixel limit.")
        image.load()
    except ValueError:
        raise
    except Exception:
        if not source_url.lower().split("?", 1)[0].endswith(".exr"):
            raise ValueError("NASA frame uses an unsupported or corrupt image format.")
        try:
            import OpenEXR
        except ImportError as exc:
            raise RuntimeError("This NASA frame is EXR; install OpenEXR to decode it.") from exc
        # OpenEXR's supported API reads a path and returns NumPy channel arrays.
        with tempfile.TemporaryDirectory(prefix="thesound-earth-exr-") as temp_dir:
            exr_path = Path(temp_dir) / "frame.exr"
            exr_path.write_bytes(data)
            with OpenEXR.File(str(exr_path)) as exr:
                channels = exr.channels()
                packed = channels.get("RGB") or channels.get("RGBA")
                if packed is not None:
                    pixels = np.asarray(packed.pixels)[..., :3]
                else:
                    channels_by_name = {key.rsplit(".", 1)[-1]: np.asarray(value.pixels) for key, value in channels.items()}
                    if not all(key in channels_by_name for key in ("R", "G", "B")):
                        raise ValueError("NASA EXR frame has no RGB channels.")
                    pixels = np.stack([channels_by_name[key] for key in ("R", "G", "B")], axis=-1)
                if pixels.ndim != 3 or pixels.shape[0] * pixels.shape[1] > 100_000_000:
                    raise ValueError("NASA EXR frame dimensions are unsupported.")
                # Convert HDR values to display range for image-derived analysis only.
                display = np.zeros(pixels.shape, dtype=np.uint8)
                for channel in range(3):
                    plane = np.nan_to_num(pixels[..., channel], nan=0.0, posinf=0.0, neginf=0.0)
                    low, high = np.percentile(plane, [1, 99])
                    if high <= low:
                        high = low + 1.0
                    display[..., channel] = (np.clip((plane - low) / (high - low), 0, 1) * 255).astype(np.uint8)
                image = Image.fromarray(display, "RGB")
    if image.width * image.height > 100_000_000:
        raise ValueError("NASA frame exceeds the pixel limit.")
    return image


def analyze_frames(metadata: dict, sample_every: int = 4, max_frames: int = 120, cancelled: threading.Event | None = None, progress=None) -> tuple[list[dict], dict]:
    if not 1 <= sample_every <= 120 or not 1 <= max_frames <= MAX_FRAMES:
        raise ValueError("Frame sampling values are outside the supported range.")
    assets = metadata.get("media", [])
    frame_assets = [a for a in assets if str(a.get("type", "")).lower() == "frames"]
    movie_assets = [a for a in assets if str(a.get("type", "")).lower() in {"movie", "video"}]
    out: list[dict] = []
    selected = None
    if frame_assets:
        # Favor a suitable lower-resolution sequence; retain NASA's frame order.
        asset = min(frame_assets, key=lambda a: (_media_size(a), a["url"]))
        try:
            urls = _frame_urls(asset["url"])
            if not urls:
                raise ValueError("NASA frame directory did not list supported image files.")
            selected = asset
            prior = None
            picked = urls[::sample_every][:max_frames]
            total = len(picked)
            for index, url in enumerate(picked):
                if cancelled and cancelled.is_set():
                    raise InterruptedError("Frame processing cancelled.")
                data = _get(url, timeout=30, limit=MAX_FRAME_BYTES)
                image = _decode_frame(data, url)
                frame_id = _frame_id(url, index * sample_every)
                fps_match = re.search(r"(\d+)p", asset["url"])
                fps = int(fps_match.group(1)) if fps_match else None
                try:
                    feature, current_small = _features(image, frame_id, frame_id / fps if fps else None, prior)
                finally:
                    image.close()
                if prior is not None:
                    prior.close()
                prior = current_small
                out.append(asdict(feature))
                if progress:
                    progress(index + 1, total)
        except InterruptedError:
            raise
        except Exception:
            if not movie_assets:
                raise
            out = []
            selected = None
    if not out and movie_assets:
        asset = min(movie_assets, key=lambda a: (_media_size(a), a["url"]))
        selected = asset
        out.extend(_analyze_video(asset, sample_every, max_frames, cancelled, progress))
    elif not frame_assets and not movie_assets:
        raise ValueError("This NASA visualization has no downloadable frame sequence or video.")
    if not out:
        raise ValueError("NASA media contained no decodable image frames.")
    return out, {"url": selected["url"], "type": selected["type"], "width": selected.get("width"), "height": selected.get("height"), "sample_every": sample_every, "analyzed_frames": len(out), "analysis_resolution": list(ANALYSIS_SIZE)}


def _analyze_video(asset, sample_every, max_frames, cancelled, progress):
    """Use bundled FFmpeg or system FFmpeg and a short-lived file; the TemporaryDirectory always cleans up."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        try:
            import imageio_ffmpeg
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except ImportError as exc:
            raise RuntimeError("This visualization only has video media. Install imageio-ffmpeg or ffmpeg to enable frame extraction.") from exc
    from io import BytesIO
    out, prior = [], None
    with tempfile.TemporaryDirectory(prefix="thesound-earth-svs-") as temp_dir:
        video = Path(temp_dir) / "source-video"
        # Bounded download with cancellation and immediate cleanup on all exit paths.
        req = Request(trusted_nasa_url(asset["url"]), headers={"User-Agent": "THESOUND.EARTH/1.0"})
        with _opener.open(req, timeout=30) as response, video.open("wb") as target:
            total_bytes = 0
            while True:
                if cancelled and cancelled.is_set():
                    raise InterruptedError("Frame processing cancelled.")
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > 1024 * 1024 * 1024:
                    raise ValueError("NASA video exceeds the 1 GB temporary-processing limit.")
                target.write(chunk)
        cmd = [ffmpeg, "-v", "error", "-i", str(video), "-vf", f"select='not(mod(n\\,{sample_every}))',setpts=N/FRAME_RATE/TB,scale=256:256:force_original_aspect_ratio=decrease", "-frames:v", str(max_frames), "-f", "image2pipe", "-vcodec", "mjpeg", "-"]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert proc.stdout
        frame_num = 0
        buffer = bytearray()
        try:
            while frame_num < max_frames:
                if cancelled and cancelled.is_set():
                    raise InterruptedError("Frame processing cancelled.")
                chunk = proc.stdout.read(64 * 1024)
                if not chunk:
                    break
                buffer.extend(chunk)
                while True:
                    start = buffer.find(b"\xff\xd8")
                    end = buffer.find(b"\xff\xd9", start + 2) if start >= 0 else -1
                    if start < 0 or end < 0:
                        if start > 0:
                            del buffer[:start]
                        break
                    image = Image.open(BytesIO(bytes(buffer[start:end + 2])))
                    image.load()
                    try:
                        feature, current_small = _features(image, frame_num * sample_every, None, prior)
                    finally:
                        image.close()
                    if prior is not None:
                        prior.close()
                    prior = current_small
                    out.append(asdict(feature))
                    frame_num += 1
                    del buffer[:end + 2]
                    if progress:
                        progress(frame_num, max_frames)
                    if frame_num >= max_frames:
                        proc.terminate()
                        break
            _, stderr = proc.communicate(timeout=10)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)
        if proc.returncode not in {0, -15}:
            raise RuntimeError(f"FFmpeg could not decode this NASA video: {stderr[-500:].decode('utf-8', 'replace')}")
    return out


def sonify_visual_features(features: list[dict], cfg: dict, out_path: Path, mode: str = "musical"):
    """Convert bounded image features to events, then reuse existing arranger and WAV renderer."""
    from .arranger import arrange_events
    from .sonification_mapper import map_visual_features_to_events
    from .synthesizer import render_wav
    mapping = cfg["visual_mapping"]
    duration = float(cfg["sonification"]["phrase_duration_sec"])
    events = map_visual_features_to_events(features, mapping, duration)
    arranged = arrange_events(events, cfg["sonification"], mode=mode)
    wav = render_wav(arranged, duration, cfg["sonification"]["sample_rate_hz"], out_path, mode)
    return wav, arranged
