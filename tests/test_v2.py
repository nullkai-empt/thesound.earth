import hashlib
import json
from pathlib import Path
import mido
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

from aetherwaves.adapters.fires import FIRMSAdapter
from aetherwaves.adapters.oscar import OscarAdapter
from aetherwaves.blocks import group_days_into_blocks
from aetherwaves.engine_v2.pipeline_v2 import build_midi_v2
from aetherwaves.rhythm import normalize_series_5_95

PRESETS_PATH = REPO_ROOT / "config" / "presets_v2.json"


def test_sounding_notes_strictly_within_preset_scale(tmp_path: Path):
    """Every sounding note (melody and harmony) in india and kuroshio falls strictly within that preset's scale semitones."""
    presets = json.loads(PRESETS_PATH.read_text(encoding="utf-8"))["presets"]

    # --- 1. India ---
    land_cfg = json.loads((REPO_ROOT / "config/land_regions.json").read_text(encoding="utf-8"))["regions"]
    india_cfg = next(r for r in land_cfg if r["id"] == "india")["fires"]
    adapter_in = FIRMSAdapter(west=india_cfg["lon"][0], south=india_cfg["lat"][0], east=india_cfg["lon"][1], north=india_cfg["lat"][1], year=2025)
    rows_in = adapter_in.rows()
    blocks_in = group_days_into_blocks(rows_in, block_size=7)
    norm_in, _ = normalize_series_5_95(blocks_in)

    mid_in_path = tmp_path / "india.mid"
    build_midi_v2(blocks_in, norm_in, presets["india"], "india", seed=42, out_mid_path=mid_in_path)

    scale_in = set(presets["india"]["scale"])
    mid_in = mido.MidiFile(str(mid_in_path))
    in_note_count = 0
    for track in mid_in.tracks:
        for msg in track:
            if msg.type == "note_on" and msg.velocity > 0:
                if msg.channel != 9:  # non-percussion channels
                    in_note_count += 1
                    assert (msg.note % 12) in scale_in, f"India note {msg.note} (pc={msg.note % 12}) not in scale {scale_in}"
    assert in_note_count > 0, "India must contain sounding notes"

    # --- 2. Kuroshio ---
    src_ku = REPO_ROOT / "data/raw_oscar/regions/kuroshio/oscar_2025_daily.json"
    adapter_ku = OscarAdapter(src_ku)
    rows_ku = adapter_ku.rows()
    blocks_ku = group_days_into_blocks(rows_ku, block_size=7)
    norm_ku, _ = normalize_series_5_95(blocks_ku)

    mid_ku_path = tmp_path / "kuroshio.mid"
    build_midi_v2(blocks_ku, norm_ku, presets["kuroshio"], "kuroshio", seed=42, out_mid_path=mid_ku_path)

    scale_ku = set(presets["kuroshio"]["scale"])
    mid_ku = mido.MidiFile(str(mid_ku_path))
    ku_note_count = 0
    for track in mid_ku.tracks:
        for msg in track:
            if msg.type == "note_on" and msg.velocity > 0:
                if msg.channel != 9:  # non-percussion channels
                    ku_note_count += 1
                    assert (msg.note % 12) in scale_ku, f"Kuroshio note {msg.note} (pc={msg.note % 12}) not in scale {scale_ku}"
    assert ku_note_count > 0, "Kuroshio must contain sounding notes"


def test_determinism_two_runs(tmp_path: Path):
    """Two runs of build_midi_v2 produce byte-identical MIDI files."""
    presets = json.loads(PRESETS_PATH.read_text(encoding="utf-8"))["presets"]

    src_ku = REPO_ROOT / "data/raw_oscar/regions/kuroshio/oscar_2025_daily.json"
    adapter_ku = OscarAdapter(src_ku)
    rows_ku = adapter_ku.rows()
    blocks_ku = group_days_into_blocks(rows_ku, block_size=7)
    norm_ku, _ = normalize_series_5_95(blocks_ku)

    run1 = tmp_path / "run1.mid"
    run2 = tmp_path / "run2.mid"
    build_midi_v2(blocks_ku, norm_ku, presets["kuroshio"], "kuroshio", seed=12345, out_mid_path=run1)
    build_midi_v2(blocks_ku, norm_ku, presets["kuroshio"], "kuroshio", seed=12345, out_mid_path=run2)

    assert run1.read_bytes() == run2.read_bytes(), "MIDI output differs across deterministic runs!"


def test_none_input_produces_rest_and_zero_fires_valid():
    """A None input row produces a rest (silence) and zero FIRMS fire produces valid 0.0."""
    adapter = FIRMSAdapter(west=73.0, south=18.0, east=85.0, north=28.0, year=2025)

    # Empty CSV query with valid header -> valid 0.0 detection
    header_only = "latitude,longitude,brightness,scan,track,acq_date,acq_time,satellite,confidence,version,bright_t31,frp,daynight\n"
    zero_row = adapter._parse_csv(header_only, "2025-07-01")
    assert zero_row["valid"] is True
    assert zero_row["speed_p95"] == 0.0
    assert zero_row["magnitude"] == 0.0

    # API failure / invalid response -> rest (None)
    err_row = adapter._parse_csv("Invalid Key", "2025-07-01")
    assert err_row["valid"] is False
    assert err_row["speed_p95"] is None

    # Test that None rows produce silence in engine_v2
    presets = json.loads(PRESETS_PATH.read_text(encoding="utf-8"))["presets"]
    all_none_rows = [adapter.rest_row(f"2025-01-{i+1:02d}") for i in range(7)]
    blocks = group_days_into_blocks(all_none_rows, block_size=7)
    assert len(blocks) == 1
    assert blocks[0]["speed_p95"] is None

    from aetherwaves.engine_v2.harmony import generate_harmony_v2
    from aetherwaves.engine_v2.melody import generate_melody_v2

    h_bars = generate_harmony_v2(blocks, [None], presets["india"], "india")
    assert len(h_bars) == 1
    assert h_bars[0].is_rest is True
    assert h_bars[0].bass_velocity == 0

    mel_events = generate_melody_v2(blocks, h_bars, [None], presets["india"], seed=42)
    assert len(mel_events) == 0, "Missing data block must produce zero melody events (rest)"


def test_zero_cc11_events_in_v2_midi(tmp_path: Path):
    """Zero CC11 expression events exist in the generated v2 MIDI."""
    presets = json.loads(PRESETS_PATH.read_text(encoding="utf-8"))["presets"]

    src_ku = REPO_ROOT / "data/raw_oscar/regions/kuroshio/oscar_2025_daily.json"
    adapter_ku = OscarAdapter(src_ku)
    rows_ku = adapter_ku.rows()
    blocks_ku = group_days_into_blocks(rows_ku, block_size=7)
    norm_ku, _ = normalize_series_5_95(blocks_ku)

    mid_path = tmp_path / "kuroshio_cc_check.mid"
    build_midi_v2(blocks_ku, norm_ku, presets["kuroshio"], "kuroshio", seed=42, out_mid_path=mid_path)

    mid = mido.MidiFile(str(mid_path))
    for track in mid.tracks:
        for msg in track:
            if msg.type == "control_change" and msg.control == 11:
                pytest.fail("CC11 event found in generated v2 MIDI!")
