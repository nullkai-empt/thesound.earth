"""harmony_v3.py — Modal harmony generator for AetherWaves Engine v3.

Harmonic derivation:
- Ocean: OSCAR surface currents (majority ageostrophic sector, 2-bar hysteresis, hold < 0.013 m/s)
- Land Combined: GEDI gridded canopy height (35 steps, floor(bar*35/53), gap = HOLD, chords from gradient)
- Land Fire Only (Siberia): Weekly fire-centroid shift (derived from cached daily VIIRS CSV detections)
- Looping: Final bar (52) returns to opening chord for seamless loop continuity
- Scale membership: Every sounding chord tone and bass root strictly belongs to preset["scale"]
- Texture layer: Sustained quiet pad/seashore following harmony, silent on rest
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal, Sequence
import numpy as np

SectionName = Literal["intro", "build", "peak", "decline", "calm"]

PITCH_CLASS_NAMES = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]

# Preset role chords: (chord_name, numeral, pitch_classes, bass_midi_note)
# All pitch classes and roots strictly belong to each preset's scale.
# Numerals are strictly relative to tonic root C.
PRESET_CHORD_DEFINITIONS: dict[str, dict[str, tuple[str, str, list[int], int]]] = {
    # Natural Minor (gulf_stream, drake_acc, australia) [0, 2, 3, 5, 7, 8, 10]
    "natural_minor": {
        "i": ("Cm", "i", [0, 3, 7, 10], 48),
        "VI": ("Ab", "bVI", [8, 0, 3], 44),
        "iv": ("Fm", "iv", [5, 8, 0], 41),
        "VII": ("Bb", "bVII", [10, 2, 5], 46),
        "III": ("Eb", "bIII", [3, 7, 10], 39),
        "IV_calm": ("Fm", "iv", [5, 8, 0], 41),
    },
    # Dorian (east_australian, nordic_seas, india) [0, 2, 3, 5, 7, 9, 10]
    "dorian": {
        "i": ("Cm", "i", [0, 3, 7, 10], 48),
        "VI": ("Bb", "bVII", [10, 2, 5], 46),
        "iv": ("Gm", "v", [7, 10, 2], 43),
        "VII": ("F", "iv", [5, 9, 0], 41),
        "III": ("Eb", "bIII", [3, 7, 10], 39),
        "IV_calm": ("F", "iv", [5, 9, 0], 41),
    },
    # Insen (kuroshio) [0, 1, 5, 7, 10]
    "kuroshio": {
        "i": ("Csus7", "i", [0, 5, 7, 10], 48),
        "VI": ("Bbsus2", "bVII", [10, 0, 5], 46),
        "iv": ("Gsus4", "v", [7, 0, 5, 10], 43),
        "VII": ("Fsus4", "iv", [5, 10, 0], 41),
        "III": ("Db_add6", "bII", [1, 5, 10], 37),
        "IV_calm": ("Fsus4", "iv", [5, 10, 0], 41),
    },
    # Harmonic Minor (brazil_malvinas) [0, 2, 3, 5, 7, 8, 11]
    "harmonic_minor": {
        "i": ("Cm_maj7", "i", [0, 3, 7, 11], 48),
        "VI": ("Ab", "bVI", [8, 0, 3], 44),
        "iv": ("Fm", "iv", [5, 8, 0], 41),
        "VII": ("G", "V", [7, 11, 2], 43),
        "III": ("Bdim", "vii_dim", [11, 2, 5], 47),
        "IV_calm": ("Fm", "iv", [5, 8, 0], 41),
    },
    # Phrygian Dominant (arabian_sea, europe) [0, 1, 4, 5, 7, 8, 10]
    "phrygian_dominant": {
        "i": ("C7", "I", [0, 4, 7, 10], 48),
        "VI": ("Bbm", "bVII", [10, 1, 5], 46),
        "iv": ("Fm", "iv", [5, 8, 0], 41),
        "VII": ("Db", "bII", [1, 5, 8], 37),
        "III": ("Gdim", "v", [7, 10, 1], 43),
        "IV_calm": ("Fm", "iv", [5, 8, 0], 41),
    },
    # Minor Pentatonic (amazon) [0, 3, 5, 7, 10]
    "minor_pentatonic": {
        "i": ("Cm7", "i", [0, 3, 7, 10], 48),
        "VI": ("Bbsus2", "bVII", [10, 0, 5], 46),
        "iv": ("Gsus4", "v", [7, 0, 10], 43),
        "VII": ("Fsus4", "iv", [5, 10, 0], 41),
        "III": ("Eb_add9", "bIII", [3, 5, 10], 39),
        "IV_calm": ("Fsus4", "iv", [5, 10, 0], 41),
    },
    # Major Pentatonic (congo) [0, 2, 4, 7, 9]
    "major_pentatonic": {
        "i": ("C_add9", "I", [0, 4, 7, 2], 48),
        "VI": ("Am", "vi", [9, 0, 4], 45),
        "iv": ("Gsus4", "V", [7, 0, 2], 43),
        "VII": ("Csus2", "I", [0, 2, 7], 48),
        "III": ("Em7_no5", "iii", [4, 7, 2], 40),
        "IV_calm": ("Am", "vi", [9, 0, 4], 45),
    },
    # Pelog Approximation (se_asia) [0, 1, 3, 7, 8]
    "pelog": {
        "i": ("C_pelog", "i", [0, 1, 3, 7], 48),
        "VI": ("Ab_sus", "bVI", [8, 0, 1], 44),
        "iv": ("Gsus_b9", "v", [7, 8, 1], 43),
        "VII": ("Db_no5", "bII", [1, 7, 8], 37),
        "III": ("Eb_sus", "bIII", [3, 7, 8], 39),
        "IV_calm": ("Ab_sus", "bVI", [8, 0, 1], 44),
    },
    # Mixolydian (w_north_america) [0, 2, 4, 5, 7, 9, 10]
    "mixolydian": {
        "i": ("C7", "I", [0, 4, 7, 10], 48),
        "VI": ("Bb", "bVII", [10, 2, 5], 46),
        "iv": ("Gm", "v", [7, 10, 2], 43),
        "VII": ("F", "IV", [5, 9, 0], 41),
        "III": ("Dm", "ii", [2, 5, 9], 38),
        "IV_calm": ("F", "IV", [5, 9, 0], 41),
    },
    # Suspended Pentatonic (siberia) [0, 2, 5, 7, 10]
    "siberia": {
        "i": ("Csus2", "i", [0, 2, 7, 10], 48),
        "VI": ("Bbsus2", "bVII", [10, 0, 5], 46),
        "iv": ("Gsus4", "v", [7, 0, 2, 10], 43),
        "VII": ("Fsus2", "iv", [5, 7, 0, 10], 41),
        "III": ("Dsus4", "ii", [2, 7, 0], 38),
        "IV_calm": ("Fsus2", "iv", [5, 7, 0], 41),
    },
    # Direct mappings for track IDs
    "india": {
        "i": ("Cm", "i", [0, 3, 7, 10], 48),
        "VI": ("Bb", "bVII", [10, 2, 5], 46),
        "iv": ("Gm", "v", [7, 10, 2], 43),
        "VII": ("F", "iv", [5, 9, 0], 41),
        "III": ("Eb", "bIII", [3, 7, 10], 39),
        "IV_calm": ("F", "iv", [5, 9, 0], 41),
    },
    "europe": {
        "i": ("C7", "I", [0, 4, 7, 10], 48),
        "VI": ("Bbm", "bVII", [10, 1, 5], 46),
        "iv": ("Fm", "iv", [5, 8, 0], 41),
        "VII": ("Db", "bII", [1, 5, 8], 37),
        "III": ("Gdim", "v", [7, 10, 1], 43),
        "IV_calm": ("Fm", "iv", [5, 8, 0], 41),
    },
    "default_minor": {
        "i": ("Cm", "i", [0, 3, 7, 10], 48),
        "VI": ("Ab", "bVI", [8, 0, 3], 44),
        "iv": ("Fm", "iv", [5, 8, 0], 41),
        "VII": ("Bb", "bVII", [10, 2, 5], 46),
        "III": ("Eb", "bIII", [3, 7, 10], 39),
        "IV_calm": ("Fm", "iv", [5, 8, 0], 41),
    },
}

TRACK_TO_CHORD_SET = {
    "gulf_stream": "natural_minor",
    "kuroshio": "kuroshio",
    "east_australian": "dorian",
    "brazil_malvinas": "harmonic_minor",
    "arabian_sea": "phrygian_dominant",
    "drake_acc": "natural_minor",
    "nordic_seas": "dorian",
    "amazon": "minor_pentatonic",
    "congo": "major_pentatonic",
    "se_asia": "pelog",
    "australia": "natural_minor",
    "w_north_america": "mixolydian",
    "siberia": "siberia",
    "india": "dorian",
    "europe": "phrygian_dominant",
}


@dataclass(frozen=True)
class BarHarmonyV3:
    """Harmonic and bass content for a single measure in v3."""
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
    pad_octave_shift: int
    raw_magnitude: float | None = None
    raw_angle: float | None = None


def get_sector_v3(angle_deg: float) -> str:
    norm_ang = ((angle_deg + 180.0) % 360.0) - 180.0
    if -45.0 <= norm_ang <= 45.0:
        return "East"
    elif 45.0 < norm_ang < 135.0:
        return "North"
    elif -135.0 < norm_ang < -45.0:
        return "South"
    else:
        return "West"


def sector_to_role(sector: str, is_calm: bool = False) -> str:
    if is_calm:
        if sector == "East":
            return "i"
        elif sector == "North":
            return "III"
        elif sector == "West":
            return "IV_calm"
        else:
            return "VI"
    else:
        if sector == "East":
            return "i"
        elif sector == "North":
            return "VI"
        elif sector == "West":
            return "iv"
        else:
            return "VII"


def build_pad_voicings_v3(
    chord_tones_pcs: list[int],
    scale_pcs: set[int],
    octave_shift: int = 1,
) -> list[int]:
    """
    Generate 4-note chord voicing strictly using chord_tones_pcs.
    Base range: [48 + 12*shift, 67 + 12*shift].
    All sounding notes assertedly belong to scale_pcs.
    """
    min_m = 48 + 12 * octave_shift
    max_m = 67 + 12 * octave_shift
    cand_notes = [n for n in range(min_m, max_m + 1) if (n % 12) in chord_tones_pcs]
    assert all((n % 12) in scale_pcs for n in cand_notes)

    # Group candidate notes by pitch class
    notes_by_pc: dict[int, list[int]] = {pc: [] for pc in chord_tones_pcs}
    for n in cand_notes:
        notes_by_pc[n % 12].append(n)

    # Pick 4 notes covering all pitch classes if possible
    selected: list[int] = []
    for pc in chord_tones_pcs:
        if notes_by_pc[pc]:
            selected.append(notes_by_pc[pc][0])

    # If < 4 notes, duplicate lower octave or 5th
    while len(selected) < 4:
        for n in cand_notes:
            if n not in selected:
                selected.append(n)
                break
        else:
            break

    selected = sorted(selected)[:4]
    assert all((n % 12) in scale_pcs for n in selected)
    return selected


def generate_harmony_v3(
    blocks: list[dict[str, Any]],
    preset: dict[str, Any],
    track_id: str,
    form_info: dict[str, Any],
    canopy_rows: list[dict[str, Any]] | None = None,
    fire_centroids: list[tuple[float | None, float | None, int]] | None = None,
    hold_threshold: float = 0.013,
) -> list[BarHarmonyV3]:
    """
    Generate 53 bars of harmony for engine_v3.
    """
    scale_pcs = set(preset["scale"])
    domain = preset.get("domain", "ocean")

    # Select chord definitions
    set_key = TRACK_TO_CHORD_SET.get(track_id, track_id)
    chord_defs = PRESET_CHORD_DEFINITIONS.get(set_key, PRESET_CHORD_DEFINITIONS.get("default_minor", {}))
    # Validate chord definitions against scale_pcs
    for r_name, (c_name, num, pcs, bass) in chord_defs.items():
        assert all(p in scale_pcs for p in pcs), f"Chord {c_name} pcs {pcs} not in scale {scale_pcs}"
        assert (bass % 12) in scale_pcs, f"Chord {c_name} bass {bass} not in scale {scale_pcs}"

    bar_to_section = form_info["bar_to_section"]
    n_bars = len(blocks)
    result: list[BarHarmonyV3] = []

    # State tracking
    last_active_role = "i"
    pending_role = "i"
    pending_count = 0

    for bar_idx in range(n_bars):
        block = blocks[bar_idx]
        section = bar_to_section[bar_idx]
        is_calm = (section in ("calm", "intro"))
        date_str = block.get("date", f"Bar-{bar_idx}")

        # Looping condition: in bar 52 (last bar), return to opening chord "i"
        if bar_idx == n_bars - 1:
            target_role = "i"
            held = False
            raw_mag = 1.0
            raw_ang = 0.0
            octave_shift = 1
        elif domain == "land_combined":
            # Land Combined: Canopy transect
            # step = floor(bar * 35 / 53)
            step_idx = math.floor(bar_idx * 35 / 53)
            c_row = canopy_rows[step_idx] if (canopy_rows and step_idx < len(canopy_rows)) else None

            # Pad register from canopy height
            h = c_row.get("speed_p95") if c_row else None
            if h is None or h <= 0.0:
                octave_shift = 1
            elif h < 6.0:
                octave_shift = 0  # lower register
            elif h < 11.0:
                octave_shift = 1  # mid register
            else:
                octave_shift = 2  # high canopy register

            # Canopy gap = HOLD previous chord
            if c_row is None or not c_row.get("valid") or c_row.get("speed_p95") is None:
                target_role = last_active_role
                held = True
                raw_mag = None
                raw_ang = None
            else:
                ang = c_row.get("ageo_angle_deg")
                mag = c_row.get("magnitude")
                raw_mag = mag
                raw_ang = ang

                if ang is None or mag is None or mag < hold_threshold:
                    target_role = last_active_role
                    held = True
                else:
                    sec_name = get_sector_v3(ang)
                    target_role = sector_to_role(sec_name, is_calm=is_calm)
                    held = False

        elif domain == "land_fire_only":
            # Siberia: fire-centroid shift
            octave_shift = 1
            if fire_centroids is None or bar_idx >= len(fire_centroids) or fire_centroids[bar_idx][0] is None:
                target_role = last_active_role
                held = True
                raw_mag = None
                raw_ang = None
            else:
                c_lat, c_lon, _ = fire_centroids[bar_idx]
                # Shift relative to previous centroid
                prev_lat, prev_lon = None, None
                for p_idx in range(bar_idx - 1, -1, -1):
                    if fire_centroids[p_idx][0] is not None:
                        prev_lat, prev_lon = fire_centroids[p_idx][0], fire_centroids[p_idx][1]
                        break

                if prev_lat is None or prev_lon is None:
                    target_role = "i"
                    held = False
                    raw_mag = 1.0
                    raw_ang = 0.0
                else:
                    d_lat = c_lat - prev_lat
                    d_lon = (c_lon - prev_lon) * math.cos(math.radians(c_lat))
                    mag = math.hypot(d_lat, d_lon)
                    raw_mag = mag
                    if mag < hold_threshold:
                        target_role = last_active_role
                        held = True
                        raw_ang = None
                    else:
                        ang = math.degrees(math.atan2(d_lat, d_lon))
                        raw_ang = ang
                        sec_name = get_sector_v3(ang)
                        target_role = sector_to_role(sec_name, is_calm=is_calm)
                        held = False

        else:
            # Ocean (Kuroshio)
            octave_shift = 1
            mag = block.get("magnitude")
            ang = block.get("ageo_angle_deg")
            raw_mag = mag
            raw_ang = ang

            if mag is None or ang is None or mag < hold_threshold:
                target_role = last_active_role
                held = True
            else:
                sec_name = get_sector_v3(ang)
                target_role = sector_to_role(sec_name, is_calm=is_calm)
                held = False

        # Apply 2-bar hysteresis for active changes
        if target_role == pending_role:
            pending_count += 1
        else:
            pending_role = target_role
            pending_count = 1

        if pending_count >= 2 and not held:
            effective_role = pending_role
            last_active_role = pending_role
        else:
            effective_role = last_active_role

        # If last bar, force loop resolution to 'i'
        if bar_idx == n_bars - 1:
            effective_role = "i"

        chord_name, numeral, pcs, bass_m = chord_defs[effective_role]
        voicing_midi = build_pad_voicings_v3(pcs, scale_pcs, octave_shift=octave_shift)
        chord_tone_names = [PITCH_CLASS_NAMES[p] for p in pcs]

        # Bass velocity capped at 80
        bass_vel = min(68, 80) if not held else min(55, 80)

        # Check if block is complete rest (e.g. invalid speed_p95)
        is_rest = (block.get("speed_p95") is None and block.get("valid") is False)

        result.append(
            BarHarmonyV3(
                bar=bar_idx,
                date=date_str,
                section=section,
                chord=chord_name,
                chord_numeral=numeral,
                chord_tones=chord_tone_names,
                chord_tones_midi=voicing_midi,
                bass_note=bass_m,
                bass_velocity=bass_vel,
                bass_duration=3.6,
                held=held,
                is_rest=is_rest,
                target_chord=chord_name,
                pad_octave_shift=octave_shift,
                raw_magnitude=raw_mag,
                raw_angle=raw_ang,
            )
        )

    return result
