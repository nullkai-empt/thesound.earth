from __future__ import annotations

import base64
import hashlib
import json
import math
import uuid
from pathlib import Path
from typing import Any

import cv2  # type: ignore
import numpy as np

from aetherwaves.engine_v3.form_v3 import compute_form_sections
from aetherwaves.engine_v3.harmony_v3 import (
    BarHarmonyV3,
    generate_harmony_v3,
    get_sector_v3,
)
from aetherwaves.engine_v3.melody_v3 import generate_melody_v3
from aetherwaves.engine_v3.pipeline_v3 import build_midi_v3, render_v3_audio
from aetherwaves.engine_v3.rhythm_v3 import generate_drum_events_v3
from aetherwaves.engine_v3.svs_v3 import (
    SVS_PRESET_V3,
    compute_svs_form,
    normalize_series_5_95,
)


def sonify_frame_energies(
    frame_energies: list[dict[str, Any]],
    out_dir: Path,
    track_id: str = "custom_visual",
    mode: str = "musical",
) -> tuple[Path, dict[str, Any]]:
    """Compute bar-by-bar musical events directly from GPU frame energies:
    brightness, motion delta, and RGB color ratios -> MIDI -> FluidSynth -> 48k mono Opus.
    """
    if not frame_energies:
        raise ValueError("No frame energies provided.")

    norm_frames: list[dict[str, Any]] = []
    for f in frame_energies:
        br = float(f.get("brightness", 0.0))
        br = br / 255.0 if br > 1.0 else max(0.0, min(1.0, br))

        mot = float(f.get("motion", f.get("motion_delta", 0.0)))
        mot = mot / 255.0 if mot > 1.0 else max(0.0, min(1.0, mot))

        r_val = float(f.get("r", 0.0))
        r_val = r_val / 255.0 if r_val > 1.0 else max(0.0, min(1.0, r_val))

        g_val = float(f.get("g", 0.0))
        g_val = g_val / 255.0 if g_val > 1.0 else max(0.0, min(1.0, g_val))

        b_val = float(f.get("b", 0.0))
        b_val = b_val / 255.0 if b_val > 1.0 else max(0.0, min(1.0, b_val))

        u_val = float(f["u"]) if "u" in f and f["u"] is not None else None
        v_val = float(f["v"]) if "v" in f and f["v"] is not None else None

        is_rest = br < 0.031  # Mean luminance < 8 / 255
        norm_frames.append({
            "brightness": br,
            "motion": mot,
            "r": r_val,
            "g": g_val,
            "b": b_val,
            "u": u_val,
            "v": v_val,
            "is_rest": is_rest,
        })

    total_frames = len(norm_frames)
    duration = max(float(total_frames), 16.0)

    # 1 bar = bar_seconds of video time; tempo strictly within [56, 96] BPM
    target_bar_sec = 3.75
    n_bars = max(3, int(round(duration / target_bar_sec)))
    bar_seconds = duration / n_bars
    tempo = 240.0 / bar_seconds

    if tempo < 56.0:
        n_bars = max(3, int(math.ceil(56.0 * duration / 240.0)))
        bar_seconds = duration / n_bars
        tempo = 240.0 / bar_seconds
    elif tempo > 96.0:
        n_bars = max(3, int(math.floor(96.0 * duration / 240.0)))
        bar_seconds = duration / n_bars
        tempo = 240.0 / bar_seconds

    bars: list[dict[str, Any]] = []
    for b in range(n_bars):
        t_start = b * bar_seconds
        t_end = (b + 1) * bar_seconds

        idx_start = max(0, min(int(math.floor(t_start)), total_frames - 1))
        idx_end = max(idx_start + 1, min(int(math.ceil(t_end)), total_frames))
        bar_slice = norm_frames[idx_start:idx_end]

        valid_slice = [x for x in bar_slice if not x["is_rest"]]
        bar_tag = f"Bar-{b:02d}"

        if not valid_slice:
            bars.append({
                "bar": b,
                "valid": False,
                "is_rest": True,
                "speed_p95": None,
                "magnitude": None,
                "ageo_u": 0.0,
                "ageo_v": 0.0,
                "ageo_angle_deg": None,
                "sector": None,
                "date": bar_tag,
                "brightness": 0.0,
                "motion": 0.0,
                "r": 0.0,
                "g": 0.0,
                "b": 0.0,
            })
        else:
            mean_br = float(np.mean([x["brightness"] for x in valid_slice]))
            mean_mot = float(np.mean([x["motion"] for x in valid_slice]))
            mean_r = float(np.mean([x["r"] for x in valid_slice]))
            mean_g = float(np.mean([x["g"] for x in valid_slice]))
            mean_b = float(np.mean([x["b"] for x in valid_slice]))

            tot_rgb = mean_r + mean_g + mean_b
            warmth = (mean_r - mean_b) / (tot_rgb + 1e-6) if tot_rgb > 1e-4 else 0.0

            has_explicit_uv = any(x["u"] is not None and x["v"] is not None for x in valid_slice)
            if has_explicit_uv:
                calc_u = float(np.mean([x["u"] for x in valid_slice if x["u"] is not None]))
                calc_v = float(np.mean([x["v"] for x in valid_slice if x["v"] is not None]))
            else:
                calc_u = warmth * mean_mot
                calc_v = (1.0 - abs(warmth)) * mean_mot

            ang = float(math.degrees(math.atan2(calc_v, calc_u)))
            sec = get_sector_v3(ang)

            # Bar energy combines motion and brightness
            bar_energy = max(0.01, 0.6 * mean_mot + 0.4 * mean_br)

            bars.append({
                "bar": b,
                "valid": True,
                "is_rest": False,
                "speed_p95": bar_energy,
                "magnitude": bar_energy,
                "ageo_u": calc_u,
                "ageo_v": calc_v,
                "ageo_angle_deg": ang,
                "sector": sec,
                "date": bar_tag,
                "brightness": mean_br,
                "motion": mean_mot,
                "r": mean_r,
                "g": mean_g,
                "b": mean_b,
            })

    # Overall color balance across all active bars
    tot_R = sum(b["r"] for b in bars if not b["is_rest"])
    tot_G = sum(b["g"] for b in bars if not b["is_rest"])
    tot_B = sum(b["b"] for b in bars if not b["is_rest"])
    tot_sum = tot_R + tot_G + tot_B + 1e-6
    r_ratio = tot_R / tot_sum
    b_ratio = tot_B / tot_sum

    if tot_R > tot_B * 1.15 or r_ratio > 0.38:
        # Red/orange dominance (Fire, Wildfire, Smoke): Phrygian Dominant intervals
        scale_name = "Phrygian Dominant (Fire/Smoke)"
        scale = [0, 1, 4, 5, 7, 8, 10]
        color_tone = 11  # B (leading tone)
        color_tone_name = "B (leading tone)"
        track_chord_set = "phrygian_dominant"
        drum_pattern = "fire_sparse"
        gm_programs = {
            "pad": 89,
            "harmony": 89,
            "bass": 33,
            "melody": 25,  # Steel String Guitar
            "riser": 119,
            "texture": 127,  # Crackling atmosphere
            "drone": 89,
        }
        gm_instrument_names = {
            "harmony": "Warm Pad (GM 89)",
            "bass": "Electric Bass (GM 33)",
            "melody": "Steel Guitar (GM 25)",
            "texture": "Atmosphere (GM 127)",
            "drone": "Warm Pad (GM 89)",
        }
    elif tot_B > tot_R * 1.15 or b_ratio > 0.38:
        # Blue/cyan dominance (Ocean, Sea Ice, Water): Open fifths, Dorian mode
        scale_name = "Dorian (Ocean/Ice)"
        scale = [0, 2, 3, 5, 7, 9, 10]
        color_tone = 1  # Db
        color_tone_name = "Db (minor second)"
        track_chord_set = "dorian"
        drum_pattern = "soft_brush"
        gm_programs = {
            "pad": 89,
            "harmony": 89,
            "bass": 33,
            "melody": 24,  # Nylon Guitar
            "riser": 119,
            "texture": 122,  # Seashore
            "drone": 89,
        }
        gm_instrument_names = {
            "harmony": "Warm Pad (GM 89)",
            "bass": "Electric Bass (GM 33)",
            "melody": "Nylon Guitar (GM 24)",
            "texture": "Seashore (GM 122)",
            "drone": "Warm Pad (GM 89)",
        }
    else:
        # Neutral: Aeolian (Natural Minor)
        scale_name = "Natural Minor (Aeolian)"
        scale = [0, 2, 3, 5, 7, 8, 10]
        color_tone = 1
        color_tone_name = "Db (minor second)"
        track_chord_set = "natural_minor"
        drum_pattern = "soft_brush"
        gm_programs = dict(SVS_PRESET_V3["gm_programs"])
        gm_instrument_names = dict(SVS_PRESET_V3["gm_instrument_names"])

    preset = dict(SVS_PRESET_V3)
    preset["tempo"] = tempo
    preset["bar_seconds"] = bar_seconds
    preset["bars"] = n_bars
    preset["track_id"] = track_id
    preset["scale_name"] = scale_name
    preset["scale"] = scale
    preset["color_tone"] = color_tone
    preset["color_tone_name"] = color_tone_name
    preset["drum_pattern"] = drum_pattern
    preset["gm_programs"] = gm_programs
    preset["gm_instrument_names"] = gm_instrument_names

    raw_series = [b.get("speed_p95") for b in bars]
    form_info = compute_svs_form(raw_series)
    norm_speeds, _ = normalize_series_5_95(bars)

    # Derive unique seed from incoming energy and color series
    digest_input = json.dumps([
        {
            k: round(v, 4) if isinstance(v, float) else v
            for k, v in b.items()
            if k in ("speed_p95", "ageo_u", "ageo_v", "brightness", "motion", "r", "g", "b")
        }
        for b in bars
    ], sort_keys=True)
    seed_str = hashlib.sha256(f"{track_id}:{digest_input}".encode("utf-8")).hexdigest()
    seed_int = int(seed_str[:16], 16)

    harmony_bars = generate_harmony_v3(
        blocks=bars,
        preset=preset,
        track_id=track_chord_set,
        form_info=form_info,
        hold_threshold=preset.get("hold_threshold", 0.013),
    )
    rest_bars = [h.is_rest for h in harmony_bars]

    drum_events, effective_tiers, tier_counts = generate_drum_events_v3(
        norm_speeds=norm_speeds,
        preset=preset,
        track_id="svs_visual",
        seed=seed_int,
        rest_bars=rest_bars,
    )

    melody_bars, color_tone_bars = generate_melody_v3(
        blocks=bars,
        norm_speeds=norm_speeds,
        harmony_bars=harmony_bars,
        preset=preset,
        seed=seed_int,
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    job_uid = uuid.uuid4().hex[:8]
    midi_path = out_dir / f"frame_{job_uid}.mid"
    wav_path = out_dir / f"frame_{job_uid}.wav"
    opus_path = out_dir / f"frame_{job_uid}.opus"

    build_midi_v3(bars, norm_speeds, harmony_bars, melody_bars, drum_events, preset, midi_path)
    render_v3_audio(midi_path, wav_path, opus_path, target_lufs=-24.0)

    h_opus = hashlib.sha256(opus_path.read_bytes()).hexdigest()

    # Cleanup intermediate mid and wav
    for p in (midi_path, wav_path):
        try:
            if p.exists():
                p.unlink()
        except Exception:
            pass

    tier_map = {"base": 0, "low": 1, "medium": 2, "high": 3, "rest": 0}
    bars_summary = []
    for b in range(n_bars):
        h = harmony_bars[b]
        m = melody_bars[b]
        bar_tier = effective_tiers[b] if b < len(effective_tiers) else "base"
        vel = m.notes[0].velocity if (not m.is_rest and m.notes) else 0
        note_cnt = len(m.notes) if not m.is_rest else 0
        bars_summary.append({
            "bar": b,
            "is_rest": h.is_rest,
            "scale": scale_name,
            "chord": h.chord_numeral,
            "chord_name": h.chord,
            "brightness": round(bars[b].get("brightness", 0.0), 3),
            "motion": round(bars[b].get("motion", 0.0), 3),
            "r": round(bars[b].get("r", 0.0), 3),
            "g": round(bars[b].get("g", 0.0), 3),
            "b": round(bars[b].get("b", 0.0), 3),
            "note_density": note_cnt,
            "velocity": vel,
            "drum_tier": tier_map.get(bar_tier, 0),
            "drum_tier_name": bar_tier,
        })

    return opus_path, {
        "bars": n_bars,
        "tempo": round(tempo, 1),
        "bar_seconds": round(bar_seconds, 4),
        "duration_s": round(duration, 2),
        "scale": scale_name,
        "chord_set": track_chord_set,
        "bars_summary": bars_summary,
        "opus_sha256": h_opus,
    }


def sonify_extracted_frames(
    frames_b64: list[str],
    out_dir: Path,
    track_id: str = "custom_visual",
    mode: str = "musical",
) -> tuple[Path, dict[str, Any]]:
    """Decode base64 video frames, compute brightness, motion, and color energies,
    and sonify via Engine v3.
    """
    frame_energies: list[dict[str, Any]] = []
    prev_gray: np.ndarray | None = None

    for idx, item in enumerate(frames_b64):
        raw_b64 = item.split(",", 1)[1] if "," in item else item
        try:
            raw_bytes = base64.b64decode(raw_b64)
            np_arr = np.frombuffer(raw_bytes, dtype=np.uint8)
            img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if img is not None:
                # Downsample to 160 width if larger
                if img.shape[1] > 160:
                    h = int(img.shape[0] * 160 / img.shape[1])
                    img = cv2.resize(img, (160, h), interpolation=cv2.INTER_AREA)

                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                br = float(gray.mean()) / 255.0

                # Compute motion delta relative to previous frame
                if prev_gray is not None and prev_gray.shape == gray.shape:
                    diff = cv2.absdiff(prev_gray, gray)
                    motion = float(diff.mean()) / 255.0
                else:
                    motion = 0.0
                prev_gray = gray

                b_mean = float(img[:, :, 0].mean()) / 255.0
                g_mean = float(img[:, :, 1].mean()) / 255.0
                r_mean = float(img[:, :, 2].mean()) / 255.0

                frame_energies.append({
                    "brightness": br,
                    "motion": motion,
                    "r": r_mean,
                    "g": g_mean,
                    "b": b_mean,
                })
            else:
                frame_energies.append({
                    "brightness": 0.0,
                    "motion": 0.0,
                    "r": 0.0,
                    "g": 0.0,
                    "b": 0.0,
                })
        except Exception:
            frame_energies.append({
                "brightness": 0.0,
                "motion": 0.0,
                "r": 0.0,
                "g": 0.0,
                "b": 0.0,
            })

    if not frame_energies:
        raise ValueError("No frames could be decoded.")

    return sonify_frame_energies(frame_energies, out_dir, track_id=track_id, mode=mode)
