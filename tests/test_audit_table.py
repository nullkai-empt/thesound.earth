from __future__ import annotations

import json
from pathlib import Path

import pytest

from aetherwaves.blocks import group_days_into_blocks
from pipeline.prove_data_link import (
    build_audit_table_for_year,
    compute_bar_drum_tiers,
    run_melody_sensitivity_test,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_audit_table_row_count_equals_bars() -> None:
    """Requirement: Row count in audit table equals number of bars."""
    for year in [2023, 2024, 2025]:
        json_path = REPO_ROOT / f"data/raw_oscar/oscar_{year}_daily.json"
        daily_records = json.loads(json_path.read_text(encoding="utf-8"))
        blocks = group_days_into_blocks(daily_records, block_size=7)

        rows, summary = build_audit_table_for_year(year)
        assert len(rows) == len(blocks), f"Year {year} row count {len(rows)} != bars {len(blocks)}"
        assert summary["bars"] == len(blocks)


def test_audit_table_dates_match_json() -> None:
    """Requirement: Start and end dates are computed directly from the JSON records without hardcoding."""
    for year in [2023, 2024, 2025]:
        json_path = REPO_ROOT / f"data/raw_oscar/oscar_{year}_daily.json"
        daily_records = json.loads(json_path.read_text(encoding="utf-8"))
        rows, _ = build_audit_table_for_year(year)

        for i, row in enumerate(rows):
            start_idx = i * 7
            end_idx = min(start_idx + 7, len(daily_records))
            chunk = daily_records[start_idx:end_idx]

            expected_start = chunk[0]["date"]
            expected_end = chunk[-1]["date"]
            expected_days = len(chunk)

            assert row["start_date"] == expected_start, (
                f"Bar {i} start_date '{row['start_date']}' != expected '{expected_start}'"
            )
            assert row["end_date"] == expected_end, (
                f"Bar {i} end_date '{row['end_date']}' != expected '{expected_end}'"
            )
            assert row["days_in_block"] == expected_days, (
                f"Bar {i} days_in_block {row['days_in_block']} != expected {expected_days}"
            )


def test_audit_table_deterministic() -> None:
    """Requirement: Audit table generation is completely deterministic."""
    rows1, summary1 = build_audit_table_for_year(2025, seed=42)
    rows2, summary2 = build_audit_table_for_year(2025, seed=42)

    assert rows1 == rows2, "Rows must be identical on two runs with same seed"
    assert summary1 == summary2, "Summaries must be identical on two runs"


def test_audit_table_valid_values_and_reasons() -> None:
    """Requirement: All values, hold explanations, and melody REST reasons follow specification."""
    rows, _ = build_audit_table_for_year(2025)

    valid_rest_reasons = {"intro", "held", "phrase rule", "missing data", "rest"}
    valid_drum_tiers = {"low", "medium", "high", "rest"}
    valid_accents = {"none", "crash", "riser", "crash + riser"}

    for row in rows:
        assert isinstance(row["bar"], int)
        assert 0.70 <= row["velocity_scale"] <= 1.00
        assert row["drum_tier"] in valid_drum_tiers
        assert row["accent"] in valid_accents

        if row["held"]:
            assert "0.013" in row["held_why"] or "missing" in row["held_why"]

        if row["melody_notes"] is None:
            assert row["melody_rest_reason"] in valid_rest_reasons
        else:
            assert isinstance(row["melody_notes"], list)
            assert len(row["melody_notes"]) in (1, 2)
            for note in row["melody_notes"]:
                assert 52 <= note <= 67


def test_melody_sensitivity_numbers() -> None:
    """Requirement: Shifting speed by +/-0.2 changes a non-zero count of melody bars."""
    plus_cnt, minus_cnt = run_melody_sensitivity_test(year=2025, delta=0.2)
    assert plus_cnt > 0, "Shifting speed +0.2 must change melody notes"
    assert minus_cnt > 0, "Shifting speed -0.2 must change melody notes"
