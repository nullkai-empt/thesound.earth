from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

# Ensure repo root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import winsound
import numpy as np
import soundfile as sf

from aetherwaves.rhythm import (
    drum_events_to_midi,
    generate_drum_events,
    load_daily_data,
    normalize_series_5_95,
    speed_to_tier,
)


def find_fluidsynth() -> Path:
    """Find fluidsynth executable in tools/ or system PATH."""
    candidates = [
        Path("tools/fluidsynth/fluidsynth-v2.6.2-win10-x64-cpp11/bin/fluidsynth.exe"),
        Path("tools/fluidsynth/bin/fluidsynth.exe"),
    ]
    for c in candidates:
        if c.exists():
            return c.resolve()
    import shutil
    which = shutil.which("fluidsynth")
    if which:
        return Path(which)
    raise FileNotFoundError("FluidSynth executable not found.")


def find_soundfont() -> Path:
    """Find a valid SoundFont (.sf2 or .dls)."""
    candidates = [
        Path("soundfonts/FluidR3_GM.sf2"),
        Path("soundfonts/GeneralUser_GS.sf2"),
        Path("C:/Windows/System32/drivers/gm.dls"),
    ]
    for c in candidates:
        if c.exists():
            return c.resolve()
    raise FileNotFoundError("SoundFont file not found in soundfonts/ or Windows drivers.")


def render_with_fluidsynth(
    midi_path: Path,
    soundfont_path: Path,
    out_wav_path: Path,
    sample_rate: int = 44100,
    gain: float = 1.0,
) -> Path:
    """
    Render a MIDI file to WAV using FluidSynth with higher gain.
    """
    fluidsynth = find_fluidsynth()
    out_wav_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(fluidsynth),
        "-ni",                       # Non-interactive shell
        "-g", str(gain),             # Higher master gain
        "-r", str(sample_rate),      # 44.1 kHz
        "-F", str(out_wav_path.resolve()),
        str(soundfont_path.resolve()),
        str(midi_path.resolve()),
    ]

    print(f"[FluidSynth] Rendering {midi_path.name} with gain={gain}...")
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print("[FluidSynth Error]", res.stderr, file=sys.stderr)
        raise RuntimeError(f"FluidSynth failed with returncode {res.returncode}: {res.stderr}")

    if not out_wav_path.exists() or out_wav_path.stat().st_size == 0:
        raise RuntimeError(f"FluidSynth did not create a valid WAV file: {out_wav_path}")

    return out_wav_path


def normalize_wav_to_dbfs(wav_path: Path, target_dbfs: float = -1.0) -> tuple[float, float]:
    """
    Peak-normalize WAV file to target dBFS (default: -1.0 dBFS).
    Returns (initial_peak, final_peak).
    """
    data, sr = sf.read(str(wav_path))
    initial_peak = float(np.max(np.abs(data)))
    if initial_peak > 1e-6:
        target_peak = 10.0 ** (target_dbfs / 20.0)  # ~0.89125
        gain = target_peak / initial_peak
        normalized = np.clip(data * gain, -1.0, 1.0)
        sf.write(str(wav_path), normalized, sr, subtype="PCM_16")
        final_peak = float(np.max(np.abs(normalized)))
        return initial_peak, final_peak
    return initial_peak, initial_peak


def print_scorecard(
    dates: list[str],
    raw_speeds: list[float | None],
    norm_speeds: list[float | None],
    events: list,
    low_thresh: float = 0.35,
    high_thresh: float = 0.70,
    max_rows: int | None = None,
) -> None:
    """Print aligned table of speed series next to tier and drum details per bar."""
    print("\n" + "=" * 98)
    print(f"{'Bar':<4} | {'Date':<10} | {'Raw p95':<9} | {'Norm Spd':<8} | {'Tier':<7} | {'K/Sn/Sh Vel':<11} | {'Events in Bar':<36}")
    print("-" * 98)

    active_tier = "low"
    candidate_tier = None
    candidate_streak = 0

    display_len = min(len(dates), max_rows) if max_rows else len(dates)

    for b in range(len(dates)):
        d_str = dates[b]
        raw_sp = raw_speeds[b]
        norm_sp = norm_speeds[b]
        bar_evs = [e for e in events if e.bar == b]

        if norm_sp is None:
            tier_display = "REST"
            vel_str = "-"
            summary = "Full-bar rest (0 events)"
        else:
            tgt = speed_to_tier(norm_sp, low_thresh, high_thresh)
            if tgt != active_tier:
                if candidate_tier == tgt:
                    candidate_streak += 1
                else:
                    candidate_tier = tgt
                    candidate_streak = 1
                if candidate_streak >= 2:
                    active_tier = candidate_tier
                    candidate_tier = None
                    candidate_streak = 0
            else:
                candidate_tier = None
                candidate_streak = 0

            tier_display = active_tier

            # Extract velocities
            k_vels = [e.velocity for e in bar_evs if e.instrument == "kick"]
            sn_vels = [e.velocity for e in bar_evs if e.instrument == "snare" and e.beat in (2.0, 4.0)]
            sh_vels = [e.velocity for e in bar_evs if e.instrument == "shaker" and e.beat == 1.0]

            k_v = str(k_vels[0]) if k_vels else "-"
            sn_v = str(sn_vels[0]) if sn_vels else "-"
            sh_v = str(sh_vels[0]) if sh_vels else "-"
            vel_str = f"{k_v:>3}/{sn_v:>3}/{sh_v:>3}"

            inst_counts = {}
            for e in bar_evs:
                inst_counts[e.instrument] = inst_counts.get(e.instrument, 0) + 1
            summary_parts = [f"{cnt} {name}" for name, cnt in inst_counts.items()]
            summary = ", ".join(summary_parts)

        if b < display_len:
            raw_str = f"{raw_sp:.4f}" if raw_sp is not None else "None"
            norm_str = f"{norm_sp:.4f}" if norm_sp is not None else "None"
            print(f"{b:<4} | {d_str:<10} | {raw_str:>9} | {norm_str:>8} | {tier_display:<7} | {vel_str:<11} | {summary:<36}")

    if max_rows and len(dates) > max_rows:
        print(f"... ({len(dates) - max_rows} more bars truncated from display table)")

    print("=" * 98 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="System 1 Rhythm Runner with Real NASA OSCAR Data")
    parser.add_argument("--json", type=str, default="data/raw_oscar/oscar_2025_daily.json", help="Path to OSCAR daily JSON")
    parser.add_argument("--seed", type=int, default=42, help="Deterministic seed for fills and ghost notes")
    parser.add_argument("--gain", type=float, default=1.0, help="FluidSynth render gain (default: 1.0)")
    parser.add_argument("--target-dbfs", type=float, default=-1.0, help="Final WAV peak normalization target in dBFS (default: -1.0)")
    parser.add_argument("--play", action="store_true", default=True, help="Play audio immediately on completion (default: True)")
    parser.add_argument("--no-play", dest="play", action="store_false", help="Do not play audio automatically")
    parser.add_argument("--limit-days", type=int, default=None, help="Limit number of days to render for preview (default: all)")
    parser.add_argument("--out-dir", type=str, default="output", help="Directory for output files")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=== AetherWaves System 1: Real NASA Ocean Rhythm Engine ===")

    # 1. Load real NASA OSCAR data, compute summary lines (Requirement 1 & 5)
    records, norm_speeds, norm_audit = load_daily_data(args.json, print_summary=True)
    print(f"Loaded {len(records)} daily records from {args.json}.")
    print(f"Whole-Series Normalization (5th-95th percentile, clamped 0-1):")
    print(f"  P5 = {norm_audit['p5']:.4f} m/s, P95 = {norm_audit['p95']:.4f} m/s")
    print(f"  Raw speed_p95 range: {norm_audit['min']:.4f} to {norm_audit['max']:.4f} m/s")

    if args.limit_days:
        records = records[:args.limit_days]
        norm_speeds = norm_speeds[:args.limit_days]

    # 2. Generate drum events from real normalized values (1 day = 1 bar)
    events = generate_drum_events(norm_speeds, seed=args.seed)
    print(f"Generated {len(events)} percussion events across {len(records)} bars (72 BPM, 4/4 meter).")

    # 3. Print scorecard matching speed to tier per bar (Requirement 7)
    dates = [str(r.get("date", f"Day-{i}")) for i, r in enumerate(records)]
    raw_speeds = [r.get("speed_p95") for r in records]
    print_scorecard(dates, raw_speeds, norm_speeds, events, max_rows=30)

    # 4. Export MIDI
    midi_path = out_dir / "rhythm_real_oscar.mid"
    drum_events_to_midi(events, midi_path, bpm=72.0)
    print(f"MIDI exported: {midi_path}")

    # 5. Render with FluidSynth using higher gain (Requirement 5)
    soundfont = find_soundfont()
    print(f"SoundFont: {soundfont.name}")
    raw_wav_path = out_dir / "rhythm_real_oscar.wav"
    render_with_fluidsynth(midi_path, soundfont, raw_wav_path, gain=args.gain)

    # 6. Normalize final WAV to -1 dBFS (Requirement 5)
    init_pk, final_pk = normalize_wav_to_dbfs(raw_wav_path, target_dbfs=args.target_dbfs)
    print(f"[Mastering] Normalized {raw_wav_path.name}: Initial Peak={init_pk:.4f} -> Final Peak={final_pk:.4f} ({args.target_dbfs} dBFS)")

    # 7. Playback
    if args.play:
        print(f"\nPlaying {raw_wav_path} via Windows Audio...")
        try:
            winsound.PlaySound(str(raw_wav_path), winsound.SND_FILENAME | winsound.SND_ASYNC)
            print("Audio playback active in background!")
        except Exception as exc:
            print(f"Could not play automatically: {exc}. Open {raw_wav_path} in your player.")

    print("\nRun complete! Output files:")
    print(f" - MIDI:  {midi_path}")
    print(f" - Audio: {raw_wav_path}")


if __name__ == "__main__":
    main()
