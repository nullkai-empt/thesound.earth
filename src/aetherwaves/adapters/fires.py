"""FIRMSAdapter — NASA FIRMS daily fire detections for a bounding box + year.

Reads MAP_KEY from the env var whose NAME is provided at construction time.
Never hardcodes, logs, or prints the key value.

Distinction between zero detections and API failure:
- API failure (HTTP error, connection timeout, non-200, invalid key):
  returns rest_row (valid: False, speed_p95: None) -> produces a REST bar.
- Successful API query with zero detections:
  returns valid: True, speed_p95: 0.0, magnitude: 0.0 -> zero detections.

Caching:
- Raw daily responses are cached in output/firms_cache/ to prevent
  redundant network calls and rate limiting.

FIRMS CSV API:
  https://firms.modaps.eosdis.nasa.gov/api/area/csv/<MAP_KEY>/<PRODUCT>/
  <west>,<south>,<east>,<north>/<days>/<date>
"""
from __future__ import annotations

import csv
import hashlib
import io
import os
import sys
import time
import urllib.request
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .base import AdapterBase


class FIRMSAdapter(AdapterBase):
    """Fetch NASA FIRMS daily fire detections for a lat/lon bounding box."""

    source_fields: dict[str, str] = {
        "speed_p95": (
            "Count of active-fire detections in the region box for "
            "that day — derived from satellite data. Zero detections = 0.0; "
            "API failure = None (rest)."
        ),
        "ageo_angle_deg": (
            "Conventional direction: 0° (East) used as a fixed convention; "
            "fire detection data does not carry a flow direction. "
            "Every note is computed from the data by rules we chose."
        ),
        "magnitude": "Same as speed_p95 for this adapter",
        "ageo_u": "Conventional: 1.0 (East convention, not from data)",
        "ageo_v": "Conventional: 0.0 (East convention, not from data)",
    }

    hold_threshold: float = 0.013
    bar_unit: str = "day"
    ADAPTER_VERSION: str = "1.1"

    _BASE = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"

    def __init__(
        self,
        map_key_env: str = "FIRMS_MAP_KEY",
        west: float = -65.0,
        south: float = -15.0,
        east: float = -45.0,
        north: float = -3.0,
        year: int = 2025,
        product: str = "VIIRS_SNPP_SP",
        retry: int = 3,
        sleep_s: float = 1.0,
        cache_dir: str | Path = "output/firms_cache",
    ) -> None:
        self._key_env = map_key_env
        self._west = west
        self._south = south
        self._east = east
        self._north = north
        self._year = year
        self._product = product
        self._retry = retry
        self._sleep_s = sleep_s
        self._cache_dir = Path(cache_dir)

    def _get_key(self) -> str:
        key = os.environ.get(self._key_env, "")
        if not key and sys.platform == "win32":
            try:
                import winreg
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as k:
                    key, _ = winreg.QueryValueEx(k, self._key_env)
            except Exception:
                pass
        return key or ""

    def _cache_path(self, day_str: str) -> Path:
        bbox_slug = f"{self._west}_{self._south}_{self._east}_{self._north}_{self._product}"
        sub = self._cache_dir / bbox_slug / str(self._year)
        sub.mkdir(parents=True, exist_ok=True)
        return sub / f"{day_str}.csv"

    def rows(self, **kwargs: Any) -> list[dict[str, Any]]:
        """Return one row per calendar day of self._year."""
        key = self._get_key()
        if not key:
            raise EnvironmentError(
                f"FIRMS MAP_KEY env var '{self._key_env}' is not set. "
                "Set it before running the adapter."
            )

        result: list[dict[str, Any]] = []
        start = date(self._year, 1, 1)
        end = date(self._year, 12, 31)
        day = start
        while day <= end:
            row = self._fetch_day(key, day)
            result.append(row)
            day += timedelta(days=1)
        return result

    def fetch_single_day(self, day: date) -> dict[str, Any]:
        """Fetch and return parsed row for a single day."""
        key = self._get_key()
        if not key:
            raise EnvironmentError(f"FIRMS MAP_KEY env var '{self._key_env}' is not set.")
        return self._fetch_day(key, day)

    def _fetch_day(self, key: str, day: date) -> dict[str, Any]:
        day_str = day.isoformat()
        cp = self._cache_path(day_str)
        if cp.exists():
            try:
                text = cp.read_text(encoding="utf-8")
                return self._parse_csv(text, day_str)
            except Exception:
                pass

        bbox = f"{self._west},{self._south},{self._east},{self._north}"
        url = f"{self._BASE}/{key}/{self._product}/{bbox}/1/{day_str}"
        for attempt in range(self._retry):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "AetherWaves/1.0"})
                with urllib.request.urlopen(req, timeout=20) as resp:
                    if resp.status != 200:
                        continue
                    text = resp.read().decode("utf-8", errors="replace")
                if "Invalid" in text or "Error" in text or "Bad Request" in text:
                    return self.rest_row(day_str)
                # Cache successful response
                tmp = cp.with_suffix(".tmp")
                tmp.write_text(text, encoding="utf-8")
                tmp.replace(cp)
                return self._parse_csv(text, day_str)
            except Exception:
                if attempt < self._retry - 1:
                    time.sleep(self._sleep_s)
        # Failure -> None (rest, never zero)
        return self.rest_row(day_str)

    def _parse_csv(self, text: str, date_str: str) -> dict[str, Any]:
        if "Invalid" in text or "Error" in text:
            return self.rest_row(date_str)

        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)
        # Empty rows = successful query with 0 detections -> valid 0.0
        if not rows:
            return {
                "valid": True,
                "speed_p95": 0.0,
                "ageo_u": 1.0,
                "ageo_v": 0.0,
                "ageo_angle_deg": 0.0,
                "magnitude": 0.0,
                "date": date_str,
            }

        count = len(rows)
        total_frp = 0.0
        for r in rows:
            try:
                total_frp += float(r.get("frp", 0) or 0)
            except (ValueError, TypeError):
                pass

        intensity = float(count) if count > 0 else total_frp
        return {
            "valid": True,
            "speed_p95": intensity,
            "ageo_u": 1.0,
            "ageo_v": 0.0,
            "ageo_angle_deg": 0.0,
            "magnitude": intensity,
            "date": date_str,
        }
