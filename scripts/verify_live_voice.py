import base64
import json
import subprocess
import sys
import time
import urllib.request

PORT = 8011
BASE_URL = f"http://127.0.0.1:{PORT}"

print(f"Starting Uvicorn server on port {PORT}...")
proc = subprocess.Popen(
    [
        sys.executable,
        "-m",
        "uvicorn",
        "src.aetherwaves.server:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(PORT),
        "--log-level",
        "warning",
    ],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
)

server_up = False
try:
    # Wait for server /health to be responsive
    for _ in range(30):
        try:
            req = urllib.request.Request(f"{BASE_URL}/health")
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                if resp.status == 200:
                    health_data = json.loads(resp.read().decode("utf-8"))
                    print(f"Server is up! Health: {health_data}")
                    server_up = True
                    break
        except Exception:
            time.sleep(0.5)

    if not server_up:
        print("ERROR: Server failed to start in time.")
        sys.exit(1)

    # Test POST /api/voice-navigate with {"transcript": "Go to India"}
    payload = json.dumps({"transcript": "Go to India"}).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}/api/voice-navigate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    print("Sending POST /api/voice-navigate with {\"transcript\": \"Go to India\"}...")
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=5.0) as resp:
        elapsed = time.perf_counter() - t0
        body = resp.read()
        res = json.loads(body.decode("utf-8"))

    print(f"Response received in {elapsed:.3f} seconds (Target: < 1.5s)")
    print(f"Action: {res.get('action')}")
    print(f"Region ID: {res.get('region_id')}")
    print(f"Spoken Reply: {res.get('spoken_reply')}")
    audio_b64 = res.get("audio_base64", "")
    print(f"Audio Base64 length: {len(audio_b64)} chars")

    if audio_b64:
        raw_audio = base64.b64decode(audio_b64)
        print(f"Decoded Opus Audio: {len(raw_audio)} bytes, header: {raw_audio[:4]}")
        assert raw_audio[:4] == b"OggS", "Audio header does not match OggS container!"
        assert len(raw_audio) > 10000, f"Audio bytes {len(raw_audio)} is suspiciously short!"

    assert res.get("action") == "navigate_region", f"Unexpected action: {res.get('action')}"
    assert res.get("region_id") == "india", f"Unexpected region_id: {res.get('region_id')}"
    assert elapsed < 1.5, f"Response time {elapsed:.3f}s exceeded 1.5s target!"
    assert "India" in res.get("spoken_reply", "") or "Bay of Bengal" in res.get("spoken_reply", "")
    print("\nSUCCESS: All live verification checks PASSED!")

finally:
    print("Terminating Uvicorn server...")
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    print("Uvicorn server stopped.")
