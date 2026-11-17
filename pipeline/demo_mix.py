from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

# Ensure repo root and src/ are on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

import numpy as np
import soundfile as sf
import mido

# Requirement: Check if blocks.py exists. If not, stop and inform.
BLOCKS_PY = REPO_ROOT / "src" / "aetherwaves" / "blocks.py"
if not BLOCKS_PY.exists():
    print(f"Error: Required file {BLOCKS_PY} does not exist.")
    sys.exit(1)

from aetherwaves.blocks import group_days_into_blocks
from aetherwaves.dynamics import (
    apply_velocity_scale,
    compute_smooth_speeds,
    compute_velocity_scales,
    find_top5_runs,
    generate_crash_events,
    generate_riser_actions,
    scale_drum_events,
)
from aetherwaves.harmony import (
    BarHarmony,
    compute_data_bounds,
    compute_key_offset,
    compute_section_counts,
    generate_harmony,
    get_tonic_name,
    seed_from_period,
)
from aetherwaves.melody import (
    MELODY_PROGRAM,
    PROGRAM_CELLO,
    PROGRAM_FRENCH_HORN,
    PROGRAM_STRINGS,
    MelodyEvent,
    build_melody_actions,
    build_melody_midi,
    generate_melody,
    render_melody_wav,
)
from aetherwaves.rhythm import DrumEvent, generate_drum_events, normalize_series_5_95

# --- Named Constants ---
PAD_PROGRAM: int = 94                 # GM 94: Halo Pad (was Warm Pad 89)
PAD_OCTAVE_SHIFT: int = 1             # Voicings one octave higher (+1), sits in MIDI 60-79
PAD_MIN_MIDI: int = 48 + 12 * PAD_OCTAVE_SHIFT   # 60
PAD_MAX_MIDI: int = 67 + 12 * PAD_OCTAVE_SHIFT   # 79
PAD_VELOCITY_SCALE: float = 0.8 * 0.85           # Pad velocity multiplied by 0.85

CELLO_BASS_VELOCITY_SCALE: float = 0.8 * 0.75    # Cello bass velocity lowered by a further 25%
KICK_VELOCITY_SCALE: float = 0.85                # Kick velocity lowered by 15%
SHAKER_VELOCITY_SCALE: float = 0.75              # Lower shaker velocity by 25%
MELODY_PROGRAM_DEFAULT: int = PROGRAM_STRINGS    # String Ensemble 2 (GM 49)

# Pitch classes for chords with scale 9th (mod 12)
# Dm add9 = E (4), Bb add9 = C (0), Gm add9 = A (9), C add9 = D (2), F add9 = G (7), G add9 = A (9)
ADD9_INFO: dict[str, dict[str, int]] = {
    "Dm": {"root": 2, "fifth": 9, "third": 5, "ninth": 4},   # D, A, F, E
    "Bb": {"root": 10, "fifth": 5, "third": 2, "ninth": 0},  # Bb, F, D, C
    "Gm": {"root": 7, "fifth": 2, "third": 10, "ninth": 9},  # G, D, Bb, A
    "C":  {"root": 0, "fifth": 7, "third": 4, "ninth": 2},   # C, G, E, D
    "F":  {"root": 5, "fifth": 0, "third": 9, "ninth": 7},   # F, C, A, G
    "G":  {"root": 7, "fifth": 2, "third": 11, "ninth": 9},  # G, D, B, A (Dorian)
}

PITCH_CLASS_MAP: dict[str, int] = {
    "C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4,
    "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8, "Ab": 8, "A": 9,
    "A#": 10, "Bb": 10, "B": 11,
}


def get_chord_add9_pcs(chord: str) -> dict[str, int]:
    """Get pitch classes for root, fifth, third, and scale ninth."""
    if chord in ADD9_INFO:
        return ADD9_INFO[chord]
    is_minor = chord.endswith("m")
    root_name = chord[:-1] if is_minor else chord
    root = PITCH_CLASS_MAP.get(root_name, 2)
    third = (root + 3) % 12 if is_minor else (root + 4) % 12
    fifth = (root + 7) % 12
    ninth = (root + 2) % 12
    return {"root": root, "fifth": fifth, "third": third, "ninth": ninth}


def get_pad_candidates(chord: str, octave_shift: int = PAD_OCTAVE_SHIFT) -> list[tuple[int, int, int, int]]:
    """
    Get all valid 4-note voicings (inversions/octave layouts) of the add9 chord
    where every note is strictly between MIDI 60 and 79 inclusive (when octave_shift=+1).
    """
    pcs = get_chord_add9_pcs(chord)
    min_midi = 48 + 12 * octave_shift
    max_midi = 67 + 12 * octave_shift
    notes_per_role: dict[str, list[int]] = {}
    for role in ["root", "fifth", "third", "ninth"]:
        pc = pcs[role]
        notes_per_role[role] = [n for n in range(min_midi, max_midi + 1) if n % 12 == pc]

    candidates: list[tuple[int, int, int, int]] = []
    for r in notes_per_role["root"]:
        for f in notes_per_role["fifth"]:
            for t in notes_per_role["third"]:
                for n in notes_per_role["ninth"]:
                    voicing = tuple(sorted([r, f, t, n]))
                    if len(set(voicing)) == 4:
                        candidates.append(voicing)  # type: ignore[arg-type]

    return sorted(list(set(candidates)))


def find_fluidsynth() -> Path:
    """Find fluidsynth executable in tools/ or system PATH."""
    candidates = [
        REPO_ROOT / "tools/fluidsynth/fluidsynth-v2.6.2-win10-x64-cpp11/bin/fluidsynth.exe",
        REPO_ROOT / "tools/fluidsynth/bin/fluidsynth.exe",
    ]
    for c in candidates:
        if c.exists():
            return c.resolve()
    import shutil
    which = shutil.which("fluidsynth")
    if which:
        return Path(which)
    raise FileNotFoundError("FluidSynth executable not found.")


def find_soundfont() -> Path:
    """Find FluidR3_GM SoundFont."""
    candidates = [
        REPO_ROOT / "soundfonts/FluidR3_GM.sf2",
        REPO_ROOT / "soundfonts/GeneralUser_GS.sf2",
        Path("C:/Windows/System32/drivers/gm.dls"),
    ]
    for c in candidates:
        if c.exists():
            return c.resolve()
    raise FileNotFoundError("SoundFont file not found in soundfonts/ or Windows drivers.")


def render_with_fluidsynth(
    midi_path: Path,
    soundfont_path: Path,
    out_wav_path: Path,
    sample_rate: int = 44100,
    gain: float = 1.0,
) -> Path:
    """
    Render MIDI file to WAV using FluidSynth with built-in reverb (-R 1)
    configured for small room and low level, chorus off (-C 0), and no other effects.
    """
    fluidsynth = find_fluidsynth()
    out_wav_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(fluidsynth),
        "-ni",
        "-R", "1",
        "-C", "0",
        "-o", "synth.reverb.room-size=0.5",
        "-o", "synth.reverb.level=0.5",
        "-g", str(gain),
        "-r", str(sample_rate),
        "-F", str(out_wav_path.resolve()),
        str(soundfont_path.resolve()),
        str(midi_path.resolve()),
    ]

    print(f"[FluidSynth] Rendering {midi_path.name} -> {out_wav_path.name} (gain={gain}, reverb=on)...")
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print("[FluidSynth Error]", res.stderr, file=sys.stderr)
        raise RuntimeError(f"FluidSynth failed with returncode {res.returncode}: {res.stderr}")

    if not out_wav_path.exists() or out_wav_path.stat().st_size == 0:
        raise RuntimeError(f"FluidSynth did not create valid WAV: {out_wav_path}")

    return out_wav_path


def normalize_wav_to_dbfs(wav_path: Path, target_dbfs: float = -1.0) -> tuple[float, float]:
    """Peak-normalize WAV file to target dBFS (-1.0 dBFS)."""
    data, sr = sf.read(str(wav_path))
    initial_peak = float(np.max(np.abs(data)))
    if initial_peak > 1e-6:
        target_peak = 10.0 ** (target_dbfs / 20.0)  # ~0.89125
        scale = target_peak / initial_peak
        normalized = np.clip(data * scale, -1.0, 1.0)
        sf.write(str(wav_path), normalized, sr, subtype="PCM_16")
        final_peak = float(np.max(np.abs(normalized)))
        return initial_peak, final_peak
    return initial_peak, initial_peak


def build_track_from_actions(
    track_name: str,
    channel: int,
    program: int | None,
    actions: list[tuple[int, float, str, int, int]],
    bpm: float = 72.0,
    ticks_per_beat: int = 480,
    include_tempo: bool = True,
) -> mido.MidiTrack:
    """
    Build a mido.MidiTrack from action tuples: (abs_tick, priority, msg_type, note_or_prog_or_ctrl, vel_or_val).
    Priorities:
      -2.0: meta (tempo, time_signature)
      -1.0: program_change
      -0.5: control_change (CC11 expression)
       0.0: note_off
       1.0: note_on
    """
    track = mido.MidiTrack()
    tempo_us = int(round(60_000_000.0 / bpm))

    if include_tempo:
        track.append(mido.MetaMessage("set_tempo", tempo=tempo_us, time=0))
        track.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))

    track.append(mido.MetaMessage("track_name", name=track_name, time=0))

    if program is not None:
        actions.append((0, -1.0, "program_change", program, 0))

    # Sort actions by absolute tick, then priority
    actions.sort(key=lambda a: (a[0], a[1]))

    current_tick = 0
    for abs_tick, _, msg_type, note_or_prog, vel in actions:
        delta = max(0, abs_tick - current_tick)
        if msg_type == "program_change":
            track.append(mido.Message("program_change", channel=channel, program=note_or_prog, time=delta))
        elif msg_type == "control_change":
            track.append(mido.Message("control_change", channel=channel, control=note_or_prog, value=vel, time=delta))
        elif msg_type in ("note_on", "note_off"):
            track.append(mido.Message(msg_type, channel=channel, note=note_or_prog, velocity=vel, time=delta))
        current_tick = abs_tick

    track.append(mido.MetaMessage("end_of_track", time=ticks_per_beat))
    return track


def get_pad_actions(
    harmony_bars: Sequence[BarHarmony],
    norm_speeds: Sequence[float | None],
    ticks_per_beat: int = 480,
    scales: Sequence[float] | None = None,
) -> list[tuple[int, float, str, int, int]]:
    """
    Generate Halo Pad actions:
    - Root and 5th low, 3rd and 9th above.
    - Scale 9th note (Dm=E, Bb=C, Gm=A, C=D, F=G, G=A).
    - Every pad note between MIDI 60 and 79 inclusive (PAD_OCTAVE_SHIFT=+1).
    - Smooth voice leading: choose inversion with least movement from previous bar.
    - Hold each chord for whole bar and overlap ~0.3 beat into next bar.
    - Velocity soft (scaled by 0.8 * 0.85 * dynamics_scale): inside 1-110 following normalized speed.
    """
    if scales is None:
        smooth_s = compute_smooth_speeds(norm_speeds)
        scales = compute_velocity_scales(smooth_s)

    actions: list[tuple[int, float, str, int, int]] = []
    bar_ticks = 4 * ticks_per_beat
    overlap_ticks = int(round(0.3 * ticks_per_beat))

    # Base initial voicing for Dm shifted by +1 octave (D4=62, A4=69, E5=76, F5=77)
    # Root (62) and 5th (69) low, 9th (76) and 3rd (77) above
    prev_voicing = (
        50 + 12 * PAD_OCTAVE_SHIFT,
        57 + 12 * PAD_OCTAVE_SHIFT,
        64 + 12 * PAD_OCTAVE_SHIFT,
        65 + 12 * PAD_OCTAVE_SHIFT,
    )

    for bar_idx, h in enumerate(harmony_bars):
        norm_spd = norm_speeds[bar_idx] if bar_idx < len(norm_speeds) else None
        if h.is_rest or norm_spd is None:
            # Full-bar rest for missing data
            continue

        cands = get_pad_candidates(h.chord, octave_shift=PAD_OCTAVE_SHIFT)
        # Choose inversion with least total movement from previous bar
        best_cand = min(
            cands,
            key=lambda c: (
                sum(abs(c[i] - prev_voicing[i]) for i in range(4)),
                sum((c[i] - prev_voicing[i]) ** 2 for i in range(4)),
            ),
        )
        prev_voicing = best_cand

        speed_val = float(np.clip(norm_spd, 0.0, 1.0))
        base_vel = int(round((40.0 + 30.0 * speed_val) * PAD_VELOCITY_SCALE))
        bar_scale = scales[bar_idx] if bar_idx < len(scales) else 1.0
        velocity = apply_velocity_scale(base_vel, bar_scale)

        start_tick = bar_idx * bar_ticks
        dur_tick = bar_ticks + overlap_ticks  # Whole bar + 0.3 beat overlap
        end_tick = start_tick + dur_tick

        for note in best_cand:
            actions.append((start_tick, 1.0, "note_on", note, velocity))
            actions.append((end_tick, 0.0, "note_off", note, 0))

    return actions


def get_cello_actions(
    harmony_bars: Sequence[BarHarmony],
    ticks_per_beat: int = 480,
    scales: Sequence[float] | None = None,
) -> list[tuple[int, float, str, int, int]]:
    """
    Generate cello bass actions from harmony.py bass events.
    Keep notes in spec range (MIDI 36-50). Lower cello bass velocity by a further 25% (0.8 * 0.75 = 0.60).
    Multiplied by dynamics velocity scale and clamped to 1-110.
    """
    actions: list[tuple[int, float, str, int, int]] = []
    bar_ticks = 4 * ticks_per_beat

    for h in harmony_bars:
        if h.is_rest:
            continue
        bar_scale = scales[h.bar] if scales and h.bar < len(scales) else 1.0
        for ev in h.bass_events:
            start_tick = int(round(ev.bar * bar_ticks + (ev.beat - 1.0) * ticks_per_beat))
            dur_tick = max(1, int(round(ev.duration_beats * ticks_per_beat)))
            end_tick = start_tick + dur_tick

            base_vel = int(round(ev.velocity * CELLO_BASS_VELOCITY_SCALE))
            cello_vel = apply_velocity_scale(base_vel, bar_scale)

            actions.append((start_tick, 1.0, "note_on", ev.midi_note, cello_vel))
            actions.append((end_tick, 0.0, "note_off", ev.midi_note, 0))

    return actions


def get_drum_actions(
    drum_events: Sequence[DrumEvent],
    ticks_per_beat: int = 480,
) -> list[tuple[int, float, str, int, int]]:
    """
    Generate drum actions from rhythm.py drum events.
    Lower shaker velocity by 25% (multiplier 0.75).
    Lower kick velocity by 15% (multiplier 0.85).
    """
    actions: list[tuple[int, float, str, int, int]] = []
    bar_ticks = 4 * ticks_per_beat

    for ev in drum_events:
        start_tick = int(round(ev.bar * bar_ticks + (ev.beat - 1.0) * ticks_per_beat))
        dur_tick = max(1, int(round(ev.duration_beats * ticks_per_beat)))
        end_tick = start_tick + dur_tick

        # Adjust velocity per instrument
        if ev.instrument == "shaker":
            vel = int(np.clip(round(ev.velocity * SHAKER_VELOCITY_SCALE), 1, 127))
        elif ev.instrument == "kick":
            vel = int(np.clip(round(ev.velocity * KICK_VELOCITY_SCALE), 1, 127))
        else:
            vel = ev.velocity

        actions.append((start_tick, 1.0, "note_on", ev.midi_note, vel))
        actions.append((end_tick, 0.0, "note_off", ev.midi_note, 0))

    return actions


def build_drums_midi(
    drum_events: Sequence[DrumEvent],
    out_path: Path,
    bpm: float = 72.0,
    ticks_per_beat: int = 480,
) -> Path:
    """Build mix_drums.mid on Channel 10 (0-indexed 9)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    mid = mido.MidiFile(type=1, ticks_per_beat=ticks_per_beat)

    drum_actions = get_drum_actions(drum_events, ticks_per_beat=ticks_per_beat)
    drum_track = build_track_from_actions(
        track_name="Percussion",
        channel=9,  # GM Channel 10
        program=None,
        actions=drum_actions,
        bpm=bpm,
        ticks_per_beat=ticks_per_beat,
        include_tempo=True,
    )
    mid.tracks.append(drum_track)
    mid.save(str(out_path))
    return out_path


def build_harmony_midi(
    harmony_bars: Sequence[BarHarmony],
    norm_speeds: Sequence[float | None],
    section_counts: Sequence[tuple[str, int]] | None = None,
    out_path: Path | None = None,
    bpm: float = 72.0,
    ticks_per_beat: int = 480,
) -> Path:
    """
    Build mix_harmony.mid:
    Track 1: Warm Pad (GM program 89, channel 0)
    Track 2: Cello (GM program 42, channel 1)
    """
    if out_path is None:
        raise ValueError("out_path must be provided")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    mid = mido.MidiFile(type=1, ticks_per_beat=ticks_per_beat)

    # Pad Track (no CC11, default expression)
    pad_actions = get_pad_actions(harmony_bars, norm_speeds, ticks_per_beat=ticks_per_beat)
    pad_track = build_track_from_actions(
        track_name="Halo Pad",
        channel=0,
        program=PAD_PROGRAM,  # GM Program 94: Halo Pad
        actions=pad_actions,
        bpm=bpm,
        ticks_per_beat=ticks_per_beat,
        include_tempo=True,
    )
    mid.tracks.append(pad_track)

    # Cello Track (no CC11, default expression)
    cello_actions = get_cello_actions(harmony_bars, ticks_per_beat=ticks_per_beat)
    cello_track = build_track_from_actions(
        track_name="Cello",
        channel=1,
        program=42,  # GM Program 42: Cello
        actions=cello_actions,
        bpm=bpm,
        ticks_per_beat=ticks_per_beat,
        include_tempo=True,
    )
    mid.tracks.append(cello_track)

    mid.save(str(out_path))
    return out_path


def build_combined_midi(
    drum_events: Sequence[DrumEvent],
    harmony_bars: Sequence[BarHarmony],
    norm_speeds: Sequence[float | None],
    section_counts: Sequence[tuple[str, int]] | None = None,
    out_path: Path | None = None,
    bpm: float = 72.0,
    ticks_per_beat: int = 480,
    melody_events: Sequence[MelodyEvent] | None = None,
    melody_program: int = MELODY_PROGRAM_DEFAULT,
    scales: Sequence[float] | None = None,
    top5_run_starts: Sequence[int] | None = None,
    riser_bars: Sequence[int] | None = None,
) -> Path:
    """
    Build combined MIDI file in one Type-1 MIDI file with separate tracks:
    Track 1: Halo Pad (GM program 94, channel 0)
    Track 2: Cello Bass (GM program 42, channel 1)
    Track 3: Melody (System 3 v3, GM program 49, channel 2, if melody_events provided)
    Track 4: Reverse Cymbal Riser (GM program 119, channel 3, on bars before top 5% runs)
    Track 5: Percussion (channel 9 / GM 10, shaker -25%, kick -15%, crash on top 5% run starts)
    """
    if out_path is None:
        raise ValueError("out_path must be provided")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    mid = mido.MidiFile(type=1, ticks_per_beat=ticks_per_beat)

    if scales is None:
        smooth_s = compute_smooth_speeds(norm_speeds)
        scales = compute_velocity_scales(smooth_s)
    if top5_run_starts is None or riser_bars is None:
        runs, risers = find_top5_runs(norm_speeds)
        if top5_run_starts is None:
            top5_run_starts = runs
        if riser_bars is None:
            riser_bars = risers

    # Track 1: Halo Pad (no CC11, dynamic velocity)
    pad_actions = get_pad_actions(harmony_bars, norm_speeds, ticks_per_beat=ticks_per_beat, scales=scales)
    pad_track = build_track_from_actions(
        track_name="Halo Pad",
        channel=0,
        program=PAD_PROGRAM,
        actions=pad_actions,
        bpm=bpm,
        ticks_per_beat=ticks_per_beat,
        include_tempo=True,
    )
    mid.tracks.append(pad_track)

    # Track 2: Cello (no CC11, dynamic velocity)
    cello_actions = get_cello_actions(harmony_bars, ticks_per_beat=ticks_per_beat, scales=scales)
    cello_track = build_track_from_actions(
        track_name="Cello",
        channel=1,
        program=42,
        actions=cello_actions,
        bpm=bpm,
        ticks_per_beat=ticks_per_beat,
        include_tempo=True,
    )
    mid.tracks.append(cello_track)

    # Track 3: Melody (System 3 v3, dynamic velocity)
    if melody_events:
        scaled_melody_events = [
            MelodyEvent(
                bar=ev.bar,
                beat=ev.beat,
                midi_note=ev.midi_note,
                velocity=apply_velocity_scale(ev.velocity, scales[ev.bar] if ev.bar < len(scales) else 1.0),
                duration_beats=ev.duration_beats,
                timing_offset_ms=ev.timing_offset_ms,
            )
            for ev in melody_events
        ]
        melody_actions = build_melody_actions(
            scaled_melody_events,
            bpm=bpm,
            ticks_per_beat=ticks_per_beat,
            program=melody_program,
        )
        melody_track = build_track_from_actions(
            track_name="Melody",
            channel=2,
            program=None,  # Program change and controllers are handled within melody_actions
            actions=melody_actions,
            bpm=bpm,
            ticks_per_beat=ticks_per_beat,
            include_tempo=True,
        )
        mid.tracks.append(melody_track)

    # Track 4: Riser (GM 119 Reverse Cymbal, channel 3)
    if riser_bars:
        riser_actions = generate_riser_actions(riser_bars, ticks_per_beat=ticks_per_beat, channel=3, program=119)
        if riser_actions:
            riser_track = build_track_from_actions(
                track_name="Reverse Cymbal",
                channel=3,
                program=None,
                actions=riser_actions,
                bpm=bpm,
                ticks_per_beat=ticks_per_beat,
                include_tempo=True,
            )
            mid.tracks.append(riser_track)

    # Track 5: Percussion (scaled velocities + crash on top 5% run starts)
    scaled_drums = scale_drum_events(drum_events, scales)
    crash_events = generate_crash_events(top5_run_starts, norm_speeds)
    all_drum_events = list(scaled_drums) + crash_events

    drum_actions = get_drum_actions(all_drum_events, ticks_per_beat=ticks_per_beat)
    drum_track = build_track_from_actions(
        track_name="Percussion",
        channel=9,
        program=None,
        actions=drum_actions,
        bpm=bpm,
        ticks_per_beat=ticks_per_beat,
        include_tempo=True,
    )
    mid.tracks.append(drum_track)

    mid.save(str(out_path))
    return out_path


def generate_mix_midis(
    blocks: Sequence[dict[str, Any]],
    seed: int = 42,
    out_dir: Path | str = "output",
    bpm: float = 72.0,
    hysteresis: int = 2,
    eight_sectors: bool = False,
    mid_name: str = "mix_combined.mid",
    key_offset: int = 0,
) -> tuple[Path, Path, Path]:
    """
    Generate mix MIDI files from blocks with deterministic seed:
      - mix_drums.mid
      - mix_harmony.mid
      - mix_combined.mid (Halo Pad GM 94, Cello Bass GM 42, Reverse Cymbal GM 119, Percussion, Strings GM 49)
    Returns (drums_mid, harmony_mid, combined_mid).
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    norm_speeds, _ = normalize_series_5_95(blocks)
    smooth_speeds = compute_smooth_speeds(norm_speeds)
    scales = compute_velocity_scales(smooth_speeds)
    top5_run_starts, riser_bars = find_top5_runs(norm_speeds)

    drum_events = generate_drum_events(norm_speeds, seed=seed)
    harmony_bars = generate_harmony(
        blocks,
        norm_speeds,
        hold_threshold=0.013,
        hysteresis=hysteresis,
        eight_sectors=eight_sectors,
        key_offset=key_offset,
    )
    section_counts = compute_section_counts(len(blocks))
    melody_events = generate_melody(blocks, harmony_bars, norm_speeds, seed=seed, key_offset=key_offset)

    # Drum MIDI with dynamics and crashes
    scaled_drums = scale_drum_events(drum_events, scales)
    crash_events = generate_crash_events(top5_run_starts, norm_speeds)
    all_drums = list(scaled_drums) + crash_events
    drums_mid = build_drums_midi(all_drums, out_dir / "mix_drums.mid", bpm=bpm)

    harmony_mid = build_harmony_midi(harmony_bars, norm_speeds, section_counts, out_dir / "mix_harmony.mid", bpm=bpm)
    combined_mid = build_combined_midi(
        drum_events,
        harmony_bars,
        norm_speeds,
        section_counts,
        out_dir / mid_name,
        bpm=bpm,
        melody_events=melody_events,
        melody_program=PROGRAM_STRINGS,
        scales=scales,
        top5_run_starts=top5_run_starts,
        riser_bars=riser_bars,
    )

    return drums_mid, harmony_mid, combined_mid


def main() -> None:
    parser = argparse.ArgumentParser(description="AetherWaves Demo Mix Runner")
    parser.add_argument("--json", type=str, default="data/raw_oscar/oscar_2025_daily.json", help="Path to OSCAR daily JSON")
    parser.add_argument("--month", type=str, default=None, help="Filter to specific month, e.g. 2025-01 or 2026-01 (defaults block-size to 1 day for ~2 min live data music)")
    parser.add_argument("--block-size", type=int, default=None, help="Block size in days (default: 7 for year, 1 for month)")
    parser.add_argument("--seed", type=int, default=None, help="Deterministic seed override (default: sha256 of period label)")
    parser.add_argument("--key-offset", type=int, default=None, help="Key offset k in 0..6 override (default: data-driven)")
    parser.add_argument("--prefix", type=str, default=None, help="Output filename prefix override")
    parser.add_argument("--gain", type=float, default=1.0, help="FluidSynth render gain")
    parser.add_argument("--target-dbfs", type=float, default=-1.0, help="Normalization target in dBFS")
    parser.add_argument("--eight-sectors", action="store_true", default=False, help="Enable 8-sector dynamic modal harmony")
    parser.add_argument("--hysteresis", type=int, default=None, help="Hysteresis streak (default: 2 for year and month)")
    parser.add_argument("--play", action="store_true", default=False, help="Play output WAV on completion")
    parser.add_argument("--no-play", dest="play", action="store_false", help="Do not play audio automatically")
    parser.add_argument("--out-dir", type=str, default="output", help="Output directory")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Load data and group into blocks
    json_path = REPO_ROOT / args.json
    if not json_path.exists():
        raise FileNotFoundError(f"OSCAR daily data not found at {json_path}")

    with open(json_path, "r", encoding="utf-8") as f:
        daily_records: list[dict[str, Any]] = json.load(f)

    # Monthly filtering and settings (UNDO: same chord rules as yearly: 4 sectors, hysteresis 2)
    if args.month:
        daily_records = [r for r in daily_records if str(r.get("date", "")).startswith(args.month)]
        if not daily_records:
            raise ValueError(f"No records found for month {args.month} in {json_path}")
        block_size = 1 if args.block_size is None else args.block_size
        eight_sectors = args.eight_sectors  # off by default
        hysteresis = 2 if args.hysteresis is None else args.hysteresis
        period_label = args.month
        is_month = True
        prefix = args.prefix if args.prefix else f"mix_{args.month.replace('-', '_')}"
    else:
        block_size = 7 if args.block_size is None else args.block_size
        eight_sectors = args.eight_sectors
        hysteresis = 2 if args.hysteresis is None else args.hysteresis
        is_month = False
        # Derive year label
        year_cand = None
        for y in ["2021", "2022", "2023", "2024", "2025", "2026"]:
            if y in str(args.json):
                year_cand = y
                break
        if year_cand is None and daily_records and "date" in daily_records[0]:
            year_cand = str(daily_records[0]["date"])[:4]
        period_label = year_cand if year_cand else "2025"
        prefix = args.prefix if args.prefix else (f"mix_{period_label}" if period_label != "2025" else "mix_combined")

    speeds = [float(d["speed_p95"]) for d in daily_records if d.get("speed_p95") is not None]
    if not speeds:
        raise ValueError(f"No valid speed_p95 found in records for {period_label}")
    period_mean_speed = sum(speeds) / len(speeds)

    # Key offset k and tonic name
    if args.key_offset is not None:
        k = args.key_offset
    else:
        k = compute_key_offset(period_mean_speed, is_month=is_month)
    tonic_name = get_tonic_name(k)

    # Seed from sha256 of period label unless overridden
    if args.seed is not None:
        seed = args.seed
    else:
        seed = seed_from_period(period_label)

    blocks = group_days_into_blocks(daily_records, block_size=block_size)
    total_bars = len(blocks)
    bpm = 72.0
    seconds_per_bar = 4.0 * (60.0 / bpm)
    total_seconds = total_bars * seconds_per_bar

    # Count chord changes
    norm_speeds, _ = normalize_series_5_95(blocks)
    harmony_bars = generate_harmony(
        blocks,
        norm_speeds,
        hold_threshold=0.013,
        hysteresis=hysteresis,
        eight_sectors=eight_sectors,
        key_offset=k,
    )
    chords = [h.chord for h in harmony_bars]
    chord_changes = sum(1 for idx in range(1, len(chords)) if chords[idx] != chords[idx - 1])

    # 2. Build MIDI files
    print(f"Generating MIDI file for {total_bars} bars (period={period_label}, mean={period_mean_speed:.6f}, k={k}, tonic={tonic_name}, seed={seed}, block_size={block_size}, eight_sectors={eight_sectors}, hysteresis={hysteresis})...")
    drums_mid, harmony_mid, combined_mid = generate_mix_midis(
        blocks,
        seed=seed,
        out_dir=out_dir,
        bpm=bpm,
        hysteresis=hysteresis,
        eight_sectors=eight_sectors,
        mid_name=f"{prefix}.mid",
        key_offset=k,
    )

    # 3. Render and normalize WAV file with built-in reverb (-R 1)
    soundfont = find_soundfont()
    print(f"Using SoundFont: {soundfont.name}")

    combined_wav = out_dir / f"{prefix}.wav"
    render_with_fluidsynth(combined_mid, soundfont, combined_wav, gain=args.gain)
    init_pk, final_pk = normalize_wav_to_dbfs(combined_wav, target_dbfs=args.target_dbfs)
    print(f"[Mastering] {combined_wav.name}: Peak {init_pk:.4f} -> {final_pk:.4f} ({args.target_dbfs} dBFS)")

    # Maintain dual names for 2025
    if period_label == "2025" and not is_month:
        import shutil
        if prefix == "mix_combined":
            shutil.copy2(combined_wav, out_dir / "mix_2025.wav")
            shutil.copy2(combined_mid, out_dir / "mix_2025.mid")
        elif prefix == "mix_2025":
            shutil.copy2(combined_wav, out_dir / "mix_combined.wav")
            shutil.copy2(combined_mid, out_dir / "mix_combined.mid")

    # 4. Print summary
    print("\n" + "=" * 60)
    print("=== AetherWaves Mix Render Summary ===")
    print(f"Period:        {period_label}")
    print(f"Mean speed:    {period_mean_speed:.6f}")
    print(f"Key offset k:  {k}")
    print(f"Tonic:         {tonic_name}")
    print(f"Chord changes: {chord_changes}")
    print(f"Total bars:    {total_bars}")
    print(f"Total seconds: {total_seconds:.1f}s ({total_seconds / 60.0:.2f} minutes @ {bpm} BPM)")
    print("Files created:")
    print(f"  - Combined MIDI: {combined_mid.resolve()}")
    print(f"  - Combined WAV:  {combined_wav.resolve()}")
    print("=" * 60 + "\n")

    # Explicit summary format: period, mean speed_p95, k, tonic name, chord changes
    print(f"SUMMARY_LINE: {period_label}, {period_mean_speed:.6f}, {k}, {tonic_name}, {chord_changes}")

    # Play mix WAV if requested
    if args.play:
        print(f"Playing {combined_wav.name} via Windows Audio...")
        try:
            import winsound
            winsound.PlaySound(str(combined_wav), winsound.SND_FILENAME | winsound.SND_ASYNC)
            print("Audio playback started in background!")
        except Exception as exc:
            print(f"Playback error: {exc}")


if __name__ == "__main__":
    main()
