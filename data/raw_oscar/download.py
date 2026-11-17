import json, os, sys, time, argparse
import earthaccess, xarray as xr
from feat import load_regions, load_fields, region_features

def out_path(rid, year):
    if rid == "gulf_stream":                    # legacy location, so blocks.py still works
        return f"oscar_{year}_daily.json"
    d = os.path.join("regions", rid); os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"oscar_{year}_daily.json")

def save(path, rows):
    rows.sort(key=lambda o: o["date"])
    json.dump(rows, open(path + ".tmp", "w"), indent=1)
    os.replace(path + ".tmp", path)

def run_year(year, regions):
    data, done = {}, {}
    for g in regions:
        p = out_path(g["id"], year)
        data[g["id"]] = json.load(open(p)) if os.path.exists(p) else []
        done[g["id"]] = {o["date"] for o in data[g["id"]]}
    res = earthaccess.search_data(short_name="OSCAR_L4_OC_FINAL_V2.0",
                                  temporal=(f"{year}-01-01", f"{year}-12-31"))
    print(year, "files found:", len(res), flush=True)
    for i, item in enumerate(res):
        name = item.data_links()[0].split("/")[-1]
        d = name.split("_")[-1][:8]; date = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
        need = [g for g in regions if date not in done[g["id"]]]
        if not need:
            continue
        f = ds = None
        try:
            f = str(earthaccess.download([item], "tmp")[0])
            ds = xr.open_dataset(f)
            F = load_fields(ds)
            if F["date"] != date:
                raise ValueError(f"file date {date} != data date {F['date']}")
            for g in need:
                data[g["id"]].append(region_features(F, g))
                done[g["id"]].add(date)
                save(out_path(g["id"], year), data[g["id"]])
            print(i + 1, "/", len(res), date, [g["id"] for g in need], flush=True)
        except Exception as e:
            print("FAILED", date, repr(e), flush=True); time.sleep(3)
        finally:
            if ds is not None: ds.close()
            if f and os.path.exists(f): os.remove(f)   # always delete the download
    print("done", year, {k: len(v) for k, v in data.items()})

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("years", nargs="+", type=int)
    ap.add_argument("--regions", default=None)
    ap.add_argument("--only", default=None, help="comma-separated region ids")
    a = ap.parse_args()
    regions = load_regions(a.regions or os.path.join("..", "..", "config", "regions.json"),
                           only=a.only.split(",") if a.only else None)
    earthaccess.login()
    os.makedirs("tmp", exist_ok=True)
    for y in a.years:
        run_year(y, regions)