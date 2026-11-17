from __future__ import annotations
import argparse
import json
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import soundfile as sf
import xarray as xr


def render_dashboard(
    nc_path: str | Path,
    json_path: str | Path,
    wav_path: str | Path,
    out_png: str | Path = "output/aetherwaves_visual.png",
) -> Path:
    audit = json.loads(Path(json_path).read_text(encoding="utf-8"))
    samples = audit["samples"]
    lat_val = samples[0]["latitude"]
    lon_val = samples[0]["longitude"]

    ds = xr.open_dataset(nc_path, mask_and_scale=True)
    lat_dim = "latitude" if "latitude" in ds.coords else "lat"
    lon_dim = "longitude" if "longitude" in ds.coords else "lon"

    u0 = ds["u"].isel(time=0) if "time" in ds["u"].dims else ds["u"]
    v0 = ds["v"].isel(time=0) if "time" in ds["v"].dims else ds["v"]
    speed_grid = np.hypot(u0.values, v0.values)
    lons = ds[lon_dim].values
    lats = ds[lat_dim].values

    audio, sr = sf.read(wav_path, dtype="float32")
    mono = audio.mean(axis=1) if audio.ndim > 1 else audio
    t_audio = np.arange(len(mono)) / sr

    timestamps = [s["timestamp"] for s in samples]
    u_series = [s["variables"]["u"] if s["is_valid"] else np.nan for s in samples]
    v_series = [s["variables"]["v"] if s["is_valid"] else np.nan for s in samples]
    spd_series = [s["derived"]["speed"] if s["is_valid"] else np.nan for s in samples]

    plt.style.use("dark_background")
    fig, axes = plt.subplots(2, 2, figsize=(14, 8.5), facecolor="#0b0f14")
    for ax in axes.flat:
        ax.set_facecolor("#111720")

    # 1. Global Ocean Current Speed Map
    ax_map = axes[0, 0]
    mesh = ax_map.pcolormesh(lons, lats, speed_grid.T if speed_grid.shape == (len(lons), len(lats)) else speed_grid,
                             cmap="viridis", shading="auto", vmin=0, vmax=1.5)
    ax_map.scatter([lon_val], [lat_val], color="#ff4d6d", s=90, marker="o", edgecolors="white", linewidth=1.5, zorder=5)
    ax_map.set_title(f"OSCAR v2.0 Global Speed (m/s) — Target ({lat_val:.2f}°, {lon_val:.2f}°)", fontsize=11)
    ax_map.set_xlabel("Longitude")
    ax_map.set_ylabel("Latitude")
    fig.colorbar(mesh, ax=ax_map, fraction=0.046, pad=0.04)

    # 2. Scientific Time Series (u, v, speed)
    ax_ts = axes[0, 1]
    x_idx = np.arange(len(timestamps))
    ax_ts.plot(x_idx, spd_series, color="#38bdf8", linewidth=2.2, marker="o", label="Speed (m/s)")
    ax_ts.plot(x_idx, u_series, color="#34d399", linewidth=1.5, linestyle="--", label="u Eastward (m/s)")
    ax_ts.plot(x_idx, v_series, color="#fbbf24", linewidth=1.5, linestyle=":", label="v Northward (m/s)")
    ax_ts.axhline(0, color="#475569", linewidth=0.8)
    ax_ts.set_title("Extracted Ocean Velocity Components", fontsize=11)
    ax_ts.set_xticks(x_idx[::max(1, len(x_idx) // 5)])
    ax_ts.set_xticklabels([timestamps[i] for i in x_idx[::max(1, len(x_idx) // 5)]], rotation=20, fontsize=8)
    ax_ts.set_ylabel("m/s")
    ax_ts.legend(frameon=False, fontsize=9)

    # 3. Audio Waveform
    ax_wav = axes[1, 0]
    ax_wav.plot(t_audio, mono, color="#38bdf8", linewidth=0.6, alpha=0.9)
    ax_wav.set_title(f"Synthesized Waveform ({audit['render_mode']} mode)", fontsize=11)
    ax_wav.set_xlabel("Time (s)")
    ax_wav.set_ylabel("Amplitude")
    ax_wav.set_ylim(-1.0, 1.0)

    # 4. Spectrogram
    ax_spec = axes[1, 1]
    ax_spec.specgram(mono, Fs=sr, NFFT=1024, noverlap=512, cmap="magma")
    ax_spec.set_title("Audio Spectrogram (Pitch & Pulse Density)", fontsize=11)
    ax_spec.set_xlabel("Time (s)")
    ax_spec.set_ylabel("Frequency (Hz)")
    ax_spec.set_ylim(0, 2500)

    fig.suptitle(f"AetherWaves — {audit['dataset']} ({audit['mapping_version']})", fontsize=14, color="#f8fafc")
    plt.tight_layout()
    out = Path(out_png)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=180, facecolor=fig.get_facecolor())
    plt.close(fig)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="AetherWaves Visual Dashboard Generator")
    parser.add_argument("--nc", default="data/oscar_global.nc")
    parser.add_argument("--json", default="output/aetherwaves_musical.json")
    parser.add_argument("--wav", default="output/aetherwaves_musical.wav")
    parser.add_argument("--out", default="output/aetherwaves_visual.png")
    args = parser.parse_args()
    out = render_dashboard(args.nc, args.json, args.wav, args.out)
    print(f"Generated visual dashboard: {out}")


if __name__ == "__main__":
    main()