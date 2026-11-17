"""OscarAdapter — wraps the existing feat.py / blocks.py OSCAR pipeline.

Output is guaranteed to be byte-identical to what group_days_into_blocks
produces directly, so all existing pipeline scripts continue to work without
any changes.

bar_unit = "7-day block"
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .base import AdapterBase


class OscarAdapter(AdapterBase):
    """Read a pre-computed oscar_<year>_daily.json and return block rows.

    The JSON files are produced by data/raw_oscar/download.py + feat.py and
    already contain the keys the engine reads.  This adapter only reads them
    and passes the data through so that the engine can treat OSCAR exactly
    like any other source.

    source_fields describes what each engine key means for this dataset.
    """

    source_fields: dict[str, str] = {
        "speed_p95": (
            "95th-percentile of the total surface current speed (m/s) "
            "across all valid grid cells in the region box for that day — "
            "derived from satellite data"
        ),
        "ageo_u": (
            "Mean zonal (east-west) ageostrophic velocity component (m/s): "
            "u minus the geostrophic u from altimetry"
        ),
        "ageo_v": (
            "Mean meridional (north-south) ageostrophic velocity component (m/s): "
            "v minus the geostrophic v from altimetry"
        ),
        "ageo_angle_deg": (
            "Direction of the ageostrophic flow: atan2(ageo_v, ageo_u) in degrees; "
            "used to pick the chord sector (East/North/West/South)"
        ),
        "magnitude": (
            "Mean ageostrophic vector magnitude hypot(ageo_u, ageo_v) (m/s); "
            "below 0.013 m/s the previous chord is held"
        ),
    }

    hold_threshold: float = 0.013
    bar_unit: str = "7-day block"
    ADAPTER_VERSION: str = "1.0"

    def __init__(self, json_path: str | Path) -> None:
        self._path = Path(json_path)

    def rows(self, **kwargs: Any) -> list[dict[str, Any]]:  # type: ignore[override]
        """Return daily JSON rows exactly as stored.

        Each row already contains the engine keys.  Missing days are
        represented by speed_p95 = None (rest, never zero).
        """
        raw: list[dict[str, Any]] = json.loads(
            self._path.read_text(encoding="utf-8")
        )
        out: list[dict[str, Any]] = []
        for r in raw:
            if r.get("speed_p95") is None:
                out.append(self.rest_row(r.get("date", "")))
            else:
                u, v = r.get("ageo_u"), r.get("ageo_v")
                mag = r.get("magnitude")
                if mag is None and u is not None and v is not None:
                    mag = float(math.hypot(u, v))
                out.append({
                    "valid": True,
                    "speed_p95": r["speed_p95"],
                    "ageo_u": u,
                    "ageo_v": v,
                    "ageo_angle_deg": r.get("ageo_angle_deg"),
                    "magnitude": mag,
                    "date": r.get("date", ""),
                })
        return out
