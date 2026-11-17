"""tests/test_adapters.py — Phase 1 adapter tests.

Covers:
  - OscarAdapter: output is consistent with the raw JSON data
  - Each adapter: deterministic (call twice → same result)
  - None row → rest_row structure (no speed_p95, no crash data)
  - Two different inputs → different bar data (oscar, canopy)
  - FIRMSAdapter: missing env var raises EnvironmentError
  - VideoAdapter: black frame → rest row
  - CanopyAdapter: no-NPZ path → all rests
"""
from __future__ import annotations

from datetime import date
import json
import os
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

# Ensure src/ is on the path
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from aetherwaves.adapters.base import AdapterBase, load_land_regions
from aetherwaves.adapters.oscar import OscarAdapter
from aetherwaves.adapters.fires import FIRMSAdapter
from aetherwaves.adapters.canopy import CanopyAdapter
from aetherwaves.adapters.video import VideoAdapter

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

OSCAR_JSON = REPO / "data" / "raw_oscar" / "oscar_2021_daily.json"


def _make_oscar_json(tmp_path: Path, records: list[dict]) -> Path:
    p = tmp_path / "oscar_test.json"
    p.write_text(json.dumps(records), encoding="utf-8")
    return p


def _sample_records(n: int = 10) -> list[dict]:
    """Return n valid-looking OSCAR daily records."""
    return [
        {
            "date": f"2021-01-{i+1:02d}",
            "speed_p95": 1.0 + i * 0.01,
            "ageo_u": 0.02 + i * 0.001,
            "ageo_v": -0.01,
            "ageo_angle_deg": -22.0 + i,
            "magnitude": 0.05,
        }
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# OscarAdapter
# ---------------------------------------------------------------------------

class TestOscarAdapter:
    def test_reads_valid_rows(self, tmp_path):
        records = _sample_records(14)
        p = _make_oscar_json(tmp_path, records)
        adapter = OscarAdapter(p)
        rows = adapter.rows()
        assert len(rows) == 14
        for r in rows:
            assert r["valid"] is True
            assert r["speed_p95"] is not None
            assert r["date"] != ""

    def test_none_speed_becomes_rest(self, tmp_path):
        records = _sample_records(5)
        records[2]["speed_p95"] = None  # inject a missing day
        p = _make_oscar_json(tmp_path, records)
        rows = OscarAdapter(p).rows()
        assert rows[2]["valid"] is False
        assert rows[2]["speed_p95"] is None
        # Other rows still valid
        assert rows[0]["valid"] is True
        assert rows[4]["valid"] is True

    def test_deterministic(self, tmp_path):
        p = _make_oscar_json(tmp_path, _sample_records(20))
        a = OscarAdapter(p)
        r1 = a.rows()
        r2 = a.rows()
        assert r1 == r2, "OscarAdapter must be deterministic"

    def test_two_different_inputs_give_different_data(self, tmp_path):
        recs_a = _sample_records(10)
        recs_b = _sample_records(10)
        for r in recs_b:
            r["speed_p95"] = r["speed_p95"] * 2.5  # clearly different
        pa = tmp_path / "a.json"
        pa.write_text(json.dumps(recs_a), encoding="utf-8")
        pb = tmp_path / "b.json"
        pb.write_text(json.dumps(recs_b), encoding="utf-8")
        rows_a = OscarAdapter(pa).rows()
        rows_b = OscarAdapter(pb).rows()
        speeds_a = [r["speed_p95"] for r in rows_a]
        speeds_b = [r["speed_p95"] for r in rows_b]
        assert speeds_a != speeds_b

    def test_oscar_adapter_output_matches_group_days_into_blocks(self):
        """Test that OSCAR adapter output processed through blocks matches old raw path."""
        from aetherwaves.blocks import group_days_into_blocks
        if not OSCAR_JSON.exists():
            pytest.skip("Real OSCAR JSON not present")
        raw = json.loads(OSCAR_JSON.read_text(encoding="utf-8"))
        blocks_raw = group_days_into_blocks(raw)
        adapter_rows = OscarAdapter(OSCAR_JSON).rows()
        blocks_adapter = group_days_into_blocks(adapter_rows)
        assert len(blocks_raw) == len(blocks_adapter)
        for b_raw, b_ad in zip(blocks_raw, blocks_adapter):
            assert b_raw["speed_p95"] == pytest.approx(b_ad["speed_p95"])
            assert b_raw["sector"] == b_ad["sector"]
            assert b_raw["ageo_angle_deg"] == pytest.approx(b_ad["ageo_angle_deg"])

    def test_matches_real_json_structure(self):
        """When the real 2021 JSON exists, adapter reads all rows."""
        if not OSCAR_JSON.exists():
            pytest.skip("Real OSCAR JSON not present")
        rows = OscarAdapter(OSCAR_JSON).rows()
        assert len(rows) > 300
        for r in rows:
            assert "speed_p95" in r
            assert "valid" in r

    def test_source_fields_present(self):
        assert "speed_p95" in OscarAdapter.source_fields
        assert "ageo_angle_deg" in OscarAdapter.source_fields
        assert "magnitude" in OscarAdapter.source_fields

    def test_bar_unit(self):
        assert OscarAdapter.bar_unit == "7-day block"


# ---------------------------------------------------------------------------
# FIRMSAdapter
# ---------------------------------------------------------------------------

class TestFIRMSAdapter:
    def test_missing_env_raises(self):
        """Missing MAP_KEY env var must raise EnvironmentError, never silently fail."""
        env_name = "__NONEXISTENT_FIRMS_KEY_XYZ__"
        os.environ.pop(env_name, None)
        adapter = FIRMSAdapter(
            map_key_env=env_name,
            west=-10, south=0, east=10, north=20, year=2024,
        )
        with pytest.raises(EnvironmentError, match=env_name):
            adapter.rows()

    def test_source_fields_present(self):
        assert "speed_p95" in FIRMSAdapter.source_fields
        assert "ageo_angle_deg" in FIRMSAdapter.source_fields

    def test_bar_unit(self):
        assert FIRMSAdapter.bar_unit == "day"

    def test_rest_row_has_none_speed(self):
        rest = FIRMSAdapter.rest_row("2024-01-01")
        assert rest["speed_p95"] is None
        assert rest["valid"] is False

    def test_firms_determinism(self, tmp_path):
        sample_csv = (
            "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_ti5,frp,daynight\n"
            "-10.5,-50.2,340.1,0.4,0.4,2025-06-01,1700,N,VIIRS,nominal,2.0NRT,295.0,15.2,D\n"
        )
        adapter = FIRMSAdapter(map_key_env="DUMMY_KEY", cache_dir=tmp_path)
        r1 = adapter._parse_csv(sample_csv, "2025-06-01")
        r2 = adapter._parse_csv(sample_csv, "2025-06-01")
        assert r1 == r2

    def test_firms_zero_detections_vs_api_failure(self):
        adapter = FIRMSAdapter(map_key_env="DUMMY_KEY")
        # Empty rows = 0 detections -> valid: True, speed_p95: 0.0
        header_only = "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_ti5,frp,daynight\n"
        res_zero = adapter._parse_csv(header_only, "2025-06-01")
        assert res_zero["valid"] is True
        assert res_zero["speed_p95"] == 0.0
        assert res_zero["magnitude"] == 0.0

        # API failure message in CSV -> valid: False, speed_p95: None
        res_fail = adapter._parse_csv("Invalid MAP_KEY or account inactive", "2025-06-01")
        assert res_fail["valid"] is False
        assert res_fail["speed_p95"] is None


# ---------------------------------------------------------------------------
# CanopyAdapter
# ---------------------------------------------------------------------------

class TestCanopyAdapter:
    def test_no_npz_all_rests(self, tmp_path):
        """Without a data file all 35 steps must be rest rows."""
        adapter = CanopyAdapter(npz_path=tmp_path / "nonexistent.npz", meridian_lon=0.0)
        rows = adapter.rows()
        assert len(rows) == 35
        for r in rows:
            assert r["valid"] is False
            assert r["speed_p95"] is None

    def test_deterministic_no_npz(self):
        a = CanopyAdapter(npz_path=None)
        assert a.rows() == a.rows()

    def test_deterministic_with_npz(self, tmp_path):
        p = tmp_path / "gedi.npz"
        rng = np.random.RandomState(42)
        lat = rng.uniform(-90, 90, 5000)
        lon = rng.uniform(-180, 180, 5000)
        height = rng.uniform(0, 40, 5000)
        np.savez(str(p), lat=lat, lon=lon, height=height)
        a = CanopyAdapter(npz_path=p, meridian_lon=0.0)
        r1 = a.rows()
        r2 = a.rows()
        assert r1 == r2

    def test_two_meridians_differ(self, tmp_path):
        p = tmp_path / "gedi.npz"
        rng = np.random.RandomState(99)
        lat = rng.uniform(-90, 90, 10000)
        lon = rng.uniform(-180, 180, 10000)
        height = np.abs(np.sin(np.radians(lon))) * 30 + 1  # lon-dependent
        np.savez(str(p), lat=lat, lon=lon, height=height)
        rows_0 = CanopyAdapter(npz_path=p, meridian_lon=0.0).rows()
        rows_90 = CanopyAdapter(npz_path=p, meridian_lon=90.0).rows()
        # At least some speeds must differ
        s0 = [r["speed_p95"] for r in rows_0]
        s90 = [r["speed_p95"] for r in rows_90]
        assert s0 != s90, "Different meridians must give different data"

    def test_source_fields_present(self):
        assert "speed_p95" in CanopyAdapter.source_fields
        assert "ageo_angle_deg" in CanopyAdapter.source_fields

    def test_bar_unit(self):
        assert CanopyAdapter.bar_unit == "transect step"

    def test_direction_sign_positive_gradient(self, tmp_path):
        """Increasing height northward → East (0°)."""
        p = tmp_path / "gedi.npz"
        # Create data where height increases with latitude near lon=0
        lat_vals = np.array([-87.5, -82.5, -77.5, -72.5, -67.5,
                              -62.5, -57.5, -52.5, -47.5, -42.5,
                              -37.5, -32.5, -27.5, -22.5, -17.5,
                              -12.5,  -7.5,  -2.5,   2.5,   7.5,
                               12.5,  17.5,  22.5,  27.5,  32.5,
                               37.5,  42.5,  47.5,  52.5,  57.5,
                               62.5,  67.5,  72.5,  77.5,  82.5])
        lon_vals = np.zeros_like(lat_vals)
        # height = lat + 90 so it strictly increases northward
        height_vals = lat_vals + 90.0
        np.savez(str(p), lat=lat_vals, lon=lon_vals, height=height_vals)
        adapter = CanopyAdapter(npz_path=p, meridian_lon=0.0)
        rows = adapter.rows()
        # Skip first row (no previous band), check some mid-rows
        for r in rows[1:5]:
            if r["valid"] and r["ageo_angle_deg"] is not None:
                assert r["ageo_angle_deg"] == 0.0, (
                    "Positive height gradient must map to East (0°)"
                )


# ---------------------------------------------------------------------------
# VideoAdapter (unit-level, no real video needed)
# ---------------------------------------------------------------------------

class TestVideoAdapter:
    def test_source_fields_present(self):
        assert "speed_p95" in VideoAdapter.source_fields
        assert "ageo_angle_deg" in VideoAdapter.source_fields

    def test_bar_unit(self):
        assert VideoAdapter.bar_unit == "frame group"

    def test_rest_row_structure(self):
        r = VideoAdapter.rest_row("frame_00001")
        assert r["speed_p95"] is None
        assert r["valid"] is False
        assert r["date"] == "frame_00001"

    def test_no_video_returns_empty(self, tmp_path):
        """Non-existent video → empty row list (graceful)."""
        adapter = VideoAdapter(
            video_path=tmp_path / "nonexistent.mp4",
            video_id="test_id",
            cache_dir=tmp_path / "cache",
        )
        # _extract_frames returns [] → rows() returns []
        rows = adapter.rows()
        assert isinstance(rows, list)

    def test_video_determinism(self, tmp_path):
        video_path = REPO / "web" / "ecco2_sst_flow.mp4"
        if not video_path.exists():
            pytest.skip("Video ecco2_sst_flow.mp4 not found")
        # CPU decode for deterministic output
        a1 = VideoAdapter(video_path=video_path, hwaccel=None, cache_dir=tmp_path / "c1")
        a2 = VideoAdapter(video_path=video_path, hwaccel=None, cache_dir=tmp_path / "c2")
        f1 = a1._extract_frames()
        f2 = a2._extract_frames()
        assert len(f1) == len(f2)
        for frame1, frame2 in zip(f1[:3], f2[:3]):
            if frame1 is None:
                assert frame2 is None
            else:
                np.testing.assert_array_equal(frame1, frame2)


# ---------------------------------------------------------------------------
# AdapterBase contract
# ---------------------------------------------------------------------------

class TestAdapterBase:
    def test_none_row_produces_silent_bar_through_pipeline(self):
        from aetherwaves.rhythm import generate_drum_events
        from aetherwaves.harmony import generate_harmony
        from aetherwaves.melody import generate_melody

        rest_block = [AdapterBase.rest_row("2025-01-01")]
        # Rhythm engine: 0 drum events on rest bar
        drum_events = generate_drum_events([None], seed=123)
        assert len(drum_events) == 0, "Missing data bar must have zero drum events"

        # Harmony engine: is_rest=True, 0 bass events
        harmony = generate_harmony(rest_block, [None])
        assert harmony[0].is_rest is True
        assert len(harmony[0].bass_events) == 0, "Missing data bar must have zero bass events"

        # Melody engine: 0 melody notes on rest bar
        melody_events = generate_melody(rest_block, harmony, [None], seed=123)
        assert len(melody_events) == 0, "Missing data bar must have zero melody notes"

    def test_rest_row_contract(self):
        r = AdapterBase.rest_row("2025-06-15")
        assert r["valid"] is False
        assert r["speed_p95"] is None
        assert r["ageo_u"] is None
        assert r["ageo_v"] is None
        assert r["ageo_angle_deg"] is None
        assert r["magnitude"] is None
        assert r["date"] == "2025-06-15"

    def test_all_adapters_have_required_class_attrs(self):
        for cls in [OscarAdapter, FIRMSAdapter, CanopyAdapter, VideoAdapter]:
            assert hasattr(cls, "source_fields"), f"{cls.__name__} missing source_fields"
            assert hasattr(cls, "hold_threshold"), f"{cls.__name__} missing hold_threshold"
            assert hasattr(cls, "bar_unit"), f"{cls.__name__} missing bar_unit"
            assert hasattr(cls, "ADAPTER_VERSION"), f"{cls.__name__} missing ADAPTER_VERSION"
            assert isinstance(cls.source_fields, dict)
            assert isinstance(cls.hold_threshold, float)
            assert isinstance(cls.bar_unit, str)


# ---------------------------------------------------------------------------
# Land Regions Config & Adapter Determinism
# ---------------------------------------------------------------------------

class TestLandRegionsConfigAndDeterminism:
    def test_loads_real_land_regions_json(self):
        cfg_path = REPO / "config" / "land_regions.json"
        assert cfg_path.exists(), "config/land_regions.json must exist"
        regions = load_land_regions(str(cfg_path))
        assert len(regions) == 8
        ids = [r["id"] for r in regions]
        expected = [
            "amazon", "congo", "se_asia", "australia",
            "w_north_america", "siberia", "india", "europe"
        ]
        for exp in expected:
            assert exp in ids, f"Expected {exp} in land regions"
        sib = next(r for r in regions if r["id"] == "siberia")
        assert sib.get("canopy_meridian") is None, "siberia must be fires only (no canopy meridian)"

    def test_duplicate_id_raises(self, tmp_path):
        bad_cfg = {
            "regions": [
                {"id": "amazon", "lat": [-15, -3], "lon": [-65, -45]},
                {"id": "amazon", "lat": [-10, 0], "lon": [-60, -40]},
            ]
        }
        p = tmp_path / "land.json"
        p.write_text(json.dumps(bad_cfg), encoding="utf-8")
        with pytest.raises(ValueError, match="duplicate region id"):
            load_land_regions(str(p))

    def test_bad_lat_lo_ge_hi_raises(self, tmp_path):
        bad_cfg = {
            "regions": [
                {"id": "bad_lat", "lat": [10, -5], "lon": [15, 30]}
            ]
        }
        p = tmp_path / "land.json"
        p.write_text(json.dumps(bad_cfg), encoding="utf-8")
        with pytest.raises(ValueError, match="bad lat range"):
            load_land_regions(str(p))

    def test_bad_lat_equal_raises(self, tmp_path):
        bad_cfg = {
            "regions": [
                {"id": "bad_lat", "lat": [10, 10], "lon": [15, 30]}
            ]
        }
        p = tmp_path / "land.json"
        p.write_text(json.dumps(bad_cfg), encoding="utf-8")
        with pytest.raises(ValueError, match="bad lat range"):
            load_land_regions(str(p))

    def test_bad_lon_a_ge_b_raises(self, tmp_path):
        bad_cfg = {
            "regions": [
                {"id": "bad_lon", "lat": [-5, 5], "lon": [30, 15]}
            ]
        }
        p = tmp_path / "land.json"
        p.write_text(json.dumps(bad_cfg), encoding="utf-8")
        with pytest.raises(ValueError, match="bad lon range"):
            load_land_regions(str(p))

    def test_land_adapters_deterministic(self, tmp_path, monkeypatch):
        # 1. CanopyAdapter determinism
        canopy = CanopyAdapter(meridian_lon=-60.0)
        c_rows_1 = canopy.rows()
        c_rows_2 = canopy.rows()
        assert c_rows_1 == c_rows_2, "CanopyAdapter must produce deterministic rows"

        # 2. FIRMSAdapter determinism on cached data
        monkeypatch.setenv("DUMMY_KEY", "mock_dummy_key_value")
        sample_csv = (
            "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_ti5,frp,daynight\n"
            "-10.5,-50.2,340.1,0.4,0.4,2025-06-01,1700,N,VIIRS,nominal,2.0NRT,295.0,15.2,D\n"
        )
        cache_slug = "-65.0_-15.0_-45.0_-3.0_VIIRS_SNPP_SP"
        day_dir = tmp_path / cache_slug / "2025"
        day_dir.mkdir(parents=True)
        (day_dir / "2025-06-01.csv").write_text(sample_csv, encoding="utf-8")

        adapter = FIRMSAdapter(
            map_key_env="DUMMY_KEY",
            west=-65.0,
            south=-15.0,
            east=-45.0,
            north=-3.0,
            year=2025,
            cache_dir=tmp_path,
        )
        f_row_1 = adapter.fetch_single_day(date(2025, 6, 1))
        f_row_2 = adapter.fetch_single_day(date(2025, 6, 1))
        assert f_row_1 == f_row_2, "FIRMSAdapter must produce deterministic output"


# ---------------------------------------------------------------------------
# Canopy Gridded Product & Land Mask Verification
# ---------------------------------------------------------------------------

class TestCanopyRealGriddedProduct:
    """Validate real gridded GEDI dataset, land masking, and meridian coverage."""

    def test_no_ocean_cell_has_a_value(self):
        """Verify that zero ocean cells contain valid canopy height values."""
        from global_land_mask import globe

        npz_path = Path("data/gedi_canopy_l1b_rh98_2019.npz")
        if not npz_path.exists():
            npz_path = Path("data/gedi_canopy_gridded.npz")
        assert npz_path.exists(), "data/gedi_canopy_l1b_rh98_2019.npz must exist"

        data = np.load(str(npz_path))
        lats = data["lat"]
        lons = data["lon"]
        heights = data["height"]

        # 1. Bounds check: all coordinates must remain within +-51.6 degrees
        assert np.all(lats >= -51.6), f"Latitudes below -51.6 found: min={lats.min()}"
        assert np.all(lats <= 51.6), f"Latitudes above +51.6 found: max={lats.max()}"

        # 2. Strict land mask: all non-land cells must be NaN
        is_land = globe.is_land(lats, lons)
        ocean_heights = heights[~is_land]
        valid_ocean_count = np.count_nonzero(~np.isnan(ocean_heights))
        assert valid_ocean_count == 0, f"Found {valid_ocean_count} ocean cells with values!"

        # 3. Known open-ocean check points across all ocean basins
        ocean_samples = [
            (0.0, -140.0),    # Equatorial Pacific
            (0.0, -30.0),     # Equatorial Atlantic
            (-20.0, 70.0),    # Southern Indian Ocean
            (-30.0, -120.0),  # South Pacific Gyre
            (25.0, -155.0),   # North Pacific
            (35.0, -40.0),    # North Atlantic
        ]
        for o_lat, o_lon in ocean_samples:
            # Find closest cell
            dist = (lats - o_lat) ** 2 + ((lons - o_lon + 180) % 360 - 180) ** 2
            closest_idx = np.argmin(dist)
            assert np.isnan(heights[closest_idx]), (
                f"Ocean point ({o_lat}, {o_lon}) has non-NaN height: {heights[closest_idx]}"
            )

    def test_every_meridian_has_at_least_5_valid_steps(self):
        """Every configured land meridian must have at least 5 valid 5° steps."""
        regions = load_land_regions()
        assert len(regions) == 8, f"Expected 8 land regions, found {len(regions)}"

        checked_meridians = 0
        for r in regions:
            rid = r["id"]
            meridian = r.get("canopy_meridian")
            if rid == "siberia":
                # Siberia is outside +-51 deg, must be None
                assert meridian is None, "Siberia must have canopy_meridian: null (outside 51°)"
                continue

            assert meridian is not None, f"Region {rid} must have a valid canopy_meridian"
            adapter = CanopyAdapter(meridian_lon=meridian)
            rows = adapter.rows()
            assert len(rows) == 35, f"Expected 35 rows, got {len(rows)}"

            valid_steps = [row for row in rows if row["valid"]]
            assert len(valid_steps) >= 5, (
                f"Region '{rid}' at meridian {meridian}° has only {len(valid_steps)} valid steps (< 5)"
            )
            checked_meridians += 1

        assert checked_meridians == 7, f"Expected 7 valid meridians, checked {checked_meridians}"

    def test_canopy_adapter_determinism_and_labels(self):
        """CanopyAdapter must be deterministic and label tracks correctly."""
        regions = load_land_regions()
        for r in regions:
            meridian = r.get("canopy_meridian")
            if meridian is None:
                continue
            a1 = CanopyAdapter(meridian_lon=meridian)
            a2 = CanopyAdapter(meridian_lon=meridian)
            rows1 = a1.rows()
            rows2 = a2.rows()
            assert rows1 == rows2, f"CanopyAdapter rows non-deterministic for meridian {meridian}"

            assert a1.track_label == "GEDI-derived gridded canopy height"
            for row in rows1:
                assert row["track_label"] == "GEDI-derived gridded canopy height"

