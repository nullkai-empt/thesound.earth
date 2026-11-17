import os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from src.aetherwaves.server import app, SVS_CACHE_DIR

client = TestClient(app)


def test_oscar_daily_2025_returns_365_rows():
    response = client.get("/api/oscar_daily/2025")
    assert response.status_code == 200
    assert response.headers.get("content-type") == "application/json"
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 365
    assert data[0]["date"] == "2025-01-01"
    assert data[-1]["date"] == "2025-12-31"


def test_oscar_daily_unknown_year_returns_404_json():
    response = client.get("/api/oscar_daily/1999")
    assert response.status_code == 404
    data = response.json()
    assert "detail" in data
    assert "1999" in data["detail"]


def test_svs_video_range_support(tmp_path):
    # Mock video cache by pre-populating SVS_CACHE_DIR with a test dummy mp4 file
    test_id = 5687
    cached_file = SVS_CACHE_DIR / f"{test_id}.mp4"
    dummy_bytes = b"0" * 4096
    cached_file.write_bytes(dummy_bytes)

    try:
        # Request with Range header
        response = client.get(f"/api/svs/{test_id}/video", headers={"Range": "bytes=0-1023"})
        assert response.status_code == 206
        assert response.headers.get("accept-ranges") == "bytes"
        assert response.headers.get("content-range") == "bytes 0-1023/4096"
        assert response.headers.get("access-control-allow-origin") == "*"
        assert len(response.content) == 1024
    finally:
        cached_file.unlink(missing_ok=True)


def test_api_tracks_returns_15_enriched_tracks():
    response = client.get("/api/tracks")
    assert response.status_code == 200
    tracks = response.json()
    assert isinstance(tracks, list)
    assert len(tracks) == 15, f"Expected 15 tracks, got {len(tracks)}"

    track_ids = {t["id"] for t in tracks}
    expected_ids = {
        "gulf_stream", "kuroshio", "east_australian", "brazil_malvinas",
        "arabian_sea", "drake_acc", "nordic_seas", "amazon", "congo",
        "se_asia", "australia", "w_north_america", "siberia", "india", "europe"
    }
    assert track_ids == expected_ids

    for t in tracks:
        assert "audio_url" in t
        assert t["audio_url"] == f"/api/stream/{t['id']}"
        assert "meta_url" in t
        assert t["meta_url"].endswith(".json")
        assert "lat" in t and isinstance(t["lat"], list) and len(t["lat"]) == 2
        assert "lon" in t and isinstance(t["lon"], list) and len(t["lon"]) == 2
        assert "bbox" in t and len(t["bbox"]) == 4
        assert "center_lat" in t
        assert "center_lon" in t


def test_final_gulf_stream_meta_json():
    response = client.get("/final/2025/gulf_stream/meta.json")
    assert response.status_code == 200
    meta = response.json()
    assert meta["preset"]["track_id"] == "gulf_stream"
    assert "scientific_data" in meta
    assert "audit_table" in meta["scientific_data"]
    assert len(meta["scientific_data"]["audit_table"]) == 53
    assert "facts_narrative" in meta
    assert "story" in meta
    assert "ai_disclosure" in meta


def test_final_india_track_opus():
    response = client.get("/final/2025/india/track.opus")
    assert response.status_code == 200
    assert len(response.content) > 100000


def test_api_stream_opaque_headers_and_security():
    response = client.get("/api/stream/india")
    assert response.status_code == 200
    assert response.headers.get("content-type") == "audio/ogg"
    assert response.headers.get("cache-control") == "no-store"
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert response.headers.get("content-disposition") == "inline"
    assert len(response.content) > 100000

    # Also test support with .opus suffix
    response_suffix = client.get("/api/stream/india.opus")
    assert response_suffix.status_code == 200
    assert response_suffix.headers.get("content-type") == "audio/ogg"

    # Test path traversal and unknown region rejection
    assert client.get("/api/stream/unknown_region").status_code == 404
    assert client.get("/api/stream/..").status_code == 404
    assert client.get("/api/stream/../../etc/passwd").status_code == 404


def test_root_serves_html():
    response = client.get("/")
    assert response.status_code == 200
    assert "<!DOCTYPE html>" in response.text or "<html" in response.text
    assert "globeViz" in response.text

