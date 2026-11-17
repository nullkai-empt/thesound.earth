from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import xarray as xr


def compute_region_percentiles(nc_path: str | Path) -> dict:
    ds = xr.open_dataset(nc_path, mask_and_scale=True)
    u = ds["u"].values.astype(np.float64)
    v = ds["v"].values.astype(np.float64)

    valid_mask = np.isfinite(u) & np.isfinite(v) & (np.abs(u) <= 10.0) & (np.abs(v) <= 10.0)
    u_valid = u[valid_mask]
    v_valid = v[valid_mask]
    if u_valid.size == 0:
        raise ValueError("No valid ocean cells found in NetCDF file for calibration.")

    speed_valid = np.hypot(u_valid, v_valid)
    return {
        "valid_cell_count": int(u_valid.size),
        "speed_mps": {
            "low": round(float(np.percentile(speed_valid, 5)), 4),
            "high": round(float(np.percentile(speed_valid, 95)), 4),
            "median": round(float(np.median(speed_valid)), 4),
        },
        "u_abs_mps": {
            "low": round(float(np.percentile(np.abs(u_valid), 5)), 4),
            "high": round(float(np.percentile(np.abs(u_valid), 95)), 4),
        },
        "v_abs_mps": {
            "low": round(float(np.percentile(np.abs(v_valid), 5)), 4),
            "high": round(float(np.percentile(np.abs(v_valid), 95)), 4),
        },
    }


if __name__ == "__main__":
    stats = compute_region_percentiles("data/sample_oscar.nc")
    print(json.dumps(stats, indent=2))