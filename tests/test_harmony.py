from __future__ import annotations

import json
import math
import numpy as np
import pytest

from aetherwaves.harmony import (
    D_DORIAN,
    D_NATURAL_MINOR,
    compute_section_counts,
    generate_harmony,
    get_section_for_bar,
    print_harmony_table,
    sector_to_chord,
)
from aetherwaves.rhythm import normalize_series_5_95


def _make_bar(
    u: float | None = 0.05,
    v: float | None = 0.0,
    angle: float | None = 0.0,
    speed_p95: float | None = 1.20,
    date: str = "2025-01-01",
) -> dict:
    return {
        "date": date,
        "ageo_u": u,
        "ageo_v": v,
        "ageo_angle_deg": angle,
        "speed_p95": speed_p95,
    }


def test_section_counts_exist_and_sum_to_total():
    """All 5 sections exist and their counts sum exactly to the bar count."""
    for n in [5, 10, 16, 50, 100, 187, 365, 1000]:
        counts = compute_section_counts(n)
        assert len(counts) == 5
        names = [name for name, _ in counts]
        assert names == ["intro", "build", "peak", "calm", "outro"]

        total = sum(c for _, c in counts)
        assert total == n, f"Sum of section counts {total} must equal {n}"

        # Each section must have at least 1 bar
        for name, cnt in counts:
            assert cnt >= 1, f"Section {name} has 0 bars for total {n}"


def test_chord_changes_only_on_bar_lines():
    """Each measure has exactly one active chord (changes only on bar lines)."""
    with open("data/raw_oscar/oscar_2025_daily.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    norm_speeds, _ = normalize_series_5_95(data)
    bars = generate_harmony(data, norm_speeds)

    for b in bars:
        assert isinstance(b.chord, str)
        assert b.chord in {"Dm", "Bb", "Gm", "C", "F", "G"}
        # All bass root notes in the measure match the bar's chord root
        root_pc = {"Dm": 2, "Bb": 10, "Gm": 7, "C": 0, "F": 5, "G": 7}[b.chord]
        for ev in b.bass_events:
            if not ev.is_approach:
                assert (ev.midi_note % 12) == root_pc


def test_new_chord_needs_2_bars():
    """A new chord switches only after 2 consecutive bars pick it."""
    # 20-bar piece: Intro=bars 0-1, Build=bars 2-5, Peak=bars 6-12
    # Bars 0-5 are in Intro/Build (D minor rules apply)
    bars_data = [_make_bar(0.05, 0.0, 0.0) for _ in range(20)]
    # Bar 0: East -> Dm
    # Bar 1: North (90 deg -> Bb): 1 bar only -> must stay Dm
    bars_data[1] = _make_bar(0.0, 0.05, 90.0)
    # Bar 2: North (90 deg -> Bb): 2nd consecutive bar -> switches to Bb
    bars_data[2] = _make_bar(0.0, 0.05, 90.0)
    # Bar 3: West (180 deg -> Gm): 1 bar only -> must stay Bb
    bars_data[3] = _make_bar(-0.05, 0.0, 180.0)
    # Bar 4: East (Dm) 1 bar only -> must stay Bb
    bars_data[4] = _make_bar(0.05, 0.0, 0.0)

    norm_speeds = [0.2] * 20
    result = generate_harmony(bars_data, norm_speeds)

    assert result[0].chord == "Dm"
    assert result[1].chord == "Dm", "Single bar of North must not trigger chord change"
    assert result[2].chord == "Bb", "Two consecutive bars of North must switch to Bb"
    assert result[3].chord == "Bb", "Single bar of West must not trigger chord change"
    assert result[4].chord == "Bb", "Single bar of East must not trigger chord change"


def test_hold_below_threshold_and_missing():
    """Hold the previous chord if hypot(ageo_u, ageo_v) < 0.013 or if bar is missing."""
    # 20-bar piece: Intro=bars 0-1, Build=bars 2-5
    bars_data = [_make_bar(0.05, 0.0, 0.0) for _ in range(20)]
    # Establish Bb (North: 90 deg) at bars 0 and 1
    bars_data[0] = _make_bar(0.0, 0.05, 90.0)
    bars_data[1] = _make_bar(0.0, 0.05, 90.0)
    # Bar 2: ageo_magnitude = 0.010 (< 0.013), angle 0 (East -> would be Dm)
    bars_data[2] = _make_bar(0.010, 0.0, 0.0)
    # Bar 3: ageo_magnitude = 0.005 (< 0.013)
    bars_data[3] = _make_bar(0.005, 0.0, 0.0)
    # Bar 4: Missing data
    bars_data[4] = _make_bar(None, None, None, speed_p95=None)

    norm_speeds = [0.5] * 20
    norm_speeds[4] = None
    result = generate_harmony(bars_data, norm_speeds, hold_threshold=0.013)

    assert result[1].chord == "Bb"
    assert result[2].chord == "Bb"
    assert result[2].held is True

    assert result[3].chord == "Bb"
    assert result[3].held is True

    assert result[4].chord == "Bb"
    assert result[4].held is True
    assert result[4].is_rest is True
    assert len(result[4].bass_events) == 0, "Missing data bar must have no bass notes"


def test_calm_has_only_dm_c_g():
    """Calm section uses Dm, C, G major only (never Bb or Gm)."""
    with open("data/raw_oscar/oscar_2025_daily.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    norm_speeds, _ = normalize_series_5_95(data)
    bars = generate_harmony(data, norm_speeds)

    calm_bars = [b for b in bars if b.section == "calm"]
    assert len(calm_bars) > 0

    for b in calm_bars:
        assert b.chord in {"Dm", "C", "G"}, f"Calm bar {b.bar} has invalid chord {b.chord}"
        assert b.chord not in {"Bb", "Gm"}


def test_every_bass_note_is_in_scale():
    """Every bass note must be in D minor (or D Dorian in calm), inside cello range 36-50."""
    with open("data/raw_oscar/oscar_2025_daily.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    norm_speeds, _ = normalize_series_5_95(data)
    bars = generate_harmony(data, norm_speeds)

    for b in bars:
        scale_pcs = D_DORIAN if b.section == "calm" else D_NATURAL_MINOR
        for ev in b.bass_events:
            assert (ev.midi_note % 12) in scale_pcs, (
                f"Bar {b.bar} ({b.section}) bass note {ev.midi_note} (pc {ev.midi_note % 12}) "
                f"not in scale {scale_pcs}"
            )
            assert 36 <= ev.midi_note <= 50, (
                f"Bass note {ev.midi_note} outside cello range (36-50)"
            )


def test_same_input_gives_identical_output():
    """System 2 is 100% deterministic: same input gives identical output."""
    with open("data/raw_oscar/oscar_2025_daily.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    norm_speeds, _ = normalize_series_5_95(data)
    run_1 = generate_harmony(data, norm_speeds)
    run_2 = generate_harmony(data, norm_speeds)

    assert run_1 == run_2


def test_peak_lift_and_outro_last_bar():
    """Peak lift plays III (F) when chord is i and norm_speed >= 0.85; outro last bar is Dm."""
    section_counts = compute_section_counts(20)
    curr = 0
    peak_indices = []
    for name, cnt in section_counts:
        if name == "peak":
            peak_indices = list(range(curr, curr + cnt))
        curr += cnt

    assert len(peak_indices) > 0

    bars_data = [_make_bar(0.05, 0.0, 0.0) for _ in range(20)]  # all East -> Dm
    norm_speeds = [0.3] * 20
    lift_bar = peak_indices[1]
    norm_speeds[lift_bar] = 0.90

    result = generate_harmony(bars_data, norm_speeds)

    # The lift bar must be F (III)
    assert result[lift_bar].chord == "F"
    assert result[lift_bar].chord_numeral == "III"

    # Outro last bar must always be Dm (i)
    assert result[-1].chord == "Dm"
    assert result[-1].chord_numeral == "i"
