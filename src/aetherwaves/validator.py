from __future__ import annotations
import hashlib
from pathlib import Path
import numpy as np
import soundfile as sf


def validate_config(cfg: dict) -> None:
    norm = cfg.get("normalization", {})
    for key in ("speed_mps", "u_abs_mps", "v_abs_mps"):
        bounds = norm.get(key)
        if not bounds or bounds["high"] <= bounds["low"]:
            raise ValueError(f"Config error: normalization.{key} must have high > low.")

    son = cfg.get("sonification", {})
    if son.get("phrase_duration_sec", 0) <= 0:
        raise ValueError("Config error: phrase_duration_sec must be > 0.")
    if son.get("sample_rate_hz", 0) not in (22050, 44100, 48000):
        raise ValueError("Config error: sample_rate_hz must be 22050, 44100, or 48000.")
    rate = son.get("event_rate_per_min", {})
    if rate.get("max", 0) <= rate.get("min", 0):
        raise ValueError("Config error: event_rate_per_min max must be > min.")


def check_grid_proximity(
    req_lat: float, req_lon: float, actual_lat: float, actual_lon: float, max_deg: float = 0.5
) -> list[str]:
    warnings: list[str] = []
    if abs(req_lat - actual_lat) > max_deg or abs(req_lon - actual_lon) > max_deg:
        warnings.append(
            f"Requested ({req_lat}, {req_lon}) snapped to distant grid cell ({actual_lat}, {actual_lon})."
        )
    return warnings


def verify_rendered_audio(wav_path: Path, expected_sr: int, all_invalid: bool) -> dict:
    data, sr = sf.read(wav_path, dtype="float32")
    if sr != expected_sr:
        raise RuntimeError(f"Audio sample rate mismatch: expected {expected_sr}, got {sr}.")

    peak = float(np.max(np.abs(data))) if data.size > 0 else 0.0
    if peak > 0.99:
        raise RuntimeError(f"Audio clipping detected: peak={peak:.4f}")
    if all_invalid and peak > 1e-6:
        raise RuntimeError("Invalid/missing data produced non-silent audio.")
    if not all_invalid and peak == 0.0:
        raise RuntimeError("Valid data produced completely silent audio.")

    sha256 = hashlib.sha256(wav_path.read_bytes()).hexdigest()
    return {"peak_amplitude": round(peak, 6), "sample_rate_hz": sr, "wav_sha256": sha256}