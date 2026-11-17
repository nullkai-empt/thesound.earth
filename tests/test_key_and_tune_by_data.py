from __future__ import annotations

import json
from pathlib import Path
import mido
import pytest

from aetherwaves.blocks import group_days_into_blocks
from aetherwaves.harmony import (
    compute_data_bounds,
    compute_key_offset,
    compute_section_counts,
    generate_harmony,
    get_tonic_name,
    sector_to_chord,
    sector_to_role,
    seed_from_period,
)
from aetherwaves.melody import generate_melody
from aetherwaves.rhythm import normalize_series_5_95
from pipeline.demo_mix import (
    generate_mix_midis,
    get_pad_actions,
    get_pad_candidates,
)


def _load_period_data(period: str) -> tuple[list[dict], int, int, str]:
    """Load records for a year or month, return (records, k, seed, tonic)."""
    raw_dir = Path("data/raw_oscar")
    is_month = "-" in period
    if is_month:
        year = period.split("-")[0]
        fpath = raw_dir / f"oscar_{year}_daily.json"
        with open(fpath, "r", encoding="utf-8") as f:
            records = [r for r in json.load(f) if str(r.get("date", "")).startswith(period)]
    else:
        fpath = raw_dir / f"oscar_{period}_daily.json"
        with open(fpath, "r", encoding="utf-8") as f:
            records = json.load(f)

    speeds = [float(d["speed_p95"]) for d in records if d.get("speed_p95") is not None]
    period_mean = sum(speeds) / len(speeds)
    k = compute_key_offset(period_mean, is_month=is_month)
    seed = seed_from_period(period)
    tonic = get_tonic_name(k)
    return records, k, seed, tonic


def test_determinism_same_period_gives_identical_output(tmp_path: Path):
    """Requirement: same period gives identical MIDI output on repeat runs."""
    records, k, seed, tonic = _load_period_data("2025")
    blocks = group_days_into_blocks(records, block_size=7)

    dir1 = tmp_path / "run1"
    dir2 = tmp_path / "run2"

    d1, h1, c1 = generate_mix_midis(blocks, seed=seed, key_offset=k, out_dir=dir1)
    d2, h2, c2 = generate_mix_midis(blocks, seed=seed, key_offset=k, out_dir=dir2)

    assert d1.read_bytes() == d2.read_bytes(), "Drums MIDI must be byte-for-byte identical"
    assert h1.read_bytes() == h2.read_bytes(), "Harmony MIDI must be byte-for-byte identical"
    assert c1.read_bytes() == c2.read_bytes(), "Combined MIDI must be byte-for-byte identical"


def test_different_periods_give_different_offset_or_seed():
    """Requirement: different periods give different key offset k or seed."""
    periods = ["2025", "2024", "2023", "2025-01", "2026-01"]
    results = {}
    for p in periods:
        records, k, seed, tonic = _load_period_data(p)
        results[p] = (k, seed, tonic)

    # Check key offsets
    assert results["2025"][0] == 5, f"2025 should have k=5 (Gm), got {results['2025'][0]}"
    assert results["2024"][0] == 4, f"2024 should have k=4 (F#m), got {results['2024'][0]}"
    assert results["2023"][0] == 6, f"2023 should have k=6 (Abm), got {results['2023'][0]}"
    assert results["2025-01"][0] == 2, f"2025-01 should have k=2 (Em), got {results['2025-01'][0]}"
    assert results["2026-01"][0] == 4, f"2026-01 should have k=4 (F#m), got {results['2026-01'][0]}"

    # All seeds must be distinct
    seeds = [results[p][1] for p in periods]
    assert len(set(seeds)) == len(periods), f"Seeds must be distinct across periods: {seeds}"


def test_all_notes_in_range_across_periods(tmp_path: Path):
    """
    Requirement: across all periods and key offsets:
    - Bass notes strictly in [36, 50]
    - Pad notes strictly in [60, 79]
    - Melody notes strictly in [52, 67]
    """
    periods = ["2025", "2024", "2023", "2025-01", "2026-01"]
    for p in periods:
        records, k, seed, tonic = _load_period_data(p)
        b_size = 1 if "-" in p else 7
        blocks = group_days_into_blocks(records, block_size=b_size)
        norm_speeds, _ = normalize_series_5_95(blocks)

        harmony_bars = generate_harmony(blocks, norm_speeds, key_offset=k)
        melody_events = generate_melody(blocks, harmony_bars, norm_speeds, seed=seed, key_offset=k)

        # Check bass notes
        for h in harmony_bars:
            for ev in h.bass_events:
                assert 36 <= ev.midi_note <= 50, (
                    f"Period {p}: Bass note {ev.midi_note} at bar {ev.bar} out of range [36, 50]"
                )

        # Check pad notes
        pad_actions = get_pad_actions(harmony_bars, norm_speeds, ticks_per_beat=480)
        note_on_actions = [a for a in pad_actions if a[2] == "note_on"]
        for _, _, _, note, vel in note_on_actions:
            assert 60 <= note <= 79, (
                f"Period {p}: Pad note {note} out of range [60, 79]"
            )

        # Check melody notes
        for m in melody_events:
            assert 52 <= m.midi_note <= 67, (
                f"Period {p}: Melody note {m.midi_note} at bar {m.bar} out of range [52, 67]"
            )


def test_no_cc11_messages_in_midi(tmp_path: Path):
    """Requirement: no CC11 expression messages exist anywhere in the generated MIDI."""
    periods = ["2025", "2025-01"]
    for p in periods:
        records, k, seed, tonic = _load_period_data(p)
        b_size = 1 if "-" in p else 7
        blocks = group_days_into_blocks(records, block_size=b_size)

        d_mid, h_mid, c_mid = generate_mix_midis(
            blocks, seed=seed, key_offset=k, out_dir=tmp_path / p
        )
        for mid_path in [d_mid, h_mid, c_mid]:
            mid = mido.MidiFile(mid_path)
            for track_idx, track in enumerate(mid.tracks):
                for msg in track:
                    if msg.type == "control_change" and msg.control == 11:
                        pytest.fail(f"Found CC11 in {mid_path.name} track {track_idx}")


def test_last_bar_is_tonic_minor_chord():
    """Requirement: last bar is always the tonic minor chord, and melody resolves to tonic root."""
    periods = ["2025", "2024", "2023", "2025-01", "2026-01"]
    for p in periods:
        records, k, seed, tonic = _load_period_data(p)
        b_size = 1 if "-" in p else 7
        blocks = group_days_into_blocks(records, block_size=b_size)
        norm_speeds, _ = normalize_series_5_95(blocks)

        harmony_bars = generate_harmony(blocks, norm_speeds, key_offset=k)
        melody_events = generate_melody(blocks, harmony_bars, norm_speeds, seed=seed, key_offset=k)

        # Last bar harmony chord must be the tonic minor
        last_harmony = harmony_bars[-1]
        assert last_harmony.chord == tonic, (
            f"Period {p}: Last bar chord is {last_harmony.chord}, expected tonic {tonic}"
        )
        assert last_harmony.chord_numeral == "i", (
            f"Period {p}: Last bar chord numeral is {last_harmony.chord_numeral}, expected 'i'"
        )

        # Last bar melody note must resolve to tonic root in [52, 67]
        last_bar_idx = len(blocks) - 1
        last_mel_events = [ev for ev in melody_events if ev.bar == last_bar_idx]
        assert len(last_mel_events) >= 1, f"Period {p}: Last bar must have melody note"
        note1 = last_mel_events[0].midi_note
        tonic_pc = (2 + k) % 12
        assert note1 % 12 == tonic_pc, (
            f"Period {p}: Last bar note {note1} pc {note1 % 12} must match tonic pc {tonic_pc}"
        )
        assert 52 <= note1 <= 67


def test_eight_sectors_south_west_fix():
    """Requirement: SW sector (-157.5..-112.5) must map to C (role VII) as docstring states, not Bb."""
    # Test SW angle -135 degrees
    role = sector_to_role(-135.0, is_calm=False, eight_sectors=True)
    assert role == "VII", f"SW in 8-sectors should be role VII, got {role}"
    chord = sector_to_chord(-135.0, is_calm=False, eight_sectors=True, key_offset=0)
    assert chord == "C", f"SW in 8-sectors should be C in key 0, got {chord}"


def test_month_mode_uses_same_rules_as_yearly():
    """Requirement: Month mode uses same chord rules as yearly: 4 sectors, hysteresis 2, 1 day = 1 bar."""
    records_jan, k, seed, tonic = _load_period_data("2025-01")
    assert len(records_jan) == 31
    # 1 day = 1 bar
    blocks = group_days_into_blocks(records_jan, block_size=1)
    assert len(blocks) == 31

    norm_speeds, _ = normalize_series_5_95(blocks)
    # Default generate_harmony uses 4 sectors and hysteresis 2
    harmony_bars = generate_harmony(blocks, norm_speeds, key_offset=k)
    assert len(harmony_bars) == 31
    # Check that Calm section only contains allowed chords (transposed i, VII, IV_calm)
    from aetherwaves.harmony import ROLE_CHORD_TABLE
    allowed_calm_roles = {"i", "VII", "IV_calm"}
    allowed_calm_chords = {ROLE_CHORD_TABLE[k][r][0] for r in allowed_calm_roles}
    for h in harmony_bars:
        if h.section == "calm":
            assert h.chord in allowed_calm_chords, (
                f"Calm bar {h.bar} has chord {h.chord} not in allowed calm set {allowed_calm_chords}"
            )
