"""scripts/build_static.py — Build static site distribution for Cloudflare Pages.

Creates a completely standalone static folder `dist/` that runs with NO Python server.
All dynamic APIs (/api/grid, /api/oscar_daily, SVS items) are pre-computed as static files.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from aetherwaves.server import get_global_grid, NC_PATH
from preprocess_svs import preprocess_svs_item

DIST_DIR = REPO_ROOT / "dist"
WEB_DIR = REPO_ROOT / "web"
DATA_DIR = REPO_ROOT / "data"
RAW_OSCAR_DIR = DATA_DIR / "raw_oscar"

MAX_FILE_BYTES = 20 * 1024 * 1024  # 20 MB target warning threshold

def _handle_remove_readonly(func, path, exc):
    import stat
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        pass

def clean_dist():
    if DIST_DIR.exists():
        print(f"Cleaning existing {DIST_DIR}...")
        try:
            shutil.rmtree(DIST_DIR, onexc=_handle_remove_readonly)
        except TypeError:
            shutil.rmtree(DIST_DIR, onerror=_handle_remove_readonly)
    DIST_DIR.mkdir(parents=True, exist_ok=True)

def copy_web_assets():
    print("Copying core web assets...")
    api_base = os.environ.get("API_BASE", "").strip().rstrip("/")
    for fname in ["index.html", "flow.worker.js", "credits.html"]:
        src = WEB_DIR / fname
        if src.exists():
            if fname == "index.html" and api_base:
                content = src.read_text(encoding="utf-8")
                if '<meta name="api-base" content="" />' in content:
                    content = content.replace(
                        '<meta name="api-base" content="" />',
                        f'<meta name="api-base" content="{api_base}" />',
                    )
                else:
                    import re
                    content = re.sub(
                        r'<meta\s+name=["\']api-base["\']\s+content=["\'][^"\']*["\']\s*/?>',
                        f'<meta name="api-base" content="{api_base}" />',
                        content,
                    )
                (DIST_DIR / fname).write_text(content, encoding="utf-8")
                print(f"  Copied {fname} with API_BASE={api_base}")
            else:
                shutil.copy2(src, DIST_DIR / fname)
                print(f"  Copied {fname}")
        else:
            print(f"  Warning: {src} not found")

def copy_data_and_audio():
    print("Copying data and audio tracks...")
    dist_data = DIST_DIR / "data"
    dist_data.mkdir(parents=True, exist_ok=True)
    
    # 1. web/data contents (tracks.json, audit_*.json, source_info.json, etc.)
    web_data = WEB_DIR / "data"
    if web_data.exists():
        for item in web_data.iterdir():
            if item.is_file() and not item.name.startswith("screenshot"):
                shutil.copy2(item, dist_data / item.name)
    
    # 2. Daily OSCAR files from data/raw_oscar
    for item in RAW_OSCAR_DIR.glob("oscar_*_daily.json"):
        shutil.copy2(item, dist_data / item.name)
        print(f"  Copied {item.name}")
        
    # 3. Audio tracks from web/tracks and web/audio
    dist_tracks = DIST_DIR / "tracks"
    dist_tracks.mkdir(parents=True, exist_ok=True)
    web_tracks = WEB_DIR / "tracks"
    if web_tracks.exists():
        for pattern in ["*.mp3", "*.ogg"]:
            for item in web_tracks.glob(pattern):
                shutil.copy2(item, dist_tracks / item.name)
                print(f"  Copied track {item.name}")

    dist_audio = DIST_DIR / "audio"
    dist_audio.mkdir(parents=True, exist_ok=True)
    web_audio = WEB_DIR / "audio"
    if web_audio.exists():
        for pattern in ["*.mp3", "*.ogg"]:
            for item in web_audio.glob(pattern):
                shutil.copy2(item, dist_audio / item.name)
                print(f"  Copied audio {item.name}")

def precompute_grid():
    print("Pre-computing global grid (/api/grid -> /data/grid/4_<day_idx>.json)...")
    grid_dir = DIST_DIR / "data" / "grid"
    grid_dir.mkdir(parents=True, exist_ok=True)
    
    # Check available days in NC_PATH
    g0 = get_global_grid(step=4, day_idx=0)
    dates = g0.get("dates", ["2026-01-01"])
    num_days = len(dates)
    print(f"  Dataset contains {num_days} real days of grid data.")
    
    manifest = []
    for day_idx in range(num_days):
        g = get_global_grid(step=4, day_idx=day_idx) if day_idx > 0 else g0
        filename = f"4_{day_idx}.json"
        out_p = grid_dir / filename
        out_p.write_text(json.dumps(g), encoding="utf-8")
        date_str = dates[day_idx] if day_idx < len(dates) else "2026-01-01"
        manifest.append({
            "day_idx": day_idx,
            "date": date_str,
            "file": filename
        })
    
    # Write manifest dist/data/grid/index.json
    manifest_p = grid_dir / "index.json"
    manifest_p.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"  Generated {num_days} static grid files and index.json in {grid_dir.relative_to(REPO_ROOT)}.")

def copy_and_compress_video():
    print("Preparing background video (ecco2_small.mp4 under 20 MB)...")
    src_video = WEB_DIR / "ecco2_small.mp4"
    if not src_video.exists():
        src_video = WEB_DIR / "ecco2_sst_flow.mp4"
        
    dst_video = DIST_DIR / "ecco2_small.mp4"
    
    if src_video.exists():
        # Check size; if over 20 MB, compress with ffmpeg
        if src_video.stat().st_size <= MAX_FILE_BYTES:
            shutil.copy2(src_video, dst_video)
            print(f"  Copied directly: {dst_video.stat().st_size / (1024*1024):.2f} MB")
        else:
            print(f"  Source video is {src_video.stat().st_size / (1024*1024):.2f} MB. Compressing to < 20 MB...")
            cmd = [
                "ffmpeg", "-y", "-i", str(src_video),
                "-vf", "scale=1280:-2",
                "-c:v", "libx264", "-crf", "30", "-preset", "fast",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart",
                str(dst_video)
            ]
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            print(f"  Compressed video ready: {dst_video.stat().st_size / (1024*1024):.2f} MB")
    else:
        print("  Warning: No ecco2 video found in web/")

def build_svs():
    print("Preparing static SVS catalog items (5688, 5687, 4950, 3912)...")
    cache_svs = REPO_ROOT / "output" / "svs_dist"
    target_svs = DIST_DIR / "svs"
    target_svs.mkdir(parents=True, exist_ok=True)
    
    for svs_id in ["5688", "5687", "4950", "3912"]:
        src_id_dir = cache_svs / svs_id
        dst_id_dir = target_svs / svs_id
        if src_id_dir.exists() and (src_id_dir / "video.mp4").exists():
            shutil.copytree(src_id_dir, dst_id_dir, dirs_exist_ok=True)
            print(f"  Copied cached SVS {svs_id} assets")
        else:
            try:
                preprocess_svs_item(svs_id, DIST_DIR)
            except Exception as e:
                print(f"  Error preprocessing SVS {svs_id}: {e}", file=sys.stderr)

def write_headers():
    print("Writing Cloudflare Pages _headers file...")
    headers_content = (
        "/tracks/*\n"
        "  Cache-Control: public, max-age=86400\n"
        "\n"
        "/audio/*\n"
        "  Cache-Control: public, max-age=86400\n"
        "\n"
        "/svs/*\n"
        "  Cache-Control: public, max-age=86400\n"
        "\n"
        "/*.mp4\n"
        "  Cache-Control: public, max-age=86400\n"
        "\n"
        "/data/*\n"
        "  Cache-Control: public, max-age=86400\n"
    )
    (DIST_DIR / "_headers").write_text(headers_content, encoding="utf-8")

def report_dist_stats():
    print("\n==================================================")
    print("=== Dist Directory Static Build Report ===")
    print("==================================================")
    
    total_bytes = 0
    large_files = []
    file_count = 0
    
    for root, dirs, files in os.walk(DIST_DIR):
        # Exclude any edge_profile or screenshots if accidentally present
        if "edge_profile" in root:
            continue
        for f in files:
            if f.startswith("screenshot_"):
                continue
            fp = Path(root) / f
            sz = fp.stat().st_size
            total_bytes += sz
            file_count += 1
            if sz > MAX_FILE_BYTES:
                large_files.append((fp.relative_to(DIST_DIR), sz))
                
    print(f"Total static files: {file_count}")
    print(f"Total dist size:    {total_bytes / (1024*1024):.2f} MB")
    
    if large_files:
        print(f"\nFiles over 20 MB ({len(large_files)}):")
        for rel_path, sz in large_files:
            print(f"  - {rel_path}: {sz / (1024*1024):.2f} MB (Limit: 25 MB)")
    else:
        print("\nAll files are under 20 MB (Cloudflare Pages 25 MB limit fully respected).")
    print("==================================================")

def main():
    clean_dist()
    copy_web_assets()
    copy_data_and_audio()
    precompute_grid()
    copy_and_compress_video()
    build_svs()
    write_headers()
    report_dist_stats()

if __name__ == "__main__":
    main()
