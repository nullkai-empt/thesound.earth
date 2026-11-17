from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Sequence
import numpy as np

# Scale Pitch Classes (modulo 12: D=2, E=4, F=5, G=7, A=9, Bb=10, B=11, C=0)
D_NATURAL_MINOR = {2, 4, 5, 7, 9, 10, 0}
D_DORIAN = {2, 4, 5, 7, 9, 11, 0}

# Tonic names for key offset k in 0..6 semitones above D
TONIC_NAMES: dict[int, str] = {
    0: "Dm",
    1: "Ebm",
    2: "Em",
    3: "Fm",
    4: "F#m",
    5: "Gm",
    6: "Abm",
}

# Role chord table for key offsets k in 0..6:
# role -> (chord_name, numeral, chord_tones, root_midi)
# Bass roots are strictly folded into [36, 50].
ROLE_CHORD_TABLE: dict[int, dict[str, tuple[str, str, list[str], int]]] = {
    0: {
        "i": ("Dm", "i", ["D", "F", "A"], 38),
        "VI": ("Bb", "VI", ["Bb", "D", "F"], 46),
        "iv": ("Gm", "iv", ["G", "Bb", "D"], 43),
        "VII": ("C", "VII", ["C", "E", "G"], 48),
        "III": ("F", "III", ["F", "A", "C"], 41),
        "IV_calm": ("G", "IV", ["G", "B", "D"], 43),
    },
    1: {
        "i": ("Ebm", "i", ["Eb", "Gb", "Bb"], 39),
        "VI": ("B", "VI", ["B", "D#", "F#"], 47),
        "iv": ("Abm", "iv", ["Ab", "B", "Eb"], 44),
        "VII": ("Db", "VII", ["Db", "F", "Ab"], 49),
        "III": ("Gb", "III", ["Gb", "Bb", "Db"], 42),
        "IV_calm": ("Ab", "IV", ["Ab", "C", "Eb"], 44),
    },
    2: {
        "i": ("Em", "i", ["E", "G", "B"], 40),
        "VI": ("C", "VI", ["C", "E", "G"], 48),
        "iv": ("Am", "iv", ["A", "C", "E"], 45),
        "VII": ("D", "VII", ["D", "F#", "A"], 50),
        "III": ("G", "III", ["G", "B", "D"], 43),
        "IV_calm": ("A", "IV", ["A", "C#", "E"], 45),
    },
    3: {
        "i": ("Fm", "i", ["F", "Ab", "C"], 41),
        "VI": ("Db", "VI", ["Db", "F", "Ab"], 49),
        "iv": ("Bbm", "iv", ["Bb", "Db", "F"], 46),
        "VII": ("Eb", "VII", ["Eb", "G", "Bb"], 39),
        "III": ("Ab", "III", ["Ab", "C", "Eb"], 44),
        "IV_calm": ("Bb", "IV", ["Bb", "D", "F"], 46),
    },
    4: {
        "i": ("F#m", "i", ["F#", "A", "C#"], 42),
        "VI": ("D", "VI", ["D", "F#", "A"], 50),
        "iv": ("Bm", "iv", ["Bm", "D", "F#"], 47),
        "VII": ("E", "VII", ["E", "G#", "B"], 40),
        "III": ("A", "III", ["A", "C#", "E"], 45),
        "IV_calm": ("B", "IV", ["B", "D#", "F#"], 47),
    },
    5: {
        "i": ("Gm", "i", ["G", "Bb", "D"], 43),
        "VI": ("Eb", "VI", ["Eb", "G", "Bb"], 39),
        "iv": ("Cm", "iv", ["C", "Eb", "G"], 48),
        "VII": ("F", "VII", ["F", "A", "C"], 41),
        "III": ("Bb", "III", ["Bb", "D", "F"], 46),
        "IV_calm": ("C", "IV", ["C", "E", "G"], 48),
    },
    6: {
        "i": ("Abm", "i", ["Ab", "B", "Eb"], 44),
        "VI": ("E", "VI", ["E", "G#", "B"], 40),
        "iv": ("C#m", "iv", ["C#", "E", "G#"], 49),
        "VII": ("F#", "VII", ["F#", "A#", "C#"], 42),
        "III": ("B", "III", ["B", "D#", "F#"], 47),
        "IV_calm": ("Db", "IV", ["Db", "F", "Ab"], 49),
    },
}

# Default precomputed bounds from data/raw_oscar
DEFAULT_YEAR_LO: float = 1.1160188001859604
DEFAULT_YEAR_HI: float = 1.2250567084534888
DEFAULT_MONTH_LO: float = 1.0125492314545803
DEFAULT_MONTH_HI: float = 1.3735936746813292


def compute_data_bounds(raw_dir: Path | str | None = None) -> tuple[float, float, float, float]:
    """
    Compute lo/hi speed_p95 bounds over:
    - Full years in data/raw_oscar (2021-2025)
    - All calendar months available in data/raw_oscar (including Jan 2026).
    Returns (year_lo, year_hi, month_lo, month_hi).
    """
    if raw_dir is None:
        raw_dir = Path("data/raw_oscar")
    else:
        raw_dir = Path(raw_dir)

    year_lo = DEFAULT_YEAR_LO
    year_hi = DEFAULT_YEAR_HI
    month_lo = DEFAULT_MONTH_LO
    month_hi = DEFAULT_MONTH_HI

    if raw_dir.exists():
        import json
        # Year tracks: full years 2021-2025
        year_files = sorted(raw_dir.glob("oscar_202[1-5]_daily.json"))
        year_means: list[float] = []
        for yf in year_files:
            try:
                with open(yf, "r", encoding="utf-8") as f:
                    data = json.load(f)
                speeds = [d["speed_p95"] for d in data if d.get("speed_p95") is not None]
                if speeds:
                    year_means.append(sum(speeds) / len(speeds))
            except Exception:
                pass
        if len(year_means) >= 2:
            year_lo = min(year_means)
            year_hi = max(year_means)

        # Month tracks: all calendar months available
        all_files = sorted(raw_dir.glob("oscar_*_daily.json"))
        month_groups: dict[str, list[float]] = {}
        for mf in all_files:
            try:
                with open(mf, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for d in data:
                    dt = d.get("date", "")
                    sp = d.get("speed_p95")
                    if dt and sp is not None:
                        mo = dt[:7]
                        month_groups.setdefault(mo, []).append(float(sp))
            except Exception:
                pass
        month_means = [sum(v) / len(v) for v in month_groups.values() if v]
        if len(month_means) >= 2:
            month_lo = min(month_means)
            month_hi = max(month_means)

    return year_lo, year_hi, month_lo, month_hi


def compute_key_offset(
    period_mean_speed: float,
    is_month: bool = False,
    bounds: tuple[float, float, float, float] | None = None,
) -> int:
    """
    Compute offset k in 0..6 semitones above D:
    k = round(6 * (period_mean_speed_p95 - lo) / (hi - lo)).
    Clamped to 0..6.
    """
    if bounds is None:
        bounds = compute_data_bounds()
    year_lo, year_hi, month_lo, month_hi = bounds
    lo, hi = (month_lo, month_hi) if is_month else (year_lo, year_hi)
    if hi <= lo:
        return 0
    raw_k = 6.0 * (period_mean_speed - lo) / (hi - lo)
    k = int(round(raw_k))
    return max(0, min(6, k))


def seed_from_period(period_label: str) -> int:
    """Deterministic integer seed from sha256 of the period label."""
    import hashlib
    return int(hashlib.sha256(period_label.encode("utf-8")).hexdigest(), 16)


def get_tonic_name(k: int) -> str:
    """Return tonic chord name for offset k (0..6 semitones above D)."""
    return TONIC_NAMES.get(k, f"k={k}")

# Cello bass range & dynamics constants (MIDI 36-50)
CELLO_BASS_MIN_MIDI: int = 36
CELLO_BASS_MAX_MIDI: int = 50
CELLO_VELOCITY_SCALE: float = 0.75  # Lower cello bass velocity by 25%

# Standard Chord Palettes
CHORD_INFO: dict[str, dict[str, Any]] = {
    "Dm": {
        "numeral": "i",
        "tones": ["D", "F", "A"],
        "tones_midi": [62, 65, 69],
        "root_midi": 38,  # D2
    },
    "Bb": {
        "numeral": "VI",
        "tones": ["Bb", "D", "F"],
        "tones_midi": [58, 62, 65],
        "root_midi": 46,  # Bb2
    },
    "Gm": {
        "numeral": "iv",
        "tones": ["G", "Bb", "D"],
        "tones_midi": [55, 58, 62],
        "root_midi": 43,  # G2
    },
    "C": {
        "numeral": "VII",
        "tones": ["C", "E", "G"],
        "tones_midi": [60, 64, 67],
        "root_midi": 48,  # C3 (or 36 C2; 48 keeps inside 36-50)
    },
    "F": {
        "numeral": "III",
        "tones": ["F", "A", "C"],
        "tones_midi": [65, 69, 72],
        "root_midi": 41,  # F2
    },
    "G": {
        "numeral": "IV",
        "tones": ["G", "B", "D"],
        "tones_midi": [55, 59, 62],
        "root_midi": 43,  # G2
    },
}

SectionName = Literal["intro", "build", "peak", "calm", "outro"]


@dataclass(frozen=True)
class BassEvent:
    """A bass note event in a measure."""
    bar: int
    beat: float
    midi_note: int
    velocity: int
    duration_beats: float
    is_approach: bool = False


@dataclass(frozen=True)
class BarHarmony:
    """Harmonic and bass content for a single measure."""
    bar: int
    date: str
    section: SectionName
    chord: str
    chord_numeral: str
    chord_tones: list[str]
    chord_tones_midi: list[int]
    bass_events: list[BassEvent] = field(default_factory=list)
    is_rest: bool = False
    held: bool = False
    ageo_magnitude: float | None = None
    ageo_angle_deg: float | None = None


def compute_section_counts(total_bars: int) -> list[tuple[SectionName, int]]:
    """
    Split total_bars into 5 sections by exact proportions:
    Intro 10%, Build 20%, Peak 35%, Calm 20%, Outro 15%.
    
    Uses largest remainder method so rounded counts sum exactly to total_bars.
    """
    sections: list[tuple[SectionName, float]] = [
        ("intro", 0.10),
        ("build", 0.20),
        ("peak", 0.35),
        ("calm", 0.20),
        ("outro", 0.15),
    ]

    if total_bars <= 0:
        return [(s, 0) for s, _ in sections]

    # Handle short sequences (< 5 bars)
    if total_bars < 5:
        res: list[tuple[SectionName, int]] = []
        rem = total_bars
        for s, _ in sections:
            take = 1 if rem > 0 else 0
            res.append((s, take))
            rem -= take
        return res

    exact = [total_bars * p for _, p in sections]
    counts = [int(math.floor(e)) for e in exact]
    # Ensure at least 1 bar per section
    counts = [max(1, c) for c in counts]

    remainder = total_bars - sum(counts)
    if remainder > 0:
        # Give remaining bars to sections with largest fractional parts
        fractional = [(exact[i] - math.floor(exact[i]), i) for i in range(len(sections))]
        fractional.sort(key=lambda x: x[0], reverse=True)
        for _, idx in fractional[:remainder]:
            counts[idx] += 1
    elif remainder < 0:
        # If min 1 bumped total over, reduce from largest
        for _ in range(abs(remainder)):
            max_idx = int(np.argmax(counts))
            if counts[max_idx] > 1:
                counts[max_idx] -= 1

    return [(sections[i][0], counts[i]) for i in range(len(sections))]


def get_section_for_bar(bar_idx: int, section_counts: list[tuple[SectionName, int]]) -> SectionName:
    """Determine section name for a given bar index."""
    curr = 0
    for name, cnt in section_counts:
        if curr <= bar_idx < curr + cnt:
            return name
        curr += cnt
    return section_counts[-1][0] if section_counts else "outro"


def sector_to_role(angle_deg: float, is_calm: bool = False, eight_sectors: bool = False) -> str:
    """
    Map ageostrophic angle in degrees to a chord role.
    Standard 4-sector mapping:
      East -45..45 = i
      North 45..135 = VI (IV_calm in calm)
      West |a| >= 135 = iv (i in calm)
      South -135..-45 = VII
    Expanded 8-sector dynamic mapping:
      East (-22.5..22.5) = i
      NE (22.5..67.5) = III
      North (67.5..112.5) = IV_calm if is_calm else VI
      NW (112.5..157.5) = i if is_calm else iv
      West (|a| >= 157.5) = i if is_calm else iv
      SW (-157.5..-112.5) = VII  [SW is VII / C as spec states]
      South (-112.5..-67.5) = VII
      SE (-67.5..-22.5) = IV_calm
    """
    norm_ang = ((angle_deg + 180.0) % 360.0) - 180.0

    if eight_sectors:
        if -22.5 <= norm_ang < 22.5:
            return "i"
        elif 22.5 <= norm_ang < 67.5:
            return "III"
        elif 67.5 <= norm_ang < 112.5:
            return "IV_calm" if is_calm else "VI"
        elif 112.5 <= norm_ang < 157.5:
            return "i" if is_calm else "iv"
        elif norm_ang >= 157.5 or norm_ang < -157.5:
            return "i" if is_calm else "iv"
        elif -157.5 <= norm_ang < -112.5:
            return "VII"
        elif -112.5 <= norm_ang < -67.5:
            return "VII"
        else:  # -67.5 <= norm_ang < -22.5
            return "IV_calm"

    if -45.0 <= norm_ang <= 45.0:
        return "i"
    elif 45.0 < norm_ang < 135.0:
        return "IV_calm" if is_calm else "VI"
    elif -135.0 < norm_ang < -45.0:
        return "VII"
    else:
        return "i" if is_calm else "iv"


def sector_to_chord(
    angle_deg: float,
    is_calm: bool = False,
    eight_sectors: bool = False,
    key_offset: int = 0,
) -> str:
    """
    Map ageostrophic angle in degrees to a chord.
    Standard 4-sector mapping:
      East -45..45 = i (Dm in key 0)
      North 45..135 = VI (Bb)  [In calm: G major]
      West |a| >= 135 = iv (Gm) [In calm: Dm]
      South -135..-45 = VII (C) [In calm: C]
    Expanded 8-sector dynamic mapping:
      East (-22.5..22.5) = Dm
      NE (22.5..67.5) = F
      North (67.5..112.5) = Bb (G in calm)
      NW (112.5..157.5) = Gm (Dm in calm)
      West (|a| >= 157.5) = Gm (Dm in calm)
      SW (-157.5..-112.5) = C
      South (-112.5..-67.5) = C
      SE (-67.5..-22.5) = G
    """
    role = sector_to_role(angle_deg, is_calm=is_calm, eight_sectors=eight_sectors)
    role_map = ROLE_CHORD_TABLE.get(key_offset, ROLE_CHORD_TABLE[0])
    return role_map[role][0]


def get_scale_step_approach(
    next_root_midi: int,
    direction: Literal["from_below", "from_above"],
    is_calm: bool = False,
    key_offset: int = 0,
) -> int:
    """
    Find approach note a scale step above or below the next root,
    staying strictly in D minor (or D Dorian in calm) transposed by key_offset,
    inside cello range (36-50).
    """
    base_scale_pcs = D_DORIAN if is_calm else D_NATURAL_MINOR
    scale_pcs = {(pc + key_offset) % 12 for pc in base_scale_pcs}

    if direction == "from_below":
        # Search downward from next_root_midi - 1
        for candidate in range(next_root_midi - 1, next_root_midi - 5, -1):
            if (candidate % 12) in scale_pcs:
                while candidate < 36:
                    candidate += 12
                while candidate > 50:
                    candidate -= 12
                return candidate
        cand = next_root_midi - 2
        while cand < 36:
            cand += 12
        while cand > 50:
            cand -= 12
        return cand
    else:
        # Search upward from next_root_midi + 1
        for candidate in range(next_root_midi + 1, next_root_midi + 5):
            if (candidate % 12) in scale_pcs:
                while candidate > 50:
                    candidate -= 12
                while candidate < 36:
                    candidate += 12
                return candidate
        cand = next_root_midi + 2
        while cand > 50:
            cand -= 12
        while cand < 36:
            cand += 12
        return cand


def generate_harmony(
    bars: Sequence[dict[str, Any]],
    normalized_speeds: Sequence[float | None],
    hold_threshold: float = 0.013,
    hysteresis: int = 2,
    eight_sectors: bool = False,
    key_offset: int = 0,
) -> list[BarHarmony]:
    """
    Build System 2 Harmony and Bass according to MUSIC_SPEC.md.

    Requirements:
    1. Sections by proportion: intro 10%, build 20%, peak 35%, calm 20%, outro 15%.
    2. Direction sector from ageo_angle_deg:
       East -45..45 = i (Dm), North 45..135 = VI (Bb), West |a|>=135 = iv (Gm), South -135..-45 = VII (C).
    3. Hold previous chord if hypot(ageo_u, ageo_v) < 0.013 m/s, or if bar is missing.
    4. A new chord switches only after 2 consecutive bars pick it, on a bar line.
    5. Peak lift: In Peak, if chosen chord is i and normalized speed >= 0.85, play III (F) for that bar.
    6. Calm section (D Dorian): only Dm, C, G major. Map East=Dm, West=Dm, South=C, North=G. No Bb, no Gm.
    7. Outro's last bar is always i (Dm in key 0, transposed tonic minor in key_offset).
    8. Bass: always plays chord root in cello range (36-50) on Beat 1 always, and Beat 3 when kick fires.
       On the last beat of a bar before a chord change, play one approach note (scale step above/below).
       Trend (sign of 7-bar change in normalized speed) picks direction (rising = from below, falling = from above).
    9. Output per bar: section, chord name, chord tones, bass events. Missing data = hold chord, bass rests.
    """
    total_bars = len(bars)
    if total_bars == 0:
        return []

    section_counts = compute_section_counts(total_bars)
    role_map = ROLE_CHORD_TABLE.get(key_offset, ROLE_CHORD_TABLE[0])

    # Pre-calculate active roles bar by bar with hysteresis
    active_role = "i"
    candidate_role: str | None = None
    candidate_streak: int = 0

    bar_roles: list[str] = []
    is_held_flags: list[bool] = []
    is_missing_flags: list[bool] = []
    ageo_mags: list[float | None] = []
    ageo_angles: list[float | None] = []

    for bar_idx in range(total_bars):
        bar_data = bars[bar_idx]
        sec = get_section_for_bar(bar_idx, section_counts)
        is_calm = (sec == "calm")

        u = bar_data.get("ageo_u")
        v = bar_data.get("ageo_v")
        angle = bar_data.get("ageo_angle_deg")

        # Check for missing data
        is_missing = False
        if u is None or v is None or not np.isfinite(u) or not np.isfinite(v):
            is_missing = True

        mag = bar_data.get("magnitude")
        if mag is None and not is_missing:
            mag = float(math.hypot(u, v))

        ageo_mags.append(mag)
        ageo_angles.append(angle if (angle is not None and np.isfinite(angle)) else None)
        is_missing_flags.append(is_missing)

        # Rule 3: Hold previous chord if missing or magnitude < hold_threshold
        if is_missing or (mag is not None and mag < hold_threshold):
            # Hold previous chord
            is_held_flags.append(True)
            candidate_role = None
            candidate_streak = 0
            # If in calm section, ensure held chord is allowed in calm
            if is_calm and active_role in ("VI", "iv"):
                active_role = "i"
            bar_roles.append(active_role)
            continue

        # Valid bar: determine target role from ageo direction sector
        is_held_flags.append(False)
        target_role = sector_to_role(
            float(angle) if angle is not None else 0.0,
            is_calm=is_calm,
            eight_sectors=eight_sectors,
        )

        # In calm section, ensure no VI or iv if not eight_sectors
        if is_calm and not eight_sectors and target_role in ("VI", "iv"):
            target_role = "i"

        # If transitioning into calm and active_role was VI or iv, force reset to i if not eight_sectors
        if is_calm and not eight_sectors and active_role in ("VI", "iv"):
            active_role = "i"

        # Rule 4: Hysteresis - new chord switches only after hysteresis consecutive bars pick it
        if target_role != active_role:
            if candidate_role == target_role:
                candidate_streak += 1
            else:
                candidate_role = target_role
                candidate_streak = 1

            if candidate_streak >= max(1, hysteresis):
                active_role = candidate_role
                candidate_role = None
                candidate_streak = 0
        else:
            candidate_role = None
            candidate_streak = 0

        bar_roles.append(active_role)

    # Rule 7: Outro's last bar is always i (tonic minor)
    if total_bars > 0:
        bar_roles[-1] = "i"

    # Now apply Rule 5 (Peak Lift) to determine final played roles
    played_roles: list[str] = []
    for bar_idx in range(total_bars):
        sec = get_section_for_bar(bar_idx, section_counts)
        base_role = bar_roles[bar_idx]
        norm_spd = normalized_speeds[bar_idx] if bar_idx < len(normalized_speeds) else None

        # Rule 5: Peak lift: in Peak, if chosen chord is i and normalized speed >= 0.85, play III
        if sec == "peak" and base_role == "i" and norm_spd is not None and norm_spd >= 0.85:
            played_roles.append("III")
        else:
            played_roles.append(base_role)

    # Generate BarHarmony and Bass events for each bar
    result: list[BarHarmony] = []

    for bar_idx in range(total_bars):
        bar_data = bars[bar_idx]
        date_str = str(bar_data.get("date", f"Bar-{bar_idx}"))
        sec = get_section_for_bar(bar_idx, section_counts)
        is_calm = (sec == "calm")
        role = played_roles[bar_idx]
        chord_name, numeral, chord_tones, root_midi = role_map[role]

        # Base tones midi shifted by key_offset
        base_k0_chord = ROLE_CHORD_TABLE[0][role][0]
        base_tones_midi = CHORD_INFO[base_k0_chord]["tones_midi"]
        tones_midi = [m + key_offset for m in base_tones_midi]

        is_missing = is_missing_flags[bar_idx]
        held = is_held_flags[bar_idx]
        mag = ageo_mags[bar_idx]
        angle = ageo_angles[bar_idx]

        bass_events: list[BassEvent] = []

        # If data is missing: bass rests (0 events)
        if not is_missing:
            # Velocity based on normalized speed if available
            norm_spd = normalized_speeds[bar_idx] if bar_idx < len(normalized_speeds) else 0.5
            s = float(np.clip(norm_spd if norm_spd is not None else 0.5, 0.0, 1.0))
            bass_vel = int(np.clip(round(60 + 35 * s), 45, 105))

            # Beat 1 always
            bass_events.append(
                BassEvent(
                    bar=bar_idx,
                    beat=1.0,
                    midi_note=root_midi,
                    velocity=bass_vel,
                    duration_beats=1.8,
                )
            )

            # Beat 3 when kick fires (always for valid bars)
            bass_events.append(
                BassEvent(
                    bar=bar_idx,
                    beat=3.0,
                    midi_note=root_midi,
                    velocity=int(round(bass_vel * 0.92)),
                    duration_beats=0.9 if bar_idx < total_bars - 1 and played_roles[bar_idx] != played_roles[bar_idx + 1] else 1.8,
                )
            )

            # Check if approach note on Beat 4 is needed (bar before a chord change)
            if bar_idx < total_bars - 1 and played_roles[bar_idx] != played_roles[bar_idx + 1]:
                next_role = played_roles[bar_idx + 1]
                next_root = role_map[next_role][3]

                # 7-bar trend in normalized speed: speed[i] - speed[max(0, i - 7)]
                prev_idx = max(0, bar_idx - 7)
                curr_s = norm_spd if norm_spd is not None else 0.5
                prev_s = normalized_speeds[prev_idx] if prev_idx < len(normalized_speeds) and normalized_speeds[prev_idx] is not None else curr_s
                delta_7 = curr_s - prev_s

                direction: Literal["from_below", "from_above"] = "from_below" if delta_7 > 0 else "from_above"
                approach_midi = get_scale_step_approach(next_root, direction=direction, is_calm=is_calm, key_offset=key_offset)

                bass_events.append(
                    BassEvent(
                        bar=bar_idx,
                        beat=4.0,
                        midi_note=approach_midi,
                        velocity=int(round(bass_vel * 0.85)),
                        duration_beats=0.85,
                        is_approach=True,
                    )
                )

        result.append(
            BarHarmony(
                bar=bar_idx,
                date=date_str,
                section=sec,
                chord=chord_name,
                chord_numeral=numeral,
                chord_tones=chord_tones,
                chord_tones_midi=tones_midi,
                bass_events=bass_events,
                is_rest=is_missing,
                held=held,
                ageo_magnitude=mag,
                ageo_angle_deg=angle,
            )
        )

    return result


def print_harmony_table(
    harmony_bars: Sequence[BarHarmony],
    max_rows: int | None = 40,
) -> None:
    """Print aligned table: bar, date, section, ageo angle, ageo magnitude, chord, bass notes."""
    print("\n" + "=" * 96)
    print(f"{'Bar':<4} | {'Date':<10} | {'Section':<7} | {'Ageo Ang':<8} | {'Ageo Mag':<8} | {'Chord':<7} | {'Bass Notes (Beat:MIDI)':<34}")
    print("-" * 96)

    display_len = min(len(harmony_bars), max_rows) if max_rows else len(harmony_bars)

    for b in range(display_len):
        h = harmony_bars[b]
        ang_str = f"{h.ageo_angle_deg:6.1f}°" if h.ageo_angle_deg is not None else "   -   "
        mag_str = f"{h.ageo_magnitude:6.4f}" if h.ageo_magnitude is not None else "   -   "

        if h.is_rest:
            chord_str = f"{h.chord} (REST)"
            bass_str = "Rest (no bass)"
        else:
            held_mark = "*" if h.held else ""
            chord_str = f"{h.chord} ({h.chord_numeral}){held_mark}"
            bass_desc = []
            for ev in h.bass_events:
                app_mark = " (app)" if ev.is_approach else ""
                bass_desc.append(f"{ev.beat:3.1f}:{ev.midi_note}{app_mark}")
            bass_str = ", ".join(bass_desc)

        print(f"{h.bar:<4} | {h.date:<10} | {h.section:<7} | {ang_str:<8} | {mag_str:<8} | {chord_str:<7} | {bass_str:<34}")

    if max_rows and len(harmony_bars) > max_rows:
        print(f"... ({len(harmony_bars) - max_rows} more bars truncated from display table)")

    print("=" * 96 + "\n")


if __name__ == "__main__":
    import json
    from aetherwaves.rhythm import normalize_series_5_95

    json_file = Path("data/raw_oscar/oscar_2025_daily.json")
    if json_file.exists():
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        norm_speeds, _ = normalize_series_5_95(data)
        harmony_bars = generate_harmony(data, norm_speeds)
        print_harmony_table(harmony_bars, max_rows=30)

