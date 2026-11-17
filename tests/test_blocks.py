from __future__ import annotations

import json
import math
import numpy as np
import pytest

from aetherwaves.blocks import (
    analyze_blocks,
    get_sector,
    group_days_into_blocks,
    process_and_run,
)
from aetherwaves.harmony import generate_harmony


def _make_day(
    date: str = "2025-01-01",
    p95: float | None = 1.15,
    u: float | None = 0.02,
    v: float | None = 0.01,
    angle: float | None = None,
) -> dict:
    if angle is None and u is not None and v is not None:
        angle = math.degrees(math.atan2(v, u))
    return {
        "date": date,
        "speed_p95": p95,
        "ageo_u": u,
        "ageo_v": v,
        "ageo_angle_deg": angle,
    }


def test_365_days_grouping_7_day_blocks():
    """Requirement 1: 7-day blocks (364 days = 52 blocks; 365 days gives 52 full blocks + shorter final block)."""
    with open("data/raw_oscar/oscar_2025_daily.json", "r", encoding="utf-8") as f:
        daily_records = json.load(f)

    assert len(daily_records) == 365, "Dataset must have 365 days"
    blocks = group_days_into_blocks(daily_records, block_size=7)

    # 365 days / 7 = 52 full 7-day blocks + 1 shorter 1-day block = 53 blocks
    assert len(blocks) == 53
    assert blocks[0]["total_days"] == 7
    assert blocks[51]["total_days"] == 7
    assert blocks[52]["total_days"] == 1  # Shorter last block kept

    # Exactly 364 days yields exactly 52 full blocks
    syn_364 = [_make_day(f"2025-day-{i}") for i in range(364)]
    blocks_364 = group_days_into_blocks(syn_364, block_size=7)
    assert len(blocks_364) == 52

    # Shorter final block retention with arbitrary count (e.g. 15 days = 7 + 7 + 1 -> 3 blocks)
    syn_15 = [_make_day(f"2025-day-{i}") for i in range(15)]
    blocks_15 = group_days_into_blocks(syn_15, block_size=7)
    assert len(blocks_15) == 3
    assert blocks_15[-1]["total_days"] == 1


def test_majority_sector_and_tie_breaking():
    """Requirement 2: Most common daily sector wins; ties go to sector of the later day."""
    # Day 0: East (0 deg)
    # Day 1: East (10 deg)
    # Day 2: North (90 deg)
    # Day 3: North (80 deg)
    # Tie: East has 2, North has 2. North appears later (day 3 vs day 1). North must win!
    days = [
        _make_day("2025-01-01", p95=1.0, u=0.03, v=0.0, angle=0.0),       # East
        _make_day("2025-01-02", p95=1.0, u=0.03, v=0.005, angle=10.0),   # East
        _make_day("2025-01-03", p95=1.0, u=0.0, v=0.03, angle=90.0),     # North
        _make_day("2025-01-04", p95=1.0, u=0.005, v=0.03, angle=80.0),   # North
    ]
    blocks = group_days_into_blocks(days, block_size=4)
    assert len(blocks) == 1
    b = blocks[0]
    assert b["sector"] == "North", f"Ties should go to later day sector, got {b['sector']}"
    assert b["method"] == "majority sector of the ageostrophic component"

    # Verify circular mean angle of winning sector (North: 90 and 80 -> mean is 85.0)
    assert math.isclose(b["ageo_angle_deg"], 85.0, abs_tol=1e-3)

    # Verify ageo_u and ageo_v are mean of winning sector only (North: u=(0.0+0.005)/2=0.0025, v=(0.03+0.03)/2=0.03)
    assert math.isclose(b["ageo_u"], 0.0025, abs_tol=1e-5)
    assert math.isclose(b["ageo_v"], 0.03, abs_tol=1e-5)

    # Verify magnitude is mean of daily hypots across all valid days (all 4 days)
    expected_mag = np.mean([math.hypot(d["ageo_u"], d["ageo_v"]) for d in days])
    assert math.isclose(b["magnitude"], expected_mag, abs_tol=1e-5)


def test_missing_day_is_ignored():
    """Requirement 2: Missing day in a block is ignored; statistics computed from valid days."""
    chunk = [
        _make_day("2025-01-01", p95=1.00, u=0.03, v=0.04, angle=53.13),   # North
        _make_day("2025-01-02", p95=None, u=None, v=None, angle=None),    # Missing
        _make_day("2025-01-03", p95=1.20, u=0.06, v=0.08, angle=53.13),   # North
        _make_day("2025-01-04", p95=float("nan"), u=float("nan"), v=float("nan"), angle=float("nan")), # NaN
        _make_day("2025-01-05", p95=1.40, u=0.09, v=0.12, angle=53.13),   # North
        _make_day("2025-01-06", p95=None, u=None, v=None, angle=None),    # Missing
        _make_day("2025-01-07", p95=1.60, u=0.12, v=0.16, angle=53.13),   # North
    ]
    blocks = group_days_into_blocks(chunk, block_size=7)
    assert len(blocks) == 1
    b = blocks[0]

    assert b["valid_count"] == 4
    assert b["total_days"] == 7
    assert math.isclose(b["speed_p95"], (1.00 + 1.20 + 1.40 + 1.60) / 4, rel_tol=1e-5)
    assert b["sector"] == "North"
    assert b["magnitude"] is not None


def test_all_missing_block_is_none():
    """Requirement 2: If all days in a block are missing, everything is None (rest, never zero)."""
    chunk = [
        _make_day("2025-01-01", p95=None, u=None, v=None, angle=None),
        _make_day("2025-01-02", p95=float("nan"), u=float("nan"), v=float("nan"), angle=float("nan")),
        _make_day("2025-01-03", p95=None, u=None, v=None, angle=None),
    ]
    blocks = group_days_into_blocks(chunk, block_size=3)
    assert len(blocks) == 1
    b = blocks[0]

    assert b["speed_p95"] is None
    assert b["sector"] is None
    assert b["ageo_u"] is None
    assert b["ageo_v"] is None
    assert b["ageo_angle_deg"] is None
    assert b["magnitude"] is None
    assert b["valid_count"] == 0


def test_magnitude_key_used_for_hold_rule_and_fallback():
    """
    Requirement 4 / user prompt:
    A bar with a "magnitude" key uses that value for the 0.013 hold rule,
    and a bar without it still uses hypot(ageo_u, ageo_v).
    """
    # Create a 20-bar sequence in Intro/Build
    base_bars = [
        {"date": f"2025-01-{i+1:02d}", "speed_p95": 1.0, "ageo_u": 0.04, "ageo_v": 0.0, "ageo_angle_deg": 0.0}
        for i in range(20)
    ]
    norm_speeds = [0.5] * 20

    # Test 1: bar with magnitude key < 0.013, even though hypot(u, v) = 0.04 > 0.013
    # Initial chord is Dm. At bar 5 & 6, angle points to North (Bb).
    bars_with_mag = [dict(b) for b in base_bars]
    bars_with_mag[5]["ageo_angle_deg"] = 90.0
    bars_with_mag[5]["ageo_u"] = 0.0
    bars_with_mag[5]["ageo_v"] = 0.04  # hypot is 0.04 > 0.013
    bars_with_mag[5]["magnitude"] = 0.005  # BUT magnitude < 0.013 -> MUST HOLD!

    bars_with_mag[6]["ageo_angle_deg"] = 90.0
    bars_with_mag[6]["ageo_u"] = 0.0
    bars_with_mag[6]["ageo_v"] = 0.04
    bars_with_mag[6]["magnitude"] = 0.005  # MUST HOLD!

    harm_mag = generate_harmony(bars_with_mag, norm_speeds, hold_threshold=0.013)
    assert harm_mag[5].held is True, "Bar with magnitude < 0.013 must hold"
    assert harm_mag[6].held is True, "Bar with magnitude < 0.013 must hold"
    assert harm_mag[5].chord == "Dm"
    assert harm_mag[6].chord == "Dm"

    # Test 2: bar without magnitude key: uses hypot(u, v)
    bars_no_mag = [dict(b) for b in base_bars]
    # At bars 5 and 6, hypot(0, 0.04) = 0.04 > 0.013 -> should NOT hold, should switch to Bb after 2 bars
    bars_no_mag[5]["ageo_angle_deg"] = 90.0
    bars_no_mag[5]["ageo_u"] = 0.0
    bars_no_mag[5]["ageo_v"] = 0.04
    assert "magnitude" not in bars_no_mag[5]

    bars_no_mag[6]["ageo_angle_deg"] = 90.0
    bars_no_mag[6]["ageo_u"] = 0.0
    bars_no_mag[6]["ageo_v"] = 0.04
    assert "magnitude" not in bars_no_mag[6]

    harm_no_mag = generate_harmony(bars_no_mag, norm_speeds, hold_threshold=0.013)
    assert harm_no_mag[5].held is False, "Bar without magnitude key with hypot > 0.013 must not hold"
    assert harm_no_mag[6].held is False, "Bar without magnitude key with hypot > 0.013 must not hold"
    assert harm_no_mag[6].chord == "Bb", "After 2 consecutive non-held bars picking North, chord must switch to Bb"

    # Test 3: bar without magnitude key where hypot(u, v) < 0.013 -> MUST HOLD
    bars_no_mag_small = [dict(b) for b in base_bars]
    bars_no_mag_small[5]["ageo_angle_deg"] = 90.0
    bars_no_mag_small[5]["ageo_u"] = 0.005
    bars_no_mag_small[5]["ageo_v"] = 0.005  # hypot ~ 0.00707 < 0.013
    harm_no_mag_small = generate_harmony(bars_no_mag_small, norm_speeds, hold_threshold=0.013)
    assert harm_no_mag_small[5].held is True, "Bar without magnitude key with hypot < 0.013 must hold"


def test_output_is_identical_on_every_run():
    """Requirement 7(d): The output is deterministic and identical on repeated executions."""
    with open("data/raw_oscar/oscar_2025_daily.json", "r", encoding="utf-8") as f:
        daily_records = json.load(f)

    run1 = group_days_into_blocks(daily_records, block_size=7)
    run2 = group_days_into_blocks(daily_records, block_size=7)

    assert len(run1) == len(run2)
    for b1, b2 in zip(run1, run2):
        assert b1["speed_p95"] == b2["speed_p95"]
        assert b1["sector"] == b2["sector"]
        assert b1["ageo_u"] == b2["ageo_u"]
        assert b1["ageo_v"] == b2["ageo_v"]
        assert b1["ageo_angle_deg"] == b2["ageo_angle_deg"]
        assert b1["magnitude"] == b2["magnitude"]
