from __future__ import annotations
import math
from .models import OceanSample


def validate_sample(raw: dict, source_doi: str) -> OceanSample:
    flags: list[str] = []
    u_val = raw.get("u")
    v_val = raw.get("v")
    units = str(raw.get("units", "unknown")).strip()

    if units not in {"m/s", "m s-1", "meter second-1"}:
        flags.append(f"unexpected_units:{units}")

    u_missing = u_val is None or math.isnan(u_val) or abs(u_val) > 10.0
    v_missing = v_val is None or math.isnan(v_val) or abs(v_val) > 10.0

    if u_missing or v_missing:
        flags.append("missing_or_fill_value")
        return OceanSample(
            timestamp=raw["timestamp"],
            latitude=float(raw["latitude"]),
            longitude=float(raw["longitude"]),
            u=None,
            v=None,
            units=units,
            product_variant=raw.get("product_variant", "UNKNOWN"),
            dataset_name=raw.get("dataset_name", "OSCAR_V2.0"),
            source_doi=source_doi,
            is_valid=False,
            qc_flags=tuple(flags),
        )

    return OceanSample(
        timestamp=raw["timestamp"],
        latitude=float(raw["latitude"]),
        longitude=float(raw["longitude"]),
        u=float(u_val),
        v=float(v_val),
        units=units,
        product_variant=raw.get("product_variant", "UNKNOWN"),
        dataset_name=raw.get("dataset_name", "OSCAR_V2.0"),
        source_doi=source_doi,
        is_valid=True,
        qc_flags=tuple(flags),
    )