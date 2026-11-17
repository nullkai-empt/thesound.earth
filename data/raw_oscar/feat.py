import json, os
import numpy as np

DEFAULT_REGIONS = os.path.join("..", "..", "config", "regions.json")

def angle(u, v):
    return float(np.degrees(np.arctan2(v, u)))

# ---------- config ----------
def load_regions(path=DEFAULT_REGIONS, only=None):
    cfg = json.load(open(path, encoding="utf-8"))
    seen, out = set(), []
    for r in cfg["regions"]:
        rid = r["id"]
        if rid in seen:
            raise ValueError(f"duplicate region id: {rid}")
        seen.add(rid)
        lo, hi = r["lat"]; a, b = r["lon"]
        if not (-90 <= lo < hi <= 90):
            raise ValueError(f"{rid}: bad lat range {r['lat']}")
        if not (-360 <= a <= 360 and -360 <= b <= 360) or (b - a) % 360 == 0:
            raise ValueError(f"{rid}: bad lon range {r['lon']}")
        if not r.get("enabled", True):
            continue
        if only and rid not in only:
            continue
        out.append(r)
    if not out:
        raise ValueError("no enabled regions selected")
    return out

# ---------- masks ----------
def lon_mask(lon, a, b):
    lon, a, b = lon % 360, a % 360, b % 360
    return (lon >= a) & (lon <= b) if a <= b else (lon >= a) | (lon <= b)  # wraps 0/360

def lat_mask(lat, lo, hi):
    return (lat >= lo) & (lat <= hi)

GULF = {"id": "gulf_stream", "lat": [30, 40], "lon": [280, 300]}

# ---------- per file ----------
def load_fields(ds):
    ok_all = lambda a: np.isfinite(a) & (a != -999)
    U = ds.u.isel(time=0).values; V = ds.v.isel(time=0).values
    UG = ds.ug.isel(time=0).values; VG = ds.vg.isel(time=0).values
    return {"lon": ds.lon.values, "lat": ds.lat.values,
            "U": U, "V": V, "UG": UG, "VG": VG,
            "mask": ok_all(U) & ok_all(V) & ok_all(UG) & ok_all(VG),
            "date": str(ds.time.values[0])[:10]}

def region_features(F, region):
    bm = np.ix_(lon_mask(F["lon"], *region["lon"]), lat_mask(F["lat"], *region["lat"]))
    ok = F["mask"][bm]
    date, total = F["date"], int(ok.size)
    if ok.sum() == 0:   # all missing -> REST, never zero
        return {"date": date, "valid_cells": 0, "box_cells": total,
                "speed_mean": None, "speed_p95": None}
    u, v, ug, vg = F["U"][bm][ok], F["V"][bm][ok], F["UG"][bm][ok], F["VG"][bm][ok]
    sp = np.hypot(u, v)
    core = sp >= np.percentile(sp, 90)
    eu, ev = u - ug, v - vg
    return {"date": date, "valid_cells": int(ok.sum()), "box_cells": total,
            "speed_mean": float(sp.mean()), "speed_p95": float(np.percentile(sp, 95)),
            "speed_max": float(sp.max()),
            "u_mean": float(u.mean()), "v_mean": float(v.mean()),
            "core_u": float(u[core].mean()), "core_v": float(v[core].mean()),
            "core_angle_deg": angle(u[core].mean(), v[core].mean()),
            "geo_speed_mean": float(np.hypot(ug, vg).mean()),
            "ageo_u": float(eu.mean()), "ageo_v": float(ev.mean()),
            "ageo_speed": float(np.hypot(eu, ev).mean()),
            "ageo_angle_deg": angle(eu.mean(), ev.mean())}

# ---------- old API, kept so nothing else breaks ----------
def day_features(ds):
    F = load_fields(ds)
    f = region_features(F, GULF)
    return F["date"], (f if f["valid_cells"] else None), (F["U"], F["V"], F["mask"])

def globe_blocks(U, V, mask):
    U = np.where(mask, U, 0.0)[:, :712]; V = np.where(mask, V, 0.0)[:, :712]
    m = mask[:, :712]
    r = lambda a: a.reshape(180, 8, 89, 8).sum(axis=(1, 3))
    return r(U), r(V), r(m.astype(np.int32))