"""CanopyAdapter — GEDI-derived gridded canopy height static transect.

Spatial transect of real gridded GEDI canopy height data (April-July 2019,
RH98 canopy top height, 0.5 degree average, model-estimated from GEDI L1B
waveforms; Lang et al. 2022, DOI: 10.5281/zenodo.5704852).  We sonify it as
a **spatial journey**: one bar per 5-degree latitude step along the single
nearest 0.5-degree meridian column within ±51.6°.

  intensity  = mean RH98 canopy top height (m) along the meridian column
  direction  = sign of the height gradient between adjacent bands:
               positive gradient → East (angle 0°)
               negative gradient → West (angle 180°)
               zero / missing    → hold (None magnitude)
  bar_unit   = "transect step"
  Label      = "GEDI-derived gridded canopy height"

The adapter reads from the pre-processed numpy .npz at
data/gedi_canopy_l1b_rh98_2019.npz (or data/gedi_canopy_gridded.npz fallback),
or falls back to synthetic zero-height rows (all None → all rests) so
tests do not need a real file.

The meridian longitude is read from config key "canopy_meridian"
(default 0.0 = Greenwich).  Latitude steps: -85 .. +85 in 5° increments
(35 steps total, with orbital coverage bounded to ±51.6°).
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np

from .base import AdapterBase


class CanopyAdapter(AdapterBase):
    """Spatial transect of GEDI canopy height along a meridian."""

    track_label: str = "GEDI-derived gridded canopy height"

    source_fields: dict[str, str] = {
        "speed_p95": (
            "RH98 canopy top height (m), 0.5 degree average, model-estimated "
            "from GEDI L1B waveforms (April-July 2019 composite; Lang et al. 2022). "
            "This is a spatial journey, not a year."
        ),
        "ageo_angle_deg": (
            "Sign of the latitudinal canopy-height gradient: 0° (East) if "
            "height increases northward, 180° (West) if it decreases. "
            "Every note is computed from the data by rules we chose."
        ),
        "magnitude": (
            "Absolute value of the height gradient (m per 5° step); "
            "below 0.013 the previous chord is held"
        ),
        "ageo_u": "East convention: +1 if gradient positive, -1 if negative",
        "ageo_v": "0 (meridional transect — no north-south flow component)",
    }

    hold_threshold: float = 0.013
    bar_unit: str = "transect step"
    ADAPTER_VERSION: str = "2.0"

    # Latitude steps: centre of each 5-degree band, −85 to +85
    _LAT_CENTRES = list(range(-85, 90, 5))  # −85, −80, …, +85  → 35 steps

    def __init__(
        self,
        npz_path: str | Path | None = None,
        meridian_lon: float = 0.0,
    ) -> None:
        """
        Args:
            npz_path:     Path to a .npz with keys 'lat', 'lon', 'height'.
                          May be None — in that case all rows are rests
                          (useful for tests that do not need real GEDI data).
            meridian_lon: Longitude of the transect (decimal degrees,
                          read from config; default 0.0).
        """
        if npz_path is not None:
            self._npz_path = Path(npz_path)
        else:
            default_p = Path("data/gedi_canopy_l1b_rh98_2019.npz")
            if not default_p.exists():
                default_p = Path("data/gedi_canopy_gridded.npz")
            self._npz_path = default_p if default_p.exists() else None
        self._meridian = meridian_lon

    # ------------------------------------------------------------------
    def rows(self, **kwargs: Any) -> list[dict[str, Any]]:
        """Return one row per 5-degree latitude step (35 rows total)."""
        heights = self._load_heights()
        result: list[dict[str, Any]] = []

        prev_h: float | None = None
        for i, lat in enumerate(self._LAT_CENTRES):
            h = heights[i]
            step_label = f"lat_{lat:+04d}"

            if h is None:
                rr = self.rest_row(step_label)
                rr["track_label"] = self.track_label
                result.append(rr)
                prev_h = None
                continue

            # Gradient relative to previous band
            if prev_h is None:
                grad = 0.0
            else:
                grad = h - prev_h

            abs_grad = abs(grad)

            # Direction: sign of gradient → East / West
            if abs_grad < self.hold_threshold:
                # magnitude below threshold → hold previous chord (None)
                angle = None
                mag = None
                u, v = None, None
            elif grad >= 0:
                angle = 0.0    # East
                mag = abs_grad
                u, v = 1.0, 0.0
            else:
                angle = 180.0  # West
                mag = abs_grad
                u, v = -1.0, 0.0

            result.append({
                "valid": True,
                "speed_p95": h,
                "ageo_u": u,
                "ageo_v": v,
                "ageo_angle_deg": angle,
                "magnitude": mag,
                "date": step_label,
                "track_label": self.track_label,
            })
            prev_h = h

        return result

    # ------------------------------------------------------------------
    def _load_heights(self) -> list[float | None]:
        """Return mean canopy height per latitude band.

        Falls back to all-None (all rests) when no NPZ is available.
        """
        n = len(self._LAT_CENTRES)

        if self._npz_path is None or not self._npz_path.exists():
            return [None] * n

        try:
            data = np.load(str(self._npz_path))
            lats = data["lat"]    # 1-D array of grid-cell latitudes
            lons = data["lon"]    # 1-D array of grid-cell longitudes
            heights = data["height"]  # 1-D array of canopy heights (m)

            # Select the single nearest 0.5-degree meridian column
            unique_lons = np.unique(lons)
            diff = np.abs((unique_lons - self._meridian + 180) % 360 - 180)
            nearest_lon = unique_lons[np.argmin(diff)]
            lon_ok = np.isclose(lons, nearest_lon)
            lats_m = lats[lon_ok]
            hts_m = heights[lon_ok]

            result: list[float | None] = []
            for lat_c in self._LAT_CENTRES:
                band = (lats_m >= lat_c - 2.5) & (lats_m < lat_c + 2.5)
                valid = hts_m[band]
                valid = valid[np.isfinite(valid) & (valid > 0)]
                if valid.size == 0:
                    result.append(None)
                else:
                    result.append(float(valid.mean()))
            return result
        except Exception:
            return [None] * n
