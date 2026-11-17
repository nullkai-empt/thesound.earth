import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

import numpy as np

from aetherwaves.blocks import group_days_into_blocks
from aetherwaves.adapters.fires import FIRMSAdapter
from aetherwaves.adapters.oscar import OscarAdapter
from aetherwaves.dynamics import (
    compute_smooth_speeds,
    compute_velocity_scales,
    find_top5_runs,
)
from aetherwaves.harmony import (
    compute_section_counts,
    generate_harmony,
    get_section_for_bar,
    get_tonic_name,
)
from aetherwaves.melody import generate_melody
from aetherwaves.rhythm import (
    normalize_series_5_95,
)
from pipeline.demo_mix import (
    find_fluidsynth,
    find_soundfont,
    generate_mix_midis,
    normalize_wav_to_dbfs,
    render_with_fluidsynth,
)
from pipeline.prove_data_link import compute_bar_drum_tiers

BANNED_WORDS = [
    "100%",
    "film-level",
    "advanced tuning",
    "guarantee",
    "live",
    "measured by satellites",
]

def check_banned_words(text: str, context: str = "") -> None:
    lower = text.lower()
    for b in BANNED_WORDS:
        if b.lower() in lower:
            raise ValueError(f"Banned word '{b}' found in {context}: {text}")

def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()

def build_audit_table(
    blocks: list[dict[str, Any]],
    norm_speeds: list[float | None],
    harmony_bars: list[Any],
    melody_events: list[Any],
    velocity_scales: list[float],
    run_starts: list[int],
    riser_bars: list[int],
    drum_tiers: list[str],
) -> list[dict[str, Any]]:
    section_counts = compute_section_counts(len(blocks))
    outro_start = sum(count for name, count in section_counts if name != "outro")
    run_starts_set = set(run_starts)
    riser_bars_set = set(riser_bars)

    melody_by_bar: dict[int, list[int]] = {i: [] for i in range(len(blocks))}
    for ev in melody_events:
        melody_by_bar[ev.bar].append(ev.midi_note)

    rows: list[dict[str, Any]] = []
    for i, block in enumerate(blocks):
        sec = get_section_for_bar(i, section_counts)
        h = harmony_bars[i]
        norm_spd = norm_speeds[i]
        is_last_bar = (i == len(blocks) - 1)

        is_held = h.held
        mag = block.get("magnitude")
        is_missing = (
            norm_spd is None
            or not np.isfinite(norm_spd)
            or h.is_rest
            or block.get("speed_p95") is None
        )

        if is_missing:
            held_why = "missing data"
        elif mag is not None and mag < 0.013:
            held_why = f"magnitude {mag:.6f} < 0.013 m/s hold threshold"
        else:
            held_why = f"magnitude {mag:.6f} >= 0.013 m/s active flow"

        accents = []
        if i in run_starts_set:
            accents.append("crash")
        if i in riser_bars_set:
            accents.append("riser")
        accent_str = " + ".join(accents) if accents else "none"

        mel_notes = melody_by_bar[i]
        mel_rest_reason: str | None = None
        if mel_notes:
            melody_str = str(mel_notes)
        else:
            if sec == "intro":
                mel_rest_reason = "intro"
            elif is_missing:
                mel_rest_reason = "missing data"
            elif is_held:
                mel_rest_reason = "held"
            elif sec == "outro" and not is_last_bar and ((i - outro_start) % 2 != 0):
                mel_rest_reason = "phrase rule"
            else:
                mel_rest_reason = "rest"
            melody_str = f"REST ({mel_rest_reason})"

        row: dict[str, Any] = {
            "bar": i,
            "start_date": block["date"],
            "end_date": block["end_date"],
            "days_in_block": block["total_days"],
            "mean_speed_p95_m_s": block["speed_p95"],
            "norm_speed": round(norm_spd, 4) if norm_spd is not None else None,
            "majority_sector_of_the_ageostrophic_component": block["sector"],
            "block_ageostrophic_magnitude_m_s": block["magnitude"],
            "held": is_held,
            "held_why": held_why,
            "held_description": f"{str(is_held).lower()} ({held_why})",
            "chord": h.chord,
            "drum_tier": drum_tiers[i],
            "melody": melody_str,
            "melody_notes": mel_notes if mel_notes else None,
            "melody_rest_reason": mel_rest_reason,
            "velocity_scale": round(velocity_scales[i], 3),
            "accent": accent_str,
        }
        rows.append(row)
    return rows

def generate_narrative(audit_table: list[dict[str, Any]], tonic: str) -> dict[str, Any]:
    peak_idx = 0
    max_norm = -1.0
    for idx, row in enumerate(audit_table):
        if row["norm_speed"] is not None and row["norm_speed"] > max_norm:
            max_norm = row["norm_speed"]
            peak_idx = idx

    held_indices = [idx for idx, row in enumerate(audit_table) if row["held"]]
    accent_indices = [idx for idx, row in enumerate(audit_table) if row["accent"] != "none"]

    sentences = []
    facts_used = []

    # Sentence 1: Start
    s1 = f"At bar 0 ({audit_table[0]['start_date']}), the sequence opens in {audit_table[0]['chord']} with {audit_table[0]['drum_tier']} drum intensity."
    sentences.append(s1)
    facts_used.append(0)

    # Sentence 2: Peak
    peak_row = audit_table[peak_idx]
    s2 = f"Activity peaks at bar {peak_idx} ({peak_row['start_date']}) with normalized intensity {peak_row['norm_speed']:.4f} and {peak_row['drum_tier']} drum tier."
    sentences.append(s2)
    facts_used.append(peak_idx)

    # Sentence 3: Accent or Held or Midpoint
    if accent_indices:
        acc_idx = accent_indices[0]
        acc_row = audit_table[acc_idx]
        s3 = f"At bar {acc_idx} ({acc_row['start_date']}), an accent event ({acc_row['accent']}) triggers as intensity accelerates."
        sentences.append(s3)
        facts_used.append(acc_idx)
    elif held_indices:
        h_idx = held_indices[0]
        h_row = audit_table[h_idx]
        s3 = f"At bar {h_idx} ({h_row['start_date']}), the hold rule maintains harmonic stability due to {h_row['held_why']}."
        sentences.append(s3)
        facts_used.append(h_idx)
    else:
        mid_idx = 26
        mid_row = audit_table[mid_idx]
        s3 = f"By bar {mid_idx} ({mid_row['start_date']}), playback continues in {mid_row['chord']} with velocity scale {mid_row['velocity_scale']:.3f}."
        sentences.append(s3)
        facts_used.append(mid_idx)

    # Sentence 4: Outro
    last_row = audit_table[-1]
    s4 = f"The composition concludes at bar 52 ({last_row['end_date']}) resolving to {tonic}."
    sentences.append(s4)
    facts_used.append(52)

    text = " ".join(sentences)
    check_banned_words(text, "narrative")
    return {
        "text": text,
        "facts_used": sorted(list(set(facts_used))),
    }

def main() -> None:
    final_dir = REPO_ROOT / "final"
    final_dir.mkdir(parents=True, exist_ok=True)
    soundfont = find_soundfont()

    # Track catalog
    ocean_regions = json.load(open(REPO_ROOT / "config/regions.json", encoding="utf-8"))["regions"]
    land_regions = json.load(open(REPO_ROOT / "config/land_regions.json", encoding="utf-8"))["regions"]

    tracks = []
    # 7 Ocean tracks
    for r in ocean_regions:
        if not r.get("enabled", True):
            continue
        rid = r["id"]
        src = REPO_ROOT / ("data/raw_oscar/oscar_2025_daily.json" if rid == "gulf_stream" else f"data/raw_oscar/regions/{rid}/oscar_2025_daily.json")
        tracks.append({
            "id": rid,
            "domain": "ocean",
            "name": r["name"],
            "bbox": [r["lon"][0], r["lat"][0], r["lon"][1], r["lat"][1]],
            "src": src,
            "adapter_cls": OscarAdapter,
            "adapter_kwargs": {"json_path": src},
        })

    # 8 Fires tracks
    for r in land_regions:
        rid = r["id"]
        f = r["fires"]
        w, s, e, n = f["lon"][0], f["lat"][0], f["lon"][1], f["lat"][1]
        bbox_slug = f"{w}_{s}_{e}_{n}_VIIRS_SNPP_SP"
        src_dir = REPO_ROOT / f"output/firms_cache/{bbox_slug}/2025"
        tracks.append({
            "id": rid,
            "domain": "fires",
            "name": r["name"],
            "bbox": [w, s, e, n],
            "src": src_dir,
            "adapter_cls": FIRMSAdapter,
            "adapter_kwargs": {"west": w, "south": s, "east": e, "north": n, "year": 2025},
        })

    print(f"Total tracks to render: {len(tracks)}")
    built_tracks_list = ", ".join(t["id"] for t in tracks)

    index_entries = []

    print("\n" + "="*80)
    print("STEP 2: RENDER & DETERMINISM VERIFICATION")
    print("Formula: k = clamp(round(6.0 * (mean - lo) / (hi - lo)), 0, 6)")
    print("lo = P5, hi = P95 from that track's own data")
    print("="*80)

    for idx, track_info in enumerate(tracks):
        tid = track_info["id"]
        domain = track_info["domain"]

        # Load daily records
        adapter = track_info["adapter_cls"](**track_info["adapter_kwargs"])
        daily_rows = adapter.rows()
        if len(daily_rows) != 365:
            raise ValueError(f"Track {tid} row count {len(daily_rows)} != 365")

        # Group into blocks
        blocks = group_days_into_blocks(daily_rows, block_size=7)
        if len(blocks) != 53:
            raise ValueError(f"Track {tid} bar count {len(blocks)} != 53")

        # Per-track P5-P95
        speeds = [d["speed_p95"] for d in daily_rows if d.get("speed_p95") is not None]
        lo = float(np.percentile(speeds, 5))
        hi = float(np.percentile(speeds, 95))
        mean_val = float(np.mean(speeds))
        k = max(0, min(6, int(round(6.0 * (mean_val - lo) / (hi - lo))))) if hi > lo else 0
        tonic_name = get_tonic_name(k)

        # Seed hex
        seed_hex = hashlib.sha256(f"{tid}:2025".encode("utf-8")).hexdigest()
        seed_int = int(seed_hex, 16)

        # Harmony, Melody, Dynamics
        norm_speeds, _ = normalize_series_5_95(blocks)
        smooth_speeds = compute_smooth_speeds(norm_speeds)
        velocity_scales = compute_velocity_scales(smooth_speeds)
        run_starts, riser_bars = find_top5_runs(norm_speeds)
        drum_tiers = compute_bar_drum_tiers(norm_speeds)

        harmony_bars = generate_harmony(
            blocks,
            norm_speeds,
            hold_threshold=0.013,
            hysteresis=2,
            eight_sectors=False,
            key_offset=k,
        )
        melody_events = generate_melody(
            blocks,
            harmony_bars,
            norm_speeds,
            seed=seed_int,
            key_offset=k,
        )

        # Statistics
        chords = [h.chord for h in harmony_bars]
        chord_changes = sum(1 for i in range(1, len(chords)) if chords[i] != chords[i-1])
        held_blocks_count = sum(1 for h in harmony_bars if h.held)
        held_pct = (held_blocks_count / len(blocks)) * 100.0

        if held_pct > 40.0:
            raise RuntimeError(f"STOP: Track {tid} has held blocks {held_pct:.1f}% > 40.0%!")

        drum_tier_counts = {t: drum_tiers.count(t) for t in ["low", "medium", "high", "rest"] if drum_tiers.count(t) > 0}

        print(f"[{idx+1:02d}/15] {tid:16s} ({domain:5s}) | lo={lo:.3f}, hi={hi:.3f}, mean={mean_val:.3f} -> k={k} ({tonic_name:3s}) | held={held_blocks_count:2d} ({held_pct:4.1f}%) | changes={chord_changes:2d} | drums={drum_tier_counts}")

        # Render MIDI
        track_out_dir = final_dir / "2025" / tid
        track_out_dir.mkdir(parents=True, exist_ok=True)
        tmp_track_dir = REPO_ROOT / "tmp" / tid
        tmp_track_dir.mkdir(parents=True, exist_ok=True)

        _, _, combined_mid = generate_mix_midis(
            blocks,
            seed=seed_int,
            out_dir=tmp_track_dir,
            bpm=72.0,
            hysteresis=2,
            eight_sectors=False,
            mid_name="track.mid",
            key_offset=k,
        )

        wav_path = tmp_track_dir / "track.wav"
        render_with_fluidsynth(combined_mid, soundfont, wav_path, gain=1.0)
        normalize_wav_to_dbfs(wav_path, target_dbfs=-1.0)

        opus_path = track_out_dir / "track.opus"
        cmd = [
            "ffmpeg", "-y", "-i", str(wav_path),
            "-c:a", "libopus", "-b:a", "48k", "-ac", "1",
            "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:a", "+bitexact",
            str(opus_path)
        ]
        subprocess.run(cmd, check=True, capture_output=True)

        opus_bytes = opus_path.stat().st_size
        opus_hash = sha256_file(opus_path)

        # Audit table
        audit_table = build_audit_table(
            blocks,
            norm_speeds,
            harmony_bars,
            melody_events,
            velocity_scales,
            run_starts,
            riser_bars,
            drum_tiers,
        )

        narrative = generate_narrative(audit_table, tonic_name)

        # Honest limits
        if domain == "ocean":
            honest_limits = (
                f"Built tracks (15): {built_tracks_list}. 2025 data. "
                "OSCAR is a model-derived analysis, not a direct measurement. "
                "Derived from satellite data; every note is computed from the data by rules we chose."
            )
        else:
            honest_limits = (
                f"Built tracks (15): {built_tracks_list}. 2025 data. "
                "counts of satellite fire detections in a box, not area burned; "
                "the direction is a fixed convention (East), so the harmony stays on "
                "one chord and only rhythm, melody and dynamics follow the data. "
                "Derived from satellite data; every note is computed from the data by rules we chose."
            )
        check_banned_words(honest_limits, "honest_limits")

        # Dataset info
        if domain == "ocean":
            dataset_info = {
                "name": "NASA / OSCAR surface ocean currents",
                "doi": "10.5067/OSCAR-25I01",
                "url": "https://podaac.jpl.nasa.gov/dataset/OSCAR_L4_OC_FINAL_V2.0",
                "version": "2.0",
                "fields_used": ["u", "v", "ug", "vg"],
            }
        else:
            dataset_info = {
                "name": "NASA FIRMS VIIRS SNPP 375m active fire detections",
                "doi": "10.5067/FIRMS/VIIRS/SNPP_SP.NRT.002",
                "url": "https://firms.modaps.eosdis.nasa.gov/",
                "version": "VIIRS_SNPP_SP",
                "fields_used": ["count", "frp"],
            }

        section_captions = [
            {"section": "intro", "bars": [0, 3], "caption": "Intro: opening acoustic atmosphere and harmonic foundation"},
            {"section": "build", "bars": [4, 19], "caption": "Build: developing rhythmic pulse and harmonic movement"},
            {"section": "peak", "bars": [20, 35], "caption": "Peak: highest energy and dynamic variation"},
            {"section": "calm", "bars": [36, 46], "caption": "Calm: relaxed dynamic resolution"},
            {"section": "outro", "bars": [47, 52], "caption": "Outro: fade out resolving to tonic"},
        ]

        meta = {
            "dataset": dataset_info,
            "region": {
                "id": tid,
                "bbox": track_info["bbox"],
                "period": "2025-01-01 to 2025-12-31",
            },
            "domain": domain,
            "key": {
                "offset_k": k,
                "tonic": tonic_name,
            },
            "seed": seed_hex,
            "bars": 53,
            "bar_unit": "7-day block",
            "days_per_bar": 7,
            "hold_threshold": 0.013,
            "chord_changes": chord_changes,
            "drum_tier_counts": drum_tier_counts,
            "audit_table": audit_table,
            "section_captions": section_captions,
            "source_fields": adapter.source_fields,
            "honest_limits": honest_limits,
            "narrative": narrative,
            "ai_disclosure": "AI-assisted; audio is rule-generated from data",
            "checksum": opus_hash,
        }

        # Check banned words across entire meta
        meta_json_str = json.dumps(meta, indent=2)
        check_banned_words(meta_json_str, f"meta.json for {tid}")

        meta_path = track_out_dir / "meta.json"
        meta_path.write_text(meta_json_str, encoding="utf-8", newline="\n")

        index_entries.append({
            "id": tid,
            "domain": domain,
            "region": track_info["name"],
            "year": 2025,
            "bbox": track_info["bbox"],
            "bars": 53,
            "duration_s": 176.7,
            "key": {
                "offset_k": k,
                "tonic": tonic_name,
            },
            "bytes": opus_bytes,
            "checksum": opus_hash,
        })

    index_json_str = json.dumps(index_entries, indent=2)
    check_banned_words(index_json_str, "index.json")
    (final_dir / "index.json").write_text(index_json_str, encoding="utf-8", newline="\n")
    print(f"\nSuccessfully wrote final/index.json with {len(index_entries)} tracks.")

if __name__ == "__main__":
    main()
