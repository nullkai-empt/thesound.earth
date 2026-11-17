# EARTHSONIC MUSIC_SPEC v1 (Cinematic)

## Goal
Turn NASA OSCAR ocean-current data into a real, listenable Cinematic track.
Data decides the musical CHOICES. Music theory makes the NOTES.
Output is a musical encoding of data, NOT a recording of the ocean.

## Hard rules
1. Never change the scientific values (u, v, speed, time, units).
2. Missing or land data = rest (silence). Never zero, never invented.
3. Same data + same seed + same mapping version = same song.
4. Do not map every variable to pitch.
5. Tempo is FIXED. Data never changes tempo.
6. No random notes. Every note comes from the scale or the chord.
7. Style is an artistic choice, not a scientific category.
8. Audio renders via FluidSynth + a licensed SoundFont. No home-made synthesis.

## Locked settings (never change with data)
- Time Mapping: 1 data sample = 1 bar (72 BPM, 4/4, 3.333 s per bar).
- Key: D minor (Dorian in calm sections).
- Tempo: 72 BPM, 4/4.
- Instruments: string pad, piano (melody), cello (bass), soft kick, soft snare, shaker.
- Bass rule: Bass always plays the chord root. Trend only picks the approach note.
- Form: 5 sections split the samples by proportion:
  - Intro: 10%
  - Build: 20%
  - Peak: 35%
  - Calm: 20%
  - Outro: 15%
- Presets later (other styles) swap only instruments, scale and drum patterns. The data mapping stays the same.

### Chords
1. Direction comes from the ageostrophic component (u-ug, v-vg), label it "ageostrophic component".
2. Sector mapping: East = i (Dm), North = VI (Bb), West = iv (Gm) only, South = VII (C). III (F) is only a lift in Peak. Calm section uses Dm, C, G major only (no Bb, no Gm).
3. If ageo magnitude `hypot(ageo_u, ageo_v) < 0.013 m/s`, hold the previous chord.
4. Hysteresis: A new chord switches only after 2 consecutive bars choose it, on a bar line.
5. West = iv (Gm) only. III (F) is only a lift in Peak.

## Data to music mapping
| Data feature | Controls |
|---|---|
| speed_p95 (5th-95th percentile normalized) | drum density and loudness |
| ageostrophic component direction = atan2(ageo_v, ageo_u), 4 sectors | which chord of the set (East=i, North=VI, West=iv, South=VII) |
| ageo magnitude hypot(ageo_u, ageo_v) < 0.013 m/s | hold previous chord |
| monthly mean trend | bass approach note (bass always plays chord root) |
| day-to-day change (up/down/flat) | melody contour |
| top 5 percent speed events | riser, crash, extra layer |
| missing or land (speed_p95 is None/NaN) | rest (full-bar rest) |

Normalize with the 5th to 95th percentile of the selected sample, clamp
to 0-1, keep the original value for the audit.

## The 5 systems (build in this order)
1. RHYTHM: groove patterns (kick 1 and 3, snare 2 and 4, shaker 8ths or
   16ths). Speed picks the pattern level: low = kick only (1 and 3),
   medium = plus snare (2 and 4) plus 8th shaker, high = plus 16th shaker
   and a fill on the last beat of every 4th bar. Tier changes only on a
   bar line, and only after 2 bars at the new level. Fills are deterministic
   from the seed. Missing data = a full-bar rest.
2. HARMONY + BASS: Direction comes from the ageostrophic component (u-ug, v-vg),
   labeled "ageostrophic component". Direction sector picks the chord:
   East = i (Dm), North = VI (Bb), West = iv (Gm) only, South = VII (C).
   III (F) is only a lift in Peak. Calm section uses Dm, C, G major only (no Bb, no Gm).
   If ageo magnitude hypot(ageo_u, ageo_v) < 0.013 m/s, hold the previous chord.
   A new chord switches only after 2 consecutive bars choose it, on a bar line.
   Smooth voice leading. Bass always plays the chord root on the kick; trend
   only picks the approach note.
3. MELODY: one 4-8 note motif per song. Data picks the development:
   repeat, transpose, invert, stretch. Rest at phrase ends. Stay in the
   scale.
4. DYNAMICS: speed percentile sets velocity and layer count. Big events
   get a riser or crash.
5. ARRANGEMENT: 5 sections split the samples by proportion (intro 10%,
   build 20%, peak 35%, calm 20%, outro 15%). Layers enter and leave at
   section borders.

## Pipeline
Data -> features -> musical plan -> MIDI -> render with FluidSynth + a
licensed SoundFont -> light mix (EQ, compression, reverb) -> mp3 or ogg.
Render offline. Never ship the raw .nc.

## Output per song
- .mp3 or .ogg (website)
- .mid (editable)
- .json audit: dataset and version, region, dates, u, v, speed, mapping
  version, seed, style, limitations
- Label AI-generated audio in the description and metadata if AI was used.

## Tests (must pass)
- speed and direction match hand-calculated examples
- higher speed never gives lower drum density (monotonic density)
- missing data gives a rest (never zero)
- same input and seed gives identical MIDI
- sections exist and chord changes land on bar lines
- every note is in the scale or chord
- tier changes only on bar lines, and only after 2 bars at new level
- chord switches only on bar lines, and only after 2 consecutive bars choose it
- hold previous chord when ageo magnitude < 0.013 m/s

## Honest limits (say on the site)
- OSCAR is a model-derived analysis, not a direct measurement.
- No per-cell uncertainty is provided.
- The globe layer is reduced to 2 degrees and monthly values. The raw
  data stays at PO.DAAC.
- Listening test results are subjective and are not scientific proof.
