import json
import sys
from pathlib import Path

# Add repo root to sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from aetherwaves.blocks import group_days_into_blocks
from aetherwaves.harmony import generate_harmony
from aetherwaves.rhythm import normalize_series_5_95
from pipeline.demo_mix import (
    ADD9_INFO,
    generate_mix_midis,
    get_pad_actions,
    get_pad_candidates,
)

# Scale Pitch Classes (modulo 12: D=2, E=4, F=5, G=7, A=9, Bb=10, B=11, C=0)
D_NATURAL_MINOR = {2, 4, 5, 7, 9, 10, 0}
D_DORIAN = {2, 4, 5, 7, 9, 11, 0}


def test_three_midi_files_identical_on_two_runs_with_same_seed(tmp_path: Path) -> None:
    """Requirement 6: The three MIDI files are identical on two runs with the same seed."""
    json_path = Path("data/raw_oscar/oscar_2025_daily.json")
    assert json_path.exists(), "OSCAR daily data file must exist"

    with open(json_path, "r", encoding="utf-8") as f:
        daily_records = json.load(f)

    blocks = group_days_into_blocks(daily_records, block_size=7)
    assert len(blocks) == 53

    dir_run1 = tmp_path / "run1"
    dir_run2 = tmp_path / "run2"

    drums1, harm1, comb1 = generate_mix_midis(blocks, seed=42, out_dir=dir_run1)
    drums2, harm2, comb2 = generate_mix_midis(blocks, seed=42, out_dir=dir_run2)

    # All three files must exist
    assert drums1.exists() and drums2.exists()
    assert harm1.exists() and harm2.exists()
    assert comb1.exists() and comb2.exists()

    # Compare exact binary bytes
    assert drums1.read_bytes() == drums2.read_bytes(), "mix_drums.mid differs across runs with same seed"
    assert harm1.read_bytes() == harm2.read_bytes(), "mix_harmony.mid differs across runs with same seed"
    assert comb1.read_bytes() == comb2.read_bytes(), "mix_combined.mid differs across runs with same seed"


def test_every_pad_note_between_60_and_79_and_in_scale() -> None:
    """Requirement: Every pad note is between MIDI 60 and 79 (PAD_OCTAVE_SHIFT=+1) and is in the scale."""
    # 1. Test all candidate voicings directly across all supported chords
    for chord in ADD9_INFO:
        cands = get_pad_candidates(chord)
        assert len(cands) > 0, f"Chord {chord} must have valid voicings in [60, 79]"
        expected_scale = D_DORIAN if chord == "G" else D_NATURAL_MINOR
        for voicing in cands:
            assert len(voicing) == 4, "Voicing must have 4 distinct notes"
            for note in voicing:
                assert 60 <= note <= 79, f"Note {note} in {chord} voicing {voicing} out of range [60, 79]"
                assert (note % 12) in expected_scale, f"Note {note} in {chord} voicing {voicing} not in scale"

    # 2. Test actual sequence generated on real NASA OSCAR data (both 7-day and 5-day blocks)
    json_path = Path("data/raw_oscar/oscar_2025_daily.json")
    with open(json_path, "r", encoding="utf-8") as f:
        daily_records = json.load(f)

    for b_size in [7, 5]:
        blocks = group_days_into_blocks(daily_records, block_size=b_size)
        norm_speeds, _ = normalize_series_5_95(blocks)
        harmony_bars = generate_harmony(blocks, norm_speeds)

        pad_actions = get_pad_actions(harmony_bars, norm_speeds, ticks_per_beat=480)
        note_on_actions = [a for a in pad_actions if a[2] == "note_on"]
        assert len(note_on_actions) > 0, "Pad must have note events"

        for abs_tick, _, msg_type, note, vel in note_on_actions:
            bar_idx = abs_tick // (4 * 480)
            sec = harmony_bars[bar_idx].section
            scale = D_DORIAN if sec == "calm" else D_NATURAL_MINOR

            assert 60 <= note <= 79, f"Pad note {note} at bar {bar_idx} ({sec}) is outside [60, 79]"
            assert (note % 12) in scale, f"Pad note {note} at bar {bar_idx} ({sec}) is not in scale"
            assert 1 <= vel <= 127, f"Pad velocity {vel} is outside valid MIDI range [1, 127]"
            assert 19 <= vel <= 48, f"Pad velocity {vel} is outside soft dynamics range [19, 48]"


def test_no_cc11_events_in_generated_midi(tmp_path: Path) -> None:
    """Requirement 1: Verify no CC11 expression messages are sent on any track."""
    import mido

    json_path = Path("data/raw_oscar/oscar_2025_daily.json")
    with open(json_path, "r", encoding="utf-8") as f:
        daily_records = json.load(f)

    blocks = group_days_into_blocks(daily_records, block_size=7)
    drums_mid, harm_mid, comb_mid = generate_mix_midis(blocks, seed=42, out_dir=tmp_path)

    for midi_file in [harm_mid, comb_mid]:
        mid = mido.MidiFile(str(midi_file))
        for tr in mid.tracks:
            cc11_events = [m for m in tr if m.type == "control_change" and m.control == 11]
            assert len(cc11_events) == 0, f"Track {tr.name} in {midi_file.name} must not contain CC11 events"
