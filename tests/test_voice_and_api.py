from __future__ import annotations

import os
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from aetherwaves.server import app, MAX_CONCURRENT_JOBS
from aetherwaves.voice_router import (
    GeminiKeyRotator,
    REFUSAL_REPLY,
    WELCOME_PROMPT,
    match_region_alias,
    process_voice_navigation,
    rule_based_intent_fallback,
    scrub_banned_words,
)

client = TestClient(app)


# -----------------------------------------------------------------------------
# 1. Gemini 4-Key Rotation & 429 Failover Test
# -----------------------------------------------------------------------------

def test_gemini_key_rotator_round_robin():
    rotator = GeminiKeyRotator(["key_a", "key_b", "key_c", "key_d"])
    assert rotator.key_count == 4

    keys_stepped = [rotator.advance_key() for _ in range(8)]
    assert keys_stepped == [
        "key_a", "key_b", "key_c", "key_d",
        "key_a", "key_b", "key_c", "key_d",
    ]


def test_gemini_key_rotator_429_failover():
    rotator = GeminiKeyRotator(["key_fail_429", "key_success"])
    assert rotator.key_count == 2

    mock_client_fail = MagicMock()
    mock_client_fail.models.generate_content.side_effect = Exception("429 Resource exhausted: Quota exceeded")

    mock_resp = MagicMock()
    mock_resp.text = '{"action": "play_music", "spoken_reply": "Playing music derived from satellite data.", "out_of_scope": false}'
    mock_client_success = MagicMock()
    mock_client_success.models.generate_content.return_value = mock_resp

    def fake_genai_client(api_key):
        if api_key == "key_fail_429":
            return mock_client_fail
        return mock_client_success

    with patch("google.genai.Client", side_effect=fake_genai_client):
        rotator._clients.clear()
        res = rotator.generate_content(contents="play")
        assert res is not None
        assert res.action == "play_music"
        assert res.spoken_reply == "Playing music derived from satellite data."


def test_gemini_model_fallback_to_lite():
    rotator = GeminiKeyRotator(["key_a"])

    mock_client = MagicMock()

    def side_effect(model, contents, config):
        if model == "gemini-3.8-flash":
            raise Exception("404 models/gemini-3.8-flash is not found")
        resp = MagicMock()
        resp.text = '{"action": "play_music", "spoken_reply": "Playing music derived from satellite data.", "out_of_scope": false}'
        return resp

    mock_client.models.generate_content.side_effect = side_effect

    with patch("google.genai.Client", return_value=mock_client):
        rotator._clients.clear()
        res = rotator.generate_content(contents="play", model="gemini-3.8-flash")
        assert res is not None
        assert res.action == "play_music"
        called_models = [c.kwargs.get("model") for c in mock_client.models.generate_content.call_args_list]
        assert called_models == ["gemini-3.8-flash", "gemini-3.5-flash-lite"]


# -----------------------------------------------------------------------------
# 2. Canonical Region Aliases & Disambiguation Test
# -----------------------------------------------------------------------------

def test_canonical_region_resolutions():
    # "Indian Ocean" and "Arabian Sea" must resolve to "arabian_sea", NEVER "india"
    assert match_region_alias("Tell me about the Indian Ocean") == "arabian_sea"
    assert match_region_alias("Indian Ocean currents") == "arabian_sea"
    assert match_region_alias("Go to Arabian Sea") == "arabian_sea"

    res_indian = rule_based_intent_fallback("Tell me about the Indian Ocean")
    assert res_indian.region_id == "arabian_sea"
    assert res_indian.region_id != "india"

    res_arabian = rule_based_intent_fallback("Navigate to Arabian Sea")
    assert res_arabian.region_id == "arabian_sea"
    assert res_arabian.region_id != "india"

    # "North Pacific" must resolve to "kuroshio", NEVER "w_north_america"
    assert match_region_alias("Take me to North Pacific") == "kuroshio"
    res_pacific = rule_based_intent_fallback("Take me to North Pacific")
    assert res_pacific.region_id == "kuroshio"
    assert res_pacific.region_id != "w_north_america"

    # Exact regional matching for others
    assert match_region_alias("Go to India") == "india"
    res_india = rule_based_intent_fallback("Go to India")
    assert res_india.action == "navigate_region"
    assert res_india.region_id == "india"

    assert match_region_alias("Go to UAE") == "arabian_sea"
    res_uae = rule_based_intent_fallback("Go to UAE")
    assert res_uae.action == "navigate_region"
    assert res_uae.region_id == "arabian_sea"

    assert match_region_alias("Western North America") == "w_north_america"
    assert match_region_alias("South Pacific") == "east_australian"


# -----------------------------------------------------------------------------
# 3. NASA SVS Search Intent Test
# -----------------------------------------------------------------------------

def test_svs_search_intent():
    res = rule_based_intent_fallback("Go to smoke SVS data")
    assert res.action == "search_svs"
    assert res.svs_query == "smoke"
    assert res.svs_id == "5688"
    assert "NASA SVS 5688" in res.spoken_reply

    res2 = rule_based_intent_fallback("Find NASA SVS wildfire visualization")
    assert res2.action == "search_svs"
    assert res2.svs_query == "smoke"

    # Integration via API
    resp = client.post("/api/voice-navigate", json={"transcript": "Go to smoke SVS data"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] == "search_svs"
    assert data["svs_query"] == "smoke"
    assert data["svs_id"] == "5688"
    assert data["audio_base64"] is not None


# -----------------------------------------------------------------------------
# 4. Out-of-Scope Exact Refusal Message Test
# -----------------------------------------------------------------------------

@pytest.mark.parametrize("query", [
    "What is the weather in London tomorrow?",
    "Tell me a joke about cats",
    "Who won the 2024 World Cup?",
    "Write me a python script for sorting lists",
    "What is the capital of France?",
])
def test_out_of_scope_exact_refusal(query: str):
    res = rule_based_intent_fallback(query)
    assert res.action == "refuse_out_of_scope"
    assert res.out_of_scope is True
    assert res.region_id is None
    assert res.month is None
    assert res.spoken_reply == "I don't have that data. I am only capable within my NASA satellite and SVS data."

    # Test via API endpoint
    resp = client.post("/api/voice-navigate", json={"transcript": query})
    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] == "refuse_out_of_scope"
    assert data["out_of_scope"] is True
    assert data["spoken_reply"] == "I don't have that data. I am only capable within my NASA satellite and SVS data."


# -----------------------------------------------------------------------------
# 5. Region Navigation Full Narration & Kokoro Opus Audio Test
# -----------------------------------------------------------------------------

def test_region_navigation_full_narration_and_audio():
    resp = client.post("/api/voice-navigate", json={"transcript": "Go to India"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] == "navigate_region"
    assert data["region_id"] == "india"
    assert data["out_of_scope"] is False

    # Narration combines artistic framing + scientific dataset
    narration = data["spoken_reply"]
    assert "India" in narration
    assert "Kafi Thaat" in narration
    assert "NASA FIRMS" in narration or "satellite" in narration
    assert "Every note is computed from the data by rules we chose." in narration

    # Verifies Kokoro Opus audio is returned
    assert data["audio_base64"] is not None
    assert len(data["audio_base64"]) > 500


def test_region_navigation_arabian_sea_narration():
    resp = client.post("/api/voice-navigate", json={"transcript": "Go to Arabian Sea"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] == "navigate_region"
    assert data["region_id"] == "arabian_sea"
    assert data["region_id"] != "india"
    assert "Arabian Sea" in data["spoken_reply"]
    assert "OSCAR" in data["spoken_reply"]
    assert data["audio_base64"] is not None


# -----------------------------------------------------------------------------
# 6. Banned Words Scrubber Test
# -----------------------------------------------------------------------------

def test_banned_words_scrubber():
    raw_forbidden = (
        "We offer 100% film-level sound with advanced tuning! "
        "We guarantee live audio measured by satellites."
    )
    cleaned = scrub_banned_words(raw_forbidden)

    forbidden_tokens = ["100%", "film-level", "advanced tuning", "guarantee", "live", "measured by satellites"]
    for token in forbidden_tokens:
        assert token.lower() not in cleaned.lower(), f"Banned word '{token}' found in cleaned output: {cleaned}"

    assert "derived from satellite data" in cleaned
    assert "every note" in cleaned


# -----------------------------------------------------------------------------
# 7. Concurrency Limiter (MAX_CONCURRENT_JOBS = 3) Test
# -----------------------------------------------------------------------------

def test_concurrency_limiter_rejects_4th_request():
    import aetherwaves.server as srv

    with srv._JOB_LOCK:
        srv._ACTIVE_JOBS = 3

    try:
        response = client.post("/api/generate-music", json={"region_id": "india"})
        assert response.status_code == 429
        data = response.json()
        assert data["error"] == "Too Many Requests"
        assert "Many people are using the music generator right now" in data["message"]
        assert data["retry_after"] == 5
        assert "audio_base64" in data
    finally:
        with srv._JOB_LOCK:
            srv._ACTIVE_JOBS = 0


# -----------------------------------------------------------------------------
# 8. GET /health & /api/welcome-audio Tests
# -----------------------------------------------------------------------------

def test_get_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "kokoro_ready" in data
    assert data["kokoro_ready"] is True
    assert "gemini_keys_loaded" in data
    assert isinstance(data["gemini_keys_loaded"], int)
    assert "active_jobs" in data
    assert isinstance(data["active_jobs"], int)


def test_get_welcome_audio_endpoint():
    response = client.get("/api/welcome-audio?stage=1")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "Do you want voice assistance" in data["text"]
    assert "audio_base64" in data
    assert data["audio_base64"] is not None
    assert len(data["audio_base64"]) > 10000
    assert data["audio_base64"].startswith("T2dnUw")

    resp2 = client.get("/api/welcome-audio?stage=2")
    assert resp2.status_code == 200
    assert "Hello, this is The Sound of Earth assistance" in resp2.json()["text"]
    assert resp2.json()["audio_base64"] is not None
    assert len(resp2.json()["audio_base64"]) > 10000


# -----------------------------------------------------------------------------
# 9. Transport and Month Navigation Tests
# -----------------------------------------------------------------------------

def test_api_voice_navigate_transport():
    response_pause = client.post(
        "/api/voice-navigate",
        json={"transcript": "Pause the music", "active_region_id": "india"},
    )
    assert response_pause.status_code == 200
    assert response_pause.json()["action"] == "pause_music"

    response_play = client.post(
        "/api/voice-navigate",
        json={"transcript": "Play music", "active_region_id": "india"},
    )
    assert response_play.status_code == 200
    assert response_play.json()["action"] == "play_music"


def test_api_voice_navigate_month():
    response = client.post(
        "/api/voice-navigate",
        json={"transcript": "Change to July", "active_region_id": "india"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["action"] == "set_month"
    assert data["month"] == 7


# -----------------------------------------------------------------------------
# 10. Native MediaRecorder Base64 Audio Ingestion & Gemini Audio Part Test
# -----------------------------------------------------------------------------

def test_api_voice_navigate_native_audio():
    import base64
    from unittest.mock import patch
    from aetherwaves.voice_router import ROTATOR, VoiceActionResponse
    from google.genai import types

    fake_bytes = b"MOCK_WEBM_OPUS_AUDIO_BYTES_FOR_GEMINI"
    fake_b64 = base64.b64encode(fake_bytes).decode("ascii")

    original_keys = list(ROTATOR.keys)
    if not ROTATOR.keys:
        ROTATOR.keys = ["mock_gemini_key_for_test"]

    captured_contents = []

    def mock_gen_content(contents, system_instruction=None, model="gemini-3.8-flash"):
        captured_contents.append(contents)
        return VoiceActionResponse(
            action="navigate_region",
            region_id="arabian_sea",
            spoken_reply="Navigating to Arabian Sea. Derived from satellite data.",
            out_of_scope=False,
        )

    try:
        with patch.object(ROTATOR, "generate_content", side_effect=mock_gen_content):
            resp = client.post(
                "/api/voice-navigate",
                json={
                    "audio_base64": fake_b64,
                    "mime_type": "audio/webm",
                    "active_region_id": "india",
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["action"] == "navigate_region"
            assert data["region_id"] == "arabian_sea"
            assert "Arabian Sea" in data["spoken_reply"]
            # Verifies Kokoro-82M Opus audio is returned
            assert data["audio_base64"] is not None
            assert len(data["audio_base64"]) > 500

            # Verify contents had the Gemini audio Part
            assert len(captured_contents) == 1
            contents = captured_contents[0]
            assert isinstance(contents, list)
            audio_part = contents[0]
            assert isinstance(audio_part, types.Part)
            assert audio_part.inline_data.data == fake_bytes
            assert audio_part.inline_data.mime_type == "audio/webm"
    finally:
        ROTATOR.keys = original_keys


# -----------------------------------------------------------------------------
# 11. Custom & SVS Video Sonification from GPU Frame Energies Test
# -----------------------------------------------------------------------------

def test_generate_music_from_frame_energies_distinct():
    import base64
    import hashlib

    # 1. Warm/fire/smoke profile (25 frames): high red, low blue, active motion
    fire_frames = [
        {
            "sec": i,
            "brightness": 0.6 + 0.2 * (i % 3) / 2.0,
            "motion": 0.3 + 0.4 * ((i * 7) % 5) / 4.0,
            "r": 0.85,
            "g": 0.35,
            "b": 0.10,
        }
        for i in range(25)
    ]

    # 2. Cool/ocean/ice profile (25 frames): high blue, low red, gentle motion
    ocean_frames = [
        {
            "sec": i,
            "brightness": 0.4 + 0.15 * (i % 2),
            "motion": 0.05 + 0.10 * ((i * 3) % 4) / 3.0,
            "r": 0.10,
            "g": 0.45,
            "b": 0.90,
        }
        for i in range(25)
    ]

    # Fire / smoke sonification
    resp1 = client.post(
        "/api/generate-music",
        json={"svs_id": "5688", "frame_energies": fire_frames, "mode": "musical"},
    )
    assert resp1.status_code == 200, f"resp1 failed: {resp1.text}"
    data1 = resp1.json()
    assert data1["status"] == "ok"
    assert "audio_base64" in data1 and len(data1["audio_base64"]) > 1000
    assert not data1.get("audio_url", "").startswith("/final/2025/")
    assert "bars_summary" in data1 and len(data1["bars_summary"]) >= 3
    # Fire/smoke dominance uses Phrygian Dominant
    assert "Phrygian Dominant" in data1["info"]["scale"]

    raw_opus1 = base64.b64decode(data1["audio_base64"])
    hash1 = hashlib.sha256(raw_opus1).hexdigest()

    # Ocean / ice sonification
    resp2 = client.post(
        "/api/generate-music",
        json={"svs_id": "3912", "frame_energies": ocean_frames, "mode": "musical"},
    )
    assert resp2.status_code == 200, f"resp2 failed: {resp2.text}"
    data2 = resp2.json()
    assert data2["status"] == "ok"
    assert "audio_base64" in data2 and len(data2["audio_base64"]) > 1000
    assert not data2.get("audio_url", "").startswith("/final/2025/")
    assert "bars_summary" in data2 and len(data2["bars_summary"]) >= 3
    # Ocean/ice dominance uses Dorian
    assert "Dorian" in data2["info"]["scale"]

    raw_opus2 = base64.b64decode(data2["audio_base64"])
    hash2 = hashlib.sha256(raw_opus2).hexdigest()

    # Prove outputs are genuinely distinct (different SHA-256 hashes)
    assert hash1 != hash2, "Expected different Opus audio SHA-256 hashes for different frame energies"

    # Prove that when both frame_energies and region_id are provided, it NEVER falls back to /final/2025/
    resp_both = client.post(
        "/api/generate-music",
        json={"region_id": "india", "frame_energies": fire_frames, "mode": "musical"},
    )
    assert resp_both.status_code == 200
    data_both = resp_both.json()
    assert not data_both.get("audio_url", "").startswith("/final/2025/")
    assert "bars_summary" in data_both

