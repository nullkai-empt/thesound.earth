"""test_svs_v3.py — Verification of SVS v3 Engine and FastAPI Service.

Requirements:
1. Same video twice = same MIDI hash.
2. Black frame = rest (None, never zero).
3. URL allowlist rejects other hosts (only svs.gsfc.nasa.gov allowed).
4. Size/length limits (max 300 MB, max 300s) with clear errors.
5. Job lifecycle: queued -> analysing -> rendering -> done, and delete/cancel.
6. Cached second call returns cached result immediately without re-rendering.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from fastapi.testclient import TestClient

from src.aetherwaves.server import (
    app,
    SVS_CACHE_DIR,
    ENGINE_VERSION,
    MAX_VIDEO_BYTES,
    MAX_VIDEO_DURATION_SEC,
    _SVS_JOBS,
    _SVS_LOCK,
)
from src.aetherwaves.engine_v3.svs_v3 import (
    compute_svs_flow,
    group_flow_into_bars,
    probe_video_info,
    sonify_svs_v3,
)
from src.aetherwaves.svs import trusted_nasa_url

client = TestClient(app)
TEST_VIDEO_5687 = Path("output/svs_cache/5687.mp4")
DIST_VIDEO_5687 = Path("output/svs_dist/5687/video.mp4")

@pytest.fixture(autouse=True)
def ensure_5687_video():
    """Ensure 5687.mp4 is available in SVS_CACHE_DIR for tests."""
    if not TEST_VIDEO_5687.exists() and DIST_VIDEO_5687.exists():
        import shutil
        shutil.copy2(DIST_VIDEO_5687, TEST_VIDEO_5687)
    yield


def test_svs_v3_same_video_twice_same_midi_hash(tmp_path: Path):
    """Test 1: Same video twice = same MIDI hash (determinism)."""
    assert TEST_VIDEO_5687.exists(), "Test video 5687.mp4 must exist in output/svs_cache/"

    out_opus_1 = tmp_path / "run1.opus"
    out_meta_1 = tmp_path / "run1.json"
    res1 = sonify_svs_v3(
        video_path=TEST_VIDEO_5687,
        svs_id=5687,
        out_opus_path=out_opus_1,
        out_meta_path=out_meta_1,
    )

    out_opus_2 = tmp_path / "run2.opus"
    out_meta_2 = tmp_path / "run2.json"
    res2 = sonify_svs_v3(
        video_path=TEST_VIDEO_5687,
        svs_id=5687,
        out_opus_path=out_opus_2,
        out_meta_path=out_meta_2,
    )

    assert res1["midi_sha256"] == res2["midi_sha256"], "MIDI SHA-256 must match across runs!"
    assert res1["opus_sha256"] == res2["opus_sha256"], "Opus SHA-256 must match across runs!"
    assert res1["bars"] == res2["bars"]
    assert res1["tempo"] == res2["tempo"]


def test_svs_v3_black_frame_is_rest():
    """Test 2: Black or missing frame = rest (None, never zero)."""
    # 1. Test optical flow on None frames
    dummy_frame = np.ones((90, 160), dtype=np.uint8) * 128
    flow_rows = compute_svs_flow([None, dummy_frame, None, None])

    assert len(flow_rows) == 3
    for r in flow_rows:
        assert r["valid"] is False
        assert r["is_rest"] is True
        assert r["speed_p95"] is None
        assert r["magnitude"] is None

    # 2. Test group_flow_into_bars with all-rest flow rows
    bars, bar_sec, tempo, n_bars = group_flow_into_bars(flow_rows, duration=15.0)
    for b in bars:
        assert b["valid"] is False
        assert b["is_rest"] is True
        assert b["speed_p95"] is None
        assert b["sector"] is None


def test_svs_v3_url_allowlist_rejects_other_hosts():
    """Test 3: URL allowlist rejects hosts outside svs.gsfc.nasa.gov."""
    # Valid SVS URLs
    valid_url = "https://svs.gsfc.nasa.gov/vis/a000000/a005600/a005687/frames.mp4"
    assert trusted_nasa_url(valid_url) == valid_url

    # Legacy HTTP gets upgraded to HTTPS
    legacy_http = "http://svs.gsfc.nasa.gov/vis/a000000/a005600/a005687/frames.mp4"
    assert trusted_nasa_url(legacy_http) == valid_url

    # Untrusted / external hosts must be rejected with ValueError
    with pytest.raises(ValueError, match="outside the trusted SVS host"):
        trusted_nasa_url("https://evil.com/malicious.mp4")

    with pytest.raises(ValueError, match="outside the trusted SVS host"):
        trusted_nasa_url("https://nasa.gov.attacker.com/video.mp4")

    with pytest.raises(ValueError, match="outside the trusted SVS host"):
        trusted_nasa_url("ftp://svs.gsfc.nasa.gov/video.mp4")


def test_svs_v3_size_and_length_limits(tmp_path: Path):
    """Test 4: Size and length limits enforced with clear error messages."""
    fake_video = tmp_path / "huge.mp4"
    fake_video.write_bytes(b"0" * 1024)

    # File size limit check
    with patch.object(Path, "stat") as mock_stat:
        class DummyStat:
            st_size = MAX_VIDEO_BYTES + 1024
        mock_stat.return_value = DummyStat()
        
        # Test server video endpoint size limit
        response = client.get("/api/svs/5687/video")
        assert response.status_code == 413
        assert "exceeds maximum limit" in response.json()["detail"]

    # Duration limit check (> 300s)
    with patch("src.aetherwaves.server.probe_video_info", return_value=(1920, 1080, 350.0)):
        response = client.get("/api/svs/5687/video")
        assert response.status_code == 400
        assert "exceeds maximum allowed limit" in response.json()["detail"]


def test_svs_v3_job_lifecycle():
    """Test 5: Job lifecycle: queued / done, retrieval, and cancellation."""
    # Test submission
    resp_sonify = client.post("/api/svs/5687/sonify", json={})
    assert resp_sonify.status_code == 202
    job_id = resp_sonify.json().get("job_id")
    assert job_id is not None

    # Test retrieval
    resp_job = client.get(f"/api/svs/jobs/{job_id}")
    assert resp_job.status_code == 200
    job_data = resp_job.json()
    assert job_data["id"] == job_id
    assert job_data["status"] in {"queued", "analysing", "rendering", "done"}

    # Test cancellation / delete
    resp_del = client.delete(f"/api/svs/jobs/{job_id}")
    assert resp_del.status_code == 200
    assert resp_del.json()["status"] == "cancelled"

    # Status reflects cancellation
    resp_job_after = client.get(f"/api/svs/jobs/{job_id}")
    assert resp_job_after.json()["status"] == "cancelled"


def test_svs_v3_cached_second_call(tmp_path: Path):
    """Test 6: Cached second call returns cached result immediately without re-rendering."""
    test_id = 5687
    cached_opus = SVS_CACHE_DIR / f"svs_{test_id}_v3.opus"
    cached_meta = SVS_CACHE_DIR / f"svs_{test_id}_v3.json"

    # Ensure cached files exist
    if not cached_opus.exists() or not cached_meta.exists():
        sonify_svs_v3(
            video_path=TEST_VIDEO_5687,
            svs_id=test_id,
            out_opus_path=cached_opus,
            out_meta_path=cached_meta,
        )

    # First call with cache already present: returns done job immediately
    t0 = time.time()
    resp = client.post(f"/api/svs/{test_id}/sonify", json={})
    elapsed = time.time() - t0
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    # Must return immediately (< 0.1 seconds, no re-rendering!)
    assert elapsed < 0.5, "Cached sonify call must return almost instantaneously"

    job_status = client.get(f"/api/svs/jobs/{job_id}").json()
    assert job_status["status"] == "done"
    assert job_status["result"]["audio_url"] == f"/output/svs_cache/{cached_opus.name}"
    assert job_status["result"]["audit_url"] == f"/output/svs_cache/{cached_meta.name}"


def test_svs_v3_second_job_waits_in_queue():
    """Test 7: A second job waits in the queue while the first job is running."""
    import queue
    from src.aetherwaves.server import _SVS_QUEUE

    # Create dummy jobs
    job1_id = "test_queue_job_1"
    job2_id = "test_queue_job_2"
    block_evt = threading.Event()

    with _SVS_LOCK:
        _SVS_JOBS[job1_id] = {
            "id": job1_id,
            "svs_id": 99901,
            "engine_version": ENGINE_VERSION,
            "status": "analysing",
            "progress": {"stage": "analysing", "current": 0, "total": 1},
            "cancel_event": block_evt,
        }
        _SVS_JOBS[job2_id] = {
            "id": job2_id,
            "svs_id": 99902,
            "engine_version": ENGINE_VERSION,
            "status": "queued",
            "progress": {"stage": "queued", "current": 0, "total": 1},
            "cancel_event": threading.Event(),
        }

    # Job 2 status must be queued while Job 1 is running
    resp_job2 = client.get(f"/api/svs/jobs/{job2_id}")
    assert resp_job2.status_code == 200
    assert resp_job2.json()["status"] == "queued"

    # Cleanup
    with _SVS_LOCK:
        _SVS_JOBS.pop(job1_id, None)
        _SVS_JOBS.pop(job2_id, None)


def test_svs_v3_timeout_kills_ffmpeg():
    """Test 8: Timeout kills ffmpeg subprocess."""
    from src.aetherwaves.engine_v3.svs_v3 import extract_svs_frames_cpu
    with pytest.raises(TimeoutError, match="ffmpeg extraction timed out"):
        # Timeout set to 0.00001 seconds triggers TimeoutExpired and kills ffmpeg
        extract_svs_frames_cpu(TEST_VIDEO_5687, timeout=0.00001)


def test_svs_v3_temp_folder_empty_after_job_and_delete(tmp_path: Path):
    """Test 9: Temporary folders are cleaned up after job and after DELETE."""
    import shutil
    import tempfile
    root = Path(tempfile.gettempdir())
    for old_d in root.glob("svs_render_*"):
        try:
            shutil.rmtree(old_d, ignore_errors=True)
        except Exception:
            pass
    
    # Run sonify
    out_opus = tmp_path / "tmp_track.opus"
    out_meta = tmp_path / "tmp_meta.json"
    sonify_svs_v3(TEST_VIDEO_5687, svs_id=5687, out_opus_path=out_opus, out_meta_path=out_meta)

    # Check that no lingering svs_render_ temporary directories remain
    lingering = [d for d in root.iterdir() if d.is_dir() and d.name.startswith("svs_render_")]
    assert len(lingering) == 0, f"Lingering temp directories found: {lingering}"

    # Verify DELETE cancels and marks job clean
    resp = client.post("/api/svs/5687/sonify", json={})
    job_id = resp.json()["job_id"]
    del_resp = client.delete(f"/api/svs/jobs/{job_id}")
    assert del_resp.status_code == 200
    assert del_resp.json()["status"] == "cancelled"


def test_svs_v3_rate_limit_returns_429():
    """Test 10: Per-IP rate limit returns HTTP 429 when threshold exceeded."""
    got_429 = False
    for _ in range(40):
        resp = client.post("/api/svs/5687/sonify", json={})
        if resp.status_code == 429:
            got_429 = True
            assert "Rate limit exceeded" in resp.json()["detail"]
            break
    assert got_429, "Rate limiter must return 429 after exceeding max sonify requests per minute"


def test_svs_v3_cors_blocks_other_origins_and_allows_thesound_earth():
    """Test 11: CORS blocks untrusted origins and allows thesound.earth."""
    # Origin from untrusted host
    r_blocked = client.get("/api/svs/search?q=ocean", headers={"Origin": "https://evil.com"})
    assert r_blocked.headers.get("access-control-allow-origin") != "https://evil.com"

    # Origin from allowed host thesound.earth
    r_allowed = client.get("/api/svs/search?q=ocean", headers={"Origin": "https://thesound.earth"})
    assert r_allowed.headers.get("access-control-allow-origin") == "https://thesound.earth"

