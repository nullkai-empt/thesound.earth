"""Rhythm generator for engine_v2.

Generates regional percussion patterns mapped to General MIDI Channel 10.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence
import numpy as np

# GM Channel 10 drum map
MIDI_BASS_DRUM: int = 36
MIDI_SNARE: int = 38
MIDI_CLOSED_HH: int = 42
MIDI_PEDAL_HH: int = 44
MIDI_LOW_FLOOR_TOM: int = 41
MIDI_HIGH_FLOOR_TOM: int = 43
MIDI_LOW_TOM: int = 45
MIDI_MID_TOM: int = 47
MIDI_HIGH_TOM: int = 50
MIDI_CRASH: int = 49
MIDI_BELL: int = 56
MIDI_HI_BONGO: int = 60
MIDI_LOW_BONGO: int = 61
MIDI_MUTE_CONGA: int = 62
MIDI_OPEN_CONGA: int = 63
MIDI_LOW_CONGA: int = 64
MIDI_MARACAS: int = 70
MIDI_HI_WOODBLOCK: int = 76
MIDI_LOW_WOODBLOCK: int = 77


@dataclass(frozen=True)
class DrumEvent:
    bar: int
    beat: float
    instrument: str
    midi_note: int
    velocity: int
    duration_beats: float


def speed_to_tier(speed: float, low_thresh: float = 0.35, high_thresh: float = 0.70) -> str:
    if speed < low_thresh:
        return "low"
    elif speed < high_thresh:
        return "medium"
    return "high"


def generate_drum_events_v2(
    norm_speeds: Sequence[float | None],
    drum_pattern: str = "standard_maracas_kick",
    seed: int = 42,
) -> list[DrumEvent]:
    """Generate drum events for v2 using specified regional pattern."""
    events: list[DrumEvent] = []
    rng = np.random.RandomState(seed & 0xFFFFFFFF)

    active_tier = "low"
    candidate_tier = None
    candidate_streak = 0

    for bar_idx, speed_val in enumerate(norm_speeds):
        if speed_val is None or not np.isfinite(speed_val):
            # Missing data = rest (silent bar)
            continue

        s = float(np.clip(speed_val, 0.0, 1.0))
        target_tier = speed_to_tier(s)

        # 2-bar hysteresis
        if target_tier != active_tier:
            if candidate_tier == target_tier:
                candidate_streak += 1
            else:
                candidate_tier = target_tier
                candidate_streak = 1
            if candidate_streak >= 2:
                active_tier = candidate_tier
                candidate_tier = None
                candidate_streak = 0
        else:
            candidate_tier = None
            candidate_streak = 0

        # Pattern generation per bar
        if drum_pattern == "taiko_temple_drums":
            # Kuroshio regional pattern: deep floor toms + temple woodblock
            # Beat 1: Heavy low floor tom
            events.append(DrumEvent(bar=bar_idx, beat=1.0, instrument="taiko_low", midi_note=MIDI_LOW_FLOOR_TOM, velocity=int(55 + 25 * s), duration_beats=0.5))
            if active_tier in ("medium", "high"):
                # Beat 2: Temple woodblock click
                events.append(DrumEvent(bar=bar_idx, beat=2.0, instrument="temple_block", midi_note=MIDI_HI_WOODBLOCK, velocity=int(40 + 20 * s), duration_beats=0.25))
            # Beat 3: Resonant high floor tom
            events.append(DrumEvent(bar=bar_idx, beat=3.0, instrument="taiko_mid", midi_note=MIDI_HIGH_FLOOR_TOM, velocity=int(50 + 25 * s), duration_beats=0.5))
            if active_tier == "high":
                # Beat 4: Low woodblock + tom cadence
                events.append(DrumEvent(bar=bar_idx, beat=4.0, instrument="woodblock", midi_note=MIDI_LOW_WOODBLOCK, velocity=int(45 + 20 * s), duration_beats=0.25))
                events.append(DrumEvent(bar=bar_idx, beat=4.5, instrument="taiko_sub", midi_note=MIDI_LOW_TOM, velocity=int(40 + 20 * s), duration_beats=0.25))

        elif drum_pattern == "tabla_inspired_percussion":
            # India regional pattern: conga/bongo bayan & dayan strokes
            # Beat 1: Open Bayan (Low Conga) + soft kick
            events.append(DrumEvent(bar=bar_idx, beat=1.0, instrument="bayan_open", midi_note=MIDI_LOW_CONGA, velocity=int(50 + 25 * s), duration_beats=0.5))
            events.append(DrumEvent(bar=bar_idx, beat=1.0, instrument="kick", midi_note=MIDI_BASS_DRUM, velocity=int(40 + 20 * s), duration_beats=0.5))
            # Beat 2: Dayan slap (Mute Conga / Hi-hat)
            events.append(DrumEvent(bar=bar_idx, beat=2.0, instrument="dayan_slap", midi_note=MIDI_MUTE_CONGA, velocity=int(45 + 20 * s), duration_beats=0.25))
            if active_tier in ("medium", "high"):
                # Beat 3: Open Dayan (Open Conga / Low Bongo)
                events.append(DrumEvent(bar=bar_idx, beat=3.0, instrument="dayan_open", midi_note=MIDI_OPEN_CONGA, velocity=int(50 + 25 * s), duration_beats=0.5))
                events.append(DrumEvent(bar=bar_idx, beat=3.5, instrument="bongo_sub", midi_note=MIDI_LOW_BONGO, velocity=int(40 + 20 * s), duration_beats=0.25))
            if active_tier == "high":
                # Beat 4: Quick teenteen fill (Hi Bongo + Closed hat)
                events.append(DrumEvent(bar=bar_idx, beat=4.0, instrument="hi_bongo", midi_note=MIDI_HI_BONGO, velocity=int(45 + 20 * s), duration_beats=0.25))
                events.append(DrumEvent(bar=bar_idx, beat=4.5, instrument="hi_hat", midi_note=MIDI_CLOSED_HH, velocity=int(38 + 20 * s), duration_beats=0.25))

        else:
            # Default maracas / kick / snare
            for b in [1.0, 2.0, 3.0, 4.0]:
                events.append(DrumEvent(bar=bar_idx, beat=b, instrument="shaker", midi_note=MIDI_MARACAS, velocity=int(35 + 20 * s), duration_beats=0.25))
            if active_tier in ("medium", "high"):
                events.append(DrumEvent(bar=bar_idx, beat=1.0, instrument="kick", midi_note=MIDI_BASS_DRUM, velocity=int(55 + 25 * s), duration_beats=0.5))
                events.append(DrumEvent(bar=bar_idx, beat=3.0, instrument="kick", midi_note=MIDI_BASS_DRUM, velocity=int(50 + 25 * s), duration_beats=0.5))
            if active_tier == "high":
                events.append(DrumEvent(bar=bar_idx, beat=2.0, instrument="snare", midi_note=MIDI_SNARE, velocity=int(50 + 20 * s), duration_beats=0.25))
                events.append(DrumEvent(bar=bar_idx, beat=4.0, instrument="snare", midi_note=MIDI_SNARE, velocity=int(50 + 20 * s), duration_beats=0.25))

    return events
