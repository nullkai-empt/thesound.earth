from __future__ import annotations
from pathlib import Path
from typing import Literal
import numpy as np
import soundfile as sf
from scipy.signal import butter, lfilter, sosfilt
from .models import NoteEvent


def _adsr_envelope(n_samples: int, sr: int, attack_s: float, decay_s: float, sustain: float, release_s: float) -> np.ndarray:
    a = min(int(attack_s * sr), n_samples // 3)
    d = min(int(decay_s * sr), max(0, n_samples // 3 - a))
    r = min(int(release_s * sr), max(1, n_samples // 4))
    s_len = max(0, n_samples - a - d - r)

    parts = []
    if a > 0:
        parts.append(np.linspace(0.0, 1.0, a, endpoint=False))
    if d > 0:
        parts.append(np.linspace(1.0, sustain, d, endpoint=False))
    if s_len > 0:
        parts.append(np.full(s_len, sustain, dtype=np.float64))
    if r > 0:
        parts.append(np.linspace(sustain if s_len + d > 0 else 1.0, 0.0, r))
    env = np.concatenate(parts) if parts else np.ones(n_samples, dtype=np.float64)
    if len(env) < n_samples:
        env = np.pad(env, (0, n_samples - len(env)))
    return env[:n_samples]


def _synth_voice_u(freq: float, n_samples: int, sr: int, sign: int, mode: str) -> np.ndarray:
    t = np.arange(n_samples, dtype=np.float64) / sr
    if mode == "diagnostic":
        wave = np.sin(2.0 * np.pi * freq * t)
        return wave * _adsr_envelope(n_samples, sr, 0.03, 0.05, 0.85, 0.05)

    mod_index = 1.4 if sign >= 0 else 0.75
    cutoff_hz = 2200.0 if sign >= 0 else 1100.0
    modulator = mod_index * np.sin(2.0 * np.pi * (freq * 2.0) * t)
    carrier = (
        0.65 * np.sin(2.0 * np.pi * freq * t + modulator)
        + 0.35 * np.sin(2.0 * np.pi * (freq * 1.003) * t)
    )
    sos = butter(2, min(cutoff_hz, sr * 0.45), btype="low", fs=sr, output="sos")
    filtered = sosfilt(sos, carrier)
    return filtered * _adsr_envelope(n_samples, sr, 0.12, 0.25, 0.75, 0.20)


def _synth_voice_v(freq: float, n_samples: int, sr: int, sign: int, mode: str, seed: int) -> np.ndarray:
    t = np.arange(n_samples, dtype=np.float64) / sr
    if mode == "diagnostic":
        wave = np.sin(2.0 * np.pi * freq * t)
        return wave * _adsr_envelope(n_samples, sr, 0.005, 0.08, 0.0, 0.02)

    delay = max(2, int(round(sr / max(freq, 20.0))))
    rng = np.random.default_rng(seed)
    buf = rng.uniform(-1.0, 1.0, delay).astype(np.float64)
    buf -= np.mean(buf)

    damping = 0.996 if sign >= 0 else 0.988
    x = np.zeros(n_samples, dtype=np.float64)
    n_copy = min(delay, n_samples)
    x[:n_copy] = buf[:n_copy]

    a = np.zeros(delay + 2, dtype=np.float64)
    a[0] = 1.0
    a[delay] = -0.5 * damping
    a[delay + 1] = -0.5 * damping
    out = lfilter([1.0], a, x)

    fade = min(int(0.015 * sr), n_samples // 4)
    if fade > 0:
        out[-fade:] *= np.linspace(1.0, 0.0, fade)
    return out


def render_wav(
    events: list[NoteEvent],
    duration_sec: float,
    sample_rate_hz: int,
    out_path: str | Path,
    mode: Literal["diagnostic", "musical"] = "musical",
) -> Path:
    total_samples = int(round(duration_sec * sample_rate_hz))
    stereo = np.zeros((total_samples, 2), dtype=np.float64)

    for idx, ev in enumerate(events):
        if ev.is_rest or ev.frequency_hz is None:
            continue
        start_idx = max(0, int(round(ev.start_sec * sample_rate_hz)))
        n_samp = max(1, int(round(ev.duration_sec * sample_rate_hz)))
        end_idx = min(total_samples, start_idx + n_samp)
        actual_len = end_idx - start_idx
        if actual_len <= 0:
            continue

        if ev.voice == "voice_u":
            mono = _synth_voice_u(ev.frequency_hz, actual_len, sample_rate_hz, ev.sign, mode)
        else:
            mono = _synth_voice_v(ev.frequency_hz, actual_len, sample_rate_hz, ev.sign, mode, seed=1000 + idx)

        left_gain = np.sqrt(0.5 * (1.0 - ev.pan)) * ev.amplitude
        right_gain = np.sqrt(0.5 * (1.0 + ev.pan)) * ev.amplitude
        stereo[start_idx:end_idx, 0] += mono * left_gain
        stereo[start_idx:end_idx, 1] += mono * right_gain

    if mode == "musical":
        stereo = np.tanh(stereo * 0.85) * 0.92
    else:
        peak = float(np.max(np.abs(stereo)))
        if peak > 0.95:
            stereo = stereo * (0.95 / peak)

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    sf.write(out, stereo.astype(np.float32), sample_rate_hz, subtype="PCM_16")
    return out