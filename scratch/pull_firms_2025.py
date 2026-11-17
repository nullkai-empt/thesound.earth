"""Pull NASA FIRMS daily active fire detections for land regions in 2025.

Processes one region at a time. Caches each day to output/firms_cache.
Stops immediately if any API error occurs.
"""
from __future__ import annotations

import csv
import io
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import date, timedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from aetherwaves.adapters import load_land_regions, FIRMSAdapter

REPO_ROOT = Path(__file__).resolve().parent.parent

HEADER = (
    "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,"
    "confidence,version,bright_ti5,frp,daynight\n"
)


def get_api_key() -> str:
    key = os.environ.get("FIRMS_MAP_KEY", "")
    if not key and sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as k:
                key, _ = winreg.QueryValueEx(k, "FIRMS_MAP_KEY")
        except Exception:
            pass
    return key or ""


def fetch_chunk(key: str, product: str, bbox: str, chunk_start: date, num_days: int, retries: int = 3) -> tuple[date, int, str]:
    day_str = chunk_start.isoformat()
    url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/{product}/{bbox}/{num_days}/{day_str}"
    req = urllib.request.Request(url, headers={"User-Agent": "AetherWaves/1.0"})
    
    last_status = -1
    last_text = ""
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=40) as resp:
                status = resp.status
                text = resp.read().decode("utf-8", errors="replace")
            if "Invalid" in text or "Error" in text or "Bad Request" in text:
                clean_text = text.replace(key, "[REDACTED]")
                last_status = 400
                last_text = f"API Error: {clean_text.strip()}"
                if "limit" in text.lower() and num_days > 1:
                    single_day_texts = []
                    sub_success = True
                    for i in range(num_days):
                        sub_day = chunk_start + timedelta(days=i)
                        sub_url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/{product}/{bbox}/1/{sub_day.isoformat()}"
                        sub_req = urllib.request.Request(sub_url, headers={"User-Agent": "AetherWaves/1.0"})
                        try:
                            with urllib.request.urlopen(sub_req, timeout=40) as sresp:
                                stxt = sresp.read().decode("utf-8", errors="replace")
                                single_day_texts.append(stxt)
                        except Exception:
                            sub_success = False
                            break
                    if sub_success:
                        combined_lines = []
                        for idx, stxt in enumerate(single_day_texts):
                            lines = stxt.strip().splitlines()
                            if idx == 0:
                                combined_lines.extend(lines)
                            else:
                                combined_lines.extend(lines[1:])
                        return chunk_start, 200, "\n".join(combined_lines) + "\n"
                time.sleep(1.5)
                continue
            return chunk_start, status, text
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            clean_msg = err_body.replace(key, "[REDACTED]")
            last_status = e.code
            last_text = clean_msg
            if ("limit" in last_text.lower() or "transaction" in last_text.lower()) and num_days > 1:
                single_day_texts = []
                sub_success = True
                for i in range(num_days):
                    sub_day = chunk_start + timedelta(days=i)
                    sub_url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/{product}/{bbox}/1/{sub_day.isoformat()}"
                    sub_req = urllib.request.Request(sub_url, headers={"User-Agent": "AetherWaves/1.0"})
                    try:
                        with urllib.request.urlopen(sub_req, timeout=40) as sresp:
                            stxt = sresp.read().decode("utf-8", errors="replace")
                            single_day_texts.append(stxt)
                    except Exception:
                        sub_success = False
                        break
                if sub_success:
                    combined_lines = []
                    for idx, stxt in enumerate(single_day_texts):
                        lines = stxt.strip().splitlines()
                        if idx == 0:
                            combined_lines.extend(lines)
                        else:
                            combined_lines.extend(lines[1:])
                    return chunk_start, 200, "\n".join(combined_lines) + "\n"
            time.sleep(1.5)
        except Exception as e:
            clean_msg = str(e).replace(key, "[REDACTED]")
            last_status = -1
            last_text = clean_msg
            time.sleep(1.5)
            
    return chunk_start, last_status, last_text


def pull_region(region: dict, key: str, cache_dir: Path, workers: int = 1, delay: float = 0.5) -> dict:
    rid = region["id"]
    lat_lo, lat_hi = region["lat"]
    lon_a, lon_b = region["lon"]
    product = "VIIRS_SNPP_SP"
    year = 2025

    bbox_slug = f"{lon_a}_{lat_lo}_{lon_b}_{lat_hi}_{product}"
    sub_dir = cache_dir / bbox_slug / str(year)
    sub_dir.mkdir(parents=True, exist_ok=True)

    # 1. Determine which days need fetching
    start_date = date(year, 1, 1)
    end_date = date(year, 12, 31)

    # Group into 5-day chunks
    chunks_to_fetch: list[tuple[date, int]] = []
    curr = start_date
    while curr <= end_date:
        days_in_chunk = min(5, (end_date - curr).days + 1)
        needed = False
        for i in range(days_in_chunk):
            d_str = (curr + timedelta(days=i)).isoformat()
            if not (sub_dir / f"{d_str}.csv").exists():
                needed = True
                break
        if needed:
            chunks_to_fetch.append((curr, days_in_chunk))
        curr += timedelta(days=days_in_chunk)

    api_errors = 0
    bbox_str = f"{lon_a},{lat_lo},{lon_b},{lat_hi}"

    if chunks_to_fetch:
        print(f"[{rid}] Fetching {len(chunks_to_fetch)} chunks ({len(chunks_to_fetch)*5} days max) with 1 worker (delay={delay}s)...", flush=True)
        for c_start, c_days in chunks_to_fetch:
            c_start_res, status, content = fetch_chunk(key, product, bbox_str, c_start, c_days)
            if status != 200:
                print(f"[{rid}] ERROR on chunk {c_start}: status {status} - {content}", flush=True)
                api_errors += 1
                break

            # Parse lines by acq_date
            reader = csv.DictReader(io.StringIO(content))
            rows_by_date: dict[str, list[dict]] = {
                (c_start + timedelta(days=i)).isoformat(): [] for i in range(c_days)
            }
            for row in reader:
                ad = row.get("acq_date")
                if ad in rows_by_date:
                    rows_by_date[ad].append(row)

            fieldnames = reader.fieldnames or [
                "latitude", "longitude", "bright_ti4", "scan", "track",
                "acq_date", "acq_time", "satellite", "instrument",
                "confidence", "version", "bright_ti5", "frp", "daynight",
            ]

            # Save each day
            for d_str, d_rows in rows_by_date.items():
                target = sub_dir / f"{d_str}.csv"
                buf = io.StringIO()
                writer = csv.DictWriter(buf, fieldnames=fieldnames)
                writer.writeheader()
                for r in d_rows:
                    writer.writerow(r)
                target.write_text(buf.getvalue(), encoding="utf-8")

            if delay > 0:
                time.sleep(delay)
    else:
        print(f"[{rid}] All 365 days already cached.", flush=True)

    if api_errors > 0:
        return {
            "id": rid,
            "days": 0,
            "days_with_fires": 0,
            "min": 0,
            "max": 0,
            "mean": 0.0,
            "api_errors": api_errors,
        }

    # Now read all 365 days from cache
    counts: list[int] = []
    curr = start_date
    while curr <= end_date:
        d_str = curr.isoformat()
        target = sub_dir / f"{d_str}.csv"
        if not target.exists():
            api_errors += 1
            counts.append(0)
        else:
            txt = target.read_text(encoding="utf-8").strip()
            lines = [l for l in txt.splitlines() if l.strip()]
            cnt = max(0, len(lines) - 1)
            counts.append(cnt)
        curr += timedelta(days=1)

    total_days = len(counts)
    days_with_fires = sum(1 for c in counts if c > 0)
    min_c = min(counts) if counts else 0
    max_c = max(counts) if counts else 0
    mean_c = (sum(counts) / total_days) if total_days > 0 else 0.0

    return {
        "id": rid,
        "name": region.get("name", rid),
        "days": total_days,
        "days_with_fires": days_with_fires,
        "min": min_c,
        "max": max_c,
        "mean": mean_c,
        "api_errors": api_errors,
    }


def main():
    key = get_api_key()
    if not key:
        print("ERROR: FIRMS MAP_KEY is not set.")
        sys.exit(1)

    regions = load_land_regions()
    cache_dir = REPO_ROOT / "output" / "firms_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    results = []
    print(f"Starting FIRMS pull for {len(regions)} land regions, 2025, one region at a time...\n")

    for idx, r in enumerate(regions):
        print(f"--- ({idx+1}/{len(regions)}) Region: {r['id']} ---", flush=True)
        res = pull_region(r, key, cache_dir, workers=1, delay=0.5)
        if res["api_errors"] > 0:
            print(f"\nCRITICAL: API error in region {r['id']}. Halting as requested.", flush=True)
            results.append(res)
            sys.exit(1)
        results.append(res)
        print(f"Completed {r['id']}: {res['days_with_fires']}/{res['days']} days with fires, max={res['max']}\n", flush=True)

    # Print summary table
    print("\n" + "=" * 80)
    print("FIRMS 2025 LAND REGIONS SUMMARY TABLE")
    print("=" * 80)
    fmt = "| {:<18} | {:<5} | {:<15} | {:<6} | {:<7} | {:<8} | {:<10} |"
    print(fmt.format("Region", "days", "days with fires", "min", "max", "mean", "API errors"))
    print("|" + "-"*20 + "|" + "-"*7 + "|" + "-"*17 + "|" + "-"*8 + "|" + "-"*9 + "|" + "-"*10 + "|" + "-"*12 + "|")
    for res in results:
        print(fmt.format(
            res["id"],
            res["days"],
            res["days_with_fires"],
            res["min"],
            res["max"],
            f"{res['mean']:.1f}",
            res["api_errors"],
        ))
    print("=" * 80)


if __name__ == "__main__":
    main()
