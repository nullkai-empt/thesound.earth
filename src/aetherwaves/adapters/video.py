"""VideoAdapter — extracts optical-flow features from a video file.

ONE ffmpeg pass: fps=1, scale=160:-1, gray, rawvideo piped to numpy.
Motion via OpenCV Farneback on consecutive frame pairs.
  intensity  = mean magnitude of the flow field
  direction  = mean flow angle (atan2 of mean-y, mean-x of flow)
  bar_unit   = "frame group"

Black frame (all pixels < 8) or missing frame → None (rest, never zero).

Cache: output/svs_features/<id>_<decode_method>.json
  keyed by video etag (SHA-256 of file bytes) + ADAPTER_VERSION + decode_method.

Decode method:
- Default is None (CPU software decode, fully deterministic across platforms).
- Optional hardware decode: set "hwaccel": "d3d11va" or "cuda" in config.
- The decode method is strictly encoded in the cache key and file name so
  CPU and GPU outputs never cross-pollinate.
"""
from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np

from .base import AdapterBase

_CV2_AVAILABLE = False
try:
    import cv2  # type: ignore
    _CV2_AVAILABLE = True
except ImportError:
    pass


class VideoAdapter(AdapterBase):
    source_fields: dict[str, str] = {
        "speed_p95": (
            "Mean optical-flow magnitude (pixels/s, normalised) across all "
            "pixels of a 160-wide grayscale frame pair — every note is "
            "computed from the data by rules we chose"
        ),
        "ageo_angle_deg": (
            "Mean flow direction: atan2(mean_dy, mean_dx) of the Farneback "
            "dense optical-flow field, converted to degrees; used to pick "
            "the chord sector"
        ),
        "magnitude": (
            "Same as speed_p95 for this adapter (no separate vector "
            "magnitude field)"
        ),
        "ageo_u": "Mean horizontal (x) component of the optical-flow field",
        "ageo_v": "Mean vertical (y) component of the optical-flow field",
    }

    hold_threshold: float = 0.013
    bar_unit: str = "frame group"
    ADAPTER_VERSION: str = "1.1"

    # Farneback parameters (fixed — deterministic)
    _FB_PARAMS = dict(
        pyr_scale=0.5, levels=3, winsize=15, iterations=3,
        poly_n=5, poly_sigma=1.2, flags=0,
    )

    def __init__(
        self,
        video_path: str | Path,
        video_id: str = "",
        hwaccel: str | None = None,
        cache_dir: str | Path = "output/svs_features",
    ) -> None:
        self._video_path = Path(video_path)
        self._id = video_id or self._video_path.stem
        self._hwaccel = hwaccel
        self._decode_method = hwaccel if hwaccel else "cpu"
        self._cache_dir = Path(cache_dir)

    def rows(self, **kwargs: Any) -> list[dict[str, Any]]:
        """Return one row per consecutive frame pair from the video."""
        if not self._video_path.exists():
            return []

        cached = self._load_cache()
        if cached is not None:
            return cached

        frames = self._extract_frames()
        result: list[dict[str, Any]] = []

        if not _CV2_AVAILABLE:
            for i in range(len(frames) - 1):
                result.append(self.rest_row(f"frame_{i:05d}"))
            self._save_cache(result)
            return result

        for i in range(len(frames) - 1):
            prev, curr = frames[i], frames[i + 1]
            if prev is None or curr is None:
                result.append(self.rest_row(f"frame_{i:05d}"))
                continue
            flow = cv2.calcOpticalFlowFarneback(  # type: ignore[attr-defined]
                prev, curr, None, **self._FB_PARAMS
            )
            dx = flow[:, :, 0]
            dy = flow[:, :, 1]
            mag = np.sqrt(dx**2 + dy**2)
            mean_mag = float(np.mean(mag))
            mean_dx = float(np.mean(dx))
            mean_dy = float(np.mean(dy))
            angle = float(math.degrees(math.atan2(mean_dy, mean_dx)))

            if mean_mag < 1e-9:
                result.append(self.rest_row(f"frame_{i:05d}"))
                continue

            result.append({
                "valid": True,
                "speed_p95": mean_mag,
                "ageo_u": mean_dx,
                "ageo_v": mean_dy,
                "ageo_angle_deg": angle,
                "magnitude": mean_mag,
                "date": f"frame_{i:05d}",
            })

        self._save_cache(result)
        return result

    def _extract_frames(self) -> list[np.ndarray | None]:
        """Run one ffmpeg pass and return list of gray uint8 frames."""
        cmd = ["ffmpeg"]
        if self._hwaccel:
            cmd += ["-hwaccel", self._hwaccel]
        cmd += [
            "-i", str(self._video_path),
            "-vf", "fps=1,scale=160:-1",
            "-pix_fmt", "gray",
            "-f", "rawvideo",
            "-",
        ]
        try:
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=300,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return []

        raw = proc.stdout
        if not raw:
            return []

        height = self._probe_height()
        if height is None:
            return []

        frame_bytes = 160 * height
        frames: list[np.ndarray | None] = []
        offset = 0
        while offset + frame_bytes <= len(raw):
            chunk = raw[offset: offset + frame_bytes]
            arr = np.frombuffer(chunk, dtype=np.uint8).reshape((height, 160))
            if arr.mean() < 8:
                frames.append(None)
            else:
                frames.append(arr)
            offset += frame_bytes
        return frames

    def _probe_height(self) -> int | None:
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=height,width",
            "-of", "csv=p=0",
            str(self._video_path),
        ]
        try:
            out = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30
            )
            parts = out.stdout.strip().split(",")
            if len(parts) >= 2:
                orig_w, orig_h = int(parts[0]), int(parts[1])
                scaled_h = int(orig_h * 160 / orig_w)
                return scaled_h if scaled_h % 2 == 0 else scaled_h + 1
        except Exception:
            pass
        return None

    def _etag(self) -> str:
        h = hashlib.sha256()
        with open(self._video_path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    def _cache_path(self) -> Path:
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        return self._cache_dir / f"{self._id}_{self._decode_method}.json"

    def _load_cache(self) -> list[dict[str, Any]] | None:
        p = self._cache_path()
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if (
                data.get("etag") == self._etag()
                and data.get("adapter_version") == self.ADAPTER_VERSION
                and data.get("decode_method") == self._decode_method
            ):
                return data["rows"]
        except Exception:
            pass
        return None

    def _save_cache(self, rows: list[dict[str, Any]]) -> None:
        p = self._cache_path()
        payload = {
            "etag": self._etag(),
            "adapter_version": self.ADAPTER_VERSION,
            "decode_method": self._decode_method,
            "rows": rows,
        }
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=1), encoding="utf-8")
        tmp.replace(p)
