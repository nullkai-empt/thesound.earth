from __future__ import annotations
from .models import ExtractedFeatures, NormalizedControls


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def normalize_value(value: float, low: float, high: float) -> float:
    if high <= low:
        raise ValueError(f"Invalid normalization range: low={low}, high={high}")
    return clamp01((value - low) / (high - low))


def normalize_features(features: ExtractedFeatures, norm_cfg: dict) -> NormalizedControls:
    s = features.sample
    if not s.is_valid or features.speed_mps is None or s.u is None or s.v is None:
        return NormalizedControls(
            features=features,
            speed_norm=None,
            u_abs_norm=None,
            v_abs_norm=None,
            u_sign=0,
            v_sign=0,
        )

    speed_norm = normalize_value(
        features.speed_mps,
        norm_cfg["speed_mps"]["low"],
        norm_cfg["speed_mps"]["high"],
    )
    u_abs_norm = normalize_value(
        abs(s.u),
        norm_cfg["u_abs_mps"]["low"],
        norm_cfg["u_abs_mps"]["high"],
    )
    v_abs_norm = normalize_value(
        abs(s.v),
        norm_cfg["v_abs_mps"]["low"],
        norm_cfg["v_abs_mps"]["high"],
    )

    u_sign = 1 if s.u >= 0 else -1
    v_sign = 1 if s.v >= 0 else -1

    return NormalizedControls(
        features=features,
        speed_norm=speed_norm,
        u_abs_norm=u_abs_norm,
        v_abs_norm=v_abs_norm,
        u_sign=u_sign,
        v_sign=v_sign,
    )