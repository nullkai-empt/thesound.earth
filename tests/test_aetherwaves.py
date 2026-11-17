import json
import math
from pathlib import Path
import pytest


from aetherwaves.feature_extractor import extract_features
from aetherwaves.normalizer import normalize_features
from aetherwaves.quality_control import validate_sample
from aetherwaves.sonification_mapper import map_controls_to_events
from aetherwaves.synthesizer import render_wav
from aetherwaves.validator import validate_config, verify_rendered_audio

CFG = json.loads(Path("config/ocean_mapping_v1.json").read_text(encoding="utf-8"))


def _make_sample(u: float, v: float):
    return validate_sample(
        {
            "timestamp": "2026-01-15",
            "latitude": 15.0,
            "longitude": 65.0,
            "u": u,
            "v": v,
            "units": "m/s",
            "product_variant": "FINAL",
            "dataset_name": "OSCAR_L4_OC_FINAL_V2.0",
        },
        source_doi=CFG["source_doi"],
    )


def test_vector_formulas():
    feat = extract_features(_make_sample(0.6, -0.8))
    assert math.isclose(feat.speed_mps, 1.0, rel_tol=1e-9)
    assert math.isclose(feat.angle_deg, -53.13010235415598, rel_tol=1e-9)


def test_missing_data_produces_rest_never_zero():
    sample = _make_sample(float("nan"), 0.2)
    assert sample.is_valid is False
    ctrl = normalize_features(extract_features(sample), CFG["normalization"])
    events = map_controls_to_events([ctrl], CFG["sonification"])
    assert len(events) == 1
    assert events[0].is_rest is True
    assert events[0].amplitude == 0.0


def test_monotonicity_higher_speed_never_fewer_events():
    slow = normalize_features(extract_features(_make_sample(0.1, 0.1)), CFG["normalization"])
    fast = normalize_features(extract_features(_make_sample(0.8, 0.8)), CFG["normalization"])
    slow_pulses = [e for e in map_controls_to_events([slow], CFG["sonification"]) if e.voice == "voice_v"]
    fast_pulses = [e for e in map_controls_to_events([fast], CFG["sonification"]) if e.voice == "voice_v"]
    assert len(fast_pulses) > len(slow_pulses)


def test_sign_distinction_for_u():
    pos = normalize_features(extract_features(_make_sample(0.5, 0.2)), CFG["normalization"])
    neg = normalize_features(extract_features(_make_sample(-0.5, 0.2)), CFG["normalization"])
    pos_u = next(e for e in map_controls_to_events([pos], CFG["sonification"]) if e.voice == "voice_u")
    neg_u = next(e for e in map_controls_to_events([neg], CFG["sonification"]) if e.voice == "voice_u")
    assert pos_u.midi_note > neg_u.midi_note


def test_repeatability():
    ctrl = normalize_features(extract_features(_make_sample(0.4, -0.3)), CFG["normalization"])
    run_1 = map_controls_to_events([ctrl], CFG["sonification"])
    run_2 = map_controls_to_events([ctrl], CFG["sonification"])
    assert run_1 == run_2


def test_all_missing_renders_exact_silence(tmp_path):
    sample = _make_sample(float("nan"), float("nan"))
    ctrl = normalize_features(extract_features(sample), CFG["normalization"])
    events = map_controls_to_events([ctrl], CFG["sonification"])
    wav = render_wav(events, 2.0, 44100, tmp_path / "silent.wav", mode="diagnostic")
    check = verify_rendered_audio(wav, expected_sr=44100, all_invalid=True)
    assert check["peak_amplitude"] == 0.0


def test_bad_config_fails_loudly():
    bad = json.loads(json.dumps(CFG))
    bad["normalization"]["speed_mps"] = {"low": 2.0, "high": 1.0}
    with pytest.raises(ValueError):
        validate_config(bad)