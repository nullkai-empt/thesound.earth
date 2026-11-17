from pathlib import Path
import numpy as np
from global_land_mask import globe
from aetherwaves.adapters import CanopyAdapter, load_land_regions

npz_file = "data/gedi_canopy_l1b_rh98_2019.npz"
if not Path(npz_file).exists():
    npz_file = "data/gedi_canopy_gridded.npz"
data = np.load(npz_file)
lats = data["lat"]
lons = data["lon"]
heights = data["height"]

# Check ocean points
is_land = globe.is_land(lats, lons)
ocean_heights = heights[~is_land]
valid_ocean = np.count_nonzero(~np.isnan(ocean_heights))
print(f"Ocean points with values: {valid_ocean} (strictly 0)")

regions = load_land_regions()
for r in regions:
    rid = r["id"]
    meridian = r.get("canopy_meridian")
    print("=" * 72)
    if meridian is None:
        print(f"Region: {rid} (Siberia: latitude box > 51.6°N -> canopy_meridian: None)")
        print("=" * 72)
        continue
    
    adapter = CanopyAdapter(meridian_lon=meridian)
    rows = adapter.rows()
    print(f"Region: {rid} | Meridian: {meridian:+.1f}° | Track Label: \"{adapter.track_label}\"")
    print(f"Total steps: {len(rows)} | Valid land steps: {sum(1 for x in rows if x['valid'])}")
    print("-" * 72)
    print(f"{'Step':<10} | {'Band':<14} | {'Height (m)':<12} | {'Angle':<8} | {'Magnitude':<10} | {'Valid':<6}")
    print("-" * 72)
    for x in rows:
        lat_val = int(x["date"].replace("lat_", ""))
        band_str = f"[{lat_val-2.5:+.1f}, {lat_val+2.5:+.1f}]"
        h_str = f"{x['speed_p95']:.2f}" if x["speed_p95"] is not None else "None (Rest)"
        ang_str = f"{x['ageo_angle_deg']:.0f}°" if x["ageo_angle_deg"] is not None else "-"
        mag_str = f"{x['magnitude']:.3f}" if x["magnitude"] is not None else "-"
        if abs(lat_val) <= 55:
            print(f"{x['date']:<10} | {band_str:<14} | {h_str:<12} | {ang_str:<8} | {mag_str:<10} | {str(x['valid']):<6}")
