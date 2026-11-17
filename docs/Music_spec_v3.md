# AetherWaves Engine v3 Music Specification

Mapping Version: `v3`  
Standard Pitch: A4 = 440 Hz  
SoundFont: FluidR3_GM.sf2 via FluidSynth  

---

## 1. Overview & Philosophical Foundations

The AetherWaves v3 engine lifts previous musical locks (fixed key, tempo, form proportions, instruments, and drum patterns) while strictly retaining scientific integrity:
- **Never change data values**: Missing data is strictly mapped to rest or hold as declared per layer; zero fire detections represent a valid `0.0`.
- **Honest labels & data rules**: Every sounding note is computed from the data by rules we chose; no random notes, no unstated synthesis, no CC11 expression controllers.
- **Dual-dataset combination for land**: Land regions sonify two distinct datasets:
  1. NASA FIRMS Active Fire Detections (2025 calendar year, 53 weekly bars) governing rhythmic energy, drum tiers, velocity contours, and accents.
  2. GEDI Gridded Canopy Height (April–July 2019 composite, 35 latitudinal steps at 5° increments along the regional meridian column within $\pm51.6^\circ$) governing harmonic chord progressions and pad octave register.
  - Bar to step mapping: $\text{step} = \lfloor \text{bar} \times 35 / 53 \rfloor$ with zero interpolation.
  - Canopy gap rule: HOLD previous chord.
  - *Honest limits declaration*: "two datasets, fire 2025 calendar vs canopy Apr-Jul 2019 latitude line, combined by rule, not a physical link."
- **Siberia Fire-Only Harmony**: Because Siberia lies north of GEDI orbital coverage ($\pm51.6^\circ$), its harmony is derived entirely from the weekly fire-centroid shift $(\Delta\text{lat}, \Delta\text{lon})$ calculated from cached daily VIIRS CSV detections.
- **Ocean**: OSCAR 2025 ocean surface currents (speed_p95, ageostrophic angle, magnitude) mapped across 53 weekly bars.

---

## 2. Dynamic Form from Data

Form is not rigid; section boundaries are derived directly from the data series:
1. **Intro** (`[0 .. intro_end]`): Runs until the first sustained rise in activity ($\ge 3$ bars).
2. **Build** (`[intro_end + 1 .. peak_start - 1]`): Ascending energy leading into the peak ($\ge 3$ bars).
3. **Peak** (`[peak_start .. peak_end]`): Placed symmetrically around the raw series maximum (`peak_idx = argmax(data)`, $\ge 3$ bars).
4. **Decline** (`[peak_end + 1 .. outro_start - 1]`): Descending energy following peak activity ($\ge 3$ bars).
5. **Calm / Outro** (`[outro_start .. 52]`): Sits after the last decline, transitioning to loop resolution ($\ge 3$ bars).

### Opening Type Rule
Evaluated on the first 4 bars ($x_0, x_1, x_2, x_3$):
- **`ascending`**: $x_3 > 1.25 \times x_0$ with monotonically non-decreasing values.
- **`descending`**: $x_3 < 0.80 \times x_0$ with monotonically non-increasing values.
- **`ambient_sparse`**: Mean of first 4 bars $< 0.15 \times \text{raw\_maximum}$.
- **`steady_pulse`**: Default baseline activity.

---

## 3. Tempo, Timing, and Looping

- **Tempo**: Fixed per track between 56 and 96 BPM (India: 70 BPM, Kuroshio: 58 BPM, Siberia: 62 BPM).
- **Bar Duration**: $\text{bar\_seconds} = \frac{240.0}{\text{tempo}}$.
- **Looping**: Tracks are designed for continuous seamless playback (`loop: true`). In the final bar (bar 52), chord progressions and melody resolve to the tonic root and opening drone pitch class.
- **Click Check**: The audio pipeline computes the absolute sample step discontinuity between the final audio sample and first sample: $|s[-1] - s[0]|$.

---

## 4. Sound Design & Layer Architecture

- **Aesthetic**: Soft, ambient, low dynamic intensity. Master loudness normalized to approximately -24 LUFS via FFmpeg `loudnorm` (`I=-24:LRA=7:tp=-2.0`). FluidSynth internal reverb enabled (`-R 1`, room size 0.5, reverb level 0.5).
- **Velocity Limit**: All note velocities across all channels are strictly capped at 80 (`vel \le 80`).
- **Layers & MIDI Channels**:
  - **Channel 0 — Melody**: Regional lead instrument. Pitch classes strictly adhere to the preset scale modulo 12, except when the single declared color tone is triggered.
  - **Channel 1 — Harmony**: Sustained chord pad. Voicings strictly built from scale pitch classes.
  - **Channel 2 — Bass**: Low root notes (octave 2/3), following chord roots.
  - **Channel 3 — Texture Layer**: Quiet GM pad (GM 89 Warm Pad) or Seashore (GM 122 for ocean). Follows harmony and is strictly silent when harmony rests.
  - **Channel 4 — Drone**: Continuous root + fifth drone (e.g. MIDI 36 + 43) providing harmonic anchoring.
  - **Channel 9 — Percussion**: Regional drum mapping with 2-bar hysteresis between drum tiers (`none`, `low`, `med`, `high`).
- **Declared Color Tone**:
  - Exactly ONE pitch class outside the scale per preset (declared in preset and `meta.json`).
  - Condition: Played only when a stated data event occurs (a local spike where raw data exceeds the prior 4 bars), with an enforced cooldown of at least 8 bars (max once per 8 bars).
- **No CC11**: Channel volume CC7 and Pan CC10 are permitted. CC11 expression is strictly prohibited.

---

## 5. Audio Analysis

For each data-driven section, audio statistics are measured directly from the normalized WAV file:
- **RMS dB**: $20 \log_{10}(\text{RMS})$, rounded to 1 decimal place. Classified into `soft` ($< -28.0$ dB), `medium` ($-28.0$ to $-20.0$ dB), or `loud` ($> -20.0$ dB).
- **Spectral Centroid**: $\frac{\sum f \cdot |X(f)|}{\sum |X(f)|}$, rounded to the nearest 100 Hz. Classified into `dark` ($< 800$ Hz), `medium` ($800$–$1600$ Hz), or `bright` ($> 1600$ Hz).
