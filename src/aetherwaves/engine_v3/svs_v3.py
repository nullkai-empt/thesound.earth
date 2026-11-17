"""svs_v3.py — SVS visual motion sonification engine using AetherWaves Engine v3.

Mapping:
- CPU decode only: ffmpeg fps=1, scale 160:-1, gray rawvideo piped to numpy.
- Optical flow via OpenCV Farneback on consecutive frame pairs:
    intensity = mean magnitude of the optical-flow field
    direction = mean flow angle (atan2 of mean_dy, mean_dx) -> ocean-style chords
- Black or missing frame = rest (None, never zero).
- 1 bar = bar_seconds of video time (audio length = video length).
- Tempo strictly within [56, 96] BPM.
- Multi-track Type-1 MIDI (zero CC11 events).
- FluidSynth + FluidR3_GM only with reverb.
- Normalized to -24 LUFS, bitexact mono Opus export.
- Generates Opus + meta.json in v3 schema, domain "visual".
- honest_limits: motion in a rendered animation, not a measurement.
- Zero banned words.
"""
from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import cv2  # type: ignore
import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from aetherwaves.engine_v3.form_v3 import compute_form_sections
from aetherwaves.engine_v3.harmony_v3 import (
    BarHarmonyV3,
    generate_harmony_v3,
    get_sector_v3,
    sector_to_role,
)
from aetherwaves.engine_v3.melody_v3 import generate_melody_v3
from aetherwaves.engine_v3.pipeline_v3 import (
    analyze_v3_audio,
    build_midi_v3,
    render_v3_audio,
)
from aetherwaves.engine_v3.rhythm_v3 import generate_drum_events_v3
from aetherwaves.rhythm import normalize_series_5_95
from scripts.generate_meta_v3 import build_meta_v3, check_banned_words

SVS_PRESET_V3: dict[str, Any] = {
    "track_id": "svs_visual",
    "domain": "visual",
    "label": "Visual motion sonification — inspired by, not authentic",
    "disclaimer": "inspired by, not authentic",
    "scale_name": "Natural Minor (Aeolian)",
    "scale": [0, 2, 3, 5, 7, 8, 10],
    "color_tone": 1,  # Db outside scale
    "color_tone_name": "Db (minor second / chromatic inflection)",
    "gm_programs": {
        "pad": 89,          # Warm Pad
        "harmony": 89,
        "bass": 33,         # Electric Bass (finger)
        "melody": 24,       # Acoustic Guitar (nylon)
        "riser": 119,       # Reverse Cymbal
        "texture": 122,     # Seashore / atmospheric
        "drone": 89,        # Warm Pad
    },
    "gm_instrument_names": {
        "harmony": "Warm Pad (GM 89)",
        "bass": "Electric Bass (GM 33)",
        "melody": "Nylon Guitar (GM 24)",
        "texture": "Seashore (GM 122)",
        "drone": "Warm Pad (GM 89)",
    },
    "drum_pattern": "soft_brush",
    "pan": {
        "pad": -0.2,
        "harmony": -0.2,
        "bass": 0.0,
        "melody": 0.15,
        "texture": 0.3,
        "drone": 0.0,
        "drums": -0.1,
    },
    "hold_threshold": 0.013,
}

_FB_PARAMS = dict(
    pyr_scale=0.5,
    levels=3,
    winsize=15,
    iterations=3,
    poly_n=5,
    poly_sigma=1.2,
    flags=0,
)


def probe_video_info(video_path: Path) -> tuple[int, int, float]:
    """Probe video width, height, and duration using ffprobe."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,duration",
        "-show_entries", "format=duration",
        "-of", "json",
        str(video_path),
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        data = json.loads(res.stdout)
        streams = data.get("streams", [])
        w, h, dur = 1920, 1080, 0.0
        if streams:
            s0 = streams[0]
            w = int(s0.get("width", 1920))
            h = int(s0.get("height", 1080))
            if "duration" in s0:
                try:
                    dur = float(s0["duration"])
                except (ValueError, TypeError):
                    pass
        if dur <= 0.0 and "format" in data and "duration" in data["format"]:
            try:
                dur = float(data["format"]["duration"])
            except (ValueError, TypeError):
                pass
        return w, h, dur
    except Exception:
        return 1920, 1080, 0.0


def extract_svs_frames_cpu(video_path: Path, timeout: float = 300.0) -> tuple[list[np.ndarray | None], float]:
    """Run ONE CPU ffmpeg pass: fps=1, scale 160:-1, gray rawvideo piped to numpy."""
    w_orig, h_orig, duration = probe_video_info(video_path)
    scaled_h = int(h_orig * 160 / w_orig)
    if scaled_h % 2 != 0:
        scaled_h += 1
    if scaled_h <= 0:
        scaled_h = 90

    cmd = [
        "ffmpeg",
        "-v", "error",
        "-i", str(video_path),
        "-vf", "fps=1,scale=160:-1",
        "-pix_fmt", "gray",
        "-f", "rawvideo",
        "-",
    ]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout)
        raw = proc.stdout
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f"ffmpeg extraction timed out after {timeout} seconds") from exc
    if not raw:
        return [], duration

    frame_bytes = 160 * scaled_h
    frames: list[np.ndarray | None] = []
    offset = 0
    while offset + frame_bytes <= len(raw):
        chunk = raw[offset : offset + frame_bytes]
        arr = np.frombuffer(chunk, dtype=np.uint8).reshape((scaled_h, 160))
        # Black frame check: mean pixel value < 8
        if float(arr.mean()) < 8.0:
            frames.append(None)
        else:
            frames.append(arr)
        offset += frame_bytes

    if duration <= 0.0:
        duration = float(len(frames))

    return frames, duration


def compute_svs_flow(frames: list[np.ndarray | None]) -> list[dict[str, Any]]:
    """Compute Farneback optical flow on consecutive frame pairs."""
    results: list[dict[str, Any]] = []
    n_frames = len(frames)
    if n_frames < 2:
        return results

    for i in range(n_frames - 1):
        f_prev, f_curr = frames[i], frames[i + 1]
        date_tag = f"sec_{i:04d}"
        if f_prev is None or f_curr is None:
            results.append({
                "valid": False,
                "is_rest": True,
                "speed_p95": None,
                "magnitude": None,
                "ageo_u": 0.0,
                "ageo_v": 0.0,
                "ageo_angle_deg": None,
                "date": date_tag,
            })
            continue

        flow = cv2.calcOpticalFlowFarneback(f_prev, f_curr, None, **_FB_PARAMS)
        dx = flow[:, :, 0]
        dy = flow[:, :, 1]
        mag = np.sqrt(dx**2 + dy**2)
        mean_mag = float(np.mean(mag))
        mean_dx = float(np.mean(dx))
        mean_dy = float(np.mean(dy))
        mean_ang = float(math.degrees(math.atan2(mean_dy, mean_dx)))

        if mean_mag < 1e-9:
            results.append({
                "valid": False,
                "is_rest": True,
                "speed_p95": None,
                "magnitude": None,
                "ageo_u": 0.0,
                "ageo_v": 0.0,
                "ageo_angle_deg": None,
                "date": date_tag,
            })
        else:
            results.append({
                "valid": True,
                "is_rest": False,
                "speed_p95": mean_mag,
                "magnitude": mean_mag,
                "ageo_u": mean_dx,
                "ageo_v": mean_dy,
                "ageo_angle_deg": mean_ang,
                "date": date_tag,
            })

    return results


def group_flow_into_bars(
    flow_rows: list[dict[str, Any]],
    duration: float,
) -> tuple[list[dict[str, Any]], float, float, int]:
    """Map video time to musical bars so that:
    1 bar = bar_seconds of video time, and audio length = video length.
    Tempo is strictly kept within [56, 96] BPM.
    """
    T = max(duration, float(len(flow_rows) + 1))
    target_bar_sec = 3.75
    n_bars = max(3, int(round(T / target_bar_sec)))

    bar_seconds = T / n_bars
    tempo = 240.0 / bar_seconds

    # Clamp tempo to [56, 96] BPM by adjusting bar count
    if tempo < 56.0:
        n_bars = max(3, int(math.ceil(56.0 * T / 240.0)))
        bar_seconds = T / n_bars
        tempo = 240.0 / bar_seconds
    elif tempo > 96.0:
        n_bars = max(3, int(math.floor(96.0 * T / 240.0)))
        bar_seconds = T / n_bars
        tempo = 240.0 / bar_seconds

    bars: list[dict[str, Any]] = []
    n_steps = len(flow_rows)

    for b in range(n_bars):
        t_start = b * bar_seconds
        t_end = (b + 1) * bar_seconds

        # Indices of optical flow steps covering [t_start, t_end)
        idx_start = max(0, min(int(math.floor(t_start)), n_steps - 1)) if n_steps > 0 else 0
        idx_end = max(idx_start + 1, min(int(math.ceil(t_end)), n_steps)) if n_steps > 0 else 0

        bar_steps = flow_rows[idx_start:idx_end] if n_steps > 0 else []
        valid_steps = [s for s in bar_steps if s.get("valid") and s.get("speed_p95") is not None]

        bar_tag = f"Bar-{b:02d}"
        if not valid_steps:
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
            })
        else:
            m_mag = float(np.mean([s["speed_p95"] for s in valid_steps]))
            m_u = float(np.mean([s["ageo_u"] for s in valid_steps]))
            m_v = float(np.mean([s["ageo_v"] for s in valid_steps]))
            ang = float(math.degrees(math.atan2(m_v, m_u)))
            sec = get_sector_v3(ang)
            bars.append({
                "bar": b,
                "valid": True,
                "is_rest": False,
                "speed_p95": m_mag,
                "magnitude": m_mag,
                "ageo_u": m_u,
                "ageo_v": m_v,
                "ageo_angle_deg": ang,
                "sector": sec,
                "date": bar_tag,
            })

    return bars, round(bar_seconds, 4), round(tempo, 1), n_bars


def compute_svs_form(raw_series: list[float | None]) -> dict[str, Any]:
    """Compute section boundaries from data, adapting for arbitrary bar counts."""
    n_bars = len(raw_series)
    if n_bars == 53:
        return compute_form_sections(raw_series)

    valid_vals = [float(v) if v is not None else 0.0 for v in raw_series]
    raw_max = max(valid_vals) if valid_vals else 0.0
    peak_idx = next((i for i, v in enumerate(valid_vals) if v == raw_max), n_bars // 2)

    # Adaptive sections based on data and bar count
    if n_bars < 15:
        intro_end = max(0, min(peak_idx - 1, 1))
        calm_start = min(n_bars - 1, max(peak_idx + 1, n_bars - 2))
        p_start = intro_end + 1 if intro_end < peak_idx else peak_idx
        p_end = max(p_start, min(peak_idx + 1, calm_start - 1)) if calm_start > p_start else p_start

        sections = [
            {"name": "intro", "start_bar": 0, "end_bar": intro_end, "length": intro_end + 1},
            {"name": "build", "start_bar": intro_end + 1, "end_bar": max(intro_end + 1, p_start - 1), "length": max(0, p_start - intro_end - 1)},
            {"name": "peak", "start_bar": p_start, "end_bar": p_end, "length": p_end - p_start + 1},
            {"name": "decline", "start_bar": p_end + 1, "end_bar": max(p_end + 1, calm_start - 1), "length": max(0, calm_start - p_end - 1)},
            {"name": "calm", "start_bar": calm_start, "end_bar": n_bars - 1, "length": (n_bars - 1) - calm_start + 1},
        ]
    else:
        # 5 contiguous sections adapted to n_bars
        intro_len = max(2, int(round(n_bars * 0.15)))
        calm_len = max(2, int(round(n_bars * 0.15)))
        intro_end = intro_len - 1
        calm_start = n_bars - calm_len

        # Peak around peak_idx (at least 3 bars)
        p_len = max(3, int(round(n_bars * 0.2)))
        p_start = max(intro_end + 1, min(peak_idx - p_len // 2, calm_start - p_len))
        p_end = min(calm_start - 1, p_start + p_len - 1)

        b_end = p_start - 1
        d_start = p_end + 1
        d_end = calm_start - 1

        sections = [
            {"name": "intro", "start_bar": 0, "end_bar": intro_end, "length": intro_end + 1},
            {"name": "build", "start_bar": intro_end + 1, "end_bar": b_end, "length": max(0, b_end - intro_end)},
            {"name": "peak", "start_bar": p_start, "end_bar": p_end, "length": p_end - p_start + 1},
            {"name": "decline", "start_bar": d_start, "end_bar": d_end, "length": max(0, d_end - d_start + 1)},
            {"name": "calm", "start_bar": calm_start, "end_bar": n_bars - 1, "length": (n_bars - 1) - calm_start + 1},
        ]

    # Filter out empty placeholder sections
    active_sections = [s for s in sections if s["length"] > 0]
    bar_to_section = ["intro"] * n_bars
    for s in active_sections:
        for b in range(s["start_bar"], s["end_bar"] + 1):
            if b < n_bars:
                bar_to_section[b] = s["name"]

    section_captions = {
        s["name"]: f"{s['name'].capitalize()} (bars {s['start_bar']}-{s['end_bar']})"
        for s in active_sections
    }

    return {
        "sections": active_sections,
        "bar_to_section": bar_to_section,
        "section_captions": section_captions,
        "peak_idx": peak_idx,
        "raw_max": raw_max,
        "opening_type": "sustained",
    }


def generate_svs_harmony_v3(
    bars: list[dict[str, Any]],
    preset: dict[str, Any],
    form_info: dict[str, Any],
) -> list[BarHarmonyV3]:
    """Generate ocean-style modal harmony using mean optical flow angle."""
    return generate_harmony_v3(
        blocks=bars,
        preset=preset,
        track_id="default_minor",
        form_info=form_info,
        hold_threshold=preset.get("hold_threshold", 0.013),
    )


def sonify_svs_v3(
    video_path: Path,
    svs_id: int | str,
    metadata: dict[str, Any] | None = None,
    out_opus_path: Path | None = None,
    out_meta_path: Path | None = None,
) -> dict[str, Any]:
    """Execute complete SVS sonification pipeline on a video using Engine v3."""
    if not video_path.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    # 1. CPU frame extraction & Farneback optical flow
    frames, duration = extract_svs_frames_cpu(video_path)
    flow_rows = compute_svs_flow(frames)

    # 2. Map flow to bars: 1 bar = bar_seconds of video time
    bars, bar_seconds, tempo, n_bars = group_flow_into_bars(flow_rows, duration)

    # 3. Setup preset with matched tempo and bar_seconds
    preset = dict(SVS_PRESET_V3)
    preset["tempo"] = tempo
    preset["bar_seconds"] = bar_seconds
    preset["bars"] = n_bars
    preset["track_id"] = f"svs_{svs_id}"

    # 4. Form and Normalization
    raw_series = [b.get("speed_p95") for b in bars]
    form_info = compute_svs_form(raw_series)

    norm_speeds, _ = normalize_series_5_95(bars)

    seed_str = hashlib.sha256(f"svs_{svs_id}:v3".encode("utf-8")).hexdigest()
    seed_int = int(seed_str, 16)

    # 5. Harmony, Drums, Melody
    harmony_bars = generate_svs_harmony_v3(bars, preset, form_info)
    rest_bars = [h.is_rest for h in harmony_bars]

    drum_events, effective_tiers, tier_counts = generate_drum_events_v3(
        norm_speeds=norm_speeds,
        preset=preset,
        track_id=f"svs_{svs_id}",
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

    # 6. Render Audio to temporary workspace
    with tempfile.TemporaryDirectory(prefix="svs_render_", ignore_cleanup_errors=True) as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        mid_path = tmp_dir / "track.mid"
        wav_path = tmp_dir / "track.wav"
        opus_path = tmp_dir / "track.opus"

        build_midi_v3(bars, norm_speeds, harmony_bars, melody_bars, drum_events, preset, mid_path)
        render_v3_audio(mid_path, wav_path, opus_path, target_lufs=-24.0)

        h_mid = hashlib.sha256(mid_path.read_bytes()).hexdigest()
        h_wav = hashlib.sha256(wav_path.read_bytes()).hexdigest()
        h_opus = hashlib.sha256(opus_path.read_bytes()).hexdigest()

        audio_analysis, sample_step = analyze_v3_audio(wav_path, form_info["sections"], preset["tempo"])

        if out_opus_path:
            out_opus_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(opus_path, out_opus_path)

        checksums = {
            "midi_sha256": h_mid,
            "wav_sha256": h_wav,
            "opus_sha256": h_opus,
        }

        # 7. Metadata generation
        meta = build_meta_v3(
            track_id=f"svs_{svs_id}",
            preset=preset,
            blocks=bars,
            norm_speeds=norm_speeds,
            harmony_bars=harmony_bars,
            melody_bars=melody_bars,
            effective_tiers=effective_tiers,
            tier_counts=tier_counts,
            form_info=form_info,
            audio_analysis=audio_analysis,
            sample_step=sample_step,
            color_tone_bars=color_tone_bars,
            checksums=checksums,
        )

        # Enforce domain visual and honest_limits
        meta["preset"]["domain"] = "visual"
        meta["scientific_data"]["dataset"] = {
            "name": "NASA Scientific Visualization Studio",
            "doi": "not verified",
            "url": f"https://svs.gsfc.nasa.gov/{svs_id}/",
            "version": "v3",
            "fields_used": ["optical_flow_magnitude", "optical_flow_angle"],
            "intensity_metric": "optical flow magnitude (pixels/sec)",
            "direction_source": "mean optical flow angle across frame pairs",
        }
        meta["scientific_data"]["honest_limits"] = (
            "Derived from satellite data; motion in a rendered animation, not a measurement. "
            "Every note is computed from the data by rules we chose."
        )

        violations = check_banned_words(meta, f"svs_{svs_id}_meta")
        if violations:
            raise ValueError(f"Banned words violations in SVS meta:\n" + "\n".join(violations))

        if out_meta_path:
            out_meta_path.parent.mkdir(parents=True, exist_ok=True)
            out_meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

        for p in (mid_path, wav_path, opus_path):
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass

    rest_count = sum(1 for b in bars if b.get("is_rest"))
    rest_pct = (rest_count / max(1, n_bars)) * 100.0

    return {
        "svs_id": svs_id,
        "duration": duration,
        "bars": n_bars,
        "bar_seconds": bar_seconds,
        "tempo": tempo,
        "rest_bars": rest_count,
        "rest_percent": rest_pct,
        "midi_sha256": h_mid,
        "wav_sha256": h_wav,
        "opus_sha256": h_opus,
        "sample_step": sample_step,
        "meta": meta,
    }
