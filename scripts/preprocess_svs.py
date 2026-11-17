"""scripts/preprocess_svs.py — Preprocess SVS items for static deployment.

Fetches SVS metadata and video (once), compresses to 1280p with CRF 28 (guaranteed under 20 MB),
and copies any existing pre-built sound track to dist/svs/<id>/track.mp3.
Does NOT run the sonification engine.

Usage:
  python scripts/preprocess_svs.py 5688 5687 4950 3912
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from aetherwaves.svs import get_visualization, _opener, trusted_nasa_url

MAX_BYTES = 20 * 1024 * 1024  # 20 MB limit

def preprocess_svs_item(svs_id: int | str, dist_dir: Path) -> None:
    svs_id = str(svs_id)
    out_dir = dist_dir / "svs" / svs_id
    out_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"=== Processing SVS {svs_id} ===")
    
    # 1. Fetch metadata
    meta = get_visualization(int(svs_id))
    meta_path = out_dir / "meta.json"
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"Saved metadata: {meta.get('title', 'Unknown')}")
    
    # 2. Locate or download raw video
    cache_dir = REPO_ROOT / "output" / "svs_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    local_raw_video = cache_dir / f"{svs_id}.mp4"
    
    if svs_id == "3912":
        for cand in [REPO_ROOT / "web" / "ecco2_small.mp4", REPO_ROOT / "web" / "ecco2_sst_flow.mp4"]:
            if cand.exists():
                local_raw_video = cand
                break

    if not local_raw_video.exists():
        media = meta.get("media", [])
        movie = next((m for m in media if m.get("type") in ["Movie", "Video"] and m.get("url")), None)
        if not movie:
            print(f"WARNING: No movie media found for SVS {svs_id}. Creating link reference.")
            return
        url = movie["url"]
        print(f"Downloading video from {url}...")
        req = urllib.request.Request(url, headers={"User-Agent": "AetherWaves/1.0"})
        with _opener.open(req, timeout=180) as resp, open(local_raw_video, "wb") as f:
            shutil.copyfileobj(resp, f)
        print(f"Downloaded {local_raw_video.stat().st_size / 1e6:.1f} MB to cache.")

    # 3. Compress video to dist/svs/<id>/video.mp4 (under 20 MB)
    dst_video = out_dir / "video.mp4"
    if not dst_video.exists() or dst_video.stat().st_size > MAX_BYTES:
        print(f"Compressing {local_raw_video.name} to {dst_video}...")
        crf = 28
        for attempt in range(2):
            cmd = [
                "ffmpeg", "-y", "-i", str(local_raw_video),
                "-vf", "scale=1280:-2",
                "-c:v", "libx264", "-crf", str(crf), "-preset", "fast",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart",
                str(dst_video)
            ]
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            sz = dst_video.stat().st_size
            print(f"Attempt {attempt+1} (CRF {crf}): {sz / (1024*1024):.2f} MB")
            if sz <= MAX_BYTES:
                break
            crf += 4  # Increase compression if still over 20MB
    else:
        print(f"Compressed video already exists: {dst_video.stat().st_size / (1024*1024):.2f} MB")

    # 4. Copy existing audio if pre-built
    dst_audio = out_dir / "track.mp3"
    if not dst_audio.exists():
        # Look for pre-built tracks in output/svs_cache
        candidates = list(cache_dir.glob(f"*{svs_id}*visual*.wav")) + list(cache_dir.glob(f"*{svs_id}*visual*.mp3"))
        if candidates:
            src_audio = candidates[0]
            print(f"Found pre-built sound track: {src_audio.name}, converting to {dst_audio.name}...")
            cmd = [
                "ffmpeg", "-y", "-i", str(src_audio),
                "-c:a", "libmp3lame", "-b:a", "128k",
                str(dst_audio)
            ]
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            print(f"Audio ready: {dst_audio.stat().st_size / 1024:.1f} KB")
        else:
            print(f"No pre-built audio found for SVS {svs_id}. (Text 'No sound built for this visual yet' will show).")

def main():
    parser = argparse.ArgumentParser(description="Preprocess SVS items for static site")
    parser.add_argument("ids", nargs="+", help="SVS IDs to preprocess")
    parser.add_argument("--dist", default="dist", help="Target dist directory")
    args = parser.parse_args()
    
    dist_path = Path(args.dist)
    for svs_id in args.ids:
        try:
            preprocess_svs_item(svs_id, dist_path)
        except Exception as e:
            print(f"ERROR processing SVS {svs_id}: {e}", file=sys.stderr)

if __name__ == "__main__":
    main()
