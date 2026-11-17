import json
import math
from pathlib import Path

from aetherwaves.blocks import group_days_into_blocks
from aetherwaves.harmony import generate_harmony
from aetherwaves.melody import (
    CHORD_PCS,
    MAX_JUMP_SEMITONES,
    MAX_MIDI,
    MIN_MIDI,
    MelodyEvent,
    generate_melody,
)
from aetherwaves.rhythm import normalize_series_5_95


def _load_real_blocks():
    json_path = Path("data/raw_oscar/oscar_2025_daily.json")
    with open(json_path, "r", encoding="utf-8") as f:
        daily_records = json.load(f)
    blocks = group_days_into_blocks(daily_records, block_size=7)
    norm_speeds, _ = normalize_series_5_95(blocks)
    harmony_bars = generate_harmony(blocks, norm_speeds, hold_threshold=0.013)
    return blocks, harmony_bars, norm_speeds


def test_same_input_twice_gives_identical_output():
    """Requirement: same input twice gives identical output (deterministic with seed 42)."""
    blocks, harmony_bars, norm_speeds = _load_real_blocks()

    run1 = generate_melody(blocks, harmony_bars, norm_speeds, seed=42)
    run2 = generate_melody(blocks, harmony_bars, norm_speeds, seed=42)

    assert len(run1) == len(run2)
    for e1, e2 in zip(run1, run2):
        assert e1.bar == e2.bar
        assert math.isclose(e1.beat, e2.beat, abs_tol=1e-5)
        assert e1.midi_note == e2.midi_note
        assert e1.velocity == e2.velocity
        assert math.isclose(e1.duration_beats, e2.duration_beats, abs_tol=1e-5)
        assert math.isclose(e1.timing_offset_ms, e2.timing_offset_ms, abs_tol=1e-5)


def test_no_melody_notes_in_intro_bars():
    """Requirement: no melody notes in the intro section (first 10% of bars)."""
    blocks, harmony_bars, norm_speeds = _load_real_blocks()
    events = generate_melody(blocks, harmony_bars, norm_speeds, seed=42)

    intro_bar_indices = {h.bar for h in harmony_bars if h.section == "intro"}
    assert len(intro_bar_indices) > 0, "Must have intro bars"

    for ev in events:
        assert ev.bar not in intro_bar_indices, f"Found melody note at bar {ev.bar} in intro section"


def test_onsets_only_on_beats_1_and_3():
    """Requirement: note onsets only on beats 1 and 3 (the kick beats, before timing offset)."""
    blocks, harmony_bars, norm_speeds = _load_real_blocks()
    events = generate_melody(blocks, harmony_bars, norm_speeds, seed=42)

    assert len(events) > 0, "Must have generated melody events"
    for ev in events:
        is_beat_1 = math.isclose(ev.beat, 1.0, abs_tol=1e-3)
        is_beat_3 = math.isclose(ev.beat, 3.0, abs_tol=1e-3)
        assert is_beat_1 or is_beat_3, (
            f"Bar {ev.bar}: onset on beat {ev.beat} is not on beat 1 or beat 3"
        )


def test_no_jump_larger_than_4_semitones_between_bar_start_notes():
    """Requirement: no jump larger than 4 semitones between bar-start notes (voice leading)."""
    blocks, harmony_bars, norm_speeds = _load_real_blocks()
    events = generate_melody(blocks, harmony_bars, norm_speeds, seed=42)

    bar_start_notes = [e for e in events if math.isclose(e.beat, 1.0, abs_tol=1e-3)]
    assert len(bar_start_notes) > 1, "Must have multiple bar-start notes"

    for i in range(1, len(bar_start_notes)):
        prev_note = bar_start_notes[i - 1].midi_note
        curr_note = bar_start_notes[i].midi_note
        jump = abs(curr_note - prev_note)
        assert jump <= MAX_JUMP_SEMITONES, (
            f"Jump between bar {bar_start_notes[i-1].bar} (note {prev_note}) and "
            f"bar {bar_start_notes[i].bar} (note {curr_note}) is {jump} semitones > {MAX_JUMP_SEMITONES}"
        )


def test_all_notes_in_midi_52_67():
    """Requirement: all notes in range MIDI 52-67 only (nothing above G4 = 67)."""
    blocks, harmony_bars, norm_speeds = _load_real_blocks()
    events = generate_melody(blocks, harmony_bars, norm_speeds, seed=42)

    assert len(events) > 0, "Must have generated melody events"
    for ev in events:
        assert MIN_MIDI <= ev.midi_note <= MAX_MIDI, (
            f"Note {ev.midi_note} at bar {ev.bar} beat {ev.beat} is outside [{MIN_MIDI}, {MAX_MIDI}]"
        )


def test_missing_data_bar_has_no_notes():
    """Requirement: missing data or a held bar = a rest, never a note."""
    blocks, harmony_bars, norm_speeds = _load_real_blocks()

    test_blocks = [dict(b) for b in blocks]
    test_speeds = list(norm_speeds)

    # Bar 10: missing data
    test_blocks[10]["speed_p95"] = None
    test_speeds[10] = None

    # Bar 12: missing speed
    test_blocks[12]["speed_p95"] = None
    test_speeds[12] = None

    test_harmony = generate_harmony(test_blocks, test_speeds, hold_threshold=0.013)
    events = generate_melody(test_blocks, test_harmony, test_speeds, seed=42)

    # Missing bars must have 0 events
    for b_idx in [10, 12]:
        bar_events = [e for e in events if e.bar == b_idx]
        assert len(bar_events) == 0, f"Expected 0 melody notes for missing data at bar {b_idx}, got {len(bar_events)}"

    # Held bars must have 0 events
    for h in test_harmony:
        if h.held:
            held_events = [e for e in events if e.bar == h.bar]
            assert len(held_events) == 0, f"Held bar {h.bar} must have 0 melody notes, got {len(held_events)}"


def test_last_bar_starts_on_d():
    """Requirement: last outro bar starts on D (MIDI 62)."""
    blocks, harmony_bars, norm_speeds = _load_real_blocks()
    events = generate_melody(blocks, harmony_bars, norm_speeds, seed=42)

    last_bar_idx = len(blocks) - 1
    last_bar_events = [e for e in events if e.bar == last_bar_idx]

    assert len(last_bar_events) >= 1, "Last bar must have a melody event"
    first_ev = min(last_bar_events, key=lambda e: e.beat)

    assert math.isclose(first_ev.beat, 1.0, abs_tol=1e-3), f"Last bar note must start on beat 1, got {first_ev.beat}"
    # D is pitch class 2 (MIDI 62)
    assert first_ev.midi_note % 12 == 2, f"Last bar note must be D (pc=2), got note {first_ev.midi_note}"
    assert first_ev.midi_note == 62, f"Last bar note in 52-67 must be D4 (62), got {first_ev.midi_note}"


def test_beats_1_and_3_are_always_chord_tones():
    """Requirement: every note on beat 1 and beat 3 is a chord tone of that bar's chord."""
    blocks, harmony_bars, norm_speeds = _load_real_blocks()
    events = generate_melody(blocks, harmony_bars, norm_speeds, seed=42)

    for ev in events:
        chord = harmony_bars[ev.bar].chord
        allowed_pcs = CHORD_PCS[chord]
        note_pc = ev.midi_note % 12
        assert note_pc in allowed_pcs, (
            f"Bar {ev.bar} on beat {ev.beat}: note {ev.midi_note} (pc={note_pc}) is not a chord tone of {chord} ({allowed_pcs})"
        )
