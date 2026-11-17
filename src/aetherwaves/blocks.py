from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Sequence
import numpy as np

from aetherwaves.harmony import (
    compute_section_counts,
    generate_harmony,
    get_section_for_bar,
    sector_to_chord,
)
from aetherwaves.rhythm import (
    generate_drum_events,
    normalize_series_5_95,
)


def get_sector(angle_deg: float) -> str:
    """
    Map ageostrophic angle in degrees to one of 4 sectors:
    East: -45..45
    North: 45..135
    West: |a| >= 135
    South: -135..-45
    """
    norm_ang = ((angle_deg + 180.0) % 360.0) - 180.0
    if -45.0 <= norm_ang <= 45.0:
        return "East"
    elif 45.0 < norm_ang < 135.0:
        return "North"
    elif -135.0 < norm_ang < -45.0:
        return "South"
    else:
        return "West"


def group_days_into_blocks(
    daily_records: Sequence[dict[str, Any]],
    block_size: int = 7,
) -> list[dict[str, Any]]:
    """
    Group daily records into consecutive blocks (default: 7-day blocks;
    365 days gives 52 full blocks + 1 shorter 1-day block, or keeps shorter final block).

    Per block, ignoring missing days:
    - speed_p95: mean of speed_p95 over all valid days in the block
    - sector: most common daily sector of ageo_angle_deg (East -45..45, North 45..135,
      West |a|>=135, South -135..-45). Ties go to the sector of the later day.
    - ageo_angle_deg: mean daily angle of the days in that winning sector (circular mean,
      using atan2 of mean sin and mean cos).
    - ageo_u, ageo_v: mean of the days in that winning sector.
    - magnitude: mean of the daily hypot(ageo_u, ageo_v) over all valid days in the block.
    If all days in a block are missing, everything is None (rest, never zero).

    Raw daily values are preserved for audit and labeled:
    "majority sector of the ageostrophic component".
    """
    blocks: list[dict[str, Any]] = []
    n_days = len(daily_records)

    for i in range(0, n_days, block_size):
        chunk = daily_records[i : i + block_size]

        valid_days: list[dict[str, Any]] = []
        for d in chunk:
            p95 = d.get("speed_p95")
            u = d.get("ageo_u")
            v = d.get("ageo_v")

            if (
                p95 is not None
                and u is not None
                and v is not None
                and np.isfinite(p95)
                and np.isfinite(u)
                and np.isfinite(v)
            ):
                # Ensure valid angle
                ang = d.get("ageo_angle_deg")
                if ang is None or not np.isfinite(ang):
                    ang = math.degrees(math.atan2(v, u))
                valid_days.append({
                    "speed_p95": float(p95),
                    "ageo_u": float(u),
                    "ageo_v": float(v),
                    "ageo_angle_deg": float(ang),
                    "raw": d,
                })

        start_date = str(chunk[0].get("date", f"Day-{i}"))
        end_date = str(chunk[-1].get("date", f"Day-{i + len(chunk) - 1}"))

        if not valid_days:
            # If all days are missing, everything is None (rest). Never zero.
            block = {
                "date": start_date,
                "end_date": end_date,
                "speed_p95": None,
                "sector": None,
                "ageo_u": None,
                "ageo_v": None,
                "ageo_angle_deg": None,
                "magnitude": None,
                "method": "majority sector of the ageostrophic component",
                "start_idx": i,
                "end_idx": i + len(chunk),
                "valid_count": 0,
                "total_days": len(chunk),
                "raw_days": list(chunk),
            }
        else:
            # 1. speed_p95 = mean of speed_p95 across all valid days
            mean_p95 = float(np.mean([d["speed_p95"] for d in valid_days]))

            # 2. sector = most common daily sector; ties go to sector of later day
            sector_counts: dict[str, int] = {}
            sector_last_day_idx: dict[str, int] = {}
            for day_idx, d in enumerate(valid_days):
                sec = get_sector(d["ageo_angle_deg"])
                sector_counts[sec] = sector_counts.get(sec, 0) + 1
                sector_last_day_idx[sec] = day_idx

            winning_sector = max(
                sector_counts.keys(),
                key=lambda s: (sector_counts[s], sector_last_day_idx[s]),
            )

            # 3. Days in that winning sector
            winning_days = [
                d for d in valid_days if get_sector(d["ageo_angle_deg"]) == winning_sector
            ]

            # ageo_angle_deg = circular mean using atan2 of sin and cos
            angles_rad = [math.radians(d["ageo_angle_deg"]) for d in winning_days]
            sin_mean = float(np.mean([math.sin(a) for a in angles_rad]))
            cos_mean = float(np.mean([math.cos(a) for a in angles_rad]))
            circ_mean_rad = math.atan2(sin_mean, cos_mean)
            mean_angle_deg = float(math.degrees(circ_mean_rad))

            # ageo_u, ageo_v = mean of days in that winning sector
            mean_u = float(np.mean([d["ageo_u"] for d in winning_days]))
            mean_v = float(np.mean([d["ageo_v"] for d in winning_days]))

            # 4. magnitude = mean of daily hypot(ageo_u, ageo_v) over all valid days in the block
            daily_mags = [math.hypot(d["ageo_u"], d["ageo_v"]) for d in valid_days]
            mean_mag = float(np.mean(daily_mags))

            block = {
                "date": start_date,
                "end_date": end_date,
                "speed_p95": round(mean_p95, 6),
                "sector": winning_sector,
                "ageo_u": round(mean_u, 6),
                "ageo_v": round(mean_v, 6),
                "ageo_angle_deg": round(mean_angle_deg, 4),
                "magnitude": round(mean_mag, 6),
                "method": "majority sector of the ageostrophic component",
                "start_idx": i,
                "end_idx": i + len(chunk),
                "valid_count": len(valid_days),
                "total_days": len(chunk),
                "raw_days": list(chunk),
            }

        blocks.append(block)

    return blocks


def analyze_blocks(
    blocks: Sequence[dict[str, Any]],
    hold_threshold: float = 0.013,
) -> dict[str, Any]:
    """
    Compute block statistics:
    - Number of blocks.
    - 10th / 25th / 50th percentile of block magnitude.
    - Number of chord changes before and after the 2-bar rule.
    - Percent of blocks held below hold_threshold (0.013).
    - Total bars and total duration in seconds at 72 BPM.
    """
    total_blocks = len(blocks)
    if total_blocks == 0:
        return {
            "total_blocks": 0,
            "p10": None,
            "p25": None,
            "p50": None,
            "held_count": 0,
            "held_pct": 0.0,
            "holds_more_than_40_pct": False,
            "chord_changes_before": 0,
            "chord_changes_after": 0,
            "total_bars": 0,
            "total_seconds": 0.0,
        }

    # 1. Magnitude: use block magnitude
    mags: list[float] = []
    for b in blocks:
        mag = b.get("magnitude")
        if mag is None:
            u = b.get("ageo_u")
            v = b.get("ageo_v")
            if u is not None and v is not None and np.isfinite(u) and np.isfinite(v):
                mag = float(math.hypot(u, v))
        if mag is not None and np.isfinite(mag):
            mags.append(float(mag))

    p10 = float(np.percentile(mags, 10.0)) if mags else None
    p25 = float(np.percentile(mags, 25.0)) if mags else None
    p50 = float(np.percentile(mags, 50.0)) if mags else None

    # Missing blocks also count as held
    held_by_threshold = sum(1 for m in mags if m < hold_threshold)
    missing_blocks = total_blocks - len(mags)
    total_held = held_by_threshold + missing_blocks
    held_pct = (total_held / total_blocks) * 100.0 if total_blocks > 0 else 0.0
    holds_more_than_40_pct = held_pct > 40.0

    # 2. Chord changes before vs after 2-bar rule
    norm_speeds, _ = normalize_series_5_95(blocks)
    harmony_bars = generate_harmony(blocks, norm_speeds, hold_threshold=hold_threshold)

    # After 2-bar rule (active played chords)
    after_chords = [h.chord for h in harmony_bars]
    chord_changes_after = sum(
        1 for i in range(1, len(after_chords)) if after_chords[i] != after_chords[i - 1]
    )

    # Before 2-bar rule (raw target chords, without 2-bar hysteresis requirement)
    section_counts = compute_section_counts(total_blocks)
    raw_targets: list[str] = []
    last_valid_target = "Dm"
    for idx, b in enumerate(blocks):
        sec = get_section_for_bar(idx, section_counts)
        is_calm = (sec == "calm")
        mag = b.get("magnitude")
        if mag is None:
            u = b.get("ageo_u")
            v = b.get("ageo_v")
            mag = float(math.hypot(u, v)) if (u is not None and v is not None) else None
        ang = b.get("ageo_angle_deg")

        if mag is None or ang is None:
            raw_targets.append(last_valid_target)
        else:
            if mag < hold_threshold:
                raw_targets.append(last_valid_target)
            else:
                tgt = sector_to_chord(ang, is_calm=is_calm)
                last_valid_target = tgt
                raw_targets.append(tgt)

    chord_changes_before = sum(
        1 for i in range(1, len(raw_targets)) if raw_targets[i] != raw_targets[i - 1]
    )

    # 3. Timing at 72 BPM (4/4 time: 1 bar = 4 beats = 4 * 60 / 72 = 3.3333s)
    seconds_per_bar = 4.0 * (60.0 / 72.0)
    total_seconds = total_blocks * seconds_per_bar

    return {
        "total_blocks": total_blocks,
        "p10": p10,
        "p25": p25,
        "p50": p50,
        "held_count": total_held,
        "held_pct": round(held_pct, 1),
        "holds_more_than_40_pct": holds_more_than_40_pct,
        "chord_changes_before": chord_changes_before,
        "chord_changes_after": chord_changes_after,
        "total_bars": total_blocks,
        "total_seconds": round(total_seconds, 1),
    }


def process_and_run(
    json_path: str | Path = "data/raw_oscar/oscar_2025_daily.json",
    block_size: int = 7,
    hold_threshold: float = 0.013,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Read OSCAR daily data, group into 7-day blocks, analyze, and feed into
    rhythm.py and harmony.py.
    """
    path = Path(json_path)
    if not path.exists():
        raise FileNotFoundError(f"Daily OSCAR JSON file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        daily_records: list[dict[str, Any]] = json.load(f)

    # 1. Group into 7-day blocks
    blocks = group_days_into_blocks(daily_records, block_size=block_size)

    # 2. Analyze statistics
    stats = analyze_blocks(blocks, hold_threshold=hold_threshold)

    # 3. Feed into rhythm.py and harmony.py (1 block = 1 bar)
    norm_speeds, norm_audit = normalize_series_5_95(blocks)
    drum_events = generate_drum_events(norm_speeds, seed=42)
    harmony_bars = generate_harmony(blocks, norm_speeds, hold_threshold=hold_threshold)

    # 4. Print requested outputs (Requirement 5)
    print("=== AetherWaves 7-Day Block Analysis ===")
    print(f"Block count:   {stats['total_blocks']}")
    print(f"Total bars:    {stats['total_bars']}")
    print(f"Total seconds: {stats['total_seconds']:.1f}s ({stats['total_seconds'] / 60.0:.2f} minutes @ 72 BPM)")
    print(f"Chord changes before 2-bar rule: {stats['chord_changes_before']}")
    print(f"Chord changes after 2-bar rule:  {stats['chord_changes_after']}")
    print(f"Percent of blocks held below 0.013: {stats['held_pct']}% ({stats['held_count']}/{stats['total_blocks']})")
    print(f"Generated events: {len(drum_events)} drum events, {len(harmony_bars)} harmonic bars.")

    return blocks, stats


if __name__ == "__main__":
    process_and_run()
