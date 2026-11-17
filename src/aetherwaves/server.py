from __future__ import annotations
from .ssl_config import configure_global_ssl, get_ssl_context
configure_global_ssl()
import base64
import json
import logging
import os
import queue
import shutil
import threading
import time
import uuid

logger = logging.getLogger("aetherwaves.server")
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional, Any
from urllib.request import Request
import numpy as np
import uvicorn
from pydantic import BaseModel, Field
from fastapi import FastAPI, HTTPException, Query, Body, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest
from .arranger import arrange_events
from .data_reader import extract_cell_timeseries, load_oscar_dataset
from .export import write_audit_json
from .feature_extractor import extract_features
from .models import OceanSample
from .normalizer import normalize_features
from .pipeline import run_pipeline
from .sonification_mapper import map_controls_to_events
from .synthesizer import render_wav
from .validator import verify_rendered_audio
from .engine_v3.svs_v3 import probe_video_info, sonify_svs_v3
from .svs import (
    analyze_frames,
    cleanup_abandoned_temp,
    get_visualization,
    search_svs,
    sonify_visual_features,
    _opener,
    trusted_nasa_url,
)
from .voice_router import (
    KOKORO,
    WHISPER,
    ROTATOR,
    REGION_PROFILES,
    WELCOME_PROMPT,
    STAGE2_GUIDE_PROMPT,
    process_voice_navigation,
    scrub_banned_words,
)
from .frame_sonifier import sonify_extracted_frames, sonify_frame_energies

ENGINE_VERSION = "v3"
MAX_VIDEO_BYTES = 300 * 1024 * 1024  # 300 MB
MAX_VIDEO_DURATION_SEC = 300.0        # 300 seconds
JOB_TIMEOUT_SECONDS = 300             # 300 seconds


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_requests_per_minute: int = 120, max_sonify_per_minute: int = 30):
        super().__init__(app)
        self.max_requests = max_requests_per_minute
        self.max_sonify = max_sonify_per_minute
        self.ip_requests: dict[str, list[float]] = {}
        self.ip_sonify: dict[str, list[float]] = {}
        self.lock = threading.Lock()

    async def dispatch(self, request: StarletteRequest, call_next):
        client_ip = request.client.host if request.client else "127.0.0.1"
        now = time.time()
        cutoff = now - 60.0
        path = request.url.path

        with self.lock:
            # Check sonify rate limit
            if request.method == "POST" and path.endswith("/sonify"):
                timestamps = self.ip_sonify.setdefault(client_ip, [])
                self.ip_sonify[client_ip] = [t for t in timestamps if t > cutoff]
                if len(self.ip_sonify[client_ip]) >= self.max_sonify:
                    return JSONResponse(
                        status_code=429,
                        content={"detail": "Rate limit exceeded for sonification requests. Please wait before retrying."},
                    )
                self.ip_sonify[client_ip].append(now)

            # Check general rate limit
            timestamps = self.ip_requests.setdefault(client_ip, [])
            self.ip_requests[client_ip] = [t for t in timestamps if t > cutoff]
            if len(self.ip_requests[client_ip]) >= self.max_requests:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Rate limit exceeded. Please wait before retrying."},
                )
            self.ip_requests[client_ip].append(now)

        return await call_next(request)


app = FastAPI(title="THESOUND.EARTH 3D Globe API")
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https://.*\.pages\.dev",
    allow_origins=[
        "https://thesound.earth",
        "http://thesound.earth",
        "https://www.thesound.earth",
        "http://www.thesound.earth",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://127.0.0.1:8080",
        "http://localhost:8080",
        "https://thesound-earth.pages.dev",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "HEAD", "OPTIONS"],
    allow_headers=["*"],
)
app.add_middleware(RateLimitMiddleware, max_requests_per_minute=120, max_sonify_per_minute=30)

GLOBAL_FFMPEG_PATH = shutil.which("ffmpeg")

NC_PATH = Path("data/oscar_global.nc")
CFG_PATH = Path("config/ocean_mapping_v1.json")
OUT_DIR = Path("output")
OUT_DIR.mkdir(parents=True, exist_ok=True)
TRACKS_DIR = Path("web/tracks")
DATA_DIR = Path("web/data")
FINAL_DIR = Path("final")
WEB_DIR = Path("web")
FINAL_INDEX_PATH = Path("final/index.json")
REGIONS_PATH = Path("config/regions.json")
LAND_REGIONS_PATH = Path("config/land_regions.json")
RAW_OSCAR_DIR = Path("data/raw_oscar")
SVS_CACHE_DIR = OUT_DIR / "svs_cache"
SVS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
SVS_CACHE_TTL_SECONDS = 900  # 15 minutes auto-expiry TTL


def cleanup_expired_svs_cache(ttl_seconds: int = SVS_CACHE_TTL_SECONDS) -> int:
    """Delete any file in output/svs_cache/ whose mtime is older than ttl_seconds."""
    if not SVS_CACHE_DIR.exists():
        return 0
    now = time.time()
    removed = 0
    try:
        for entry in SVS_CACHE_DIR.iterdir():
            if entry.is_file():
                try:
                    file_age = now - entry.stat().st_mtime
                    if file_age > ttl_seconds:
                        try:
                            entry.unlink(missing_ok=True)
                            removed += 1
                        except (PermissionError, OSError) as e:
                            logger.debug("Skipping in-use/locked SVS file %s: %s", entry.name, e)
                        except Exception as e:
                            logger.debug("Failed to remove expired SVS file %s: %s", entry.name, e)
                except Exception as e:
                    logger.debug("Failed inspecting SVS file %s: %s", entry.name, e)
    except Exception as exc:
        logger.debug("Error scanning SVS cache directory: %s", exc)
    return removed


def _svs_cache_cleanup_worker():
    while True:
        try:
            cleanup_expired_svs_cache(SVS_CACHE_TTL_SECONDS)
        except Exception:
            pass
        time.sleep(60)


_svs_cleanup_thread = threading.Thread(target=_svs_cache_cleanup_worker, daemon=True)
_svs_cleanup_thread.start()


@app.middleware("http")
async def svs_cache_cleanup_middleware(request: Request, call_next):
    if request.url.path.startswith("/api/svs"):
        cleanup_expired_svs_cache(SVS_CACHE_TTL_SECONDS)
    return await call_next(request)

app.mount("/output", StaticFiles(directory=str(OUT_DIR)), name="output")
if FINAL_DIR.exists():
    app.mount("/final", StaticFiles(directory=str(FINAL_DIR)), name="final")
if TRACKS_DIR.exists():
    app.mount("/tracks", StaticFiles(directory=str(TRACKS_DIR)), name="tracks")
if DATA_DIR.exists():
    app.mount("/data", StaticFiles(directory=str(DATA_DIR)), name="data")

_GENAI_CLIENT = None
_SVS_JOBS: dict[str, dict] = {}
_SVS_LOCK = threading.Lock()
_OSCAR_DAILY_CACHE: dict[str, str] = {}
cleanup_abandoned_temp()


@app.api_route("/favicon.ico", methods=["GET", "HEAD"])
def favicon():
    svg_icon = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><circle cx="50" cy="50" r="46" fill="#060a12" stroke="#38bdf8" stroke-width="6"/><path d="M20 50 Q35 25 50 50 T80 50" fill="none" stroke="#38bdf8" stroke-width="6" stroke-linecap="round"/><circle cx="50" cy="50" r="8" fill="#38bdf8"/></svg>'
    return HTMLResponse(content=svg_icon, media_type="image/svg+xml")


@app.api_route("/api/oscar_daily/{year}", methods=["GET", "HEAD"])
def get_oscar_daily(year: str):
    if year not in _OSCAR_DAILY_CACHE:
        p = RAW_OSCAR_DIR / f"oscar_{year}_daily.json"
        if not p.exists():
            raise HTTPException(status_code=404, detail=f"No daily OSCAR data found for year {year}")
        _OSCAR_DAILY_CACHE[year] = p.read_text(encoding="utf-8")
    return Response(
        content=_OSCAR_DAILY_CACHE[year],
        media_type="application/json",
        headers={"Cache-Control": "public, max-age=86400"},
    )


def _get_genai_client():
    global _GENAI_CLIENT
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None
    if _GENAI_CLIENT is None:
        from google import genai
        _GENAI_CLIENT = genai.Client(api_key=api_key)
    return _GENAI_CLIENT


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    content = Path("web/index.html").read_text(encoding="utf-8")
    return HTMLResponse(
        content=content,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(status_code=204)


@app.get("/.well-known/appspecific/com.chrome.devtools.json", include_in_schema=False)
def chrome_devtools_json():
    return JSONResponse({})


@app.get("/data/grid/index.json", include_in_schema=False)
def grid_index_json():
    manifest = [
        {"day_idx": i, "date": f"2026-01-{i+1:02d}", "file": f"4_{i}.json"}
        for i in range(16)
    ]
    return JSONResponse(manifest)


@app.get("/flow.worker.js")
def flow_worker() -> HTMLResponse:
    return HTMLResponse(
        Path("web/flow.worker.js").read_text(encoding="utf-8"),
        media_type="application/javascript",
    )


@app.get("/svs_video")
def svs_video() -> FileResponse:
    for fname, mtype in [
        ("web/ecco2_sst_flow.mp4", "video/mp4"),
        ("web/ecco2_sst_flow.webmhd.webm", "video/webm"),
        ("web/ecco2_sst_flow.m4v", "video/mp4"),
    ]:
        p = Path(fname)
        if p.exists():
            return FileResponse(p, media_type=mtype)
    raise HTTPException(status_code=404, detail="SVS 3912 video not found in web/ yet.")


@app.get("/api/grid")
def get_global_grid(step: int = 4, day_idx: int = 0) -> dict:
    ds = load_oscar_dataset(NC_PATH)
    lat_dim = "latitude" if "latitude" in ds.coords else "lat"
    lon_dim = "longitude" if "longitude" in ds.coords else "lon"

    has_time = "time" in ds["u"].dims
    dates = [str(t)[:10] for t in ds["time"].values] if has_time else ["2026-01-01"]
    safe_idx = max(0, min(day_idx, len(dates) - 1))

    u0 = (ds["u"].isel(time=safe_idx) if has_time else ds["u"]).values[::step, ::step]
    v0 = (ds["v"].isel(time=safe_idx) if has_time else ds["v"]).values[::step, ::step]
    lats = ds[lat_dim].values[::step]
    lons = ds[lon_dim].values[::step]

    if u0.shape == (len(lons), len(lats)):
        u0, v0 = u0.T, v0.T

    points = []
    for i, lat in enumerate(lats):
        for j, lon in enumerate(lons):
            u_val, v_val = float(u0[i, j]), float(v0[i, j])
            if np.isfinite(u_val) and np.isfinite(v_val) and abs(u_val) <= 10 and abs(v_val) <= 10:
                spd = float(np.hypot(u_val, v_val))
                lon_180 = ((float(lon) + 180.0) % 360.0) - 180.0
                points.append({
                    "lat": round(float(lat), 2),
                    "lng": round(lon_180, 2),
                    "u": round(u_val, 3),
                    "v": round(v_val, 3),
                    "speed": round(spd, 3),
                })
    return {"dates": dates, "points": points}


_SVS_HAS_MP4_CACHE: dict[int, bool] = {}


def _check_has_valid_mp4(item_id: int) -> bool:
    if item_id in _SVS_HAS_MP4_CACHE:
        return _SVS_HAS_MP4_CACHE[item_id]
    try:
        vis = get_visualization(item_id)
        media = vis.get("media", [])
        has_mp4 = any(
            (
                m.get("type") in ("Movie", "Video")
                or (m.get("url") or "").lower().endswith(".mp4")
                or (m.get("filename") or "").lower().endswith(".mp4")
            )
            for m in media
        )
        _SVS_HAS_MP4_CACHE[item_id] = has_mp4
        return has_mp4
    except Exception:
        _SVS_HAS_MP4_CACHE[item_id] = False
        return False


@app.api_route("/api/svs/search", methods=["GET", "HEAD"])
def svs_search(
    q: str = Query("", max_length=160),
    search: str = Query("", max_length=160),
    offset: int = Query(0, ge=0),
    limit: int = Query(24, ge=1, le=100),
    eic_only: bool = False,
) -> dict:
    query = (q or search).strip()
    try:
        raw_res = search_svs(query, offset, limit, eic_only)
        if not raw_res.get("results") and eic_only:
            raw_res = search_svs(query, offset, limit, False)

        results = raw_res.get("results", [])
        with ThreadPoolExecutor(max_workers=8) as ex:
            valid_flags = list(ex.map(_check_has_valid_mp4, [item["id"] for item in results]))
        filtered_results = [it for it, valid in zip(results, valid_flags) if valid]

        return {
            "count": len(filtered_results),
            "next_offset": raw_res.get("next_offset"),
            "previous_offset": raw_res.get("previous_offset"),
            "results": filtered_results,
        }
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/svs/{visualization_id}")
def svs_visualization(visualization_id: int) -> dict:
    try:
        return get_visualization(visualization_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (RuntimeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


_SVS_QUEUE: queue.Queue[str] = queue.Queue()


def _run_svs_v3_worker_task(job_id: str) -> None:
    with _SVS_LOCK:
        job = _SVS_JOBS.get(job_id)
        if not job or job.get("status") == "cancelled" or job.get("cancel_event", threading.Event()).is_set():
            if job:
                job["status"] = "cancelled"
            return
        visualization_id = job["svs_id"]
        job["status"] = "analysing"
        job["progress"] = {"stage": "analysing", "current": 0, "total": 1}
        cancel_event = job["cancel_event"]

    start_time = time.time()
    video_path = SVS_CACHE_DIR / f"{visualization_id}.mp4"
    tmp_download = None

    try:
        if not video_path.exists():
            dist_file = Path(f"output/svs_dist/{visualization_id}/video.mp4")
            if dist_file.exists():
                shutil.copy2(dist_file, video_path)
        if not video_path.exists():
            if cancel_event.is_set():
                raise InterruptedError("Processing job cancelled.")
            metadata = get_visualization(visualization_id)
            media = metadata.get("media", [])
            movie = next((a for a in media if a.get("type") in ("Movie", "Video")), None)
            if not movie or not movie.get("url"):
                raise ValueError("NASA visualization contains no video stream.")
            video_url = trusted_nasa_url(movie["url"])
            req = Request(video_url, headers={"User-Agent": "THESOUND.EARTH/1.0"})
            tmp_download = SVS_CACHE_DIR / f"{visualization_id}_{job_id}.tmp"
            downloaded = 0
            with _opener.open(req, timeout=30) as remote_resp, open(tmp_download, "wb") as f_out:
                while chunk := remote_resp.read(256 * 1024):
                    if cancel_event.is_set():
                        raise InterruptedError("Processing job cancelled.")
                    if time.time() - start_time > JOB_TIMEOUT_SECONDS:
                        raise TimeoutError(f"Job timed out after {JOB_TIMEOUT_SECONDS} seconds.")
                    f_out.write(chunk)
                    downloaded += len(chunk)
                    if downloaded > MAX_VIDEO_BYTES:
                        raise ValueError(f"Video file size exceeds maximum limit of {MAX_VIDEO_BYTES // (1024 * 1024)} MB.")
            tmp_download.replace(video_path)
            tmp_download = None

        if cancel_event.is_set():
            raise InterruptedError("Processing job cancelled.")

        file_size = video_path.stat().st_size
        if file_size > MAX_VIDEO_BYTES:
            raise ValueError(f"Video file size exceeds maximum limit of {MAX_VIDEO_BYTES // (1024 * 1024)} MB.")

        _, _, dur = probe_video_info(video_path)
        if dur > MAX_VIDEO_DURATION_SEC:
            raise ValueError(f"Video duration ({dur:.1f}s) exceeds maximum allowed limit of {MAX_VIDEO_DURATION_SEC}s.")

        with _SVS_LOCK:
            if cancel_event.is_set():
                raise InterruptedError("Processing job cancelled.")
            job["status"] = "rendering"
            job["progress"] = {"stage": "rendering", "current": 1, "total": 1}

        out_opus = SVS_CACHE_DIR / f"svs_{visualization_id}_v3.opus"
        out_meta = SVS_CACHE_DIR / f"svs_{visualization_id}_v3.json"

        if time.time() - start_time > JOB_TIMEOUT_SECONDS:
            raise TimeoutError(f"Job timed out after {JOB_TIMEOUT_SECONDS} seconds.")

        res = sonify_svs_v3(
            video_path=video_path,
            svs_id=visualization_id,
            out_opus_path=out_opus,
            out_meta_path=out_meta,
        )

        with _SVS_LOCK:
            if cancel_event.is_set():
                out_opus.unlink(missing_ok=True)
                out_meta.unlink(missing_ok=True)
                job["status"] = "cancelled"
                return

            job["status"] = "done"
            job["progress"] = {"stage": "done", "current": 1, "total": 1}
            job["result"] = {
                "audio_url": f"/output/svs_cache/{out_opus.name}",
                "audit_url": f"/output/svs_cache/{out_meta.name}",
                "meta_url": f"/output/svs_cache/{out_meta.name}",
            }
    except InterruptedError as exc:
        with _SVS_LOCK:
            job["status"] = "cancelled"
            job["error"] = str(exc)
    except TimeoutError as exc:
        with _SVS_LOCK:
            job["status"] = "failed"
            job["error"] = f"Job timed out after {JOB_TIMEOUT_SECONDS} seconds."
    except Exception as exc:
        with _SVS_LOCK:
            job["status"] = "failed"
            job["error"] = str(exc)
    finally:
        if tmp_download and tmp_download.exists():
            tmp_download.unlink(missing_ok=True)
        cleanup_abandoned_temp()


def _svs_queue_worker() -> None:
    while True:
        try:
            job_id = _SVS_QUEUE.get()
            if job_id is None:
                break
            _run_svs_v3_worker_task(job_id)
        except Exception:
            pass
        finally:
            _SVS_QUEUE.task_done()


_svs_worker_thread = threading.Thread(target=_svs_queue_worker, daemon=True)
_svs_worker_thread.start()


_VIDEO_DOWNLOAD_LOCKS: dict[int, threading.Lock] = {}
_VIDEO_LOCKS_GUARD = threading.Lock()


def _get_video_download_lock(vid: int) -> threading.Lock:
    with _VIDEO_LOCKS_GUARD:
        if vid not in _VIDEO_DOWNLOAD_LOCKS:
            _VIDEO_DOWNLOAD_LOCKS[vid] = threading.Lock()
        return _VIDEO_DOWNLOAD_LOCKS[vid]


def _select_best_mp4(media: list[dict]) -> dict | None:
    cands = []
    for m in media:
        url = m.get("url", "")
        mtype = str(m.get("type", "")).lower()
        fmt = str(m.get("format", "")).lower()
        if fmt == "mp4" or url.lower().endswith(".mp4") or mtype in ("movie", "video"):
            cands.append(m)
    if not cands:
        return None

    def score(item):
        w = item.get("width") or 0
        h = item.get("height") or 0
        area = w * h
        # Prefer standard 1080p, 720p, or 2K resolutions (area <= 2.5M pixels)
        if 1_000_000 <= area <= 2_500_000:
            return 0
        elif area > 0 and area < 1_000_000:
            return 1
        elif area > 2_500_000:
            return 2
        return 3

    cands.sort(key=score)
    return cands[0]


def _ensure_svs_video_cached(visualization_id: int, force_download: bool = False) -> Path:
    if not 1 <= visualization_id <= 999999:
        raise HTTPException(status_code=400, detail="Invalid NASA visualization ID.")
    cached_file = SVS_CACHE_DIR / f"{visualization_id}.mp4"
    if not force_download and cached_file.exists() and cached_file.stat().st_size > 0:
        try:
            os.utime(cached_file, None)
        except Exception:
            pass
        return cached_file

    with _get_video_download_lock(visualization_id):
        if not force_download and cached_file.exists() and cached_file.stat().st_size > 0:
            try:
                os.utime(cached_file, None)
            except Exception:
                pass
            return cached_file
        dist_file = Path(f"output/svs_dist/{visualization_id}/video.mp4")
        if dist_file.exists() and dist_file.stat().st_size > 0:
            shutil.copy2(dist_file, cached_file)
            try:
                os.utime(cached_file, None)
            except Exception:
                pass
            return cached_file

        try:
            metadata = get_visualization(visualization_id)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"NASA SVS upstream error: {exc}")

        media = metadata.get("media", [])
        movie = _select_best_mp4(media)
        if not movie or not movie.get("url"):
            raise HTTPException(status_code=404, detail=f"NASA visualization {visualization_id} contains no video stream.")

        try:
            video_url = trusted_nasa_url(movie["url"])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        req = Request(video_url, headers={"User-Agent": "THESOUND.EARTH/1.0"})
        tmp_cached = SVS_CACHE_DIR / f"{visualization_id}_{uuid.uuid4().hex[:8]}.tmp"
        try:
            downloaded = 0
            with _opener.open(req, timeout=30) as remote_resp, open(tmp_cached, "wb") as f_out:
                while chunk := remote_resp.read(256 * 1024):
                    f_out.write(chunk)
                    downloaded += len(chunk)
                    if downloaded > MAX_VIDEO_BYTES:
                        raise HTTPException(
                            status_code=413,
                            detail=f"Video file size exceeds maximum limit of {MAX_VIDEO_BYTES // (1024 * 1024)} MB.",
                        )
            _, _, dur = probe_video_info(tmp_cached)
            if dur > MAX_VIDEO_DURATION_SEC:
                raise HTTPException(
                    status_code=400,
                    detail=f"Video duration ({dur:.1f}s) exceeds maximum allowed limit of {MAX_VIDEO_DURATION_SEC}s.",
                )
            replaced = False
            for _ in range(5):
                try:
                    tmp_cached.replace(cached_file)
                    replaced = True
                    break
                except PermissionError:
                    time.sleep(0.1)
            if not replaced and not (cached_file.exists() and cached_file.stat().st_size > 0):
                shutil.copy2(tmp_cached, cached_file)
            try:
                os.utime(cached_file, None)
            except Exception:
                pass
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Failed to stream NASA SVS video: {exc}")
        finally:
            if tmp_cached.exists():
                try:
                    tmp_cached.unlink(missing_ok=True)
                except Exception:
                    pass

    return cached_file


@app.api_route("/api/svs/{visualization_id}/video", methods=["GET", "HEAD"])
def get_svs_visualization_video(visualization_id: int):
    cached_file = _ensure_svs_video_cached(visualization_id)
    if not cached_file.exists() or cached_file.stat().st_size == 0:
        cached_file = _ensure_svs_video_cached(visualization_id, force_download=True)

    if not cached_file.exists() or cached_file.stat().st_size == 0:
        raise HTTPException(
            status_code=404,
            detail=f"NASA SVS video {visualization_id} is unavailable or failed to download.",
        )

    try:
        os.utime(cached_file, None)
    except Exception:
        pass

    file_size = cached_file.stat().st_size
    if file_size > MAX_VIDEO_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Video file size exceeds maximum limit of {MAX_VIDEO_BYTES // (1024 * 1024)} MB.",
        )
    _, _, dur = probe_video_info(cached_file)
    if dur > MAX_VIDEO_DURATION_SEC:
        raise HTTPException(
            status_code=400,
            detail=f"Video duration ({dur:.1f}s) exceeds maximum allowed limit of {MAX_VIDEO_DURATION_SEC}s.",
        )

    return FileResponse(
        cached_file,
        media_type="video/mp4",
        headers={"Accept-Ranges": "bytes", "Access-Control-Allow-Origin": "*"},
    )


@app.post("/api/svs/{visualization_id}/sonify", status_code=202)
def start_svs_sonification(visualization_id: int, options: dict = Body(default_factory=dict)) -> dict:
    if not isinstance(options, dict):
        raise HTTPException(status_code=400, detail="Processing options must be a JSON object.")
    if not 1 <= visualization_id <= 999999:
        raise HTTPException(status_code=400, detail="Invalid NASA visualization ID.")

    cached_opus = SVS_CACHE_DIR / f"svs_{visualization_id}_v3.opus"
    cached_meta = SVS_CACHE_DIR / f"svs_{visualization_id}_v3.json"

    job_id = uuid.uuid4().hex

    # Cached by (svs_id, engine version)
    if cached_opus.exists() and cached_meta.exists():
        with _SVS_LOCK:
            _SVS_JOBS[job_id] = {
                "id": job_id,
                "svs_id": visualization_id,
                "engine_version": ENGINE_VERSION,
                "status": "done",
                "progress": {"stage": "done", "current": 1, "total": 1},
                "result": {
                    "audio_url": f"/output/svs_cache/{cached_opus.name}",
                    "audit_url": f"/output/svs_cache/{cached_meta.name}",
                    "meta_url": f"/output/svs_cache/{cached_meta.name}",
                },
                "cached": True,
            }
        return {"job_id": job_id}

    # Queue job for single-worker processing
    cancel_evt = threading.Event()
    with _SVS_LOCK:
        _SVS_JOBS[job_id] = {
            "id": job_id,
            "svs_id": visualization_id,
            "engine_version": ENGINE_VERSION,
            "status": "queued",
            "progress": {"stage": "queued", "current": 0, "total": 1},
            "cancel_event": cancel_evt,
            "created_at": time.time(),
        }
    _SVS_QUEUE.put(job_id)
    return {"job_id": job_id}


@app.get("/api/svs/jobs/{job_id}")
def get_svs_job(job_id: str) -> dict:
    with _SVS_LOCK:
        job = _SVS_JOBS.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Processing job not found.")
        return {
            "id": job["id"],
            "svs_id": job.get("svs_id"),
            "engine_version": job.get("engine_version", ENGINE_VERSION),
            "status": job["status"],
            "progress": job.get("progress"),
            "error": job.get("error"),
            "result": job.get("result"),
        }


@app.delete("/api/svs/jobs/{job_id}")
def cancel_svs_job(job_id: str) -> dict:
    with _SVS_LOCK:
        job = _SVS_JOBS.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Processing job not found.")
        if "cancel_event" in job:
            job["cancel_event"].set()
        job["status"] = "cancelled"

        # Clean up temporary video/WAV/Opus files for this job
        cleanup_abandoned_temp()
        for p in SVS_CACHE_DIR.glob(f"*{job_id}*"):
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass
        # Clean up any temporary files stored in result
        res = job.get("result")
        if isinstance(res, dict):
            for k in ("audio_url", "meta_url", "audit_url"):
                u = res.get(k)
                if u and isinstance(u, str) and u.startswith("/output/"):
                    fp = Path(u.lstrip("/"))
                    try:
                        fp.unlink(missing_ok=True)
                    except Exception:
                        pass
        return {"status": "cancelled", "job_id": job_id}


@app.post("/api/sonify")
def sonify_point(
    lat: float = Query(...),
    lon: float = Query(...),
    mode: str = Query("musical", pattern="^(musical|diagnostic)$"),
    day_idx: int | None = Query(None),
) -> dict:
    ds = load_oscar_dataset(NC_PATH)
    lon_dim = "longitude" if "longitude" in ds.coords else "lon"
    max_lon = float(ds[lon_dim].max())
    target_lon = lon if max_lon <= 180.0 else (lon % 360.0)

    wav_path, json_path = run_pipeline(
        nc_path=NC_PATH,
        config_path=CFG_PATH,
        lat=lat,
        lon=target_lon,
        out_dir=OUT_DIR,
        mode=mode,
        day_idx=day_idx,
    )
    audit = json.loads(json_path.read_text(encoding="utf-8"))
    valid_samples = [s for s in audit["samples"] if s["is_valid"]]

    full_series = [
        {"t": r["timestamp"], "u": r["u"], "v": r["v"], "speed": float(np.hypot(r["u"], r["v"]))}
        for r in extract_cell_timeseries(ds, target_lat=lat, target_lon=target_lon)
        if np.isfinite(r["u"]) and np.isfinite(r["v"]) and abs(r["u"]) <= 10 and abs(r["v"]) <= 10
    ]

    return {
        "status": "ok" if valid_samples else "land_or_masked",
        "audio_url": f"/output/{wav_path.name}?t={int(time.time() * 1000)}" if valid_samples else None,
        "audit": audit,
        "series": full_series,
    }


@app.post("/api/sonify_visual")
def sonify_visual(
    lat: float = Query(...),
    lon: float = Query(...),
    motion: float = Query(..., ge=0.0, le=1.5),
    warmth: float = Query(..., ge=-1.0, le=1.0),
    mode: str = Query("musical", pattern="^(musical|diagnostic)$"),
) -> dict:
    cfg = json.loads(CFG_PATH.read_text(encoding="utf-8"))
    u_equiv = round(warmth * motion, 4)
    v_equiv = round((1.0 - abs(warmth)) * motion, 4)

    sample = OceanSample(
        timestamp="2007-2008 (SVS-3912)",
        latitude=lat,
        longitude=lon,
        u=u_equiv,
        v=v_equiv,
        units="visual-flux",
        product_variant="UNKNOWN",
        dataset_name="NASA_SVS_3912_VISUAL_DERIVED",
        source_doi="https://svs.gsfc.nasa.gov/3912/",
        is_valid=True,
        qc_flags=("visual_derived_sonification",),
    )
    ctrl = normalize_features(extract_features(sample), cfg["normalization"])
    events = arrange_events(map_controls_to_events([ctrl], cfg["sonification"]), cfg["sonification"], mode=mode)

    wav_path = render_wav(
        events,
        cfg["sonification"]["phrase_duration_sec"],
        cfg["sonification"]["sample_rate_hz"],
        OUT_DIR / f"thesound_earth_svs_{mode}.wav",
        mode=mode,
    )
    audio_check = verify_rendered_audio(wav_path, cfg["sonification"]["sample_rate_hz"], all_invalid=False)
    json_path = write_audit_json(
        [ctrl],
        events,
        cfg,
        wav_path,
        OUT_DIR / f"thesound_earth_svs_{mode}.json",
        mode=mode,
        audio_verification=audio_check,
    )
    audit = json.loads(json_path.read_text(encoding="utf-8"))
    return {
        "status": "ok",
        "audio_url": f"/output/{wav_path.name}?t={int(time.time() * 1000)}",
        "audit": audit,
    }


@app.api_route("/api/tracks", methods=["GET", "HEAD"])
def get_tracks() -> list[dict]:
    if not FINAL_INDEX_PATH.exists():
        raise HTTPException(status_code=404, detail="final/index.json not found")

    raw_tracks = json.loads(FINAL_INDEX_PATH.read_text(encoding="utf-8"))
    ocean_cfg = json.loads(REGIONS_PATH.read_text(encoding="utf-8")) if REGIONS_PATH.exists() else {"regions": []}
    land_cfg = json.loads(LAND_REGIONS_PATH.read_text(encoding="utf-8")) if LAND_REGIONS_PATH.exists() else {"regions": []}

    region_map: dict[str, dict] = {}
    for r in ocean_cfg.get("regions", []):
        region_map[r["id"]] = r
    for r in land_cfg.get("regions", []):
        region_map[r["id"]] = r

    enriched = []
    for item in raw_tracks:
        t = dict(item)
        tid = t["id"]
        year = t.get("year", 2025)
        reg = region_map.get(tid, {})

        lat_range = reg.get("lat")
        lon_range = reg.get("lon")
        if lat_range and lon_range:
            t["lat"] = lat_range
            t["lon"] = lon_range
            c_lat = (lat_range[0] + lat_range[1]) / 2.0
            c_lon = (lon_range[0] + lon_range[1]) / 2.0
            c_lon_norm = c_lon if c_lon <= 180.0 else c_lon - 360.0
            t["center_lat"] = round(c_lat, 4)
            t["center_lon"] = round(c_lon_norm, 4)
        if "bbox" not in t and lat_range and lon_range:
            t["bbox"] = [lon_range[0], lat_range[0], lon_range[1], lat_range[1]]

        t["audio_url"] = f"/api/stream/{tid}"
        t["meta_url"] = f"/final/{year}/{tid}/meta.json"
        enriched.append(t)

    return enriched


KNOWN_REGION_IDS = {
    "gulf_stream", "kuroshio", "east_australian", "brazil_malvinas",
    "arabian_sea", "drake_acc", "nordic_seas", "amazon", "congo",
    "se_asia", "australia", "w_north_america", "siberia", "india", "europe",
}


@app.api_route("/api/stream/{region_id}", methods=["GET", "HEAD"])
def stream_region_audio(region_id: str, year: int = 2025):
    # Strip optional .opus extension if provided by caller
    clean_id = region_id[:-5] if region_id.endswith(".opus") else region_id

    # Strictly validate against known region IDs only (prevents path traversal)
    if clean_id not in KNOWN_REGION_IDS:
        raise HTTPException(status_code=404, detail="Unknown region")

    track_path = Path(f"final/{year}/{clean_id}/track.opus")
    if not track_path.exists():
        track_path = Path(f"final/2025/{clean_id}/track.opus")
    if not track_path.exists():
        raise HTTPException(status_code=404, detail="Audio track not found")

    return FileResponse(
        path=track_path,
        media_type="audio/ogg",
        headers={
            "Content-Type": "audio/ogg",
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": "inline",
        },
    )


@app.post("/api/ocean_brief")
def ocean_brief(
    ocean_name: str = Query(...),
    lat: float = Query(...),
    lon: float = Query(...),
    speed: float = Query(...),
    u: float = Query(...),
    v: float = Query(...),
    angle: float = Query(...),
    timestamp: str = Query(...),
) -> dict:
    try:
        client = _get_genai_client()
        if client is None:
            return {"brief": "Set $env:GEMINI_API_KEY in PowerShell to enable Gemini ocean briefings."}

        prompt = (
            f"You are a physical oceanographer. In 3 concise sentences, explain the current state of "
            f"{ocean_name} at ({lat:.2f}°, {lon:.2f}°) on {timestamp}, given measured surface current values: "
            f"speed={speed:.3f} m/s, u={u:.3f} m/s (eastward), v={v:.3f} m/s (northward), bearing={angle:.1f}°. "
            f"Mention the major current system or gyre here and what this flow means for heat transport or "
            f"marine conditions. Do not invent extra numbers."
        )
        try:
            resp = client.models.generate_content(model="gemini-3.8-flash", contents=prompt)
        except Exception as model_err:
            err_str = str(model_err).lower()
            if "not found" in err_str or "no longer available" in err_str or "404" in err_str:
                resp = client.models.generate_content(model="gemini-3.5-flash-lite", contents=prompt)
            else:
                raise
        return {"brief": resp.text.strip()}
    except Exception as exc:
        return {"brief": f"Gemini API error: {exc}"}


MAX_CONCURRENT_JOBS = 3
_ACTIVE_JOBS = 0
_JOB_LOCK = threading.Lock()


class VoiceNavigateRequest(BaseModel):
    transcript: Optional[str] = None
    active_region_id: Optional[str] = None
    audio_base64: Optional[str] = None
    mime_type: Optional[str] = "audio/webm"


class GenerateMusicRequest(BaseModel):
    svs_id: Optional[str] = None
    frames: Optional[list[str]] = None
    frames_b64: Optional[list[str]] = None
    frame_energies: Optional[list[dict[str, Any]]] = None
    region_id: Optional[str] = None
    mode: str = "musical"


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "kokoro_ready": KOKORO.is_ready,
        "whisper_ready": WHISPER.is_ready,
        "gemini_keys_loaded": ROTATOR.key_count,
        "active_jobs": _ACTIVE_JOBS,
    }


@app.get("/api/welcome-audio")
def welcome_audio(stage: int = 1) -> dict:
    prompt = STAGE2_GUIDE_PROMPT if stage == 2 else WELCOME_PROMPT
    b64 = KOKORO.get_cached_audio(prompt)
    if not b64 and KOKORO.is_ready:
        b64 = KOKORO.synthesize_opus_base64(prompt)
    return {
        "status": "ok",
        "stage": stage,
        "text": prompt,
        "audio_base64": b64,
    }


@app.get("/api/guide-audio")
def guide_audio() -> dict:
    return welcome_audio(stage=2)


@app.post("/api/voice-navigate")
def voice_navigate(req: VoiceNavigateRequest) -> dict:
    return process_voice_navigation(
        transcript=req.transcript,
        active_region_id=req.active_region_id,
        audio_base64=req.audio_base64,
        mime_type=req.mime_type or "audio/webm",
    )


@app.post("/api/generate-music")
def generate_music(req: GenerateMusicRequest) -> Response:
    global _ACTIVE_JOBS
    with _JOB_LOCK:
        if _ACTIVE_JOBS >= MAX_CONCURRENT_JOBS:
            cached_audio = KOKORO.get_cached_429_audio()
            return JSONResponse(
                status_code=429,
                content={
                    "error": "Too Many Requests",
                    "message": "Many people are using the music generator right now. Please try again in a few seconds.",
                    "retry_after": 5,
                    "audio_base64": cached_audio,
                },
            )
        _ACTIVE_JOBS += 1

    try:
        # 1. Custom / GPU frame energies directly from offscreen canvas
        if req.frame_energies and len(req.frame_energies) > 0:
            track_tag = f"svs_{req.svs_id}" if req.svs_id else "custom_visual"
            opus_path, info = sonify_frame_energies(
                req.frame_energies,
                OUT_DIR,
                track_id=track_tag,
                mode=req.mode,
            )
            raw_opus = opus_path.read_bytes()
            b64_opus = base64.b64encode(raw_opus).decode("ascii")
            return JSONResponse(content={
                "status": "ok",
                "audio_url": f"/output/{opus_path.name}",
                "audio_base64": b64_opus,
                "info": info,
                "bars_summary": info.get("bars_summary", []),
            })

        # 2. Base64 encoded video frames
        raw_frames = req.frames or req.frames_b64
        if raw_frames and len(raw_frames) > 0:
            track_tag = f"svs_{req.svs_id}" if req.svs_id else "custom_visual"
            opus_path, info = sonify_extracted_frames(
                raw_frames,
                OUT_DIR,
                track_id=track_tag,
                mode=req.mode,
            )
            raw_opus = opus_path.read_bytes()
            b64_opus = base64.b64encode(raw_opus).decode("ascii")
            return JSONResponse(content={
                "status": "ok",
                "audio_url": f"/output/{opus_path.name}",
                "audio_base64": b64_opus,
                "info": info,
                "bars_summary": info.get("bars_summary", []),
            })

        # 3. NASA SVS visualization ID (server-side stream and flow)
        if req.svs_id:
            vid_path = None
            for cand in [
                OUT_DIR / "svs_cache" / f"{req.svs_id}.mp4",
                OUT_DIR / "svs_cache" / f"{req.svs_id}.webm",
                WEB_DIR / "ecco2_sst_flow.mp4",
            ]:
                if cand.exists():
                    vid_path = cand
                    break
            if vid_path is None:
                try:
                    vid_path = _ensure_svs_video_cached(int(req.svs_id))
                except Exception as exc:
                    raise HTTPException(status_code=404, detail=f"Could not load SVS video {req.svs_id}: {exc}")

            job_uid = uuid.uuid4().hex[:8]
            opus_p = OUT_DIR / f"svs_{req.svs_id}_{job_uid}.opus"
            meta_p = OUT_DIR / f"svs_{req.svs_id}_{job_uid}.json"
            res = sonify_svs_v3(vid_path, svs_id=req.svs_id, out_opus_path=opus_p, out_meta_path=meta_p)
            raw_opus = opus_p.read_bytes()
            b64_opus = base64.b64encode(raw_opus).decode("ascii")
            return JSONResponse(content={
                "status": "ok",
                "audio_url": f"/output/{opus_p.name}",
                "audio_base64": b64_opus,
                "meta": res,
            })

        # 4. Canonical pre-rendered regional tracks (ONLY when no visual/frame data provided)
        if req.region_id and req.region_id in REGION_PROFILES:
            opus_p = Path(f"final/2025/{req.region_id}/track.opus")
            if opus_p.exists():
                raw_opus = opus_p.read_bytes()
                b64_opus = base64.b64encode(raw_opus).decode("ascii")
                return JSONResponse(content={
                    "status": "ok",
                    "audio_url": f"/api/stream/{req.region_id}",
                    "audio_base64": b64_opus,
                    "region_id": req.region_id,
                })

        raise HTTPException(status_code=400, detail="Must provide svs_id, frame_energies, frames, or region_id")
    finally:
        with _JOB_LOCK:
            _ACTIVE_JOBS = max(0, _ACTIVE_JOBS - 1)


# Mount web directory for static assets (e.g. /credits.html, /flow.worker.js, etc.)
if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")


def main() -> None:
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()