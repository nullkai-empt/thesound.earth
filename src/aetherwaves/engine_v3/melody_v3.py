"""melody_v3.py — Melody generator for AetherWaves Engine v3.

Melodic rules:
- Strictly constrained to preset["scale"] pitch classes, except for ONE declared color tone.
- Stated data event for color tone: local maximum breakout (x_i > max(x_{i-4..i-1})) with cooldown >= 8 bars.
- Velocities strictly capped at 80.
- Looping: final bar resolves to tonic root pitch class for seamless loop continuation.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Sequence
import numpy as np

from .harmony_v3 import BarHarmonyV3


@dataclass(frozen=True)
class MelodyNoteV3:
    pitch: int
    start_beat: float
    duration_beats: float
    velocity: int
    is_color_tone: bool = False


@dataclass(frozen=True)
class MelodyBarV3:
    bar: int
    notes: list[MelodyNoteV3]
    is_rest: bool
    rest_reason: str | None = None
    has_color_tone: bool = False


def generate_melody_v3(
    blocks: list[dict[str, Any]],
    norm_speeds: list[float],
    harmony_bars: list[BarHarmonyV3],
    preset: dict[str, Any],
    seed: int,
) -> tuple[list[MelodyBarV3], list[int]]:
    """
    Generate 53 bars of melody for engine_v3.
    Returns (melody_bars, color_tone_bars_played).
    """
    scale_pcs = set(preset["scale"])
    color_pc = preset.get("color_tone")
    assert color_pc is not None and color_pc not in scale_pcs

    n_bars = len(blocks)
    valid_cand_notes = [n for n in range(52, 68) if (n % 12) in scale_pcs]
    assert len(valid_cand_notes) > 0

    # Color tone candidates in melodic range
    color_cand_notes = [n for n in range(52, 68) if (n % 12) == color_pc]
    assert len(color_cand_notes) > 0
    chosen_color_note = color_cand_notes[0]

    rng = np.random.RandomState(seed % (2**32))

    color_tone_bars: list[int] = []
    last_color_bar = -999

    # Pre-extract raw values for local breakout detection
    raw_vals = [float(b.get("speed_p95") if b.get("speed_p95") is not None else 0.0) for b in blocks]

    melody_bars: list[MelodyBarV3] = []

    for i in range(n_bars):
        h = harmony_bars[i]
        b = blocks[i]
        ns = norm_speeds[i] if i < len(norm_speeds) else 0.5

        if h.is_rest or (b.get("speed_p95") is None and not b.get("valid")):
            melody_bars.append(MelodyBarV3(bar=i, notes=[], is_rest=True, rest_reason="data_missing"))
            continue

        # Intro bars: sparse / gentle entry
        if h.section == "intro" and i < 2:
            melody_bars.append(MelodyBarV3(bar=i, notes=[], is_rest=True, rest_reason="intro_tacet"))
            continue

        # Check color tone trigger:
        # Event: raw value exceeds all previous 4 bars, cooldown >= 8 bars, and not last bar
        triggered_color = False
        if i >= 4 and i < n_bars - 1 and (i - last_color_bar >= 8):
            prior_max = max(raw_vals[i - 4 : i])
            if raw_vals[i] > prior_max * 1.05 and raw_vals[i] > 0.0:
                triggered_color = True
                last_color_bar = i
                color_tone_bars.append(i)

        # Base notes from chord tones if possible, else scale
        chord_pcs = set([m % 12 for m in h.chord_tones_midi])
        chord_cands = [n for n in valid_cand_notes if (n % 12) in chord_pcs]
        if not chord_cands:
            chord_cands = valid_cand_notes

        # In last bar (52), resolve to tonic root note (e.g. 60) for looping
        if i == n_bars - 1:
            root_cands = [n for n in valid_cand_notes if (n % 12) == 0]
            final_note = root_cands[0] if root_cands else valid_cand_notes[0]
            notes = [MelodyNoteV3(pitch=final_note, start_beat=0.0, duration_beats=3.5, velocity=52, is_color_tone=False)]
            melody_bars.append(MelodyBarV3(bar=i, notes=notes, is_rest=False, has_color_tone=False))
            continue

        notes: list[MelodyNoteV3] = []
        # Dynamic velocity capped at 80
        vel = int(np.clip(round(45 + 30 * ns), 40, 80))

        if triggered_color:
            # Color tone placed prominently on beat 1 or 2
            n1_pitch = int(rng.choice(chord_cands))
            notes.append(MelodyNoteV3(pitch=n1_pitch, start_beat=0.0, duration_beats=1.5, velocity=vel, is_color_tone=False))
            notes.append(MelodyNoteV3(pitch=chosen_color_note, start_beat=2.0, duration_beats=1.5, velocity=min(vel + 5, 80), is_color_tone=True))
            melody_bars.append(MelodyBarV3(bar=i, notes=notes, is_rest=False, has_color_tone=True))
        else:
            # 1 or 2 notes per bar depending on intensity ns
            n1_pitch = int(rng.choice(chord_cands))
            if ns > 0.65:
                # 2 notes
                n2_pitch = int(rng.choice(valid_cand_notes))
                notes.append(MelodyNoteV3(pitch=n1_pitch, start_beat=0.0, duration_beats=1.5, velocity=vel, is_color_tone=False))
                notes.append(MelodyNoteV3(pitch=n2_pitch, start_beat=2.0, duration_beats=1.5, velocity=max(40, vel - 4), is_color_tone=False))
            else:
                # 1 sustained lyrical note
                notes.append(MelodyNoteV3(pitch=n1_pitch, start_beat=1.0, duration_beats=2.5, velocity=vel, is_color_tone=False))
            melody_bars.append(MelodyBarV3(bar=i, notes=notes, is_rest=False, has_color_tone=False))

    return melody_bars, color_tone_bars
