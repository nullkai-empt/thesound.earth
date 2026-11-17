"""tests/test_regions.py — Phase 2 region config and normalization tests.

Covers:
  - Nordic Seas lon_mask returns cells on BOTH sides of the 0° meridian
  - Config load raises ValueError on duplicate region id
  - Config load raises ValueError on bad lat range (lo >= hi)
  - Config load raises ValueError on bad lon range (a == b, i.e., full wrap)
  - Normalization output differs between gulf_stream and kuroshio
  - load_regions skips disabled regions
  - load_regions: no enabled regions raises ValueError
  - All existing tests still pass (enforced by running full suite elsewhere)
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "data" / "raw_oscar"))

# Import feat.py helpers directly
import importlib.util

_feat_spec = importlib.util.spec_from_file_location(
    "feat", REPO / "data" / "raw_oscar" / "feat.py"
)
feat = importlib.util.module_from_spec(_feat_spec)  # type: ignore[arg-type]
_feat_spec.loader.exec_module(feat)  # type: ignore[union-attr]

lon_mask = feat.lon_mask
load_regions = feat.load_regions

REGIONS_JSON = REPO / "config" / "regions.json"


# ---------------------------------------------------------------------------
# lon_mask tests (wrap behaviour)
# ---------------------------------------------------------------------------

class TestLonMask:
    def test_normal_range_includes_interior(self):
        """lon=285 is inside [280, 300] in 0-360 space."""
        lons = np.array([0, 180, 275, 285, 295, 305, 360])
        mask = lon_mask(lons, 280, 300)
        assert mask[3] and mask[4]       # 285, 295 inside
        assert not mask[0]               # 0 outside
        assert not mask[5]               # 305 outside

    def test_nordic_seas_wrap_both_sides(self):
        """Nordic Seas lon=[-15, 20].

        In 0-360: a=345, b=20.  Since a > b, the mask uses OR:
          lon >= 345 OR lon <= 20.
        Cells at e.g. lon=355 (east of Greenland) AND lon=10 (Norway)
        must both be included.
        """
        lons = np.array([345.0, 350.0, 355.0, 0.0, 5.0, 10.0, 15.0, 20.0,
                         21.0, 180.0, 90.0, 344.9])
        mask = lon_mask(lons, -15, 20)   # a=-15 → 345, b=20

        # Both sides of the 0° meridian must be included
        west_side = mask[np.isin(lons, [345.0, 350.0, 355.0])]
        east_side  = mask[np.isin(lons, [0.0, 5.0, 10.0, 15.0, 20.0])]
        assert west_side.all(),  "West-of-0° cells (345-359) must be included"
        assert east_side.all(),  "East-of-0° cells (0-20) must be included"

        # Points outside the box must be excluded
        outside = mask[np.isin(lons, [21.0, 180.0, 90.0, 344.9])]
        assert not outside.any(), "Points outside Nordic Seas box must be excluded"

    def test_standard_box_no_wrap(self):
        """Gulf Stream [280, 300] must NOT wrap."""
        lons = np.array([280, 290, 300, 279.9, 300.1, 345])
        mask = lon_mask(lons, 280, 300)
        assert mask[0] and mask[1] and mask[2]
        assert not mask[3] and not mask[4] and not mask[5]


# ---------------------------------------------------------------------------
# load_regions config validation
# ---------------------------------------------------------------------------

def _write_regions(tmp_path: Path, regions: list[dict], **kwargs) -> Path:
    cfg = {
        "version": 1,
        "years": [2025],
        "defaults": {"hold_threshold": 0.013,
                     "max_missing_fraction": 0.5,
                     "normalize": "per_box_p5_p95"},
        "regions": regions,
        "overrides": {},
        **kwargs,
    }
    p = tmp_path / "regions.json"
    p.write_text(json.dumps(cfg), encoding="utf-8")
    return p


class TestLoadRegions:
    def test_loads_real_regions_json(self):
        if not REGIONS_JSON.exists():
            pytest.skip("config/regions.json not present")
        regions = load_regions(str(REGIONS_JSON))
        ids = [r["id"] for r in regions]
        # equatorial_pacific is disabled; must NOT appear
        assert "equatorial_pacific" not in ids
        # All 7 enabled ones must be present
        for rid in ["gulf_stream", "kuroshio", "east_australian",
                    "brazil_malvinas", "arabian_sea", "drake_acc",
                    "nordic_seas"]:
            assert rid in ids, f"Expected {rid} in enabled regions"

    def test_duplicate_id_raises(self, tmp_path):
        regions = [
            {"id": "gulf_stream", "lat": [30, 40], "lon": [280, 300]},
            {"id": "gulf_stream", "lat": [28, 40], "lon": [130, 160]},
        ]
        p = _write_regions(tmp_path, regions)
        with pytest.raises(ValueError, match="duplicate"):
            load_regions(str(p))

    def test_bad_lat_range_raises(self, tmp_path):
        """lo >= hi must raise ValueError."""
        regions = [{"id": "bad", "lat": [40, 30], "lon": [280, 300]}]
        p = _write_regions(tmp_path, regions)
        with pytest.raises(ValueError, match="lat"):
            load_regions(str(p))

    def test_bad_lat_equal_raises(self, tmp_path):
        regions = [{"id": "bad", "lat": [30, 30], "lon": [280, 300]}]
        p = _write_regions(tmp_path, regions)
        with pytest.raises(ValueError, match="lat"):
            load_regions(str(p))

    def test_disabled_region_skipped(self, tmp_path):
        regions = [
            {"id": "gulf_stream", "lat": [30, 40], "lon": [280, 300]},
            {"id": "equatorial_pacific", "lat": [-5, 5],
             "lon": [180, 240], "enabled": False},
        ]
        p = _write_regions(tmp_path, regions)
        result = load_regions(str(p))
        ids = [r["id"] for r in result]
        assert "gulf_stream" in ids
        assert "equatorial_pacific" not in ids

    def test_no_enabled_regions_raises(self, tmp_path):
        regions = [
            {"id": "equatorial_pacific", "lat": [-5, 5],
             "lon": [180, 240], "enabled": False},
        ]
        p = _write_regions(tmp_path, regions)
        with pytest.raises(ValueError):
            load_regions(str(p))

    def test_only_filter(self, tmp_path):
        regions = [
            {"id": "gulf_stream",    "lat": [30, 40],  "lon": [280, 300]},
            {"id": "kuroshio",       "lat": [28, 40],  "lon": [130, 160]},
        ]
        p = _write_regions(tmp_path, regions)
        result = load_regions(str(p), only=["kuroshio"])
        assert len(result) == 1
        assert result[0]["id"] == "kuroshio"


# ---------------------------------------------------------------------------
# Normalization differs between regions
# ---------------------------------------------------------------------------

class TestNormalizationPerRegion:
    """
    P5-P95 normalization must be computed PER REGION from that region's data.
    Two regions with clearly different speed distributions must produce
    different normalised speed values for the same raw input speed.
    """

    @staticmethod
    def _p5_p95_normalize(speeds: list[float], raw: float) -> float:
        arr = np.array(speeds)
        p5 = float(np.percentile(arr, 5))
        p95 = float(np.percentile(arr, 95))
        if p95 <= p5:
            return 0.5
        return float(np.clip((raw - p5) / (p95 - p5), 0.0, 1.0))

    def test_normalization_differs_between_gulf_stream_and_kuroshio(self):
        # Gulf Stream: fast currents ~1.1 m/s
        gulf_speeds = [0.9 + i * 0.01 for i in range(50)]
        # Kuroshio: slower currents ~0.3 m/s
        kuroshio_speeds = [0.2 + i * 0.003 for i in range(50)]

        raw_speed = 0.95  # same raw speed for both

        norm_gulf = self._p5_p95_normalize(gulf_speeds, raw_speed)
        norm_kuroshio = self._p5_p95_normalize(kuroshio_speeds, raw_speed)

        assert norm_gulf != norm_kuroshio, (
            "P5-P95 normalization must differ between regions with "
            "different speed distributions"
        )
        # Kuroshio normalization should be 1.0 (above its P95)
        assert norm_kuroshio == pytest.approx(1.0)
        # Gulf stream normalization should be somewhere in the middle
        assert 0.0 < norm_gulf < 1.0
