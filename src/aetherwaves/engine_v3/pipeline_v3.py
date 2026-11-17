"""pipeline_v3.py — Audio and MIDI pipeline for AetherWaves Engine v3.

Produces Type-1 MIDI with multi-channel layout (Melody, Harmony, Bass, Texture, Drone, Drums),
renders via FluidSynth with reverb on, normalizes to -24 LUFS via FFmpeg loudnorm,
and encodes to bitexact Opus.
Computes audio analysis (RMS dB, spectral centroid) and click check sample step.
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

import mido
import numpy as np
import soundfile as sf

from pipeline.demo_mix import find_fluidsynth, find_soundfont

from .form_v3 import compute_form_sections
from .harmony_v3 import BarHarmonyV3, generate_harmony_v3
from .melody_v3 import MelodyBarV3, generate_melody_v3
from .rhythm_v3 import DrumEventV3, generate_drum_events_v3


def build_midi_v3(
    blocks: list[dict[str, Any]],
    norm_speeds: list[float],
    harmony_bars: list[BarHarmonyV3],
    melody_bars: list[MelodyBarV3],
    drum_events: list[DrumEventV3],
    preset: dict[str, Any],
    out_midi_path: Path,
) -> Path:
    """Build a multi-track Type-1 MIDI file for v3 engine."""
    tempo_bpm = preset.get("tempo", 72)
    tempo_usec = mido.bpm2tempo(tempo_bpm)
    ticks_per_beat = 480
    ticks_per_bar = ticks_per_beat * 4
    n_bars = len(blocks)

    mid = mido.MidiFile(type=1, ticks_per_beat=ticks_per_beat)

    # Track 0: Master tempo & time signature
    track0 = mido.MidiTrack()
    mid.tracks.append(track0)
    track0.append(mido.MetaMessage("track_name", name="Master Tempo", time=0))
    track0.append(mido.MetaMessage("set_tempo", tempo=tempo_usec, time=0))
    track0.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))
    track0.append(mido.MetaMessage("end_of_track", time=ticks_per_bar * n_bars))

    # Channel configuration
    ch_melody = 0
    ch_harmony = 1
    ch_bass = 2
    ch_texture = 3
    ch_drone = 4
    ch_drums = 9

    gm = preset["gm_programs"]
    pan = preset["pan"]

    def pan_to_cc(p: float) -> int:
        return int(np.clip(round(64 + 63 * p), 0, 127))

    gm_mel = gm["melody"]
    gm_harm = gm.get("harmony", gm.get("pad", 89))
    gm_bass = gm["bass"]
    gm_tex = gm.get("texture", 89)
    gm_drone = gm.get("drone", 89)

    pan_mel = pan["melody"]
    pan_harm = pan.get("harmony", pan.get("pad", -0.2))
    pan_bass = pan["bass"]
    pan_tex = pan.get("texture", 0.2)
    pan_drone = pan.get("drone", -0.1)
    pan_drums = pan.get("drums", pan.get("percussion", -0.1))

    # Helper to create channel track with initial CCs and program change
    def create_instrument_track(name: str, ch: int, prog: int, pan_val: float) -> mido.MidiTrack:
        tr = mido.MidiTrack()
        tr.append(mido.MetaMessage("track_name", name=name, time=0))
        tr.append(mido.Message("control_change", channel=ch, control=10, value=pan_to_cc(pan_val), time=0))
        tr.append(mido.Message("control_change", channel=ch, control=7, value=100, time=0))
        if ch != 9:
            tr.append(mido.Message("program_change", channel=ch, program=prog, time=0))
        return tr

    # Track 1: Melody
    tr_melody = create_instrument_track("Melody", ch_melody, gm_mel, pan_mel)
    mel_events: list[tuple[int, str, int, int]] = []  # (abs_tick, type, note, vel)
    for mb in melody_bars:
        if mb.is_rest:
            continue
        bar_tick = mb.bar * ticks_per_bar
        for mn in mb.notes:
            t_on = bar_tick + int(round(mn.start_beat * ticks_per_beat))
            t_off = t_on + int(round(mn.duration_beats * ticks_per_beat))
            mel_events.append((t_on, "note_on", mn.pitch, min(mn.velocity, 80)))
            mel_events.append((t_off, "note_off", mn.pitch, 0))

    mel_events.sort(key=lambda e: (e[0], 0 if e[1] == "note_off" else 1))
    cur_tick = 0
    for tick, typ, note, vel in mel_events:
        delta = max(0, tick - cur_tick)
        tr_melody.append(mido.Message(typ, channel=ch_melody, note=note, velocity=vel, time=delta))
        cur_tick = tick
    tr_melody.append(mido.MetaMessage("end_of_track", time=max(0, ticks_per_bar * n_bars - cur_tick)))
    mid.tracks.append(tr_melody)

    # Track 2: Harmony Pad
    tr_harmony = create_instrument_track("Harmony", ch_harmony, gm_harm, pan_harm)
    harm_events: list[tuple[int, str, int, int]] = []
    for h in harmony_bars:
        if h.is_rest:
            continue
        bar_tick = h.bar * ticks_per_bar
        t_on = bar_tick
        t_off = bar_tick + int(round(3.8 * ticks_per_beat))
        h_vel = min(58, 80) if not h.held else min(48, 80)
        for p in h.chord_tones_midi:
            harm_events.append((t_on, "note_on", p, h_vel))
            harm_events.append((t_off, "note_off", p, 0))

    harm_events.sort(key=lambda e: (e[0], 0 if e[1] == "note_off" else 1))
    cur_tick = 0
    for tick, typ, note, vel in harm_events:
        delta = max(0, tick - cur_tick)
        tr_harmony.append(mido.Message(typ, channel=ch_harmony, note=note, velocity=vel, time=delta))
        cur_tick = tick
    tr_harmony.append(mido.MetaMessage("end_of_track", time=max(0, ticks_per_bar * n_bars - cur_tick)))
    mid.tracks.append(tr_harmony)

    # Track 3: Bass
    tr_bass = create_instrument_track("Bass", ch_bass, gm_bass, pan_bass)
    bass_events: list[tuple[int, str, int, int]] = []
    for h in harmony_bars:
        if h.is_rest:
            continue
        bar_tick = h.bar * ticks_per_bar
        t_on = bar_tick
        t_off = bar_tick + int(round(h.bass_duration * ticks_per_beat))
        bass_events.append((t_on, "note_on", h.bass_note, min(h.bass_velocity, 80)))
        bass_events.append((t_off, "note_off", h.bass_note, 0))

    bass_events.sort(key=lambda e: (e[0], 0 if e[1] == "note_off" else 1))
    cur_tick = 0
    for tick, typ, note, vel in bass_events:
        delta = max(0, tick - cur_tick)
        tr_bass.append(mido.Message(typ, channel=ch_bass, note=note, velocity=vel, time=delta))
        cur_tick = tick
    tr_bass.append(mido.MetaMessage("end_of_track", time=max(0, ticks_per_bar * n_bars - cur_tick)))
    mid.tracks.append(tr_bass)

    # Track 4: Texture Layer (follows harmony, silent on rest)
    tr_texture = create_instrument_track("Texture", ch_texture, gm_tex, pan_tex)
    tex_events: list[tuple[int, str, int, int]] = []
    for h in harmony_bars:
        if h.is_rest:
            continue
        bar_tick = h.bar * ticks_per_bar
        t_on = bar_tick
        t_off = bar_tick + int(round(3.9 * ticks_per_beat))
        # Play root & 5th of chord voicing softly
        root_m = h.chord_tones_midi[0] if h.chord_tones_midi else 60
        tex_events.append((t_on, "note_on", root_m, min(36, 80)))
        tex_events.append((t_off, "note_off", root_m, 0))

    tex_events.sort(key=lambda e: (e[0], 0 if e[1] == "note_off" else 1))
    cur_tick = 0
    for tick, typ, note, vel in tex_events:
        delta = max(0, tick - cur_tick)
        tr_texture.append(mido.Message(typ, channel=ch_texture, note=note, velocity=vel, time=delta))
        cur_tick = tick
    tr_texture.append(mido.MetaMessage("end_of_track", time=max(0, ticks_per_bar * n_bars - cur_tick)))
    mid.tracks.append(tr_texture)

    # Track 5: Drone (Root + Fifth, continuous)
    tr_drone = create_instrument_track("Drone", ch_drone, gm_drone, pan_drone)
    drone_events: list[tuple[int, str, int, int]] = []
    # Root 36 (C2) and Fifth 43 (G2)
    drone_pitches = [36, 43]
    for b_idx in range(n_bars):
        bar_tick = b_idx * ticks_per_bar
        t_on = bar_tick
        t_off = bar_tick + ticks_per_bar
        for dp in drone_pitches:
            drone_events.append((t_on, "note_on", dp, min(42, 80)))
            drone_events.append((t_off, "note_off", dp, 0))

    drone_events.sort(key=lambda e: (e[0], 0 if e[1] == "note_off" else 1))
    cur_tick = 0
    for tick, typ, note, vel in drone_events:
        delta = max(0, tick - cur_tick)
        tr_drone.append(mido.Message(typ, channel=ch_drone, note=note, velocity=vel, time=delta))
        cur_tick = tick
    tr_drone.append(mido.MetaMessage("end_of_track", time=max(0, ticks_per_bar * n_bars - cur_tick)))
    mid.tracks.append(tr_drone)

    # Track 6: Percussion (Channel 9)
    tr_drums = create_instrument_track("Percussion", ch_drums, 0, pan_drums)
    drum_ev_list: list[tuple[int, str, int, int]] = []
    for d in drum_events:
        t_on = d.bar * ticks_per_bar + int(round(d.beat * ticks_per_beat))
        t_off = t_on + int(round(d.duration_beats * ticks_per_beat))
        drum_ev_list.append((t_on, "note_on", d.midi_note, min(d.velocity, 80)))
        drum_ev_list.append((t_off, "note_off", d.midi_note, 0))

    drum_ev_list.sort(key=lambda e: (e[0], 0 if e[1] == "note_off" else 1))
    cur_tick = 0
    for tick, typ, note, vel in drum_ev_list:
        delta = max(0, tick - cur_tick)
        tr_drums.append(mido.Message(typ, channel=ch_drums, note=note, velocity=vel, time=delta))
        cur_tick = tick
    tr_drums.append(mido.MetaMessage("end_of_track", time=max(0, ticks_per_bar * n_bars - cur_tick)))
    mid.tracks.append(tr_drums)

    # Strict check: ensure zero CC11 events across entire file
    for trk in mid.tracks:
        for msg in trk:
            if msg.type == "control_change" and msg.control == 11:
                raise ValueError("Prohibited CC11 event found in MIDI output!")

    out_midi_path.parent.mkdir(parents=True, exist_ok=True)
    mid.save(str(out_midi_path))
    return out_midi_path


def render_v3_audio(
    midi_path: Path,
    out_wav_path: Path,
    out_opus_path: Path,
    target_lufs: float = -24.0,
) -> tuple[Path, Path]:
    """Render MIDI via FluidSynth with reverb, normalize to -24 LUFS, and encode to bitexact Opus."""
    fluidsynth = find_fluidsynth()
    soundfont = find_soundfont()

    raw_wav = out_wav_path.with_name(out_wav_path.stem + "_raw.wav")

    cmd_fs = [
        str(fluidsynth),
        "-ni",
        "-R", "1",
        "-C", "0",
        "-o", "synth.reverb.room-size=0.5",
        "-o", "synth.reverb.level=0.5",
        "-g", "0.8",
        "-r", "44100",
        "-F", str(raw_wav.resolve()),
        str(soundfont.resolve()),
        str(midi_path.resolve()),
    ]
    res_fs = subprocess.run(cmd_fs, capture_output=True, text=True)
    if res_fs.returncode != 0 or not raw_wav.exists():
        raise RuntimeError(f"FluidSynth failed: {res_fs.stderr}")

    # FFmpeg loudnorm to target LUFS (-24 LUFS)
    cmd_norm = [
        "ffmpeg", "-y",
        "-i", str(raw_wav.resolve()),
        "-filter:a", f"loudnorm=I={target_lufs}:LRA=7:tp=-2.0",
        "-ar", "44100",
        str(out_wav_path.resolve()),
    ]
    res_norm = subprocess.run(cmd_norm, capture_output=True, text=True)
    if res_norm.returncode != 0 or not out_wav_path.exists():
        raise RuntimeError(f"FFmpeg loudnorm failed: {res_norm.stderr}")

    # Remove temporary raw wav
    if raw_wav.exists():
        raw_wav.unlink()

    # Encode to bitexact Opus
    cmd_opus = [
        "ffmpeg", "-y",
        "-i", str(out_wav_path.resolve()),
        "-c:a", "libopus",
        "-b:a", "48k",
        "-ac", "1",
        "-map_metadata", "-1",
        "-fflags", "+bitexact",
        "-flags:a", "+bitexact",
        str(out_opus_path.resolve()),
    ]
    res_opus = subprocess.run(cmd_opus, capture_output=True, text=True)
    if res_opus.returncode != 0 or not out_opus_path.exists():
        raise RuntimeError(f"FFmpeg Opus export failed: {res_opus.stderr}")

    return out_wav_path, out_opus_path


def analyze_v3_audio(
    wav_path: Path,
    sections: list[dict[str, Any]],
    tempo: float,
) -> tuple[dict[str, Any], float]:
    """
    Perform audio analysis on normalized WAV:
    - Per section: RMS dB (1 decimal), spectral centroid (nearest 100 Hz), soft/medium/bright tiers
    - Looping check: absolute sample step between last and first audio sample
    """
    with sf.SoundFile(str(wav_path)) as sf_file:
        data = sf_file.read(dtype="float64")
        sr = sf_file.samplerate
    if data.ndim > 1:
        data = np.mean(data, axis=1)

    # End-to-start sample step (loop click check)
    sample_step = float(abs(data[-1] - data[0]))

    bar_seconds = 240.0 / tempo
    samples_per_bar = int(round(bar_seconds * sr))

    section_analysis: dict[str, Any] = {}

    for sec in sections:
        name = sec["name"]
        start_samp = sec["start_bar"] * samples_per_bar
        end_samp = min((sec["end_bar"] + 1) * samples_per_bar, len(data))

        sec_data = data[start_samp:end_samp]
        if len(sec_data) == 0:
            rms_db = -99.0
            sc_hz = 0
        else:
            # RMS dB
            rms_val = float(np.sqrt(np.mean(sec_data**2)))
            rms_db = float(round(20.0 * np.log10(rms_val + 1e-12), 1))

            # Spectral centroid
            fft_mag = np.abs(np.fft.rfft(sec_data))
            freqs = np.fft.rfftfreq(len(sec_data), 1.0 / sr)
            sum_mag = np.sum(fft_mag)
            if sum_mag > 1e-12:
                sc_raw = float(np.sum(freqs * fft_mag) / sum_mag)
                sc_hz = int(round(sc_raw / 100.0) * 100)
            else:
                sc_hz = 0

        # Tier classification
        rms_tier = "soft" if rms_db < -28.0 else ("medium" if rms_db <= -20.0 else "loud")
        centroid_tier = "dark" if sc_hz < 800 else ("medium" if sc_hz <= 1600 else "bright")

        section_analysis[name] = {
            "rms_db": rms_db,
            "rms_tier": rms_tier,
            "spectral_centroid_hz": sc_hz,
            "brightness_tier": centroid_tier,
            "start_bar": sec["start_bar"],
            "end_bar": sec["end_bar"],
        }

    return section_analysis, sample_step
