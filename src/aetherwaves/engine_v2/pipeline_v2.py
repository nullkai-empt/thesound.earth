"""AetherWaves Engine v2 Pipeline.

Deterministic rendering with regional presets, FluidSynth + FluidR3_GM,
custom General MIDI channel allocation, CC10 spatial pan, and bitexact Opus export.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

import mido
import numpy as np
import soundfile as sf

from aetherwaves.blocks import group_days_into_blocks
from aetherwaves.rhythm import normalize_series_5_95
from pipeline.demo_mix import (
    find_fluidsynth,
    find_soundfont,
    normalize_wav_to_dbfs,
    render_with_fluidsynth,
)

from .dynamics import compute_smooth_speeds, compute_velocity_scales, find_top5_runs
from .harmony import BarHarmony, generate_harmony_v2
from .melody import MelodyEvent, generate_melody_v2
from .rhythm import DrumEvent, generate_drum_events_v2


def get_pad_voicings_v2(
    chord_tones_pcs: list[int],
    scale_pcs: set[int],
    prev_voicing: tuple[int, ...] | None = None,
) -> list[int]:
    """Find a 4-note voicing in [60, 79] strictly using chord_tones_pcs (subset of scale_pcs)."""
    cand_notes = [n for n in range(60, 80) if (n % 12) in chord_tones_pcs]
    assert all((n % 12) in scale_pcs for n in cand_notes)

    # Group candidate notes by pitch class
    notes_by_pc: dict[int, list[int]] = {}
    for pc in chord_tones_pcs:
        notes_by_pc[pc] = [n for n in cand_notes if (n % 12) == pc]

    # Generate all 4-note combinations that include all pitch classes if possible
    voicings: list[list[int]] = []
    if len(chord_tones_pcs) >= 4:
        for n0 in notes_by_pc[chord_tones_pcs[0]]:
            for n1 in notes_by_pc[chord_tones_pcs[1]]:
                for n2 in notes_by_pc[chord_tones_pcs[2]]:
                    for n3 in notes_by_pc[chord_tones_pcs[3]]:
                        v = sorted([n0, n1, n2, n3])
                        if len(set(v)) == 4:
                            voicings.append(v)
    elif len(chord_tones_pcs) == 3:
        # Triad: double root or fifth
        for n0 in notes_by_pc[chord_tones_pcs[0]]:
            for n1 in notes_by_pc[chord_tones_pcs[1]]:
                for n2 in notes_by_pc[chord_tones_pcs[2]]:
                    for extra in cand_notes:
                        v = sorted(list(set([n0, n1, n2, extra])))
                        if len(v) == 4:
                            voicings.append(v)
    else:
        # 2 pitch classes
        for n0 in notes_by_pc[chord_tones_pcs[0]]:
            for n1 in notes_by_pc[chord_tones_pcs[1]]:
                for extra1 in cand_notes:
                    for extra2 in cand_notes:
                        v = sorted(list(set([n0, n1, extra1, extra2])))
                        if len(v) == 4:
                            voicings.append(v)

    if not voicings:
        # Fallback to any 4 distinct notes in cand_notes
        sorted_cands = sorted(cand_notes)
        if len(sorted_cands) >= 4:
            return sorted_cands[:4]
        return sorted_cands

    if prev_voicing is None:
        # Pick voicing with center around 69
        return min(voicings, key=lambda v: abs(np.mean(v) - 69.5))

    # Pick voicing minimizing total movement
    prev_mean = np.mean(prev_voicing)
    return min(voicings, key=lambda v: (sum(abs(a - b) for a, b in zip(v, prev_voicing)), abs(np.mean(v) - prev_mean)))


def pan_to_midi_cc10(pan: float) -> int:
    """Convert float pan [-1.0, 1.0] to MIDI CC10 [0, 127]."""
    return int(np.clip(round(64.0 + 63.0 * pan), 0, 127))


def build_midi_v2(
    blocks: Sequence[dict[str, Any]],
    norm_speeds: Sequence[float | None],
    preset: dict[str, Any],
    preset_id: str,
    seed: int,
    out_mid_path: Path,
    bpm: float = 72.0,
    ticks_per_beat: int = 480,
) -> tuple[Path, list[BarHarmony], list[MelodyEvent], list[DrumEvent]]:
    """Build multi-track Type-1 MIDI file with preset instruments and panning."""
    out_mid_path.parent.mkdir(parents=True, exist_ok=True)
    mid = mido.MidiFile(type=1, ticks_per_beat=ticks_per_beat)

    scale_pcs = set(preset["scale"])
    pan_cfg = preset.get("pan", {})
    gm_programs = preset["gm_programs"]

    harmony_bars = generate_harmony_v2(blocks, norm_speeds, preset, preset_id)
    melody_events = generate_melody_v2(blocks, harmony_bars, norm_speeds, preset, seed=seed)
    drum_events = generate_drum_events_v2(norm_speeds, drum_pattern=preset.get("drum_pattern", "standard"), seed=seed)

    smooth_speeds = compute_smooth_speeds(norm_speeds)
    scales = compute_velocity_scales(smooth_speeds)
    top5_run_starts, riser_bars = find_top5_runs(norm_speeds)

    bar_ticks = 4 * ticks_per_beat
    tempo_us = int(round(60_000_000.0 / bpm))

    # --- Track 1: Pad (Channel 0) ---
    pad_track = mido.MidiTrack()
    pad_track.append(mido.MetaMessage("set_tempo", tempo=tempo_us, time=0))
    pad_track.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))
    pad_track.append(mido.MetaMessage("track_name", name="Pad", time=0))
    pad_track.append(mido.Message("program_change", channel=0, program=gm_programs["pad"], time=0))
    pad_track.append(mido.Message("control_change", channel=0, control=10, value=pan_to_midi_cc10(pan_cfg.get("pad", 0.0)), time=0))

    pad_actions: list[tuple[int, float, str, int, int]] = []
    prev_v: tuple[int, ...] | None = None
    for bar_idx, h in enumerate(harmony_bars):
        if h.is_rest:
            continue
        tones_pcs = [m % 12 for m in h.chord_tones_midi]
        voicing = get_pad_voicings_v2(tones_pcs, scale_pcs, prev_voicing=prev_v)
        prev_v = tuple(voicing)
        start_t = bar_idx * bar_ticks
        end_t = (bar_idx + 1) * bar_ticks - 10
        scale_vel = scales[bar_idx] if bar_idx < len(scales) else 1.0
        vel = int(np.clip(round(35 * scale_vel), 20, 55))
        for note in voicing:
            assert (note % 12) in scale_pcs
            assert 60 <= note <= 79
            pad_actions.append((start_t, 1.0, "note_on", note, vel))
            pad_actions.append((end_t, 0.0, "note_off", note, 0))

    pad_actions.sort(key=lambda a: (a[0], a[1]))
    cur = 0
    for t, _, mtype, note, vel in pad_actions:
        delta = max(0, t - cur)
        pad_track.append(mido.Message(mtype, channel=0, note=note, velocity=vel, time=delta))
        cur = t
    mid.tracks.append(pad_track)

    # --- Track 2: Bass (Channel 1) ---
    bass_track = mido.MidiTrack()
    bass_track.append(mido.MetaMessage("track_name", name="Bass", time=0))
    bass_track.append(mido.Message("program_change", channel=1, program=gm_programs["bass"], time=0))
    bass_track.append(mido.Message("control_change", channel=1, control=10, value=pan_to_midi_cc10(pan_cfg.get("bass", 0.0)), time=0))

    bass_actions: list[tuple[int, float, str, int, int]] = []
    for bar_idx, h in enumerate(harmony_bars):
        if h.is_rest or h.bass_velocity == 0:
            continue
        bn = h.bass_note
        assert (bn % 12) in scale_pcs
        assert 36 <= bn <= 50
        start_t = bar_idx * bar_ticks
        end_t = start_t + int(round(h.bass_duration * ticks_per_beat)) - 10
        scale_vel = scales[bar_idx] if bar_idx < len(scales) else 1.0
        vel = int(np.clip(round(h.bass_velocity * scale_vel * 0.75), 25, 75))
        bass_actions.append((start_t, 1.0, "note_on", bn, vel))
        bass_actions.append((end_t, 0.0, "note_off", bn, 0))

    bass_actions.sort(key=lambda a: (a[0], a[1]))
    cur = 0
    for t, _, mtype, note, vel in bass_actions:
        delta = max(0, t - cur)
        bass_track.append(mido.Message(mtype, channel=1, note=note, velocity=vel, time=delta))
        cur = t
    mid.tracks.append(bass_track)

    # --- Track 3: Melody (Channel 2) ---
    melody_track = mido.MidiTrack()
    melody_track.append(mido.MetaMessage("track_name", name="Melody", time=0))
    melody_track.append(mido.Message("program_change", channel=2, program=gm_programs["melody"], time=0))
    melody_track.append(mido.Message("control_change", channel=2, control=10, value=pan_to_midi_cc10(pan_cfg.get("melody", 0.0)), time=0))

    melody_actions: list[tuple[int, float, str, int, int]] = []
    for ev in melody_events:
        assert (ev.midi_note % 12) in scale_pcs
        assert 52 <= ev.midi_note <= 67
        start_t = int(round(ev.bar * bar_ticks + (ev.beat - 1.0) * ticks_per_beat))
        end_t = start_t + int(round(ev.duration_beats * ticks_per_beat)) - 10
        scale_vel = scales[ev.bar] if ev.bar < len(scales) else 1.0
        vel = int(np.clip(round(ev.velocity * scale_vel), 30, 85))
        melody_actions.append((start_t, 1.0, "note_on", ev.midi_note, vel))
        melody_actions.append((end_t, 0.0, "note_off", ev.midi_note, 0))

    melody_actions.sort(key=lambda a: (a[0], a[1]))
    cur = 0
    for t, _, mtype, note, vel in melody_actions:
        delta = max(0, t - cur)
        melody_track.append(mido.Message(mtype, channel=2, note=note, velocity=vel, time=delta))
        cur = t
    mid.tracks.append(melody_track)

    # --- Track 4: Riser (Channel 3, Reverse Cymbal GM 119) ---
    riser_track = mido.MidiTrack()
    riser_track.append(mido.MetaMessage("track_name", name="Riser", time=0))
    riser_track.append(mido.Message("program_change", channel=3, program=gm_programs.get("riser", 119), time=0))
    riser_track.append(mido.Message("control_change", channel=3, control=10, value=pan_to_midi_cc10(pan_cfg.get("riser", 0.0)), time=0))

    riser_actions: list[tuple[int, float, str, int, int]] = []
    for rbar in riser_bars:
        start_t = int(round(rbar * bar_ticks + 2.0 * ticks_per_beat))
        end_t = (rbar + 1) * bar_ticks
        riser_actions.append((start_t, 1.0, "note_on", 60, 50))
        riser_actions.append((end_t, 0.0, "note_off", 60, 0))

    riser_actions.sort(key=lambda a: (a[0], a[1]))
    cur = 0
    for t, _, mtype, note, vel in riser_actions:
        delta = max(0, t - cur)
        riser_track.append(mido.Message(mtype, channel=3, note=note, velocity=vel, time=delta))
        cur = t
    mid.tracks.append(riser_track)

    # --- Track 5: Percussion (Channel 9 / GM 10) ---
    perc_track = mido.MidiTrack()
    perc_track.append(mido.MetaMessage("track_name", name="Percussion", time=0))
    perc_track.append(mido.Message("control_change", channel=9, control=10, value=pan_to_midi_cc10(pan_cfg.get("percussion", 0.0)), time=0))

    # Percussion actions + crash cymbals on top5 run starts
    perc_actions: list[tuple[int, float, str, int, int]] = []
    for dev in drum_events:
        start_t = int(round(dev.bar * bar_ticks + (dev.beat - 1.0) * ticks_per_beat))
        end_t = start_t + int(round(dev.duration_beats * ticks_per_beat))
        scale_vel = scales[dev.bar] if dev.bar < len(scales) else 1.0
        vel = int(np.clip(round(dev.velocity * scale_vel), 25, 110))
        perc_actions.append((start_t, 1.0, "note_on", dev.midi_note, vel))
        perc_actions.append((end_t, 0.0, "note_off", dev.midi_note, 0))

    for run_bar in top5_run_starts:
        start_t = run_bar * bar_ticks
        end_t = start_t + int(round(2.0 * ticks_per_beat))
        perc_actions.append((start_t, 1.0, "note_on", 49, 75))  # Crash Cymbal
        perc_actions.append((end_t, 0.0, "note_off", 49, 0))

    perc_actions.sort(key=lambda a: (a[0], a[1]))
    cur = 0
    for t, _, mtype, note, vel in perc_actions:
        delta = max(0, t - cur)
        perc_track.append(mido.Message(mtype, channel=9, note=note, velocity=vel, time=delta))
        cur = t
    mid.tracks.append(perc_track)

    mid.save(str(out_mid_path))
    return out_mid_path, harmony_bars, melody_events, drum_events


def render_v2_audio(
    mid_path: Path,
    wav_path: Path,
    opus_path: Path,
    soundfont_path: Path | None = None,
) -> tuple[Path, Path]:
    """Render MIDI to WAV via FluidSynth, peak-normalize to -1.0 dBFS, and encode to Opus."""
    if soundfont_path is None:
        soundfont_path = find_soundfont()

    wav_path.parent.mkdir(parents=True, exist_ok=True)
    opus_path.parent.mkdir(parents=True, exist_ok=True)

    render_with_fluidsynth(mid_path, soundfont_path, wav_path, gain=1.0)
    normalize_wav_to_dbfs(wav_path, target_dbfs=-1.0)

    cmd = [
        "ffmpeg", "-y", "-i", str(wav_path),
        "-c:a", "libopus", "-b:a", "48k", "-ac", "1",
        "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:a", "+bitexact",
        str(opus_path)
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return wav_path, opus_path
