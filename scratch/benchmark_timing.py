import subprocess
import sys
import time
import urllib.request
import json

def test_timing():
    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "src.aetherwaves.server:app", "--port", "8015"])
    time.sleep(2)

    try:
        # 1. Page load
        t0 = time.perf_counter()
        with urllib.request.urlopen("http://127.0.0.1:8015/") as r:
            _ = r.read()
        page_load_ms = (time.perf_counter() - t0) * 1000

        # 2. Year switch (cold)
        t0 = time.perf_counter()
        with urllib.request.urlopen("http://127.0.0.1:8015/api/oscar_daily/2024") as r:
            _ = r.read()
        year_switch_cold_ms = (time.perf_counter() - t0) * 1000

        # 2b. Year switch (warm cached)
        t0 = time.perf_counter()
        with urllib.request.urlopen("http://127.0.0.1:8015/api/oscar_daily/2024") as r:
            _ = r.read()
        year_switch_warm_ms = (time.perf_counter() - t0) * 1000

        # 3. SVS Search
        t0 = time.perf_counter()
        with urllib.request.urlopen("http://127.0.0.1:8015/api/svs/search?q=ocean&limit=10") as r:
            _ = r.read()
        svs_search_ms = (time.perf_counter() - t0) * 1000

        # 4. SVS Generate (WAV/JSON Cached or Quick Generate)
        body = json.dumps({"sample_every": 20, "max_frames": 5, "mode": "musical"}).encode()
        req = urllib.request.Request("http://127.0.0.1:8015/api/svs/5687/sonify", data=body, headers={"Content-Type": "application/json"}, method="POST")
        t0 = time.perf_counter()
        with urllib.request.urlopen(req) as r:
            job = json.loads(r.read().decode())
        job_id = job["job_id"]
        while True:
            time.sleep(0.5)
            with urllib.request.urlopen(f"http://127.0.0.1:8015/api/svs/jobs/{job_id}") as r:
                st = json.loads(r.read().decode())
                if st["status"] in ("done", "complete", "failed"):
                    break
        svs_gen_ms = (time.perf_counter() - t0) * 1000

        print(f"Page Load: {page_load_ms:.2f} ms")
        print(f"Year Switch (Cold): {year_switch_cold_ms:.2f} ms")
        print(f"Year Switch (Warm Memory Cache): {year_switch_warm_ms:.2f} ms")
        print(f"SVS Search: {svs_search_ms:.2f} ms")
        print(f"SVS Generate: {svs_gen_ms:.2f} ms")

    finally:
        server.terminate()

if __name__ == "__main__":
    test_timing()
