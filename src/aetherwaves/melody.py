from __future__ import annotations

import argparse
import json
import math
import random
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import mido
import numpy as np
import soundfile as sf

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
from aetherwaves.rhythm import normalize_series_5_95

# --- Named Constants ---
# Instrument programs (GM 0-indexed)
PROGRAM_FRENCH_HORN: int = 60         # GM 60 French Horn (default)
PROGRAM_CELLO: int = 42               # GM 42 Cello (melody line)
PROGRAM_STRINGS: int = 49             # GM 49 String Ensemble 2 (slow attack)

# Default instrument program: GM 49 String Ensemble 2 (slow attack)
MELODY_PROGRAM: int = PROGRAM_STRINGS

# Register (MIDI 52-67 only, E3 to G4, nothing above G4)
MIN_MIDI: int = 52
MAX_MIDI: int = 67

# Voice leading constraints
MAX_JUMP_SEMITONES: int = 4

# Controllers for timbre and mix positioning
CC74_BRIGHTNESS: int = 45             # Tames high harmonics/sharpness
CC91_REVERB: int = 110                # Deep reverb send
CC10_PAN: int = 64                    # Dead center (away from hard pan)
MELODY_GAIN_DB: float = -5.0          # Melody about 5 dB below pad
# MMA volume curve: CC7 = round(127 * 10^(dB/40)) -> 95
CC7_VOLUME: int = int(round(127.0 * (10.0 ** (MELODY_GAIN_DB / 40.0))))

# Human feel parameters (seed 42)
HUMAN_TIMING_MIN_MS: float = -12.0
HUMAN_TIMING_MAX_MS: float = 12.0
VELOCITY_BASE: float = 40.0
VELOCITY_SCALE: float = 30.0
VELOCITY_JITTER_MAX: float = 5.0
MAX_VELOCITY_CAP: int = 70
LEGATO_OVERLAP_MS: float = 40.0

# Scale Pitch Classes (modulo 12: D=2, E=4, F=5, G=7, A=9, Bb=10, B=11, C=0)
D_NATURAL_MINOR: set[int] = {2, 4, 5, 7, 9, 10, 0}
D_DORIAN: set[int] = {2, 4, 5, 7, 9, 11, 0}

# Chord Pitch Classes (base chords)
CHORD_PCS: dict[str, set[int]] = {
    "Dm": {2, 5, 9},       # D, F, A
    "Bb": {10, 2, 5},      # Bb, D, F
    "Gm": {7, 10, 2},      # G, Bb, D
    "C":  {0, 4, 7},       # C, E, G
    "F":  {5, 9, 0},       # F, A, C
    "G":  {7, 11, 2},      # G, B, D
}

PITCH_NAME_TO_PC: dict[str, int] = {
    "C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4,
    "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8, "Ab": 8, "A": 9,
    "A#": 10, "Bb": 10, "B": 11,
}


def chord_pitch_classes(chord: str) -> set[int]:
    """Return pitch classes for any major or minor chord."""
    if chord in CHORD_PCS:
        return CHORD_PCS[chord]
    is_minor = chord.endswith("m")
    root_str = chord[:-1] if is_minor else chord
    root_pc = PITCH_NAME_TO_PC.get(root_str, 2)
    third_pc = (root_pc + 3) % 12 if is_minor else (root_pc + 4) % 12
    fifth_pc = (root_pc + 7) % 12
    return {root_pc, third_pc, fifth_pc}


@dataclass(frozen=True)
class MelodyEvent:
    """A melody note event in a measure."""
    bar: int
    beat: float                    # Nominal grid onset: strictly 1.0 or 3.0
    midi_note: int                 # Pitch in [52, 67]
    velocity: int                  # Dynamics capped at 70
    duration_beats: float          # Nominal duration (whole note=4.0, half note=2.0)
    timing_offset_ms: float = 0.0  # Human feel offset in [-12.0, 12.0] ms


def get_chord_tones(chord: str, min_midi: int = MIN_MIDI, max_midi: int = MAX_MIDI) -> list[int]:
    """Get all chord tones of the chord ordered low to high within [min_midi, max_midi]."""
    pcs = chord_pitch_classes(chord)
    tones = sorted([n for n in range(min_midi, max_midi + 1) if (n % 12) in pcs])
    if not tones:
        return [62]  # Fallback D4
    return tones


def pick_voice_led_chord_tone(
    chord: str,
    prev_note: int | None,
    norm_speed: float,
    min_midi: int = MIN_MIDI,
    max_midi: int = MAX_MIDI,
    is_outro: bool = False,
    key_offset: int = 0,
) -> int:
    """
    Choose the chord tone closest to the previous melody note (smallest jump).
    Max jump = a major third (4 semitones). If no chord tone fits, hold the previous note.
    Higher norm speed pulls the choice toward upper chord tones, but never jumps > 4 semitones.
    In Outro, candidate choices are steered towards the tonic root for the final resolution.
    """
    tones = get_chord_tones(chord, min_midi=min_midi, max_midi=max_midi)
    s = float(np.clip(norm_speed, 0.0, 1.0))

    # Tonic target in melody range [min_midi, max_midi]
    tonic_target = 62 + key_offset
    while tonic_target > max_midi:
        tonic_target -= 12
    while tonic_target < min_midi:
        tonic_target += 12

    if prev_note is None:
        # First sounding note in piece: pick based on speed, centered around tonic target
        idx = int(round(s * (len(tones) - 1)))
        return tones[idx]

    # Candidates within 4 semitones of previous note
    cands = [t for t in tones if abs(t - prev_note) <= MAX_JUMP_SEMITONES]
    if not cands:
        # If no chord tone fits within 4 semitones, hold previous note
        return prev_note

    if is_outro:
        # Steer toward tonic root in outro while strictly keeping jump <= 4
        cands_outro = [t for t in cands if abs(t - tonic_target) <= MAX_JUMP_SEMITONES]
        if cands_outro:
            cands = cands_outro

    # Higher norm speed pulls toward upper chord tones
    idx = int(round(s * (len(cands) - 1)))
    return cands[idx]


def generate_melody(
    bars: Sequence[dict[str, Any]],
    harmony_bars: Sequence[BarHarmony],
    norm_speeds: Sequence[float | None],
    seed: int = 42,
    key_offset: int = 0,
) -> list[MelodyEvent]:
    """
    Build System 3 Melody (v3).

    Rules:
    1. Register: MIDI 52-67 only. Nothing above G4.
    2. Voice leading:
       - On beat 1, choose chord tone closest to previous note (smallest jump, max 4 semitones).
       - Higher norm speed pulls toward upper chord tones within <= 4 semitones jump.
       - Whole note sustains through bar, tied across barline if next bar has same pitch.
       - Peak: second note on beat 3, chord tone, half note (2 beats).
       - Calm: D Dorian, softer velocity.
       - Intro: none. Outro: fades out with fewer notes, last bar = long D (62).
       - Missing data or held bar = rest.
    3. Grid lock: Onsets strictly on beats 1 and 3.
    4. Human feel:
       - Timing offset: random -12 to +12 ms per note.
       - Velocity: 40 + 30 * norm_speed, +/- 5 random, hard cap 70.
       - Overlap legato: each note ends 40 ms after next starts.
    """
    total_bars = len(bars)
    if total_bars == 0:
        return []

    section_counts = compute_section_counts(total_bars)
    rng = random.Random(seed)
    events: list[MelodyEvent] = []
    prev_bar_start_note: int | None = None

    # Determine outro start bar
    outro_start = sum(count for name, count in section_counts if name != "outro")

    for bar_idx in range(total_bars):
        h = harmony_bars[bar_idx] if bar_idx < len(harmony_bars) else None
        bar_data = bars[bar_idx]
        sec = get_section_for_bar(bar_idx, section_counts)
        norm_spd = norm_speeds[bar_idx] if bar_idx < len(norm_speeds) else None

        # 1. Intro section: no melody
        if sec == "intro":
            continue

        # 2. Missing data or held bar = rest
        is_held = h.held if h else False
        is_missing = (
            norm_spd is None
            or not np.isfinite(norm_spd)
            or (h and h.is_rest)
            or bar_data.get("speed_p95") is None
        )
        if is_missing or is_held:
            continue

        s = float(np.clip(norm_spd, 0.0, 1.0))
        is_last_bar = (bar_idx == total_bars - 1)

        # 3. Phrasing by section:
        # Outro fades out by sounding on alternate bars, ending on last bar
        if sec == "outro" and not is_last_bar:
            if (bar_idx - outro_start) % 2 != 0:
                continue

        chord = h.chord if h else "Dm"

        # 4. Note selection on Beat 1 (voice leading from previous bar-start note)
        if is_last_bar:
            # Outro last bar is always long tonic root folded into [MIN_MIDI, MAX_MIDI]
            tonic_root = 62 + key_offset
            while tonic_root > MAX_MIDI:
                tonic_root -= 12
            while tonic_root < MIN_MIDI:
                tonic_root += 12
            note1 = tonic_root
        else:
            note1 = pick_voice_led_chord_tone(
                chord,
                prev_note=prev_bar_start_note,
                norm_speed=s,
                min_midi=MIN_MIDI,
                max_midi=MAX_MIDI,
                is_outro=(sec == "outro"),
                key_offset=key_offset,
            )
        prev_bar_start_note = note1

        # 5. Human feel: velocity & timing offset
        timing_offset_1 = rng.uniform(HUMAN_TIMING_MIN_MS, HUMAN_TIMING_MAX_MS)
        base_vel_1 = VELOCITY_BASE + VELOCITY_SCALE * s + rng.uniform(-VELOCITY_JITTER_MAX, VELOCITY_JITTER_MAX)
        if sec == "calm":
            base_vel_1 *= 0.85  # Softer in Calm
        vel_1 = max(1, min(MAX_VELOCITY_CAP, int(round(base_vel_1))))

        if sec == "peak":
            # Beat 1 half note
            events.append(
                MelodyEvent(
                    bar=bar_idx,
                    beat=1.0,
                    midi_note=note1,
                    velocity=vel_1,
                    duration_beats=2.0,
                    timing_offset_ms=timing_offset_1,
                )
            )

            # Beat 3 second note: chord tone in [52, 67]
            tones = get_chord_tones(chord, min_midi=MIN_MIDI, max_midi=MAX_MIDI)
            cands3 = [t for t in tones if abs(t - note1) <= MAX_JUMP_SEMITONES and t != note1]
            if cands3:
                idx3 = int(round(s * (len(cands3) - 1)))
                note3 = cands3[idx3]
            else:
                note3 = note1

            timing_offset_3 = rng.uniform(HUMAN_TIMING_MIN_MS, HUMAN_TIMING_MAX_MS)
            base_vel_3 = VELOCITY_BASE + VELOCITY_SCALE * s + rng.uniform(-VELOCITY_JITTER_MAX, VELOCITY_JITTER_MAX)
            vel_3 = max(1, min(MAX_VELOCITY_CAP, int(round(base_vel_3))))

            events.append(
                MelodyEvent(
                    bar=bar_idx,
                    beat=3.0,
                    midi_note=note3,
                    velocity=vel_3,
                    duration_beats=2.0,
                    timing_offset_ms=timing_offset_3,
                )
            )

        else:
            # Whole note sustains through the bar
            events.append(
                MelodyEvent(
                    bar=bar_idx,
                    beat=1.0,
                    midi_note=note1,
                    velocity=vel_1,
                    duration_beats=4.0,
                    timing_offset_ms=timing_offset_1,
                )
            )

    return events


def build_melody_actions(
    melody_events: Sequence[MelodyEvent],
    bpm: float = 72.0,
    ticks_per_beat: int = 480,
    program: int = MELODY_PROGRAM,
) -> list[tuple[int, float, str, int, int]]:
    """
    Build MIDI action tuples: (abs_tick, priority, msg_type, note_or_prog_or_ctrl, val).
    Implements:
    - Controllers: CC74 (brightness)=45, CC91 (reverb)=110, CC7 (volume)=95, CC10 (pan)=64
    - Timing offsets: random -12 to +12 ms
    - Legato overlap: each note ends 40 ms after the next starts
    - Tied notes across barline: contiguous notes of same pitch do not re-attack
    """
    actions: list[tuple[int, float, str, int, int]] = []
    if not melody_events:
        return actions

    # Initial controllers on channel 2
    actions.append((0, -1.0, "program_change", program, 0))
    actions.append((0, -0.5, "control_change", 74, CC74_BRIGHTNESS))
    actions.append((0, -0.5, "control_change", 91, CC91_REVERB))
    actions.append((0, -0.5, "control_change", 7, CC7_VOLUME))
    actions.append((0, -0.5, "control_change", 10, CC10_PAN))

    bar_ticks = 4 * ticks_per_beat
    overlap_ticks = int(round(LEGATO_OVERLAP_MS * 0.001 * (bpm / 60.0) * ticks_per_beat))

    sorted_events = sorted(melody_events, key=lambda e: (e.bar, e.beat))

    # Calculate tick positions for each event
    event_ticks: list[dict[str, Any]] = []
    for ev in sorted_events:
        nominal_tick = int(round(ev.bar * bar_ticks + (ev.beat - 1.0) * ticks_per_beat))
        offset_tick = int(round(ev.timing_offset_ms * 0.001 * (bpm / 60.0) * ticks_per_beat))
        start_tick = max(0, nominal_tick + offset_tick)
        nominal_dur = max(1, int(round(ev.duration_beats * ticks_per_beat)))
        event_ticks.append({
            "ev": ev,
            "start_tick": start_tick,
            "nominal_end_tick": start_tick + nominal_dur,
            "pitch": ev.midi_note,
            "velocity": ev.velocity,
        })

    # Group contiguous tied notes with identical pitch
    groups: list[list[dict[str, Any]]] = []
    current_group: list[dict[str, Any]] = []

    for item in event_ticks:
        if not current_group:
            current_group.append(item)
        else:
            prev_item = current_group[-1]
            gap = item["start_tick"] - prev_item["nominal_end_tick"]
            # Tied across barline if same pitch and contiguous (gap <= half beat)
            if item["pitch"] == prev_item["pitch"] and abs(gap) <= (ticks_per_beat // 2):
                current_group.append(item)
            else:
                groups.append(current_group)
                current_group = [item]
    if current_group:
        groups.append(current_group)

    # Convert groups to note_on and note_off with overlap legato
    for g_idx, grp in enumerate(groups):
        pitch = grp[0]["pitch"]
        vel = grp[0]["velocity"]
        start_tick = grp[0]["start_tick"]
        nominal_end_tick = grp[-1]["nominal_end_tick"]

        # Check next group for overlap legato
        if g_idx + 1 < len(groups):
            next_start = groups[g_idx + 1][0]["start_tick"]
            gap_to_next = next_start - nominal_end_tick
            if gap_to_next <= (ticks_per_beat // 2):
                # Contiguous note of different pitch: overlap legato 40 ms after next starts
                end_tick = max(start_tick + 1, next_start + overlap_ticks)
            else:
                # Rest between phrases: end at nominal end
                end_tick = nominal_end_tick
        else:
            end_tick = nominal_end_tick

        actions.append((start_tick, 1.0, "note_on", pitch, vel))
        actions.append((end_tick, 0.0, "note_off", pitch, 0))

    return actions


def build_melody_midi(
    melody_events: Sequence[MelodyEvent],
    out_path: Path | str,
    bpm: float = 72.0,
    ticks_per_beat: int = 480,
    program: int = MELODY_PROGRAM,
) -> Path:
    """Build standalone MIDI file for melody with timbre controllers and legato ties."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    mid = mido.MidiFile(type=1, ticks_per_beat=ticks_per_beat)
    track = mido.MidiTrack()
    mid.tracks.append(track)

    tempo_us = int(round(60_000_000.0 / bpm))
    track.append(mido.MetaMessage("set_tempo", tempo=tempo_us, time=0))
    track.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))
    track.append(mido.MetaMessage("track_name", name="Melody", time=0))

    actions = build_melody_actions(melody_events, bpm=bpm, ticks_per_beat=ticks_per_beat, program=program)
    actions.sort(key=lambda a: (a[0], a[1]))

    current_tick = 0
    for abs_tick, _, msg_type, note_or_prog, val in actions:
        delta = max(0, abs_tick - current_tick)
        if msg_type == "program_change":
            track.append(mido.Message("program_change", channel=2, program=note_or_prog, time=delta))
        elif msg_type == "control_change":
            track.append(mido.Message("control_change", channel=2, control=note_or_prog, value=val, time=delta))
        elif msg_type in ("note_on", "note_off"):
            track.append(mido.Message(msg_type, channel=2, note=note_or_prog, velocity=val, time=delta))
        current_tick = abs_tick

    track.append(mido.MetaMessage("end_of_track", time=ticks_per_beat))
    mid.save(str(out_path))
    return out_path


def render_melody_wav(
    midi_path: Path | str,
    wav_path: Path | str,
    gain: float = 1.0,
    target_dbfs: float = -1.0,
) -> Path:
    """Render melody MIDI file using FluidSynth with FluidR3_GM soundfont, normalized to target dBFS."""
    from scripts.demo_mix import find_fluidsynth, find_soundfont, normalize_wav_to_dbfs

    midi_path = Path(midi_path)
    wav_path = Path(wav_path)
    wav_path.parent.mkdir(parents=True, exist_ok=True)

    fluidsynth = find_fluidsynth()
    soundfont = find_soundfont()

    cmd = [
        str(fluidsynth),
        "-ni",
        "-R", "1",
        "-C", "0",
        "-o", "synth.reverb.room-size=0.5",
        "-o", "synth.reverb.level=0.5",
        "-g", str(gain),
        "-r", "44100",
        "-F", str(wav_path.resolve()),
        str(soundfont.resolve()),
        str(midi_path.resolve()),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"FluidSynth failed: {res.stderr}")

    normalize_wav_to_dbfs(wav_path, target_dbfs=target_dbfs)
    return wav_path


def main() -> None:
    parser = argparse.ArgumentParser(description="System 3 Melody Generator v3")
    parser.add_argument("--json", type=str, default="data/raw_oscar/oscar_2025_daily.json", help="Path to OSCAR daily JSON")
    parser.add_argument("--block-size", type=int, default=7, help="Block size in days")
    parser.add_argument("--seed", type=int, default=42, help="Seed")
    parser.add_argument("--out-dir", type=str, default="output", help="Output directory")
    args = parser.parse_args()

    json_path = REPO_ROOT / args.json
    daily_records = json.loads(json_path.read_text(encoding="utf-8"))
    blocks = group_days_into_blocks(daily_records, block_size=args.block_size)
    norm_speeds, _ = normalize_series_5_95(blocks)
    harmony_bars = generate_harmony(blocks, norm_speeds, hold_threshold=0.013)

    events = generate_melody(blocks, harmony_bars, norm_speeds, seed=args.seed)
    print(f"Generated {len(events)} melody events across {len(blocks)} bars.")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Build and render French Horn (default)
    horn_mid = build_melody_midi(events, out_dir / "mix_melody_horn.mid", program=PROGRAM_FRENCH_HORN)
    render_melody_wav(horn_mid, out_dir / "mix_melody_horn.wav")
    print(f"French Horn melody rendered: {out_dir / 'mix_melody_horn.wav'}")

    # Cello
    cello_mid = build_melody_midi(events, out_dir / "mix_melody_cello.mid", program=PROGRAM_CELLO)
    render_melody_wav(cello_mid, out_dir / "mix_melody_cello.wav")
    print(f"Cello melody rendered: {out_dir / 'mix_melody_cello.wav'}")

    # Strings
    strings_mid = build_melody_midi(events, out_dir / "mix_melody_strings.mid", program=PROGRAM_STRINGS)
    render_melody_wav(strings_mid, out_dir / "mix_melody_strings.wav")
    print(f"String Ensemble 2 melody rendered: {out_dir / 'mix_melody_strings.wav'}")


if __name__ == "__main__":
    main()
