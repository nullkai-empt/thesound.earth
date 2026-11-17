from __future__ import annotations
import math
from .models import ExtractedFeatures, OceanSample


def extract_features(sample: OceanSample) -> ExtractedFeatures:
    if not sample.is_valid or sample.u is None or sample.v is None:
        return ExtractedFeatures(
            sample=sample,
            speed_mps=None,
            angle_rad=None,
            angle_deg=None,
        )

    speed = math.hypot(sample.u, sample.v)
    angle_rad = math.atan2(sample.v, sample.u)
    angle_deg = math.degrees(angle_rad)

    return ExtractedFeatures(
        sample=sample,
        speed_mps=speed,
        angle_rad=angle_rad,
        angle_deg=angle_deg,
    )