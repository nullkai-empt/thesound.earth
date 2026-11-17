import os
import subprocess
import tempfile
from pathlib import Path

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
OUTPUT_DIR = Path("output/screenshots")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

resolutions = [
    ("normal_1280x800.png", 1280, 800, "http://127.0.0.1:8000/"),
    ("maximized_1280x800.png", 1280, 800, "http://127.0.0.1:8000/#maximized"),
    ("normal_1920x1080.png", 1920, 1080, "http://127.0.0.1:8000/"),
    ("maximized_1920x1080.png", 1920, 1080, "http://127.0.0.1:8000/#maximized"),
    ("mobile_390x844.png", 390, 844, "http://127.0.0.1:8000/"),
    ("mobile_maximized_390x844.png", 390, 844, "http://127.0.0.1:8000/#maximized"),
]

for filename, w, h, url in resolutions:
    dest = (OUTPUT_DIR / filename).resolve()
    with tempfile.TemporaryDirectory() as user_dir:
        cmd = [
            EDGE,
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-search-engine-choice-screen",
            f"--user-data-dir={user_dir}",
            f"--window-size={w},{h}",
            f"--screenshot={dest}",
            "--virtual-time-budget=2000",
            url
        ]
        try:
            res = subprocess.run(cmd, check=True, timeout=20, capture_output=True)
            print(f"Captured {dest.name} ({dest.stat().st_size} bytes)")
        except Exception as exc:
            print(f"Error {filename}: {exc}")
