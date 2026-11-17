"""form_v3.py — Data-driven section and form detection for AetherWaves v3.

Places musical sections directly from data series features:
- Intro: until the first sustained rise (min 3 bars)
- Peak: centered around raw series maximum (min 3 bars)
- Outro/Calm: after the last decline (min 3 bars)
- Build & Decline: bridging sections (min 3 bars each)
- Opening type: rule-based classification on first 4 bars
"""
from __future__ import annotations

import math
from typing import Any, Sequence
import numpy as np


def detect_opening_type(raw_series: Sequence[float | None], raw_max: float) -> str:
    """Classify opening type based on the first 4 bars (indices 0..3)."""
    vals = [float(raw_series[i] if raw_series[i] is not None else 0.0) for i in range(min(4, len(raw_series)))]
    if len(vals) < 4:
        return "ambient_sparse"

    v0, v1, v2, v3 = vals
    mean_val = float(np.mean(vals))

    if v1 >= v0 and v2 >= v1 and v3 >= v2 and v3 > (v0 * 1.25 + 1e-4):
        return "ascending"
    elif v1 <= v0 and v2 <= v1 and v3 <= v2 and v3 < (v0 * 0.80 - 1e-4):
        return "descending"
    elif raw_max > 0 and (mean_val / raw_max) < 0.15:
        return "ambient_sparse"
    else:
        return "steady_pulse"


def compute_form_sections(raw_series: Sequence[float | None]) -> dict[str, Any]:
    """
    Compute section boundaries strictly from raw data series of length N (typically 53).
    Guarantees every section (intro, build, peak, decline, calm) has >= 3 bars.
    """
    n_bars = len(raw_series)
    valid_vals = [float(x if x is not None else 0.0) for x in raw_series]
    
    # 1. Raw maximum and peak position
    peak_idx = int(np.argmax(valid_vals))
    raw_max = float(valid_vals[peak_idx])

    # 2. Opening type
    opening_type = detect_opening_type(valid_vals, raw_max)

    # 3. Baseline threshold for sustained rise/decline
    baseline = 0.15 * raw_max if raw_max > 0 else 0.0

    # 4. Intro until first sustained rise (min 3 bars, index 0..intro_end)
    intro_end = 2
    for i in range(2, min(peak_idx - 4, 15)):
        if valid_vals[i] > baseline and valid_vals[i + 1] >= valid_vals[i]:
            intro_end = i
            break
    intro_end = max(2, min(intro_end, max(2, peak_idx - 4), 30))

    # 5. Outro / calm after last decline (min 3 bars, outro_start..n_bars-1)
    outro_start = 50
    for i in range(max(peak_idx + 4, 30), 50):
        if valid_vals[i] <= baseline * 1.5:
            outro_start = i
            break
    outro_start = min(50, max(outro_start, min(50, peak_idx + 4), 22))

    if outro_start < intro_end + 10:
        if intro_end + 10 <= 50:
            outro_start = intro_end + 10
        else:
            outro_start = 50
            intro_end = 40

    # 6. Peak section: placed around peak_idx (min 3 bars)
    min_p_start = intro_end + 4
    max_p_end = outro_start - 4

    ideal_start = peak_idx - 1
    ideal_end = peak_idx + 1

    p_start = max(min_p_start, min(ideal_start, max_p_end - 2))
    p_end = min(max_p_end, max(ideal_end, p_start + 2))

    # Verify constraints: min 3 bars each
    assert intro_end >= 2, f"Intro must be >= 3 bars (0..{intro_end})"
    assert (p_start - 1) - (intro_end + 1) + 1 >= 3, f"Build must be >= 3 bars ({intro_end+1}..{p_start-1})"
    assert p_end - p_start + 1 >= 3, f"Peak must be >= 3 bars ({p_start}..{p_end})"
    assert (outro_start - 1) - (p_end + 1) + 1 >= 3, f"Decline must be >= 3 bars ({p_end+1}..{outro_start-1})"
    assert (n_bars - 1) - outro_start + 1 >= 3, f"Calm must be >= 3 bars ({outro_start}..{n_bars-1})"

    sections = [
        {"name": "intro", "start_bar": 0, "end_bar": intro_end, "length": intro_end + 1},
        {"name": "build", "start_bar": intro_end + 1, "end_bar": p_start - 1, "length": (p_start - 1) - (intro_end + 1) + 1},
        {"name": "peak", "start_bar": p_start, "end_bar": p_end, "length": p_end - p_start + 1},
        {"name": "decline", "start_bar": p_end + 1, "end_bar": outro_start - 1, "length": (outro_start - 1) - (p_end + 1) + 1},
        {"name": "calm", "start_bar": outro_start, "end_bar": n_bars - 1, "length": (n_bars - 1) - outro_start + 1},
    ]

    # Map each bar to its section name
    bar_to_section: list[str] = [""] * n_bars
    for sec in sections:
        for b in range(sec["start_bar"], sec["end_bar"] + 1):
            bar_to_section[b] = sec["name"]

    section_captions = {
        "intro": f"Intro (bars 0-{intro_end}): {opening_type} opening",
        "build": f"Build (bars {intro_end+1}-{p_start-1}): rising energy towards seasonal peak",
        "peak": f"Peak (bars {p_start}-{p_end}): maximal activity around bar {peak_idx} ({raw_max:.1f})",
        "decline": f"Decline (bars {p_end+1}-{outro_start-1}): subsidence from peak conditions",
        "calm": f"Calm (bars {outro_start}-{n_bars-1}): tranquil resolution transitioning to seamless loop",
    }

    return {
        "peak_idx": peak_idx,
        "raw_max": raw_max,
        "opening_type": opening_type,
        "sections": sections,
        "bar_to_section": bar_to_section,
        "section_captions": section_captions,
    }
