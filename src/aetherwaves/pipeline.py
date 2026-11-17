from __future__ import annotations
import argparse
import json
import logging
from pathlib import Path
from .arranger import arrange_events
from .data_reader import extract_cell_timeseries, load_oscar_dataset
from .export import write_audit_json
from .feature_extractor import extract_features
from .normalizer import normalize_features
from .quality_control import validate_sample
from .sonification_mapper import map_controls_to_events
from .synthesizer import render_wav
from .validator import check_grid_proximity, validate_config, verify_rendered_audio

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
log = logging.getLogger("aetherwaves")


def run_pipeline(
    nc_path: str | Path,
    config_path: str | Path,
    lat: float,
    lon: float,
    out_dir: str | Path = "output",
    mode: str = "musical",
    day_idx: int | None = None,
) -> tuple[Path, Path]:
    cfg = json.loads(Path(config_path).read_text(encoding="utf-8"))
    validate_config(cfg)

    ds = load_oscar_dataset(nc_path)
    raw_records = extract_cell_timeseries(ds, target_lat=lat, target_lon=lon)
    if not raw_records:
        raise ValueError("No records extracted from NetCDF file.")

    if day_idx is not None:
        safe_idx = max(0, min(day_idx, len(raw_records) - 1))
        raw_records = [raw_records[safe_idx]]

    for w in check_grid_proximity(lat, lon, raw_records[0]["latitude"], raw_records[0]["longitude"]):
        log.warning(w)

    controls = []
    invalid_count = 0
    for raw in raw_records:
        sample = validate_sample(raw, source_doi=cfg["source_doi"])
        if not sample.is_valid:
            invalid_count += 1
            log.warning("Invalid sample at %s: %s", sample.timestamp, sample.qc_flags)
        features = extract_features(sample)
        controls.append(normalize_features(features, cfg["normalization"]))

    log.info("Processed %d samples (%d invalid/masked).", len(controls), invalid_count)

    raw_events = map_controls_to_events(controls, cfg["sonification"])
    arranged = arrange_events(raw_events, cfg["sonification"], mode=mode)

    out_base = Path(out_dir)
    wav_path = render_wav(
        arranged,
        duration_sec=cfg["sonification"]["phrase_duration_sec"],
        sample_rate_hz=cfg["sonification"]["sample_rate_hz"],
        out_path=out_base / f"aetherwaves_{mode}.wav",
        mode=mode,
    )

    audio_check = verify_rendered_audio(
        wav_path,
        expected_sr=cfg["sonification"]["sample_rate_hz"],
        all_invalid=(invalid_count == len(controls)),
    )
    log.info("Audio verified: peak=%.4f, sha256=%s...", audio_check["peak_amplitude"], audio_check["wav_sha256"][:12])

    json_path = write_audit_json(
        controls,
        arranged,
        cfg,
        wav_path=wav_path,
        json_path=out_base / f"aetherwaves_{mode}.json",
        mode=mode,
        audio_verification=audio_check,
    )
    return wav_path, json_path


def main() -> None:
    parser = argparse.ArgumentParser(description="AetherWaves Ocean Sonification CLI")
    parser.add_argument("--nc", required=True, help="Path to OSCAR NetCDF file")
    parser.add_argument("--config", default="config/ocean_mapping_v1.json")
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lon", type=float, required=True)
    parser.add_argument("--out", default="output")
    parser.add_argument("--mode", choices=["diagnostic", "musical"], default="musical")
    parser.add_argument("--day-idx", type=int, default=None)
    args = parser.parse_args()

    wav_path, json_path = run_pipeline(args.nc, args.config, args.lat, args.lon, args.out, args.mode, args.day_idx)
    log.info("Generated audio: %s", wav_path)
    log.info("Generated audit: %s", json_path)


if __name__ == "__main__":
    main()