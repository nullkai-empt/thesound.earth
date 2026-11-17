"""Harmony generator for engine_v2.

Maps block ageostrophic vector angles and intensity to modal harmony
where every sounding chord tone and bass root strictly belongs to the
preset's scale semitone list.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal, Sequence
import numpy as np

SectionName = Literal["intro", "build", "peak", "calm", "outro"]

PITCH_CLASS_NAMES = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]

# Preset role chords definitions:
# For each preset scale, define role chords: "i", "VI", "iv", "VII", "III", "IV_calm".
# All chord pitch classes and roots MUST be in the scale.
PRESET_CHORD_DEFINITIONS: dict[str, dict[str, tuple[str, str, list[int], int]]] = {
    # Kuroshio: Insen Pentatonic [0, 1, 5, 7, 10]
    "kuroshio": {
        "i": ("Csus7", "i", [0, 5, 7, 10], 48),
        "VI": ("Bbsus2", "VI", [10, 0, 5], 46),
        "iv": ("Gsus4", "iv", [7, 0, 5, 10], 43),
        "VII": ("Fsus4", "VII", [5, 10, 0], 41),
        "III": ("Db_add6", "III", [1, 5, 10], 37),
        "IV_calm": ("Fsus4", "IV", [5, 10, 0], 41),
    },
    # India: Kafi Thaat / Dorian [0, 2, 3, 5, 7, 9, 10]
    "india": {
        "i": ("Cm", "i", [0, 3, 7, 10], 48),
        "VI": ("Bb", "VI", [10, 2, 5], 46),
        "iv": ("Gm", "iv", [7, 10, 2], 43),
        "VII": ("F", "VII", [5, 9, 0], 41),
        "III": ("Eb", "III", [3, 7, 10], 39),
        "IV_calm": ("F", "IV", [5, 9, 0], 41),
    },
}


@dataclass(frozen=True)
class BarHarmony:
    """Harmonic and bass content for a single measure in v2."""
    bar: int
    date: str
    section: SectionName
    chord: str
    chord_numeral: str
    chord_tones: list[str]
    chord_tones_midi: list[int]
    bass_note: int
    bass_velocity: int
    bass_duration: float
    held: bool
    is_rest: bool
    target_chord: str
    raw_magnitude: float | None = None
    raw_angle: float | None = None


def compute_section_counts(total_bars: int) -> list[tuple[SectionName, int]]:
    sections: list[tuple[SectionName, float]] = [
        ("intro", 0.10),
        ("build", 0.20),
        ("peak", 0.35),
        ("calm", 0.20),
        ("outro", 0.15),
    ]
    if total_bars <= 0:
        return [(s, 0) for s, _ in sections]
    if total_bars < 5:
        res: list[tuple[SectionName, int]] = []
        rem = total_bars
        for s, _ in sections:
            take = 1 if rem > 0 else 0
            res.append((s, take))
            rem -= take
        return res

    exact = [total_bars * p for _, p in sections]
    counts = [max(1, int(math.floor(e))) for e in exact]
    remainder = total_bars - sum(counts)
    if remainder > 0:
        fractional = [(exact[i] - math.floor(exact[i]), i) for i in range(len(sections))]
        fractional.sort(key=lambda x: x[0], reverse=True)
        for _, idx in fractional[:remainder]:
            counts[idx] += 1
    elif remainder < 0:
        for _ in range(abs(remainder)):
            max_idx = int(np.argmax(counts))
            if counts[max_idx] > 1:
                counts[max_idx] -= 1
    return [(sections[i][0], counts[i]) for i in range(len(sections))]


def get_section_for_bar(bar_idx: int, section_counts: list[tuple[SectionName, int]]) -> SectionName:
    curr = 0
    for name, cnt in section_counts:
        if curr <= bar_idx < curr + cnt:
            return name
        curr += cnt
    return section_counts[-1][0] if section_counts else "outro"


def sector_to_role(angle_deg: float, is_calm: bool = False) -> str:
    norm_ang = ((angle_deg + 180.0) % 360.0) - 180.0
    if -45.0 <= norm_ang <= 45.0:
        return "i"
    elif 45.0 < norm_ang < 135.0:
        return "IV_calm" if is_calm else "VI"
    elif -135.0 < norm_ang < -45.0:
        return "VII"
    else:
        return "i" if is_calm else "iv"


def get_preset_role_chord(
    preset_id: str,
    role: str,
    scale_pcs: list[int],
) -> tuple[str, str, list[int], int]:
    """Retrieve or derive role chord strictly within scale_pcs."""
    if preset_id in PRESET_CHORD_DEFINITIONS:
        defs = PRESET_CHORD_DEFINITIONS[preset_id]
        if role in defs:
            return defs[role]

    # Fallback generic generator for any scale
    scale_set = set(scale_pcs)
    root_pc = scale_pcs[0]
    if role == "VI" and len(scale_pcs) > 4:
        root_pc = scale_pcs[-1]
    elif role == "iv" and len(scale_pcs) > 3:
        root_pc = scale_pcs[len(scale_pcs) // 2]
    elif role == "VII" and len(scale_pcs) > 2:
        root_pc = scale_pcs[len(scale_pcs) // 2 - 1]
    elif role == "III" and len(scale_pcs) > 1:
        root_pc = scale_pcs[1]

    # Chord tones: select 3 or 4 tones in scale_set
    chord_pcs = [root_pc]
    for s in scale_pcs:
        if s != root_pc and len(chord_pcs) < 4:
            chord_pcs.append(s)

    # Bass root folded into [36, 50]
    root_midi = 36 + root_pc
    if root_midi < 36:
        root_midi += 12
    if root_midi > 50:
        root_midi -= 12

    name = f"{PITCH_CLASS_NAMES[root_pc]}_mod"
    return (name, role, chord_pcs, root_midi)


def generate_harmony_v2(
    blocks: Sequence[dict[str, Any]],
    norm_speeds: Sequence[float | None],
    preset: dict[str, Any],
    preset_id: str,
    hold_threshold: float = 0.013,
    hysteresis: int = 2,
) -> list[BarHarmony]:
    """Generate harmony bars strictly using the preset's scale semitones."""
    total_bars = len(blocks)
    if total_bars == 0:
        return []

    scale_pcs: list[int] = preset["scale"]
    scale_set = set(scale_pcs)
    section_counts = compute_section_counts(total_bars)

    # Default tonic chord
    tonic_name, tonic_num, tonic_pcs, tonic_root_midi = get_preset_role_chord(
        preset_id, "i", scale_pcs
    )

    active_chord = tonic_name
    active_numeral = tonic_num
    active_tones_pcs = tonic_pcs
    active_root_midi = tonic_root_midi

    candidate_role: str | None = None
    candidate_streak: int = 0
    harmony_bars: list[BarHarmony] = []

    for bar_idx in range(total_bars):
        block = blocks[bar_idx]
        sec = get_section_for_bar(bar_idx, section_counts)
        norm_spd = norm_speeds[bar_idx] if bar_idx < len(norm_speeds) else None

        mag = block.get("magnitude")
        ang = block.get("ageo_angle_deg")
        sp95 = block.get("speed_p95")

        is_missing = (
            sp95 is None
            or norm_spd is None
            or not np.isfinite(norm_spd)
            or mag is None
            or not np.isfinite(mag)
        )

        is_last_bar = (bar_idx == total_bars - 1)
        is_held = False

        if is_missing:
            is_held = True
            target_role = "i"
        elif mag is not None and mag < hold_threshold:
            is_held = True
            target_role = "i"
        else:
            if sec == "peak" and norm_spd is not None and norm_spd >= 0.85:
                target_role = "III"
            else:
                target_role = sector_to_role(float(ang) if ang is not None else 0.0, is_calm=(sec == "calm"))

        # Resolve last bar to tonic
        if is_last_bar:
            target_role = "i"

        tgt_name, tgt_num, tgt_pcs, tgt_root_midi = get_preset_role_chord(
            preset_id, target_role, scale_pcs
        )

        # 2-bar hysteresis rule
        if not is_held and not is_missing:
            if tgt_name != active_chord:
                if candidate_role == target_role:
                    candidate_streak += 1
                else:
                    candidate_role = target_role
                    candidate_streak = 1

                if candidate_streak >= hysteresis or is_last_bar:
                    active_chord = tgt_name
                    active_numeral = tgt_num
                    active_tones_pcs = tgt_pcs
                    active_root_midi = tgt_root_midi
                    candidate_role = None
                    candidate_streak = 0
            else:
                candidate_role = None
                candidate_streak = 0

        # Validate that active_tones_pcs and root are strictly in scale_set
        for pc in active_tones_pcs:
            assert pc in scale_set, f"Pitch class {pc} not in preset scale {scale_pcs}"
        assert (active_root_midi % 12) in scale_set, f"Bass root {active_root_midi} not in scale {scale_pcs}"

        tone_names = [PITCH_CLASS_NAMES[pc] for pc in active_tones_pcs]
        # Generate tone midis in octave 4/5 strictly in scale
        tone_midis = [60 + pc for pc in active_tones_pcs]

        harmony_bars.append(
            BarHarmony(
                bar=bar_idx,
                date=str(block.get("date", "")),
                section=sec,
                chord=active_chord,
                chord_numeral=active_numeral,
                chord_tones=tone_names,
                chord_tones_midi=tone_midis,
                bass_note=active_root_midi,
                bass_velocity=60 if not is_missing else 0,
                bass_duration=4.0,
                held=is_held,
                is_rest=is_missing,
                target_chord=tgt_name,
                raw_magnitude=mag,
                raw_angle=ang,
            )
        )

    return harmony_bars
