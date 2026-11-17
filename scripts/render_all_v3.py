"""render_all_v3.py — Batch render all 15 regional tracks using AetherWaves Engine v3.

Renders:
  Ocean (7):
    - gulf_stream
    - kuroshio
    - east_australian
    - brazil_malvinas
    - arabian_sea
    - drake_acc
    - nordic_seas
  Land (8):
    - amazon
    - congo
    - se_asia
    - australia
    - w_north_america
    - siberia
    - india
    - europe

Enforces:
  1. Complete 100% determinism (run 1 vs run 2 bit-exact check for MIDI, WAV, Opus).
  2. FluidSynth + FluidR3_GM only; no CC11.
  3. Loudnorm -24 LUFS, 48k bitexact mono Opus.
  4. File sizes strictly under 1.5 MB.
  5. Updates final/2025/<id>/track.opus and final/2025/<id>/meta.json.
  6. Generates updated final/index.json with checksums and byte sizes.
  7. Strict banned words validation.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from aetherwaves.adapters.canopy import CanopyAdapter
from aetherwaves.adapters.fires import FIRMSAdapter
from aetherwaves.adapters.oscar import OscarAdapter
from aetherwaves.blocks import group_days_into_blocks
from aetherwaves.engine_v3.form_v3 import compute_form_sections
from aetherwaves.engine_v3.harmony_v3 import generate_harmony_v3
from aetherwaves.engine_v3.melody_v3 import generate_melody_v3
from aetherwaves.engine_v3.pipeline_v3 import (
    analyze_v3_audio,
    build_midi_v3,
    render_v3_audio,
)
from aetherwaves.engine_v3.rhythm_v3 import generate_drum_events_v3
from aetherwaves.rhythm import normalize_series_5_95
from scripts.generate_meta_v3 import build_meta_v3, check_banned_words


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def compute_siberia_weekly_centroids(cache_dir: Path) -> list[tuple[float | None, float | None, int]]:
    """Compute 53 weekly centroids from cached Siberia CSVs."""
    start_date = date(2025, 1, 1)
    daily_records: list[dict[str, Any]] = []

    for d in range(365):
        cur_date = start_date + timedelta(days=d)
        d_str = cur_date.isoformat()
        f_path = cache_dir / f"{d_str}.csv"
        lats: list[float] = []
        lons: list[float] = []
        if f_path.exists():
            with open(f_path, encoding="utf-8") as fp:
                for r in csv.DictReader(fp):
                    try:
                        lats.append(float(r["latitude"]))
                        lons.append(float(r["longitude"]))
                    except (ValueError, KeyError):
                        pass
        daily_records.append({"date": d_str, "lats": lats, "lons": lons, "count": len(lats)})

    weekly_centroids: list[tuple[float | None, float | None, int]] = []
    for b_idx in range(53):
        chunk = daily_records[b_idx * 7 : min((b_idx + 1) * 7, 365)]
        all_lats: list[float] = []
        all_lons: list[float] = []
        total_cnt = 0
        for day in chunk:
            all_lats.extend(day["lats"])
            all_lons.extend(day["lons"])
            total_cnt += day["count"]
        if total_cnt > 0:
            c_lat = float(np.mean(all_lats))
            c_lon = float(np.mean(all_lons))
            weekly_centroids.append((c_lat, c_lon, total_cnt))
        else:
            weekly_centroids.append((None, None, 0))

    return weekly_centroids


def render_single_track(
    track_id: str,
    preset: dict[str, Any],
    temp_dir: Path,
    final_dir: Path,
    region_info: dict[str, Any],
) -> dict[str, Any]:
    print(f"\n{'='*70}\n[v3 Pipeline] Processing track: {track_id} ({preset['scale_name']}, {preset['tempo']} BPM)\n{'='*70}")
    seed_str = hashlib.sha256(f"{track_id}:2025".encode("utf-8")).hexdigest()
    seed_int = int(seed_str, 16)
    domain = preset["domain"]

    # 1. Load data
    canopy_rows = None
    fire_centroids = None

    if domain == "ocean":
        src = REPO_ROOT / ("data/raw_oscar/oscar_2025_daily.json" if track_id == "gulf_stream" else f"data/raw_oscar/regions/{track_id}/oscar_2025_daily.json")
        adapter = OscarAdapter(src)
        daily_rows = adapter.rows()
    elif domain == "land_combined":
        land_cfg = json.load(open(REPO_ROOT / "config/land_regions.json", encoding="utf-8"))["regions"]
        r_entry = next(r for r in land_cfg if r["id"] == track_id)
        f = r_entry["fires"]
        adapter = FIRMSAdapter(west=f["lon"][0], south=f["lat"][0], east=f["lon"][1], north=f["lat"][1], year=2025)
        daily_rows = adapter.rows()

        # Load canopy transect
        c_adapter = CanopyAdapter(meridian_lon=r_entry.get("canopy_meridian", 0.0))
        canopy_rows = c_adapter.rows()
    else:  # land_fire_only (siberia)
        land_cfg = json.load(open(REPO_ROOT / "config/land_regions.json", encoding="utf-8"))["regions"]
        r_entry = next(r for r in land_cfg if r["id"] == track_id)
        f = r_entry["fires"]
        adapter = FIRMSAdapter(west=f["lon"][0], south=f["lat"][0], east=f["lon"][1], north=f["lat"][1], year=2025)
        daily_rows = adapter.rows()

        cache_dir = REPO_ROOT / f"output/firms_cache/{f['lon'][0]}_{f['lat'][0]}_{f['lon'][1]}_{f['lat'][1]}_VIIRS_SNPP_SP/2025"
        fire_centroids = compute_siberia_weekly_centroids(cache_dir)

    # 2. Group into 53 weekly blocks
    blocks = group_days_into_blocks(daily_rows, block_size=7)
    norm_speeds, _ = normalize_series_5_95(blocks)
    raw_series = [b.get("speed_p95") for b in blocks]

    # 3. Form detection
    form_info = compute_form_sections(raw_series)

    # 4. Generate harmonic & rhythmic structures
    harmony_bars = generate_harmony_v3(
        blocks=blocks,
        preset=preset,
        track_id=track_id,
        form_info=form_info,
        canopy_rows=canopy_rows,
        fire_centroids=fire_centroids,
    )

    rest_bars = [h.is_rest for h in harmony_bars]
    drum_events, effective_tiers, tier_counts = generate_drum_events_v3(
        norm_speeds=norm_speeds,
        preset=preset,
        track_id=track_id,
        seed=seed_int,
        rest_bars=rest_bars,
    )

    melody_bars, color_tone_bars = generate_melody_v3(
        blocks=blocks,
        norm_speeds=norm_speeds,
        harmony_bars=harmony_bars,
        preset=preset,
        seed=seed_int,
    )

    # 5. Deterministic verification: Run 1 & Run 2
    track_tmp = temp_dir / track_id
    r1_dir = track_tmp / "run1"
    r2_dir = track_tmp / "run2"
    r1_dir.mkdir(parents=True, exist_ok=True)
    r2_dir.mkdir(parents=True, exist_ok=True)

    mid1 = r1_dir / "track.mid"
    wav1 = r1_dir / "track.wav"
    opus1 = r1_dir / "track.opus"

    mid2 = r2_dir / "track.mid"
    wav2 = r2_dir / "track.wav"
    opus2 = r2_dir / "track.opus"

    build_midi_v3(blocks, norm_speeds, harmony_bars, melody_bars, drum_events, preset, mid1)
    render_v3_audio(mid1, wav1, opus1, target_lufs=-24.0)

    build_midi_v3(blocks, norm_speeds, harmony_bars, melody_bars, drum_events, preset, mid2)
    render_v3_audio(mid2, wav2, opus2, target_lufs=-24.0)

    h_mid1, h_mid2 = sha256_file(mid1), sha256_file(mid2)
    h_wav1, h_wav2 = sha256_file(wav1), sha256_file(wav2)
    h_opus1, h_opus2 = sha256_file(opus1), sha256_file(opus2)

    assert h_mid1 == h_mid2, f"MIDI hash mismatch on {track_id}"
    assert h_wav1 == h_wav2, f"WAV hash mismatch on {track_id}"
    assert h_opus1 == h_opus2, f"Opus hash mismatch on {track_id}"

    # 6. Audio analysis from run1 WAV
    audio_analysis, sample_step = analyze_v3_audio(wav1, form_info["sections"], preset["tempo"])

    # 7. Write to final directory
    out_dir = final_dir / "2025" / track_id
    out_dir.mkdir(parents=True, exist_ok=True)

    target_opus = out_dir / "track.opus"
    shutil.copy2(opus1, target_opus)

    opus_bytes = target_opus.stat().st_size
    assert opus_bytes < 1.5 * 1024 * 1024, f"Opus size {opus_bytes} exceeds 1.5 MB limit"

    checksums = {
        "midi_sha256": h_mid1,
        "wav_sha256": h_wav1,
        "opus_sha256": h_opus1,
    }

    meta = build_meta_v3(
        track_id=track_id,
        preset=preset,
        blocks=blocks,
        norm_speeds=norm_speeds,
        harmony_bars=harmony_bars,
        melody_bars=melody_bars,
        effective_tiers=effective_tiers,
        tier_counts=tier_counts,
        form_info=form_info,
        audio_analysis=audio_analysis,
        sample_step=sample_step,
        color_tone_bars=color_tone_bars,
        checksums=checksums,
    )

    meta_json_str = json.dumps(meta, indent=2)
    violations = check_banned_words(meta_json_str, f"meta.json for {track_id}")
    if violations:
        raise ValueError(f"Banned words violations in {track_id} meta:\n" + "\n".join(violations))

    target_meta = out_dir / "meta.json"
    target_meta.write_text(meta_json_str, encoding="utf-8", newline="\n")

    print(f"Verified {track_id}:")
    print(f"  Opus size: {opus_bytes:,} bytes")
    print(f"  Opus SHA-256: {h_opus1}")
    print(f"  Sample step click check: {sample_step:.6f}")

    return {
        "id": track_id,
        "domain": domain,
        "region": region_info["name"],
        "year": 2025,
        "bbox": region_info["bbox"],
        "bars": 53,
        "tempo": preset["tempo"],
        "bar_seconds": preset["bar_seconds"],
        "duration_s": round(53 * preset["bar_seconds"], 1),
        "scale": preset["scale_name"],
        "key": "C",
        "bytes": opus_bytes,
        "checksum": h_opus1,
    }


def main():
    presets_cfg = json.load(open(REPO_ROOT / "config/presets_v3.json", encoding="utf-8"))["presets"]
    ocean_regions = {r["id"]: r for r in json.load(open(REPO_ROOT / "config/regions.json", encoding="utf-8"))["regions"]}
    land_regions = {r["id"]: r for r in json.load(open(REPO_ROOT / "config/land_regions.json", encoding="utf-8"))["regions"]}

    final_dir = REPO_ROOT / "final"
    temp_dir = REPO_ROOT / "tmp" / "v3_render_all"
    temp_dir.mkdir(parents=True, exist_ok=True)

    track_ids = [
        "gulf_stream",
        "kuroshio",
        "east_australian",
        "brazil_malvinas",
        "arabian_sea",
        "drake_acc",
        "nordic_seas",
        "amazon",
        "congo",
        "se_asia",
        "australia",
        "w_north_america",
        "siberia",
        "india",
        "europe",
    ]

    index_entries: list[dict[str, Any]] = []

    for tid in track_ids:
        preset = presets_cfg[tid]
        domain = preset["domain"]
        if domain == "ocean":
            r_cfg = ocean_regions[tid]
            bbox = [r_cfg["lon"][0], r_cfg["lat"][0], r_cfg["lon"][1], r_cfg["lat"][1]]
            name = r_cfg["name"]
        else:
            r_cfg = land_regions[tid]
            f = r_cfg["fires"]
            bbox = [f["lon"][0], f["lat"][0], f["lon"][1], f["lat"][1]]
            name = r_cfg["name"]

        region_info = {
            "name": name,
            "bbox": bbox,
        }

        entry = render_single_track(tid, preset, temp_dir, final_dir, region_info)
        index_entries.append(entry)

    # Write final/index.json
    index_json_str = json.dumps(index_entries, indent=2)
    violations = check_banned_words(index_json_str, "final/index.json")
    if violations:
        raise ValueError(f"Banned words violations in index.json:\n" + "\n".join(violations))

    index_path = final_dir / "index.json"
    index_path.write_text(index_json_str, encoding="utf-8", newline="\n")

    print("\n" + "="*80)
    print("ALL 15 TRACKS RENDERED AND VERIFIED SUCCESSFULLY")
    print(f"Updated: {index_path.resolve()}")
    print("="*80)
    print(f"{'Track ID':<18} | {'Domain':<14} | {'Tempo':<6} | {'Duration (s)':<12} | {'Bytes':<10} | {'Opus SHA-256'}")
    print("-" * 110)
    for e in index_entries:
        print(f"{e['id']:<18} | {e['domain']:<14} | {e['tempo']:<6} | {e['duration_s']:<12} | {e['bytes']:<10} | {e['checksum'][:16]}...")


if __name__ == "__main__":
    main()
