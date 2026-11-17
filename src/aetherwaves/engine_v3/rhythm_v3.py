"""rhythm_v3.py — Rhythm and percussion generator for AetherWaves Engine v3.

Drum specifications:
- Every bar that has data gets a soft base pulse (rest bars stay silent, hold bars keep their drums).
- Four tiers: base / low / medium / high with SHARED fixed thresholds for all tracks (0.15 / 0.35 / 0.65 of normalized value).
- 2-bar hysteresis on drum tiers.
- Fill on the last beat of every 4th bar in high.
- Soft and low velocities strictly between 35 and 75.
- Regional GM percussion mapping per preset.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Sequence
import numpy as np

DrumTier = Literal["base", "low", "medium", "high"]


@dataclass(frozen=True)
class DrumEventV3:
    bar: int
    beat: float
    midi_note: int
    velocity: int
    duration_beats: float = 0.25


def compute_drum_tiers_v3(
    norm_speeds: Sequence[float | None],
    rest_bars: Sequence[bool] | None = None,
) -> list[str]:
    """
    Compute drum tier per bar with shared thresholds:
      - None / rest bar: "rest" (silent)
      - norm < 0.15: "base"
      - 0.15 <= norm < 0.35: "low"
      - 0.35 <= norm < 0.65: "medium"
      - norm >= 0.65: "high"
    Applies 2-bar hysteresis on tier changes.
    """
    raw_tiers: list[str] = []
    n = len(norm_speeds)
    for i in range(n):
        s = norm_speeds[i]
        is_r = rest_bars[i] if rest_bars is not None else False
        if is_r or s is None or np.isnan(s):
            raw_tiers.append("rest")
        elif s < 0.15:
            raw_tiers.append("base")
        elif s < 0.35:
            raw_tiers.append("low")
        elif s < 0.65:
            raw_tiers.append("medium")
        else:
            raw_tiers.append("high")

    # 2-bar hysteresis
    effective_tiers: list[str] = []
    current_tier = raw_tiers[0] if raw_tiers else "base"
    pending_tier = current_tier
    pending_count = 0

    for t in raw_tiers:
        if t == "rest":
            effective_tiers.append("rest")
            continue

        if t == pending_tier:
            pending_count += 1
        else:
            pending_tier = t
            pending_count = 1

        if pending_count >= 2:
            current_tier = pending_tier

        effective_tiers.append(current_tier)

    return effective_tiers


def get_preset_percussion_instruments(track_id: str, drum_pattern: str | None = None) -> dict[str, int]:
    """Map regional percussion presets to General MIDI notes on Channel 9."""
    pat = drum_pattern or ""
    if track_id == "kuroshio" or "taiko" in pat:
        return {"kick": 35, "low": 77, "snare": 76, "hihat": 42, "fill": 44}
    elif track_id == "india" or "tabla" in pat:
        return {"kick": 35, "low": 64, "snare": 62, "hihat": 60, "fill": 61}
    elif track_id == "siberia" or "shamanic" in pat:
        return {"kick": 35, "low": 38, "snare": 40, "hihat": 42, "fill": 51}
    elif track_id == "europe" or "tambourine" in pat or "framedrum" in pat:
        return {"kick": 35, "low": 38, "snare": 54, "hihat": 42, "fill": 54}
    elif "conga" in pat or "woodland" in pat:
        return {"kick": 35, "low": 64, "snare": 62, "hihat": 69, "fill": 64}
    elif "metallophone" in pat or "earthy" in pat:
        return {"kick": 35, "low": 77, "snare": 76, "hihat": 69, "fill": 77}
    else:
        return {"kick": 35, "low": 38, "snare": 40, "hihat": 42, "fill": 51}


def generate_drum_events_v3(
    norm_speeds: list[float | None],
    preset: dict[str, Any],
    track_id: str,
    seed: int,
    rest_bars: list[bool] | None = None,
) -> tuple[list[DrumEventV3], list[str], dict[str, int]]:
    """
    Generate percussion events across 53 bars.
    Returns (events, effective_tiers, tier_counts).
    """
    tiers = compute_drum_tiers_v3(norm_speeds, rest_bars=rest_bars)

    tier_counts = {
        "base": tiers.count("base"),
        "low": tiers.count("low"),
        "medium": tiers.count("medium"),
        "high": tiers.count("high"),
    }
    if "rest" in tiers:
        tier_counts["rest"] = tiers.count("rest")

    drums = get_preset_percussion_instruments(track_id, preset.get("drum_pattern"))
    k_note = drums["kick"]
    low_note = drums["low"]
    sn_note = drums["snare"]
    hh_note = drums["hihat"]
    fill_note = drums["fill"]

    events: list[DrumEventV3] = []
    high_count = 0

    for bar_idx, tier in enumerate(tiers):
        if tier == "rest":
            continue

        # Last bar (52): gentle downbeat tap for seamless looping
        if bar_idx == len(tiers) - 1:
            events.append(DrumEventV3(bar=bar_idx, beat=0.0, midi_note=k_note, velocity=42))
            continue

        if tier == "base":
            # Soft base pulse: kick on beat 0, soft tap on beat 2
            events.append(DrumEventV3(bar=bar_idx, beat=0.0, midi_note=k_note, velocity=40))
            events.append(DrumEventV3(bar=bar_idx, beat=2.0, midi_note=hh_note, velocity=35))

        elif tier == "low":
            # Soft gentle pulse
            events.append(DrumEventV3(bar=bar_idx, beat=0.0, midi_note=k_note, velocity=46))
            events.append(DrumEventV3(bar=bar_idx, beat=1.0, midi_note=hh_note, velocity=36))
            events.append(DrumEventV3(bar=bar_idx, beat=2.0, midi_note=low_note, velocity=42))
            events.append(DrumEventV3(bar=bar_idx, beat=3.0, midi_note=hh_note, velocity=36))

        elif tier == "medium":
            # Flowing groove
            events.append(DrumEventV3(bar=bar_idx, beat=0.0, midi_note=k_note, velocity=56))
            events.append(DrumEventV3(bar=bar_idx, beat=1.0, midi_note=hh_note, velocity=42))
            events.append(DrumEventV3(bar=bar_idx, beat=2.0, midi_note=sn_note, velocity=50))
            events.append(DrumEventV3(bar=bar_idx, beat=3.0, midi_note=hh_note, velocity=44))

        elif tier == "high":
            high_count += 1
            # Driving energetic groove
            events.append(DrumEventV3(bar=bar_idx, beat=0.0, midi_note=k_note, velocity=68))
            events.append(DrumEventV3(bar=bar_idx, beat=1.0, midi_note=hh_note, velocity=48))
            events.append(DrumEventV3(bar=bar_idx, beat=2.0, midi_note=sn_note, velocity=62))
            events.append(DrumEventV3(bar=bar_idx, beat=2.5, midi_note=low_note, velocity=52))
            events.append(DrumEventV3(bar=bar_idx, beat=3.0, midi_note=hh_note, velocity=48))

            # Fill on the last beat of every 4th bar in high
            if high_count % 4 == 0:
                events.append(DrumEventV3(bar=bar_idx, beat=3.5, midi_note=fill_note, velocity=60))

    return events, tiers, tier_counts
