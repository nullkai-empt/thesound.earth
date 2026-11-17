from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

# NASA PO.DAAC OSCAR Cumulus Protected Endpoints
PODAAC_BASE_FINAL = "https://archive.podaac.earthdata.nasa.gov/podaac-ops-cumulus-protected/OSCAR_L4_OC_FINAL_V2.0"
PODAAC_BASE_INTERIM = "https://archive.podaac.earthdata.nasa.gov/podaac-ops-cumulus-protected/OSCAR_L4_OC_INTERIM_V2.0"


def generate_target_dates(months: list[str] | None = None) -> list[str]:
    """
    Generate daily ISO date strings (YYYY-MM-DD) for target months.
    Default: Jan 2026, Jun 2026, Dec 2025.
    """
    if months is None:
        months = ["2025-12", "2026-01", "2026-06"]

    dates: list[str] = []
    for ym in months:
        year, month = map(int, ym.split("-"))
        # Determine number of days in month
        if month in (1, 3, 5, 7, 8, 10, 12):
            num_days = 31
        elif month in (4, 6, 9, 11):
            num_days = 30
        else:
            # Leap year check for February
            num_days = 29 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 28

        for d in range(1, num_days + 1):
            dates.append(f"{year:04d}-{month:02d}-{d:02d}")
    return dates


def find_local_file(date_str: str, raw_dir: Path) -> Path | None:
    """Check if file exists locally in raw_dir (e.g. data/raw_oscar/)."""
    compact = date_str.replace("-", "")
    for variant in ["final", "interim"]:
        fname = f"oscar_currents_{variant}_{compact}.nc"
        candidate = raw_dir / fname
        if candidate.exists() and candidate.stat().st_size > 1000:
            return candidate
    return None


def download_daily_file(
    date_str: str,
    dest_path: Path,
    user: str | None = None,
    password: str | None = None,
) -> bool:
    """
    Download a single daily OSCAR file via curl.
    Tries FINAL variant first, then INTERIM.
    Returns True if downloaded successfully, False otherwise.
    """
    compact = date_str.replace("-", "")
    auth_args: list[str] = []
    if user and password:
        auth_args = ["-u", f"{user}:{password}"]

    for variant, base_url in [("final", PODAAC_BASE_FINAL), ("interim", PODAAC_BASE_INTERIM)]:
        url = f"{base_url}/oscar_currents_{variant}_{compact}.nc"
        cmd = ["curl.exe", "-s", "-L", "-f", "-o", str(dest_path), url] + auth_args
        res = subprocess.run(cmd, capture_output=True)
        if res.returncode == 0 and dest_path.exists() and dest_path.stat().st_size > 10000:
            return True
        if dest_path.exists():
            dest_path.unlink(missing_ok=True)
    return False


def extract_box_from_dataset(
    ds: xr.Dataset,
    lat_min: float = 30.0,
    lat_max: float = 40.0,
    lon_min: float = 280.0,
    lon_max: float = 300.0,
) -> dict[str, Any]:
    """
    Extract mean u, mean v, and mean speed in the bounding box.
    Treat -999, non-finite, and unreasonable magnitudes as missing.
    If the whole box is missing, returns mean values as None.
    """
    lat_coord_name = "lat" if "lat" in ds.coords else "latitude"
    lon_coord_name = "lon" if "lon" in ds.coords else "longitude"

    lat_vals = ds[lat_coord_name].values
    lon_vals = ds[lon_coord_name].values

    lat_idx = np.where((lat_vals >= lat_min) & (lat_vals <= lat_max))[0]
    lon_idx = np.where((lon_vals >= lon_min) & (lon_vals <= lon_max))[0]

    if len(lat_idx) == 0 or len(lon_idx) == 0:
        return {"mean_u": None, "mean_v": None, "mean_speed": None, "count_valid": 0}

    u_data = ds["u"].values
    v_data = ds["v"].values

    # Handle shape dimensions (e.g. time, lon, lat or time, lat, lon)
    if u_data.ndim == 3:
        u_slice = u_data[0]
        v_slice = v_data[0]
    else:
        u_slice = u_data
        v_slice = v_data

    # Slice according to dimension ordering
    if u_slice.shape == (len(lon_vals), len(lat_vals)):
        u_box = u_slice[np.ix_(lon_idx, lat_idx)]
        v_box = v_slice[np.ix_(lon_idx, lat_idx)]
    elif u_slice.shape == (len(lat_vals), len(lon_vals)):
        u_box = u_slice[np.ix_(lat_idx, lon_idx)]
        v_box = v_slice[np.ix_(lat_idx, lon_idx)]
    else:
        raise ValueError(f"Unexpected data shape: {u_slice.shape}")

    # Valid mask: not -999, finite, physical bounds
    valid = (
        (u_box != -999.0)
        & (v_box != -999.0)
        & np.isfinite(u_box)
        & np.isfinite(v_box)
        & (np.abs(u_box) <= 10.0)
        & (np.abs(v_box) <= 10.0)
    )

    count_valid = int(valid.sum())
    if count_valid == 0:
        return {"mean_u": None, "mean_v": None, "mean_speed": None, "count_valid": 0}

    u_valid = u_box[valid]
    v_valid = v_box[valid]
    speed_valid = np.sqrt(u_valid**2 + v_valid**2)

    return {
        "mean_u": round(float(np.mean(u_valid)), 4),
        "mean_v": round(float(np.mean(v_valid)), 4),
        "mean_speed": round(float(np.mean(speed_valid)), 4),
        "count_valid": count_valid,
    }


def normalize_series_5_95(
    records: list[dict[str, Any]],
) -> tuple[list[float | None], dict[str, Any]]:
    """
    Normalize speed series using 5th and 95th percentiles of valid samples,
    clamped to [0.0, 1.0]. Keeps raw values for audit.
    """
    valid_speeds = [r["mean_speed"] for r in records if r.get("mean_speed") is not None]
    if not valid_speeds:
        return [None] * len(records), {"p5": None, "p95": None}

    p5 = float(np.percentile(valid_speeds, 5.0))
    p95 = float(np.percentile(valid_speeds, 95.0))
    p_range = max(1e-6, p95 - p5)

    normalized: list[float | None] = []
    for r in records:
        sp = r.get("mean_speed")
        if sp is None:
            normalized.append(None)
        else:
            norm_val = float(np.clip((sp - p5) / p_range, 0.0, 1.0))
            normalized.append(round(norm_val, 4))

    audit = {
        "p5_speed": round(p5, 4),
        "p95_speed": round(p95, 4),
        "min_raw_speed": round(float(np.min(valid_speeds)), 4),
        "max_raw_speed": round(float(np.max(valid_speeds)), 4),
        "sample_count": len(valid_speeds),
        "total_days": len(records),
    }
    return normalized, audit


def process_region(
    dates: list[str],
    raw_dir: Path = Path("data/raw_oscar"),
    out_json: Path = Path("output/region_box_stats.json"),
    user: str | None = None,
    password: str | None = None,
) -> list[dict[str, Any]]:
    """
    Process daily OSCAR files one by one for specified box (lat 30-40, lon 280-300).
    Deletes any temporary download immediately after extraction.
    """
    out_json.parent.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []

    print(f"Processing region box (lat 30-40, lon 280-300) for {len(dates)} dates...")

    for idx, date_str in enumerate(dates):
        local_file = find_local_file(date_str, raw_dir)
        is_temp = False
        target_path: Path | None = local_file

        if target_path is None:
            # Download to temporary file
            temp_file = Path(tempfile.gettempdir()) / f"oscar_temp_{date_str}.nc"
            success = download_daily_file(date_str, temp_file, user=user, password=password)
            if success:
                target_path = temp_file
                is_temp = True
            else:
                print(f"[{idx+1}/{len(dates)}] {date_str}: Not found locally & download unavailable. Recording None.")
                results.append({
                    "date": date_str,
                    "mean_u": None,
                    "mean_v": None,
                    "mean_speed": None,
                    "count_valid": 0,
                })
                continue

        try:
            with xr.open_dataset(target_path) as ds:
                stats = extract_box_from_dataset(ds, 30.0, 40.0, 280.0, 300.0)
                record = {"date": date_str, **stats}
                results.append(record)
                spd_str = f"{record['mean_speed']:.4f} m/s" if record["mean_speed"] is not None else "None"
                print(f"[{idx+1}/{len(dates)}] {date_str}: speed={spd_str}, valid_cells={record['count_valid']}")
        except Exception as exc:
            print(f"[{idx+1}/{len(dates)}] {date_str}: Error extracting: {exc}")
            results.append({
                "date": date_str,
                "mean_u": None,
                "mean_v": None,
                "mean_speed": None,
                "count_valid": 0,
            })
        finally:
            # Delete download immediately after use
            if is_temp and target_path and target_path.exists():
                try:
                    target_path.unlink()
                except OSError:
                    pass

    # Save to JSON
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print(f"Saved {len(results)} records to {out_json}")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract daily mean OSCAR current for box lat 30-40, lon 280-300")
    parser.add_argument("--months", nargs="+", default=["2025-12", "2026-01", "2026-06"], help="Months to process (YYYY-MM)")
    parser.add_argument("--dates", nargs="+", default=None, help="Explicit dates to process (YYYY-MM-DD)")
    parser.add_argument("--raw-dir", type=str, default="data/raw_oscar", help="Local directory with raw NetCDF files")
    parser.add_argument("--out", type=str, default="output/region_box_stats.json", help="Output JSON path")
    parser.add_argument("--user", type=str, default=os.getenv("EARTHDATA_USER"), help="NASA Earthdata username")
    parser.add_argument("--password", type=str, default=os.getenv("EARTHDATA_PASSWORD"), help="NASA Earthdata password")
    args = parser.parse_args()

    dates = args.dates if args.dates else generate_target_dates(args.months)
    process_region(
        dates=dates,
        raw_dir=Path(args.raw_dir),
        out_json=Path(args.out),
        user=args.user,
        password=args.password,
    )


if __name__ == "__main__":
    main()
