from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Sequence
import numpy as np

# General MIDI Drum Map (Standard Channel 10 / index 9)
MIDI_BASS_DRUM: int = 36    # Bass Drum 1 (Kick)
MIDI_SNARE: int = 38        # Acoustic Snare
MIDI_MARACAS: int = 70      # Maracas / Shaker
MIDI_LOW_TOM: int = 45      # Low Tom
MIDI_MID_TOM: int = 47      # Mid Tom
MIDI_HIGH_TOM: int = 50     # High Tom
MIDI_CRASH: int = 49        # Crash Cymbal 1

Tier = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class DrumEvent:
    """A single percussion event in a 4/4 measure."""
    bar: int                # 0-indexed bar number
    beat: float             # Beat within the measure (1.0 to 4.75)
    instrument: str         # "kick", "snare", "shaker", "tom", "crash"
    midi_note: int          # MIDI note on percussion channel (GM Ch 10)
    velocity: int           # Velocity (1-127)
    duration_beats: float   # Duration in beats (e.g. 0.25, 0.5)


def speed_to_tier(speed: float, low_thresh: float = 0.35, high_thresh: float = 0.70) -> Tier:
    """Map normalized speed [0, 1] to a target tier."""
    if speed < low_thresh:
        return "low"
    elif speed < high_thresh:
        return "medium"
    return "high"


def _generate_fill_events(
    bar: int,
    base_velocity: int,
    seed: int,
) -> list[DrumEvent]:
    """Generate a deterministic 16th-note drum fill on beat 4."""
    rng = np.random.RandomState((seed * 31337 + bar * 101 + 3) & 0xFFFFFFFF)
    fill_styles = [
        # Style 0: Snare -> Mid Tom -> Low Tom -> Low Tom
        [
            (4.0, "snare", MIDI_SNARE, 0.25, 0),
            (4.25, "tom", MIDI_HIGH_TOM, 0.25, 2),
            (4.5, "tom", MIDI_MID_TOM, 0.25, 4),
            (4.75, "tom", MIDI_LOW_TOM, 0.25, 6),
        ],
        # Style 1: Snare roll with dynamic crescendo
        [
            (4.0, "snare", MIDI_SNARE, 0.25, -4),
            (4.25, "snare", MIDI_SNARE, 0.25, 0),
            (4.5, "snare", MIDI_SNARE, 0.25, 5),
            (4.75, "snare", MIDI_SNARE, 0.25, 10),
        ],
        # Style 2: Tom cascade into kick
        [
            (4.0, "tom", MIDI_HIGH_TOM, 0.25, 0),
            (4.25, "tom", MIDI_MID_TOM, 0.25, 3),
            (4.5, "tom", MIDI_LOW_TOM, 0.25, 5),
            (4.75, "kick", MIDI_BASS_DRUM, 0.25, 8),
        ],
    ]
    chosen = fill_styles[rng.randint(len(fill_styles))]
    events: list[DrumEvent] = []
    for beat, inst, note, dur, vel_offset in chosen:
        vel = int(np.clip(base_velocity + vel_offset, 20, 127))
        events.append(
            DrumEvent(
                bar=bar,
                beat=beat,
                instrument=inst,
                midi_note=note,
                velocity=vel,
                duration_beats=dur,
            )
        )
    return events


def normalize_series_5_95(
    data_series: Sequence[dict[str, Any] | float | None],
) -> tuple[list[float | None], dict[str, Any]]:
    """
    Normalize speed series across the whole loaded series using 5th and 95th percentiles.
    Values are clamped to [0.0, 1.0].
    
    Requirements:
    - Uses field 'speed_p95' if items are dicts (stops using speed_mean).
    - If speed_p95 is None, NaN, or missing, that day is None (excluded from P5/P95).
    - Clamped to [0.0, 1.0].
    - Returns raw P5, P95, min, and max in the audit dictionary.
    """
    raw_speeds: list[float | None] = []
    for item in data_series:
        if isinstance(item, dict):
            # Strictly use speed_p95; do NOT fall back to speed_mean
            val = item.get("speed_p95")
            if val is None:
                raw_speeds.append(None)
            else:
                try:
                    fval = float(val)
                    raw_speeds.append(fval if np.isfinite(fval) else None)
                except (ValueError, TypeError):
                    raw_speeds.append(None)
        elif item is None:
            raw_speeds.append(None)
        else:
            try:
                fval = float(item)
                raw_speeds.append(fval if np.isfinite(fval) else None)
            except (ValueError, TypeError):
                raw_speeds.append(None)

    valid_vals = [s for s in raw_speeds if s is not None and np.isfinite(s)]
    if not valid_vals:
        return [None] * len(raw_speeds), {
            "p5": None,
            "p95": None,
            "min": None,
            "max": None,
            "sample_count": 0,
            "total_days": len(raw_speeds),
        }

    p5 = float(np.percentile(valid_vals, 5.0))
    p95 = float(np.percentile(valid_vals, 95.0))
    min_v = float(np.min(valid_vals))
    max_v = float(np.max(valid_vals))
    p_range = max(1e-9, p95 - p5)

    normalized: list[float | None] = []
    for s in raw_speeds:
        if s is None:
            normalized.append(None)
        else:
            norm_val = float(np.clip((s - p5) / p_range, 0.0, 1.0))
            normalized.append(round(norm_val, 4))

    audit: dict[str, Any] = {
        "p5": round(p5, 4),
        "p95": round(p95, 4),
        "min": round(min_v, 4),
        "max": round(max_v, 4),
        "p5_speed": round(p5, 4),
        "p95_speed": round(p95, 4),
        "min_raw_speed": round(min_v, 4),
        "max_raw_speed": round(max_v, 4),
        "sample_count": len(valid_vals),
        "total_days": len(raw_speeds),
    }
    return normalized, audit


def load_daily_data(
    json_path: str | Path = "data/raw_oscar/oscar_2025_daily.json",
    print_summary: bool = True,
) -> tuple[list[dict[str, Any]], list[float | None], dict[str, Any]]:
    """
    Load OSCAR daily JSON records, print summary statistics, and return normalized speeds.
    
    Requirements:
    - Reads oscar_2025_daily.json (list of days in date order).
    - Uses field 'speed_p95' for each day.
    - Normalizes across the whole loaded series via normalize_series_5_95().
    - Prints:
        "speed changed X% over the period"
        where X = (max - min) / min * 100 of raw speed_p95, rounded to 1 decimal.
        Also: "Jan mean p95 = A, Jun mean p95 = B, change = Y%" if both months exist.
    """
    path = Path(json_path)
    if not path.exists():
        raise FileNotFoundError(f"Daily OSCAR JSON file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        records: list[dict[str, Any]] = json.load(f)

    # Ensure records are in date order
    records = sorted(records, key=lambda r: str(r.get("date", "")))

    # Compute raw statistics from valid speed_p95 entries
    valid_p95: list[float] = []
    for r in records:
        val = r.get("speed_p95")
        if val is not None:
            try:
                fval = float(val)
                if np.isfinite(fval):
                    valid_p95.append(fval)
            except (ValueError, TypeError):
                pass

    if valid_p95:
        min_p95 = float(np.min(valid_p95))
        max_p95 = float(np.max(valid_p95))
        if min_p95 > 0:
            change_x = ((max_p95 - min_p95) / min_p95) * 100.0
            line1 = f"speed changed {change_x:.1f}% over the period"
            if print_summary:
                print(line1)

        jan_vals: list[float] = []
        jun_vals: list[float] = []
        for r in records:
            d_str = str(r.get("date", ""))
            val = r.get("speed_p95")
            if val is None:
                continue
            try:
                fval = float(val)
                if not np.isfinite(fval):
                    continue
            except (ValueError, TypeError):
                continue

            # Check month in YYYY-MM-DD
            if len(d_str) >= 7:
                month = d_str[5:7]
                if month == "01":
                    jan_vals.append(fval)
                elif month == "06":
                    jun_vals.append(fval)

        if jan_vals and jun_vals:
            mean_jan = float(np.mean(jan_vals))
            mean_jun = float(np.mean(jun_vals))
            if mean_jan > 0:
                change_y = ((mean_jun - mean_jan) / mean_jan) * 100.0
                line2 = f"Jan mean p95 = {mean_jan:.3f}, Jun mean p95 = {mean_jun:.3f}, change = {change_y:.1f}%"
                if print_summary:
                    print(line2)

    norm_speeds, audit = normalize_series_5_95(records)
    return records, norm_speeds, audit


def generate_drum_events(
    speeds: Sequence[float | None],
    seed: int = 42,
    low_thresh: float = 0.35,
    high_thresh: float = 0.70,
    enable_variations: bool = True,
) -> list[DrumEvent]:
    """
    Generate drum events for a sequence of bars from normalized speed data.

    System 1 Requirements:
    - 1 sample = 1 bar (72 BPM, 4/4 meter).
    - Missing data (None) = full-bar rest (0 events).
    - Tiers:
        * Low (< 0.35): Kick on 1 and 3.
        * Medium (0.35 - 0.70): Plus Snare on 2 and 4, plus 8th-note shaker.
        * High (>= 0.70): Plus 16th-note shaker, and a fill on the last beat of every 4th bar.
    - Continuous Velocity: Kick, Snare, and Shaker velocities smoothly track
      continuous normalized speed [0, 1] each bar.
    - Seeded Variations: Subtle ghost snares and kick variations at medium and high tiers.
    - Tier change hysteresis: Tier changes only on a bar line, and only after
      2 bars observed at the new level.
    - Deterministic: Same input + same seed = identical output.
    """
    if not speeds:
        return []

    events: list[DrumEvent] = []

    # Find the first valid speed to establish initial tier
    active_tier: Tier = "low"
    for s in speeds:
        if s is not None and np.isfinite(s):
            active_tier = speed_to_tier(float(np.clip(s, 0.0, 1.0)), low_thresh, high_thresh)
            break

    candidate_tier: Tier | None = None
    candidate_streak: int = 0
    high_tier_bar_count: int = 0

    for bar_idx, raw_speed in enumerate(speeds):
        # 1. Check for missing data (None or non-finite) -> full-bar rest (never zero)
        if raw_speed is None or not np.isfinite(raw_speed):
            continue

        speed = float(np.clip(raw_speed, 0.0, 1.0))
        target = speed_to_tier(speed, low_thresh, high_thresh)

        # 2. Hysteresis logic: Tier changes only after 2 bars at the new level
        if target != active_tier:
            if candidate_tier == target:
                candidate_streak += 1
            else:
                candidate_tier = target
                candidate_streak = 1

            if candidate_streak >= 2:
                active_tier = candidate_tier
                candidate_tier = None
                candidate_streak = 0
        else:
            candidate_tier = None
            candidate_streak = 0

        # 3. Continuous velocity scaling with normalized speed each bar
        kick_vel = int(np.clip(round(50.0 + 48.0 * speed), 38, 118))
        snare_vel = int(np.clip(round(45.0 + 45.0 * speed), 35, 110))
        shaker_vel = int(np.clip(round(30.0 + 40.0 * speed), 24, 90))

        # Seeded random generator for bar-level groove variations
        bar_rng = np.random.RandomState((seed * 31337 + bar_idx * 101 + 17) & 0xFFFFFFFF)

        bar_events: list[DrumEvent] = []

        # 4. Generate tier patterns
        if active_tier == "low":
            # Low tier: Kick on beats 1 and 3 (no snare, no shaker, no variations)
            bar_events.append(DrumEvent(bar_idx, 1.0, "kick", MIDI_BASS_DRUM, kick_vel, 0.5))
            bar_events.append(DrumEvent(bar_idx, 3.0, "kick", MIDI_BASS_DRUM, kick_vel, 0.5))

        elif active_tier == "medium":
            # Kick on 1 and 3
            bar_events.append(DrumEvent(bar_idx, 1.0, "kick", MIDI_BASS_DRUM, kick_vel, 0.5))
            bar_events.append(DrumEvent(bar_idx, 3.0, "kick", MIDI_BASS_DRUM, kick_vel, 0.5))

            # Kick variation: syncopated kick on beat 3.5 (deterministic from seed)
            if enable_variations and bar_rng.uniform(0.0, 1.0) < 0.45:
                bar_events.append(DrumEvent(bar_idx, 3.5, "kick", MIDI_BASS_DRUM, int(kick_vel * 0.85), 0.35))

            # Snare on 2 and 4
            bar_events.append(DrumEvent(bar_idx, 2.0, "snare", MIDI_SNARE, snare_vel, 0.35))
            bar_events.append(DrumEvent(bar_idx, 4.0, "snare", MIDI_SNARE, snare_vel, 0.35))

            # Ghost snare: subtle tap on beat 2.75
            if enable_variations and bar_rng.uniform(0.0, 1.0) < 0.45:
                bar_events.append(DrumEvent(bar_idx, 2.75, "snare", MIDI_SNARE, int(snare_vel * 0.42), 0.20))

            # 8th-note shaker: beats 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5
            for step in range(8):
                b = 1.0 + step * 0.5
                v = shaker_vel if (step % 2 == 0) else int(round(shaker_vel * 0.75))
                bar_events.append(DrumEvent(bar_idx, b, "shaker", MIDI_MARACAS, v, 0.25))

        elif active_tier == "high":
            high_tier_bar_count += 1
            is_fill_bar = (high_tier_bar_count % 4 == 0)

            # Kick on 1 and 3
            bar_events.append(DrumEvent(bar_idx, 1.0, "kick", MIDI_BASS_DRUM, kick_vel, 0.5))
            bar_events.append(DrumEvent(bar_idx, 3.0, "kick", MIDI_BASS_DRUM, kick_vel, 0.5))

            # Kick variation in high tier: syncopated kicks on 2.5 or 3.5
            if enable_variations:
                if bar_rng.uniform(0.0, 1.0) < 0.50:
                    bar_events.append(DrumEvent(bar_idx, 3.5, "kick", MIDI_BASS_DRUM, int(kick_vel * 0.88), 0.35))
                if bar_rng.uniform(0.0, 1.0) < 0.35:
                    bar_events.append(DrumEvent(bar_idx, 2.5, "kick", MIDI_BASS_DRUM, int(kick_vel * 0.82), 0.35))

            # Snare on 2
            bar_events.append(DrumEvent(bar_idx, 2.0, "snare", MIDI_SNARE, snare_vel, 0.35))

            # Ghost snare on beat 2.75
            if enable_variations and bar_rng.uniform(0.0, 1.0) < 0.55:
                bar_events.append(DrumEvent(bar_idx, 2.75, "snare", MIDI_SNARE, int(snare_vel * 0.45), 0.20))

            # Full 16th-note shaker across all 4 beats (16 subdivisions)
            for step in range(16):
                b = 1.0 + step * 0.25
                if step % 4 == 0:
                    v = shaker_vel
                elif step % 2 == 0:
                    v = int(round(shaker_vel * 0.75))
                else:
                    v = int(round(shaker_vel * 0.58))
                bar_events.append(DrumEvent(bar_idx, b, "shaker", MIDI_MARACAS, v, 0.2))

            if is_fill_bar:
                # Add fill on beat 4
                bar_events.extend(_generate_fill_events(bar_idx, snare_vel + 5, seed))
            else:
                # Regular snare on beat 4
                bar_events.append(DrumEvent(bar_idx, 4.0, "snare", MIDI_SNARE, snare_vel, 0.35))
                # Ghost snare on beat 4.75
                if enable_variations and bar_rng.uniform(0.0, 1.0) < 0.45:
                    bar_events.append(DrumEvent(bar_idx, 4.75, "snare", MIDI_SNARE, int(snare_vel * 0.40), 0.20))

        # Sort bar events chronologically by beat
        bar_events.sort(key=lambda e: (e.beat, 0 if e.instrument == "kick" else (1 if e.instrument == "snare" else 2)))
        events.extend(bar_events)

    return events


def drum_events_to_midi(
    events: Sequence[DrumEvent],
    out_midi_path: str | Path,
    bpm: float = 72.0,
    ticks_per_beat: int = 480,
) -> Path:
    """
    Convert a list of DrumEvents into a standard Type 0/1 MIDI file.
    Drums are assigned to standard General MIDI Channel 10 (channel index 9).
    """
    import mido

    out_path = Path(out_midi_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    mid = mido.MidiFile(ticks_per_beat=ticks_per_beat)
    track = mido.MidiTrack()
    mid.tracks.append(track)

    # Set Tempo: 72 BPM -> 833,333 microseconds per beat
    tempo_us = int(round(60_000_000.0 / bpm))
    track.append(mido.MetaMessage("set_tempo", tempo=tempo_us, time=0))
    track.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))
    track.append(mido.MetaMessage("track_name", name="Drums (System 1)", time=0))

    # Convert events to timed MIDI messages (in absolute ticks)
    bar_ticks = 4 * ticks_per_beat
    raw_actions: list[tuple[int, str, int, int]] = []

    for ev in events:
        start_tick = int(round(ev.bar * bar_ticks + (ev.beat - 1.0) * ticks_per_beat))
        dur_tick = max(1, int(round(ev.duration_beats * ticks_per_beat)))
        end_tick = start_tick + dur_tick

        raw_actions.append((start_tick, "note_on", ev.midi_note, ev.velocity))
        raw_actions.append((end_tick, "note_off", ev.midi_note, 0))

    # Sort actions by absolute time; note_off before note_on at same tick
    raw_actions.sort(key=lambda a: (a[0], 0 if a[1] == "note_off" else 1))

    current_tick = 0
    for abs_tick, msg_type, note, vel in raw_actions:
        delta = max(0, abs_tick - current_tick)
        track.append(
            mido.Message(
                msg_type,
                channel=9,  # GM Channel 10 is 0-indexed 9
                note=note,
                velocity=vel,
                time=delta,
            )
        )
        current_tick = abs_tick

    track.append(mido.MetaMessage("end_of_track", time=ticks_per_beat))
    mid.save(str(out_path))
    return out_path


if __name__ == "__main__":
    load_daily_data()
