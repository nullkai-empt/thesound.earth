from __future__ import annotations
from functools import lru_cache
from pathlib import Path
import xarray as xr


@lru_cache(maxsize=4)
def load_oscar_dataset(nc_path: str | Path) -> xr.Dataset:
    path = Path(nc_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"OSCAR NetCDF file not found: {path}")
    return xr.open_dataset(path, mask_and_scale=True)


def extract_cell_timeseries(
    ds: xr.Dataset,
    target_lat: float,
    target_lon: float,
    use_geostrophic: bool = False,
) -> list[dict]:
    u_var, v_var = ("ug", "vg") if use_geostrophic else ("u", "v")
    if u_var not in ds.variables or v_var not in ds.variables:
        raise KeyError(f"Expected variables '{u_var}' and '{v_var}' in dataset.")

    lat_dim = "latitude" if "latitude" in ds.coords else "lat"
    lon_dim = "longitude" if "longitude" in ds.coords else "lon"

    cell = ds.sel({lat_dim: target_lat, lon_dim: target_lon}, method="nearest")
    actual_lat = float(cell[lat_dim].values)
    actual_lon = float(cell[lon_dim].values)
    units = str(ds[u_var].attrs.get("units", "unknown"))
    title = str(ds.attrs.get("title", "OSCAR_V2.0"))

    variant = "UNKNOWN"
    upper_title = title.upper()
    if "FINAL" in upper_title:
        variant = "FINAL"
    elif "NRT" in upper_title or "NEAR" in upper_title:
        variant = "NRT"
    elif "INTERIM" in upper_title:
        variant = "INTERIM"

    records: list[dict] = []
    times = cell["time"].values if "time" in cell.coords else [None]
    u_vals = cell[u_var].values
    v_vals = cell[v_var].values

    for idx, t in enumerate(times):
        u_raw = float(u_vals[idx]) if u_vals.ndim > 0 else float(u_vals)
        v_raw = float(v_vals[idx]) if v_vals.ndim > 0 else float(v_vals)
        records.append({
            "timestamp": str(t)[:10] if t is not None else "unknown",
            "latitude": actual_lat,
            "longitude": actual_lon,
            "u": u_raw,
            "v": v_raw,
            "units": units,
            "product_variant": variant,
            "dataset_name": title,
        })
    return records