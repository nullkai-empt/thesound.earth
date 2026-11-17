# Music Specification v2: Regional Preset Sonification Engine

> **Version:** 2.0  
> **Status:** Active Engine v2 Specification  
> **SoundFont:** FluidR3_GM.sf2 only (FluidSynth)  
> **Mapping Version:** `"v2"`

---

## 1. Principles & Constraints

1. **Deterministic Data Mapping:**  
   Every note is computed from the data by rules we chose. The physical-to-musical mapping pipeline remains consistent with v1 (7-day blocks, 53 bars total for 365 daily rows, P5-P95 normalization from the track's own dataset, hold threshold of 0.013).
2. **Missing Data Contract:**  
   Missing data equals REST (silence / `None` in JSON), never zero. Zero FIRMS fire detections produce `valid: True, speed_p95: 0.0` (active observation of no fires).
3. **Regional Presets (`config/presets_v2.json`):**  
   Each region uses an inspired regional preset with:
   - Specific General MIDI instruments from `FluidR3_GM` (0-indexed GM program numbers).
   - Modal scale semitone pitch class list: every sounding note (melody, pad, and bass) strictly belongs to the preset scale.
   - Regional drum kit mapping on GM Channel 10.
   - Stereo pan position (MIDI CC10).
   - Tempo: 72 BPM.
   - Every preset is explicitly labeled `"inspired by, not authentic"`.
4. **No CC11:**  
   Dynamic expression is achieved through note velocity scaling and instrument arrangements. No CC11 expression events are used in any generated MIDI.
5. **FluidSynth Synthesis:**  
   Rendered with small-room reverb (`-R 1 -o synth.reverb.room-size=0.5 -o synth.reverb.level=0.5`), chorus disabled (`-C 0`), peak-normalized to -1.0 dBFS, and encoded to Opus 48k mono using bitexact flags (`-c:a libopus -b:a 48k -ac 1 -map_metadata -1 -fflags +bitexact -flags:a +bitexact`).

---

## 2. Track Catalog & Regional Scales

| Region ID | Domain | Scale Name | Scale Semitones (mod 12) | Melody GM | Pad GM | Bass GM | Percussion Style |
|---|---|---|---|---|---|---|---|
| `gulf_stream` | Ocean | Natural Minor | `[0, 2, 3, 5, 7, 8, 10]` | 49 (Strings) | 94 (Halo) | 42 (Cello) | Standard Maracas/Kick |
| `kuroshio` | Ocean | Insen Pentatonic | `[0, 1, 5, 7, 10]` | 107 (Koto) | 89 (Warm Pad) | 43 (Contrabass) | Taiko & Temple Drums |
| `east_australian` | Ocean | Dorian | `[0, 2, 3, 5, 7, 9, 10]` | 73 (Flute) | 94 (Halo) | 42 (Cello) | Ocean Shaker |
| `brazil_malvinas` | Ocean | Harmonic Minor | `[0, 2, 3, 5, 7, 8, 11]` | 40 (Violin) | 89 (Warm Pad) | 42 (Cello) | Tango Inflected |
| `arabian_sea` | Ocean | Hijaz / Phrygian Dom | `[0, 1, 4, 5, 7, 8, 10]` | 15 (Dulcimer) | 91 (Choir Pad) | 43 (Contrabass) | Frame Drum & Riqq |
| `drake_acc` | Ocean | Natural Minor | `[0, 2, 3, 5, 7, 8, 10]` | 60 (Horn) | 95 (Sweep Pad) | 43 (Contrabass) | Deep Surge |
| `nordic_seas` | Ocean | Dorian | `[0, 2, 3, 5, 7, 9, 10]` | 110 (Fiddle) | 92 (Bowed Pad) | 42 (Cello) | Polar Pulse |
| `amazon` | Fires | Minor Pentatonic | `[0, 3, 5, 7, 10]` | 75 (Pan Flute) | 89 (Warm Pad) | 42 (Cello) | Woodland Shaker/Surdo |
| `congo` | Fires | Major Pentatonic | `[0, 2, 4, 7, 9]` | 108 (Kalimba) | 94 (Halo) | 35 (Fretless) | Polyrhythmic Conga |
| `se_asia` | Fires | Pelog Approximation | `[0, 1, 3, 7, 8]` | 11 (Vibraphone) | 89 (Warm Pad) | 43 (Contrabass) | Metallophone Gong |
| `australia` | Fires | Natural Minor | `[0, 2, 3, 5, 7, 8, 10]` | 25 (Steel Guitar) | 94 (Halo) | 43 (Contrabass) | Earthy Wood Shaker |
| `w_north_america` | Fires | Mixolydian | `[0, 2, 4, 5, 7, 9, 10]` | 24 (Nylon Guitar) | 94 (Halo) | 32 (Acoustic Bass) | Brushed Acoustic |
| `siberia` | Fires | Suspended Pentatonic | `[0, 2, 5, 7, 10]` | 71 (Clarinet) | 95 (Sweep Pad) | 43 (Contrabass) | Frame Drum |
| `india` | Fires | Kafi Thaat / Dorian | `[0, 2, 3, 5, 7, 9, 10]` | 104 (Sitar) | 91 (Choir Pad) | 42 (Cello) | Tabla-Inspired |
| `europe` | Fires | Phrygian Dominant | `[0, 1, 4, 5, 7, 8, 10]` | 24 (Nylon Guitar) | 89 (Warm Pad) | 42 (Cello) | Tambourine & Cajon |
