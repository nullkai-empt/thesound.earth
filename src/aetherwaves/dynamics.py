from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import mido
import numpy as np

# Ensure repo root and src/ are on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from aetherwaves.blocks import group_days_into_blocks
from aetherwaves.harmony import (
    BarHarmony,
    compute_section_counts,
    generate_harmony,
    get_section_for_bar,
)
from aetherwaves.melody import MelodyEvent, generate_melody
from aetherwaves.rhythm import DrumEvent, generate_drum_events, normalize_series_5_95

# --- Named Constants ---
DYNAMICS_BASE_SCALE: float = 0.70
DYNAMICS_SMOOTH_FACTOR: float = 0.30
MIN_VELOCITY: int = 1
MAX_VELOCITY: int = 110

# Top 5% threshold
TOP_PERCENTILE: float = 95.0

# Accent parameters
CRASH_MIDI_NOTE: int = 49             # GM Drum Map: Crash Cymbal 1
CRASH_VELOCITY: int = 100
CRASH_BEAT: float = 1.0

RISER_PROGRAM: int = 119              # GM Program 119: Reverse Cymbal
RISER_CHANNEL: int = 3                # Dedicated MIDI channel for sound effects
RISER_MIDI_NOTE: int = 60             # Middle C
RISER_VELOCITIES: tuple[int, ...] = (50, 63, 77, 90)
RISER_BEATS: tuple[float, ...] = (3.0, 3.5, 4.0, 4.5)
RISER_DURATION_BEATS: float = 0.5


def compute_smooth_speeds(norm_speeds: Sequence[float | None]) -> list[float | None]:
    """
    Compute 3-bar centered moving average of normalized speeds.
    Edges use available bars. Missing bars return None.
    """
    n = len(norm_speeds)
    smooth: list[float | None] = []
    for i in range(n):
        if norm_speeds[i] is None:
            smooth.append(None)
            continue
        window = [
            norm_speeds[j]
            for j in [i - 1, i, i + 1]
            if 0 <= j < n and norm_speeds[j] is not None
        ]
        if window:
            smooth.append(float(np.mean(window)))
        else:
            smooth.append(None)
    return smooth


def compute_velocity_scales(smooth_speeds: Sequence[float | None]) -> list[float]:
    """
    Compute per-bar velocity scale = 0.70 + 0.30 * smooth_speed.
    If bar is missing, scale is 0.0.
    """
    scales: list[float] = []
    for s in smooth_speeds:
        if s is None:
            scales.append(0.0)
        else:
            clamped_s = float(np.clip(s, 0.0, 1.0))
            scales.append(DYNAMICS_BASE_SCALE + DYNAMICS_SMOOTH_FACTOR * clamped_s)
    return scales


def find_top5_runs(
    norm_speeds: Sequence[float | None],
    percentile: float = TOP_PERCENTILE,
) -> tuple[list[int], list[int]]:
    """
    Find top 5% bars (at or above 95th percentile of all valid bars).
    Returns:
      - top5_run_starts: First bar of each contiguous run of top 5% bars (gets crash cymbal on beat 1).
      - riser_bars: The bar immediately before each top 5% run start (gets reverse cymbal on beats 3-4).
        If top-5% bar is bar 0 or 1, no riser is produced.
    """
    valid_speeds = [s for s in norm_speeds if s is not None and np.isfinite(s)]
    if not valid_speeds:
        return [], []

    threshold = float(np.percentile(valid_speeds, percentile))

    is_top5 = [
        (s is not None and np.isfinite(s) and s >= threshold)
        for s in norm_speeds
    ]

    run_starts: list[int] = []
    for i in range(len(norm_speeds)):
        if is_top5[i] and (i == 0 or not is_top5[i - 1]):
            run_starts.append(i)

    riser_bars: list[int] = []
    for r in run_starts:
        # If the top-5% bar is bar 0 or 1, no riser
        if r > 1:
            prev_bar = r - 1
            if norm_speeds[prev_bar] is not None:
                riser_bars.append(prev_bar)

    return run_starts, riser_bars


def apply_velocity_scale(
    velocity: int,
    scale: float,
    min_vel: int = MIN_VELOCITY,
    max_vel: int = MAX_VELOCITY,
) -> int:
    """Scale a velocity and clamp it to [min_vel, max_vel]."""
    return max(min_vel, min(max_vel, int(round(velocity * scale))))


def scale_drum_events(
    drum_events: Sequence[DrumEvent],
    scales: Sequence[float],
) -> list[DrumEvent]:
    """Scale drum velocities by bar velocity scale without changing hits or timing."""
    scaled_events: list[DrumEvent] = []
    for ev in drum_events:
        bar_scale = scales[ev.bar] if ev.bar < len(scales) else 1.0
        new_vel = apply_velocity_scale(ev.velocity, bar_scale)
        scaled_events.append(
            DrumEvent(
                bar=ev.bar,
                beat=ev.beat,
                instrument=ev.instrument,
                midi_note=ev.midi_note,
                velocity=new_vel,
                duration_beats=ev.duration_beats,
            )
        )
    return scaled_events


def generate_crash_events(
    top5_run_starts: Sequence[int],
    norm_speeds: Sequence[float | None],
) -> list[DrumEvent]:
    """Generate crash cymbal drum events on beat 1 for each top-5% run start."""
    crashes: list[DrumEvent] = []
    for bar_idx in top5_run_starts:
        if bar_idx < len(norm_speeds) and norm_speeds[bar_idx] is not None:
            crashes.append(
                DrumEvent(
                    bar=bar_idx,
                    beat=CRASH_BEAT,
                    instrument="crash",
                    midi_note=CRASH_MIDI_NOTE,
                    velocity=CRASH_VELOCITY,
                    duration_beats=2.0,
                )
            )
    return crashes


def generate_riser_actions(
    riser_bars: Sequence[int],
    ticks_per_beat: int = 480,
    channel: int = RISER_CHANNEL,
    program: int = RISER_PROGRAM,
) -> list[tuple[int, float, str, int, int]]:
    """
    Generate MIDI actions for Reverse Cymbal riser in the bar before top-5% runs:
    GM program 119 Reverse Cymbal, 4 notes across beats 3-4, velocities rising 50->90.
    """
    actions: list[tuple[int, float, str, int, int]] = []
    if not riser_bars:
        return actions

    # Initial program change at tick 0
    actions.append((0, -1.0, "program_change", program, 0))

    bar_ticks = 4 * ticks_per_beat
    dur_ticks = int(round(RISER_DURATION_BEATS * ticks_per_beat))

    for bar_idx in riser_bars:
        for beat, vel in zip(RISER_BEATS, RISER_VELOCITIES):
            start_tick = int(round(bar_idx * bar_ticks + (beat - 1.0) * ticks_per_beat))
            end_tick = start_tick + dur_ticks
            actions.append((start_tick, 1.0, "note_on", RISER_MIDI_NOTE, vel))
            actions.append((end_tick, 0.0, "note_off", RISER_MIDI_NOTE, 0))

    return actions


def main() -> None:
    parser = argparse.ArgumentParser(description="System 4 Dynamics Generator")
    parser.add_argument("--json", type=str, default="data/raw_oscar/oscar_2025_daily.json")
    parser.add_argument("--block-size", type=int, default=7)
    args = parser.parse_args()

    json_path = REPO_ROOT / args.json
    daily_records = json.loads(json_path.read_text(encoding="utf-8"))
    blocks = group_days_into_blocks(daily_records, block_size=args.block_size)
    norm_speeds, _ = normalize_series_5_95(blocks)
    section_counts = compute_section_counts(len(blocks))

    smooth_speeds = compute_smooth_speeds(norm_speeds)
    scales = compute_velocity_scales(smooth_speeds)
    run_starts, riser_bars = find_top5_runs(norm_speeds)

    run_starts_set = set(run_starts)
    riser_bars_set = set(riser_bars)

    print("| Bar | Section | Norm Speed | Smooth Speed | Velocity Scale | Accent |")
    print("|---|---|---|---|---|---|")

    for i in range(len(blocks)):
        sec = get_section_for_bar(i, section_counts)
        s = norm_speeds[i]
        sm = smooth_speeds[i]
        sc = scales[i]

        s_str = f"{s:.3f}" if s is not None else "None"
        sm_str = f"{sm:.3f}" if sm is not None else "None"
        sc_str = f"{sc:.3f}" if s is not None else "0.000"

        accents = []
        if i in run_starts_set:
            accents.append("crash")
        if i in riser_bars_set:
            accents.append("riser")
        accent_str = " + ".join(accents) if accents else "none"

        print(f"| {i:2d} | {sec:5s} | {s_str} | {sm_str} | {sc_str} | {accent_str} |")


if __name__ == "__main__":
    main()
