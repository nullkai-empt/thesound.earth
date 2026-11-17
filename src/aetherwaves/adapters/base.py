"""AdapterBase — abstract base class every adapter must implement.

Each adapter converts a raw data source into a list of row dicts that the
AetherWaves engine already understands.  Every row that has real data must
contain at least:

    speed_p95       float   intensity signal (may be re-labelled per adapter)
    ageo_u          float   zonal component (or proxy)
    ageo_v          float   meridional component (or proxy)
    ageo_angle_deg  float   direction in degrees
    magnitude       float   combined vector magnitude
    date            str     ISO-8601 date OR step label
    valid           bool    True if this row has real data

If a row has no data (missing / black frame / no detections), the dict must
be {valid: False, speed_p95: None, ...} — this produces a silent REST bar.
Never return zero in place of None.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class AdapterBase(ABC):
    """Abstract base for every AetherWaves data adapter.

    Subclasses must set class-level attributes:
        source_fields   dict[str, str]  key → human-readable description
        hold_threshold  float           magnitude below which chord is held
        bar_unit        str             label for one bar (shown on site)
        ADAPTER_VERSION str             bump when cache-breaking changes are made
    """

    source_fields: dict[str, str] = {}
    hold_threshold: float = 0.013
    bar_unit: str = "data unit"
    ADAPTER_VERSION: str = "1.0"

    @abstractmethod
    def rows(self, **kwargs: Any) -> list[dict[str, Any]]:
        """Return a list of engine-compatible row dicts.

        Missing / uncomputable rows must be represented as:
            {"valid": False, "speed_p95": None, "ageo_u": None,
             "ageo_v": None, "ageo_angle_deg": None, "magnitude": None,
             "date": <label>}
        Never return zero in place of None.
        """

    # ------------------------------------------------------------------
    # Shared helper
    # ------------------------------------------------------------------
    @staticmethod
    def rest_row(date: str) -> dict[str, Any]:
        """Return a canonical missing-data (REST) row."""
        return {
            "valid": False,
            "speed_p95": None,
            "ageo_u": None,
            "ageo_v": None,
            "ageo_angle_deg": None,
            "magnitude": None,
            "date": date,
        }


def load_land_regions(
    path: str | Path = "config/land_regions.json",
    only: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Load and validate land regions from configuration JSON."""
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        cfg = json.load(f)

    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for r in cfg.get("regions", []):
        rid = r.get("id")
        if not rid:
            raise ValueError("Region missing id")
        if rid in seen:
            raise ValueError(f"duplicate region id: {rid}")
        seen.add(rid)

        # Validate box (check top-level or nested under fires)
        lat = r.get("lat") or (r.get("fires", {}).get("lat"))
        lon = r.get("lon") or (r.get("fires", {}).get("lon"))
        if not lat or len(lat) != 2:
            raise ValueError(f"{rid}: missing or invalid lat range: {lat}")
        if not lon or len(lon) != 2:
            raise ValueError(f"{rid}: missing or invalid lon range: {lon}")
        lo, hi = lat
        a, b = lon
        if not (-90 <= lo < hi <= 90):
            raise ValueError(f"{rid}: bad lat range {lat}")
        if not (-360 <= a <= 360 and -360 <= b <= 360) or (b - a) % 360 == 0 or a >= b:
            raise ValueError(f"{rid}: bad lon range {lon}")

        cm = r.get("canopy_meridian")
        if cm is not None:
            if not (-360 <= cm <= 360):
                raise ValueError(f"{rid}: bad canopy meridian {cm}")

        if not r.get("enabled", True):
            continue
        if only and rid not in only:
            continue
        out.append(r)

    if not out:
        raise ValueError("no enabled land regions found")
    return out
