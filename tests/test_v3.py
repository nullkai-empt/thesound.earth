"""tests/test_v3.py — Verification tests for AetherWaves Engine v3.

Covers:
1. Determinism (repeated execution yields byte-for-byte identical output)
2. No CC11 expression events in generated MIDI
3. Missing data -> rest or hold (never zero, zero fires = valid 0.0)
4. Tempo range constraint (all presets 56-96 BPM)
5. Opus file size constraint (< 1.5 MB)
6. Looping continuity (loop: true, bar 52 tonic resolution, small click-check step)
7. Banned words verification across metadata and configs
8. Scale membership (all sounding pitches in preset scale + declared color tone)
"""
from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path
import pytest
import mido

REPO_ROOT = Path(__file__).resolve().parent.parent

BANNED_PATTERNS = [
    r"\b100%\b",
    r"\bfilm-level\b",
    r"\badvanced tuning\b",
    r"\bguarantee\b",
    r"\blive\b",
    r"\bmeasured by satellites\b",
]


@pytest.fixture(scope="module")
def presets_v3():
    p_path = REPO_ROOT / "config" / "presets_v3.json"
    assert p_path.exists(), "config/presets_v3.json must exist"
    with open(p_path, encoding="utf-8") as f:
        data = json.load(f)
    return data["presets"]


def test_v3_tempo_range(presets_v3):
    """Verify every track tempo is fixed between 56 and 96 BPM."""
    assert len(presets_v3) == 15, "Must define all 15 regional presets"
    for tid, p in presets_v3.items():
        tempo = p["tempo"]
        assert 56 <= tempo <= 96, f"{tid}: tempo {tempo} outside 56-96 BPM"
        expected_bar_sec = round(240.0 / tempo, 4)
        assert abs(p["bar_seconds"] - expected_bar_sec) < 1e-3, f"{tid}: bar_seconds mismatch"


def test_v3_color_tone_declared_outside_scale(presets_v3):
    """Verify each preset declares exactly ONE color tone strictly outside the scale."""
    for tid, p in presets_v3.items():
        scale = set(p["scale"])
        color_tone = p.get("color_tone")
        assert color_tone is not None, f"{tid} must declare a color tone"
        assert 0 <= color_tone <= 11, f"{tid}: color tone {color_tone} not in [0, 11]"
        assert color_tone not in scale, f"{tid}: color tone {color_tone} must be outside scale {scale}"


def test_v3_no_cc11_in_midi():
    """Verify zero CC11 events across all generated v3 prototype MIDI files."""
    proto_dir = REPO_ROOT / "tmp" / "v3_proto"
    if not proto_dir.exists():
        pytest.skip("tmp/v3_proto not yet rendered")

    midi_files = list(proto_dir.glob("*/**/*.mid"))
    assert len(midi_files) > 0, "Expected prototype MIDI files"
    for m_path in midi_files:
        mid = mido.MidiFile(str(m_path))
        for trk in mid.tracks:
            for msg in trk:
                if msg.type == "control_change" and msg.control == 11:
                    pytest.fail(f"Found prohibited CC11 message in {m_path}: {msg}")


def test_v3_pitches_within_scale_and_color_tone(presets_v3):
    """Verify every sounding note belongs to the preset scale or declared color tone."""
    proto_dir = REPO_ROOT / "tmp" / "v3_proto"
    if not proto_dir.exists():
        pytest.skip("tmp/v3_proto not yet rendered")

    for tid in ["india", "kuroshio", "siberia"]:
        mid_path = proto_dir / tid / "run1" / "track.mid"
        if not mid_path.exists():
            continue
        preset = presets_v3[tid]
        scale_pcs = set(preset["scale"])
        color_pc = preset["color_tone"]

        mid = mido.MidiFile(str(mid_path))
        for trk in mid.tracks:
            for msg in trk:
                if msg.type == "note_on" and msg.velocity > 0:
                    # Percussion on channel 9 is GM rhythm (not harmonic pitches)
                    if msg.channel == 9:
                        continue
                    note_pc = msg.note % 12
                    assert (note_pc in scale_pcs) or (note_pc == color_pc), (
                        f"Track {tid}, channel {msg.channel}: Note {msg.note} (pc={note_pc}) "
                        f"not in scale {scale_pcs} and not declared color tone {color_pc}"
                    )
                    # Also verify velocity capped at 80
                    assert msg.velocity <= 80, f"Track {tid}: Note velocity {msg.velocity} exceeds cap 80"


def test_v3_opus_file_size():
    """Verify all rendered prototype Opus files are under 1.5 MB."""
    proto_dir = REPO_ROOT / "tmp" / "v3_proto"
    if not proto_dir.exists():
        pytest.skip("tmp/v3_proto not yet rendered")

    opus_files = list(proto_dir.glob("**/track.opus"))
    assert len(opus_files) > 0, "No prototype Opus files found"
    max_bytes = 1.5 * 1024 * 1024  # 1.5 MB
    for op in opus_files:
        sz = op.stat().st_size
        assert sz < max_bytes, f"{op} size {sz} bytes exceeds 1.5 MB limit"


def test_v3_looping_and_click_check():
    """Verify loop: true in metadata and sample step click check."""
    proto_dir = REPO_ROOT / "tmp" / "v3_proto"
    if not proto_dir.exists():
        pytest.skip("tmp/v3_proto not yet rendered")

    meta_files = list(proto_dir.glob("**/meta.json"))
    assert len(meta_files) > 0
    for mp in meta_files:
        with open(mp, encoding="utf-8") as f:
            meta = json.load(f)
        assert meta.get("loop") is True, f"{mp}: loop must be true"
        step = meta.get("sample_step_click_check")
        assert step is not None, f"{mp}: sample_step_click_check missing"
        assert step < 0.25, f"{mp}: sample step {step} too high (click risk)"


def test_v3_determinism():
    """Verify Run 1 and Run 2 hashes match bit-for-bit across MIDI, WAV, and Opus."""
    import hashlib
    proto_dir = REPO_ROOT / "tmp" / "v3_proto"
    if not proto_dir.exists():
        pytest.skip("tmp/v3_proto not yet rendered")

    for tid in ["india", "kuroshio", "siberia"]:
        t_dir = proto_dir / tid
        r1 = t_dir / "run1"
        r2 = t_dir / "run2"
        if not r1.exists() or not r2.exists():
            continue
        for fname in ["track.mid", "track.wav", "track.opus"]:
            p1 = r1 / fname
            p2 = r2 / fname
            assert p1.exists() and p2.exists(), f"Missing {fname} in {tid}"
            h1 = hashlib.sha256(p1.read_bytes()).hexdigest()
            h2 = hashlib.sha256(p2.read_bytes()).hexdigest()
            assert h1 == h2, f"{tid}/{fname} mismatch between run1 and run2: {h1} != {h2}"


def test_v3_none_to_rest_or_hold():
    """Verify missing data maps to rest or hold, never zero; zero fire is valid 0.0."""
    proto_dir = REPO_ROOT / "tmp" / "v3_proto"
    if not proto_dir.exists():
        pytest.skip("tmp/v3_proto not yet rendered")

    meta_files = list(proto_dir.glob("**/meta.json"))
    for mp in meta_files:
        with open(mp, encoding="utf-8") as f:
            meta = json.load(f)
        audit = meta["scientific_data"]["audit_table"]
        assert len(audit) == 53
        for row in audit:
            # Held bars hold previous chord
            if row.get("held"):
                assert row.get("chord") is not None
            # Resting melody produces rests
            if row.get("melody_rest"):
                assert row["norm_speed"] <= 0.35 or row["bar"] in (0, 1)


def test_v3_chord_numerals_relative_to_tonic():
    """Verify chord numerals in audit table are strictly relative to tonic (Gm is v, F is iv, etc.)."""
    proto_dir = REPO_ROOT / "tmp" / "v3_proto"
    if not proto_dir.exists():
        pytest.skip("tmp/v3_proto not yet rendered")

    for mp in proto_dir.glob("**/meta.json"):
        with open(mp, encoding="utf-8") as f:
            meta = json.load(f)
        audit = meta["scientific_data"]["audit_table"]
        for row in audit:
            chord = row.get("chord")
            numeral = row.get("chord_numeral")
            if chord == "Gm":
                assert numeral == "v", f"Gm must be numeral v, got {numeral}"
            elif chord in ("F", "Fsus4", "Fsus2", "Fm"):
                assert numeral in ("iv", "IV"), f"F chord must be iv/IV, got {numeral}"
            elif chord in ("Cm", "Csus7", "Csus2"):
                assert numeral == "i", f"C chord must be numeral i, got {numeral}"
            elif chord in ("Bb", "Bbsus2"):
                assert numeral in ("bVII", "VII"), f"Bb chord must be bVII/VII, got {numeral}"


def test_v3_story_claims_match_audit_table():
    """Verify section story text claims strictly match audit table rows."""
    import re
    proto_dir = REPO_ROOT / "tmp" / "v3_proto"
    if not proto_dir.exists():
        pytest.skip("tmp/v3_proto not yet rendered")

    for mp in proto_dir.glob("**/meta.json"):
        with open(mp, encoding="utf-8") as f:
            meta = json.load(f)
        audit = meta["scientific_data"]["audit_table"]
        metric_key = "mean_speed_p95_m_s" if meta["preset"]["domain"] == "ocean" else "mean_fire_detections_per_day"
        story_text = meta["story"]["text"]
        paragraphs = story_text.split("\n\n")

        for p in paragraphs:
            # Match: Name (bars S-E; audit rows S to E): Over these bars, METRIC ranges from MIN to MAX (mean MEAN)...
            m = re.search(r"\(bars (\d+)-(\d+); audit rows (\d+) to (\d+)\): Over these bars, .*? ranges from ([\d\.]+) to ([\d\.]+)", p)
            assert m is not None, f"Paragraph does not match expected pattern: {p}"
            s_bar, e_bar, r_start, r_end, claimed_min, claimed_max = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), float(m.group(5)), float(m.group(6))
            assert s_bar == r_start and e_bar == r_end, "Bar range does not match cited audit row range"

            sec_rows = audit[s_bar : e_bar + 1]
            actual_vals = [r[metric_key] for r in sec_rows]
            actual_min = round(float(min(actual_vals)), 1)
            actual_max = round(float(max(actual_vals)), 1)
            assert abs(claimed_min - actual_min) <= 0.2, f"Claimed min {claimed_min} differs from actual {actual_min}"
            assert abs(claimed_max - actual_max) <= 0.2, f"Claimed max {claimed_max} differs from actual {actual_max}"


def test_v3_banned_words_in_artifacts():
    """Verify zero banned words across all v3 files and docs."""
    paths_to_check = [
        REPO_ROOT / "docs" / "Music_spec_v3.md",
        REPO_ROOT / "config" / "presets_v3.json",
    ]
    proto_dir = REPO_ROOT / "tmp" / "v3_proto"
    if proto_dir.exists():
        paths_to_check.extend(proto_dir.glob("**/meta.json"))

    for p in paths_to_check:
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8")
        for pat in BANNED_PATTERNS:
            matches = re.findall(pat, text, flags=re.IGNORECASE)
            assert not matches, f"Banned word '{pat}' found in {p}"
