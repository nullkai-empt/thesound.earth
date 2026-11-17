"""Melody generator for engine_v2.

Generates lead melody notes strictly within the preset's scale semitone list
and MIDI range [52, 67].
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Sequence
import numpy as np

from .harmony import BarHarmony, compute_section_counts, get_section_for_bar

MIN_MIDI: int = 52
MAX_MIDI: int = 67


@dataclass(frozen=True)
class MelodyEvent:
    bar: int
    beat: float
    midi_note: int
    velocity: int
    duration_beats: float
    timing_offset_ms: float = 0.0


def pick_chord_tone(
    chord_pcs: list[int],
    prev_note: int | None = None,
    min_midi: int = MIN_MIDI,
    max_midi: int = MAX_MIDI,
) -> int:
    """Pick a chord tone in [min_midi, max_midi] closest to prev_note."""
    cands = [n for n in range(min_midi, max_midi + 1) if (n % 12) in chord_pcs]
    if not cands:
        raise ValueError("No chord tone candidates in pitch range")
    if prev_note is None:
        # Default to middle of range
        mid = (min_midi + max_midi) // 2
        return min(cands, key=lambda n: abs(n - mid))
    return min(cands, key=lambda n: abs(n - prev_note))


def generate_melody_v2(
    blocks: Sequence[dict[str, Any]],
    harmony_bars: Sequence[BarHarmony],
    norm_speeds: Sequence[float | None],
    preset: dict[str, Any],
    seed: int = 42,
) -> list[MelodyEvent]:
    """Generate melody events strictly using preset scale semitones."""
    total_bars = len(blocks)
    if total_bars == 0:
        return []

    scale_pcs: set[int] = set(preset["scale"])
    section_counts = compute_section_counts(total_bars)
    outro_start = sum(count for name, count in section_counts if name != "outro")

    rng = random.Random(seed)
    events: list[MelodyEvent] = []
    prev_note: int | None = None

    for bar_idx in range(total_bars):
        h = harmony_bars[bar_idx] if bar_idx < len(harmony_bars) else None
        bar_data = blocks[bar_idx]
        sec = get_section_for_bar(bar_idx, section_counts)
        norm_spd = norm_speeds[bar_idx] if bar_idx < len(norm_speeds) else None

        # 1. Intro section: no melody
        if sec == "intro":
            continue

        # 2. Missing data or held bar = rest (silence)
        is_held = h.held if h else False
        is_missing = (
            norm_spd is None
            or not np.isfinite(norm_spd)
            or (h and h.is_rest)
            or bar_data.get("speed_p95") is None
        )
        if is_missing or is_held:
            continue

        is_last_bar = (bar_idx == total_bars - 1)

        # 3. Phrasing by section
        if sec == "outro" and not is_last_bar:
            if (bar_idx - outro_start) % 2 != 0:
                continue

        # Active chord tones (pitch classes)
        active_tones_pcs = [m % 12 for m in h.chord_tones_midi] if h else [preset["scale"][0]]

        if is_last_bar:
            # Tonic resolution to root pitch class
            root_pc = preset["scale"][0]
            cands = [n for n in range(MIN_MIDI, MAX_MIDI + 1) if (n % 12) == root_pc]
            note1 = min(cands, key=lambda n: abs(n - (prev_note or 60)))
            dur = 4.0
            vel = 62
            events.append(MelodyEvent(bar=bar_idx, beat=1.0, midi_note=note1, velocity=vel, duration_beats=dur))
            continue

        # Beat 1 note
        note1 = pick_chord_tone(active_tones_pcs, prev_note=prev_note)
        prev_note = note1
        assert (note1 % 12) in scale_pcs, f"Melody note {note1} not in scale {scale_pcs}"
        assert MIN_MIDI <= note1 <= MAX_MIDI

        dur1 = 2.0
        vel1 = int(np.clip(round(50 + 20 * (norm_spd or 0.5)), 40, 75))
        events.append(MelodyEvent(bar=bar_idx, beat=1.0, midi_note=note1, velocity=vel1, duration_beats=dur1))

        # Beat 3 note if speed > 0.40
        if norm_spd is not None and norm_spd >= 0.40:
            other_pcs = [pc for pc in active_tones_pcs if pc != (note1 % 12)]
            target_pcs = other_pcs if other_pcs else active_tones_pcs
            note3 = pick_chord_tone(target_pcs, prev_note=note1)
            assert (note3 % 12) in scale_pcs, f"Melody note {note3} not in scale {scale_pcs}"
            assert MIN_MIDI <= note3 <= MAX_MIDI

            dur3 = 2.0
            vel3 = int(np.clip(round(vel1 + rng.uniform(-3, 3)), 38, 75))
            events.append(MelodyEvent(bar=bar_idx, beat=3.0, midi_note=note3, velocity=vel3, duration_beats=dur3))
            prev_note = note3

    return events
