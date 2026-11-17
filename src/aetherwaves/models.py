from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal, Optional


@dataclass(frozen=True)
class OceanSample:
    timestamp: str
    latitude: float
    longitude: float
    u: Optional[float]
    v: Optional[float]
    units: str
    product_variant: Literal["FINAL", "INTERIM", "NRT", "UNKNOWN"]
    dataset_name: str
    source_doi: str
    is_valid: bool
    qc_flags: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ExtractedFeatures:
    sample: OceanSample
    speed_mps: Optional[float]
    angle_rad: Optional[float]
    angle_deg: Optional[float]


@dataclass(frozen=True)
class NormalizedControls:
    features: ExtractedFeatures
    speed_norm: Optional[float]
    u_abs_norm: Optional[float]
    v_abs_norm: Optional[float]
    u_sign: int  # +1, -1, or 0
    v_sign: int  # +1, -1, or 0


@dataclass(frozen=True)
class NoteEvent:
    start_sec: float
    duration_sec: float
    voice: Literal["voice_u", "voice_v", "rest"]
    midi_note: Optional[int]
    frequency_hz: Optional[float]
    amplitude: float
    pan: float  # -1.0 (left) to +1.0 (right); timbre cue only, not 360° direction
    sign: int
    is_rest: bool = False