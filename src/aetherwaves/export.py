from __future__ import annotations
import json
from pathlib import Path
from .models import NormalizedControls, NoteEvent


def write_audit_json(
    controls_series: list[NormalizedControls],
    events: list[NoteEvent],
    cfg: dict,
    wav_path: Path,
    json_path: str | Path,
    mode: str,
    audio_verification: dict | None = None,
) -> Path:
    samples_payload = []
    for ctrl in controls_series:
        feat = ctrl.features
        s = feat.sample
        samples_payload.append({
            "timestamp": s.timestamp,
            "latitude": s.latitude,
            "longitude": s.longitude,
            "is_valid": s.is_valid,
            "qc_flags": list(s.qc_flags),
            "variables": {"u": s.u, "v": s.v},
            "units": s.units,
            "derived": {"speed": feat.speed_mps, "angle_degrees": feat.angle_deg},
            "normalized": {
                "speed_norm": ctrl.speed_norm,
                "u_abs_norm": ctrl.u_abs_norm,
                "v_abs_norm": ctrl.v_abs_norm,
            },
        })

    record = {
        "project": "AetherWaves",
        "dataset": cfg["dataset"],
        "source_doi": cfg["source_doi"],
        "mapping_version": cfg["mapping_version"],
        "render_mode": mode,
        "mapping": {
            "speed_to_event_rate": "bounded 5th-95th percentile linear mapping",
            "u_to_pitch": "signed octave-separated mapping (Voice A)",
            "v_to_pitch": "signed octave-separated mapping (Voice B)",
        },
        "audio": {
            "file": wav_path.name,
            "format": "WAV",
            "sample_rate_hz": cfg["sonification"]["sample_rate_hz"],
            "event_count": len(events),
            "audio_verification": audio_verification,
        },
        "samples": samples_payload,
        "limitations": [
            "OSCAR v2.0 does not supply per-grid-cell uncertainty estimates.",
            "Scale quantization is an artistic choice in musical mode; use diagnostic mode for raw pitch fidelity.",
        ],
    }

    out = Path(json_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return out