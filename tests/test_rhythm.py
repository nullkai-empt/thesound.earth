from __future__ import annotations

import numpy as np
import pytest
from aetherwaves.rhythm import (
    DrumEvent,
    generate_drum_events,
    load_daily_data,
    normalize_series_5_95,
    speed_to_tier,
)


def test_missing_equals_rest():
    """Missing data (None) must produce a full-bar rest (0 events)."""
    # 1. Pure missing series
    events = generate_drum_events([None, None, None])
    assert len(events) == 0

    # 2. Interspersed missing bars
    speeds = [0.2, None, 0.2, None, 0.8]
    events = generate_drum_events(speeds, seed=42)

    bars_with_events = {e.bar for e in events}
    assert 1 not in bars_with_events, "Bar 1 is missing and must have no drum events"
    assert 3 not in bars_with_events, "Bar 3 is missing and must have no drum events"
    assert 0 in bars_with_events
    assert 2 in bars_with_events
    assert 4 in bars_with_events


def test_none_day_becomes_rest():
    """Requirement 7(a): Verify None, NaN, or missing speed_p95 becomes a full rest."""
    records = [
        {"date": "2025-01-01", "speed_p95": 1.15},
        {"date": "2025-01-02", "speed_p95": None},
        {"date": "2025-01-03", "speed_p95": float("nan")},
        {"date": "2025-01-04"},  # missing key
        {"date": "2025-01-05", "speed_p95": 1.28},
    ]
    norm, audit = normalize_series_5_95(records)
    assert norm[0] is not None
    assert norm[1] is None
    assert norm[2] is None
    assert norm[3] is None
    assert norm[4] is not None

    events = generate_drum_events(norm, seed=42)
    bars_with_events = {e.bar for e in events}
    assert 1 not in bars_with_events, "Bar 1 must be a rest"
    assert 2 not in bars_with_events, "Bar 2 must be a rest"
    assert 3 not in bars_with_events, "Bar 3 must be a rest"
    assert 0 in bars_with_events
    assert 4 in bars_with_events


def test_whole_series_normalization_clamped_and_uses_p5_p95():
    """Requirement 7(b): Whole-series normalization is clamped 0-1, uses P5/P95, keeps raw audit."""
    raw_vals = [1.0 + 0.05 * i for i in range(21)]
    records = [{"date": f"2025-01-{i+1:02d}", "speed_p95": v} for i, v in enumerate(raw_vals)]
    norm, audit = normalize_series_5_95(records)

    p5 = audit["p5"]
    p95 = audit["p95"]
    assert audit["min"] == min(raw_vals)
    assert audit["max"] == max(raw_vals)
    assert p5 < p95

    # Check clamping and formula
    for v, n in zip(raw_vals, norm):
        assert 0.0 <= n <= 1.0
        if v <= p5:
            assert n == 0.0
        elif v >= p95:
            assert n == 1.0
        else:
            expected = round((v - p5) / (p95 - p5), 4)
            assert abs(n - expected) < 1e-3


def test_printed_summary_lines_appear(capsys):
    """Requirement 7(c): Verify printed summary line appears after loading."""
    load_daily_data("data/raw_oscar/oscar_2025_daily.json", print_summary=True)
    captured = capsys.readouterr().out

    assert "speed changed" in captured
    assert "% over the period" in captured
    assert "Jan mean p95 = " in captured
    assert "Jun mean p95 = " in captured
    assert "change = " in captured


def test_drum_output_changes_when_real_data_changes():
    """Requirement 7(d): Verify drum output changes when real OSCAR data changes."""
    records, norm_speeds, audit = load_daily_data("data/raw_oscar/oscar_2025_daily.json", print_summary=False)

    # Compare 14 days from January (calmer) vs 14 days from June (higher speed_p95)
    jan_norm = norm_speeds[:14]
    jun_start = next(i for i, r in enumerate(records) if str(r.get("date", "")).startswith("2025-06"))
    jun_norm = norm_speeds[jun_start : jun_start + 14]

    events_jan = generate_drum_events(jan_norm, seed=42)
    events_jun = generate_drum_events(jun_norm, seed=42)

    assert events_jan != events_jun
    jan_kicks = [e.velocity for e in events_jan if e.instrument == "kick"]
    jun_kicks = [e.velocity for e in events_jun if e.instrument == "kick"]
    assert np.mean(jun_kicks) > np.mean(jan_kicks), "Higher summer current speeds must produce higher drum velocity"


def test_monotonic_density():
    """Higher speed must never produce lower drum density."""
    # Test steady-state density across tiers
    low_events = generate_drum_events([0.2] * 4, seed=42)
    med_events = generate_drum_events([0.5] * 4, seed=42)
    high_events = generate_drum_events([0.85] * 4, seed=42)

    low_bar_density = len([e for e in low_events if e.bar == 2])
    med_bar_density = len([e for e in med_events if e.bar == 2])
    high_bar_density = len([e for e in high_events if e.bar == 2])

    assert low_bar_density == 2
    assert 12 <= med_bar_density <= 14
    assert high_bar_density >= 20
    assert low_bar_density < med_bar_density < high_bar_density

    # Check that higher speed within any tier increases velocity
    low_slow = generate_drum_events([0.05] * 3, seed=42)
    low_fast = generate_drum_events([0.30] * 3, seed=42)
    kick_slow = next(e.velocity for e in low_slow if e.bar == 2 and e.instrument == "kick")
    kick_fast = next(e.velocity for e in low_fast if e.bar == 2 and e.instrument == "kick")
    assert kick_fast > kick_slow, "Velocity must scale up with higher speed"

    # Compare steady-state density across a spectrum of speeds (no variations for deterministic base checks)
    sample_speeds = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    densities = []
    for sp in sample_speeds:
        evs = generate_drum_events([sp] * 3, seed=42, enable_variations=False)
        bar_count = len([e for e in evs if e.bar == 2])
        densities.append(bar_count)

    for i in range(1, len(densities)):
        assert densities[i] >= densities[i - 1], (
            f"Density decreased from speed {sample_speeds[i-1]} ({densities[i-1]}) "
            f"to speed {sample_speeds[i]} ({densities[i]})"
        )


def test_same_seed_identical_output():
    """Same input and seed must produce identical output every time."""
    speeds = [0.2, 0.5, 0.8, 0.9, 0.85, 0.9, 0.95, 0.8, None, 0.4]
    run_1 = generate_drum_events(speeds, seed=99)
    run_2 = generate_drum_events(speeds, seed=99)

    assert run_1 == run_2, "Drum events must be byte-for-byte identical with the same seed"

    # Different seeds should produce different fills in high tier
    run_diff_seed = generate_drum_events(speeds, seed=12345)
    fills_1 = [e for e in run_1 if e.instrument in ("tom", "snare") and e.beat >= 4.0]
    fills_diff = [e for e in run_diff_seed if e.instrument in ("tom", "snare") and e.beat >= 4.0]
    assert fills_1 != fills_diff, "Different seeds should produce different deterministic fills"


def test_tier_changes_only_on_bar_lines_and_after_2_bars():
    """Tier must change only on a bar line, and only after 2 bars at the new level."""
    speeds = [0.1, 0.1, 0.1, 0.85, 0.1, 0.5, 0.5, 0.5]
    events = generate_drum_events(speeds, seed=42)

    def get_bar_events(b: int) -> list[DrumEvent]:
        return [e for e in events if e.bar == b]

    # Bars 0, 1, 2 should be low tier (2 kicks)
    assert len(get_bar_events(0)) == 2
    assert len(get_bar_events(1)) == 2
    assert len(get_bar_events(2)) == 2

    # Bar 3 has high speed, but only 1 bar -> tier remains low (debounced)
    bar_3_events = get_bar_events(3)
    assert len(bar_3_events) == 2
    assert {e.instrument for e in bar_3_events} == {"kick"}

    # Bar 4 is low -> still low tier
    assert len(get_bar_events(4)) == 2

    # Bar 5 has medium speed (1 bar at medium) -> must still be low tier
    bar_5_events = get_bar_events(5)
    assert len(bar_5_events) == 2

    # Bar 6 has medium speed (2nd consecutive bar at medium) -> switches to medium tier
    bar_6_events = get_bar_events(6)
    assert 12 <= len(bar_6_events) <= 14
    assert "snare" in {e.instrument for e in bar_6_events}
    assert "shaker" in {e.instrument for e in bar_6_events}

    # Verify that all events within a bar have beat positions strictly within that bar (1.0 <= beat < 5.0)
    for e in events:
        assert 1.0 <= e.beat < 5.0, f"Event beat {e.beat} outside 4/4 measure bounds"
