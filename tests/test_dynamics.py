from __future__ import annotations

import json
from pathlib import Path

import mido
import numpy as np
import pytest

from aetherwaves.blocks import group_days_into_blocks
from aetherwaves.dynamics import (
    CRASH_MIDI_NOTE,
    CRASH_VELOCITY,
    DYNAMICS_BASE_SCALE,
    DYNAMICS_SMOOTH_FACTOR,
    MAX_VELOCITY,
    MIN_VELOCITY,
    RISER_BEATS,
    RISER_MIDI_NOTE,
    RISER_PROGRAM,
    RISER_VELOCITIES,
    TOP_PERCENTILE,
    apply_velocity_scale,
    compute_smooth_speeds,
    compute_velocity_scales,
    find_top5_runs,
    generate_crash_events,
    generate_riser_actions,
    scale_drum_events,
)
from aetherwaves.harmony import generate_harmony
from aetherwaves.melody import generate_melody
from aetherwaves.rhythm import DrumEvent, generate_drum_events, normalize_series_5_95
from pipeline.demo_mix import build_combined_midi

DATA_PATH = Path("data/raw_oscar/oscar_2025_daily.json")


def load_test_blocks():
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        daily_records = json.load(f)
    blocks = group_days_into_blocks(daily_records, block_size=7)
    norm_speeds, _ = normalize_series_5_95(blocks)
    harmony_bars = generate_harmony(blocks, norm_speeds)
    drum_events = generate_drum_events(norm_speeds)
    melody_events = generate_melody(blocks, harmony_bars, norm_speeds)
    return blocks, norm_speeds, harmony_bars, drum_events, melody_events


def test_velocity_scale_monotonic_with_smooth_speed() -> None:
    """Requirement: scale = 0.70 + 0.30 * smooth_speed, strictly monotonic increasing."""
    speeds = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
    scales = compute_velocity_scales(speeds)
    assert len(scales) == len(speeds)
    assert scales[0] == pytest.approx(0.70, abs=1e-5)
    assert scales[-1] == pytest.approx(1.00, abs=1e-5)

    for i in range(len(scales) - 1):
        assert scales[i] < scales[i + 1], "Velocity scale must increase monotonically with smooth speed"

    # Missing bar returns 0.0
    scales_with_none = compute_velocity_scales([0.5, None, 0.8])
    assert scales_with_none[1] == 0.0


def test_centered_moving_average_edges_and_interior() -> None:
    """Requirement: 3-bar centered moving average, edges use available bars."""
    speeds = [0.2, 0.4, 0.6, 0.8, 1.0]
    smooth = compute_smooth_speeds(speeds)
    assert len(smooth) == len(speeds)

    # Edge i=0: mean(speeds[0], speeds[1])
    assert smooth[0] == pytest.approx(np.mean([0.2, 0.4]), abs=1e-5)
    # Interior i=1: mean(speeds[0], speeds[1], speeds[2])
    assert smooth[1] == pytest.approx(np.mean([0.2, 0.4, 0.6]), abs=1e-5)
    # Interior i=2: mean(speeds[1], speeds[2], speeds[3])
    assert smooth[2] == pytest.approx(np.mean([0.4, 0.6, 0.8]), abs=1e-5)
    # Edge i=4: mean(speeds[3], speeds[4])
    assert smooth[4] == pytest.approx(np.mean([0.8, 1.0]), abs=1e-5)

    # With missing data (None)
    speeds_with_missing = [0.2, None, 0.8]
    smooth_missing = compute_smooth_speeds(speeds_with_missing)
    assert smooth_missing[0] == pytest.approx(0.2, abs=1e-5)
    assert smooth_missing[1] is None
    assert smooth_missing[2] == pytest.approx(0.8, abs=1e-5)


def test_crash_only_on_top5_run_starts_and_riser_only_on_bar_before() -> None:
    """
    Requirement:
    - Top 5% bars: norm_speed >= 95th percentile of valid bars.
    - Crash cymbal (GM 49) on beat 1 of first bar of each run, velocity 100.
    - Riser in the bar before it: GM 119 Reverse Cymbal, beats 3-4, rising 50->90.
    - If top-5% bar is bar 0 or 1, no riser.
    """
    # Synthetic series with runs:
    # 20 bars: mostly 0.1, with top bars at index 0, 1 (contiguous), index 5, 6 (contiguous), and index 12
    series = [0.1] * 20
    series[0] = 0.95  # Top bar at index 0 -> no riser (r <= 1)
    series[1] = 0.95  # Top bar at index 1 -> contiguous with 0
    series[5] = 0.95  # Run start at 5 -> riser at bar 4
    series[6] = 0.95  # Contiguous run -> NO crash, NO riser
    series[12] = 0.95 # Run start at 12 -> riser at bar 11

    run_starts, riser_bars = find_top5_runs(series, percentile=80.0)
    assert 0 in run_starts
    assert 1 not in run_starts, "Only the first bar of a contiguous run gets crash"
    assert 5 in run_starts
    assert 6 not in run_starts
    assert 12 in run_starts

    # Bar 0 run start has r=0 <= 1, so no riser
    assert -1 not in riser_bars
    assert 0 not in riser_bars
    # Bar 5 run start has riser at bar 4
    assert 4 in riser_bars
    # Bar 12 run start has riser at bar 11
    assert 11 in riser_bars
    assert len(riser_bars) == 2

    # Crash events
    crashes = generate_crash_events(run_starts, series)
    crash_bars = [c.bar for c in crashes]
    assert crash_bars == run_starts
    for c in crashes:
        assert c.midi_note == CRASH_MIDI_NOTE
        assert c.velocity == CRASH_VELOCITY
        assert c.beat == 1.0

    # Riser actions
    riser_actions = generate_riser_actions(riser_bars, ticks_per_beat=480)
    prog_changes = [a for a in riser_actions if a[2] == "program_change"]
    assert len(prog_changes) == 1
    assert prog_changes[0][3] == RISER_PROGRAM

    riser_notes = [a for a in riser_actions if a[2] == "note_on"]
    # 2 riser bars * 4 notes = 8 note_ons
    assert len(riser_notes) == 8
    for a in riser_notes:
        assert a[3] == RISER_MIDI_NOTE
    # Check velocity rising sequence
    vels = [a[4] for a in riser_notes[:4]]
    assert tuple(vels) == RISER_VELOCITIES


def test_drum_hit_pattern_preserved_after_dynamics() -> None:
    """Requirement: Drum velocity may follow scale, but never change which hits play."""
    blocks, norm_speeds, _, drum_events, _ = load_test_blocks()
    smooth_speeds = compute_smooth_speeds(norm_speeds)
    scales = compute_velocity_scales(smooth_speeds)

    scaled_drums = scale_drum_events(drum_events, scales)
    assert len(scaled_drums) == len(drum_events), "Drum event count must be preserved exactly"

    for orig, scaled in zip(drum_events, scaled_drums):
        assert orig.bar == scaled.bar
        assert orig.beat == scaled.beat
        assert orig.instrument == scaled.instrument
        assert orig.midi_note == scaled.midi_note
        assert orig.duration_beats == scaled.duration_beats
        assert 1 <= scaled.velocity <= 110, f"Scaled velocity {scaled.velocity} out of [1, 110]"


def test_all_velocities_in_range_1_to_110(tmp_path: Path) -> None:
    """Requirement: Clamp final velocity to 1-110 across all tracks."""
    blocks, norm_speeds, harmony_bars, drum_events, melody_events = load_test_blocks()
    out_midi = tmp_path / "test_combined.mid"

    build_combined_midi(
        drum_events=drum_events,
        harmony_bars=harmony_bars,
        norm_speeds=norm_speeds,
        out_path=out_midi,
        melody_events=melody_events,
    )

    mid = mido.MidiFile(str(out_midi))
    for track in mid.tracks:
        for msg in track:
            if msg.type == "note_on" and msg.velocity > 0:
                assert MIN_VELOCITY <= msg.velocity <= MAX_VELOCITY, (
                    f"Note on track '{track.name}' note={msg.note} has velocity {msg.velocity}, "
                    f"outside [{MIN_VELOCITY}, {MAX_VELOCITY}]"
                )


def test_no_cc11_events_in_midi(tmp_path: Path) -> None:
    """Requirement: No CC11 ramps, no CC11 expression events anywhere in the MIDI."""
    blocks, norm_speeds, harmony_bars, drum_events, melody_events = load_test_blocks()
    out_midi = tmp_path / "test_combined.mid"

    build_combined_midi(
        drum_events=drum_events,
        harmony_bars=harmony_bars,
        norm_speeds=norm_speeds,
        out_path=out_midi,
        melody_events=melody_events,
    )

    mid = mido.MidiFile(str(out_midi))
    for track in mid.tracks:
        for msg in track:
            if msg.type == "control_change":
                assert msg.control != 11, f"Found unexpected CC11 on track '{track.name}'"


def test_dynamics_deterministic(tmp_path: Path) -> None:
    """Requirement: Same input must give exact same output byte-for-byte."""
    blocks, norm_speeds, harmony_bars, drum_events, melody_events = load_test_blocks()
    out1 = tmp_path / "mix1.mid"
    out2 = tmp_path / "mix2.mid"

    build_combined_midi(
        drum_events=drum_events,
        harmony_bars=harmony_bars,
        norm_speeds=norm_speeds,
        out_path=out1,
        melody_events=melody_events,
    )
    build_combined_midi(
        drum_events=drum_events,
        harmony_bars=harmony_bars,
        norm_speeds=norm_speeds,
        out_path=out2,
        melody_events=melody_events,
    )

    assert out1.read_bytes() == out2.read_bytes(), "Combined MIDI output must be byte-for-byte deterministic"


def test_missing_data_dynamics_behavior() -> None:
    """Requirement: Missing data = rest, no accents, no riser."""
    norm_speeds = [0.5, None, 0.99, None]
    smooth_speeds = compute_smooth_speeds(norm_speeds)
    scales = compute_velocity_scales(smooth_speeds)

    # Missing bar scale is 0.0
    assert scales[1] == 0.0
    assert scales[3] == 0.0

    run_starts, riser_bars = find_top5_runs(norm_speeds)
    # Norm speeds: valid speeds are [0.5, 0.99]. 95th percentile is >= 0.5.
    # Check that missing bars are never in run_starts or riser_bars
    assert 1 not in run_starts
    assert 3 not in run_starts
    assert 1 not in riser_bars
    assert 3 not in riser_bars
