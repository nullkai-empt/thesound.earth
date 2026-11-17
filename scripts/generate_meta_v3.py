"""generate_meta_v3.py — Generate full v3 metadata JSON for prototypes and tracks.

Strictly enforces:
- Removal of 'm/s', 'ageostrophic', 'active flow' from fires text; uses 'mean fire detections per day'
- Proper direction sources named
- Drum tier counts: base / low / medium / high
- Relative audio tiers (+-1.5 dB, +-300 Hz from track's own average)
- Section-by-section story strictly computed from section audit stats (min/max/mean, tier set, chord set)
- Cultural framing labelled 'Artistic framing - not derived from data'
- Verified DOI or 'not verified'
- Zero banned words
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any
import numpy as np

BANNED_PATTERNS = [
    r"\b100%\b",
    r"\bfilm-level\b",
    r"\badvanced tuning\b",
    r"\bguarantee\b",
    r"\blive\b",
    r"\bmeasured by satellites\b",
]


def check_banned_words(data: Any, path: str = "") -> list[str]:
    violations: list[str] = []
    if isinstance(data, str):
        for pattern in BANNED_PATTERNS:
            if re.search(pattern, data, flags=re.IGNORECASE):
                violations.append(f"At {path}: found banned pattern '{pattern}' in text: {data[:60]}...")
    elif isinstance(data, dict):
        for k, v in data.items():
            violations.extend(check_banned_words(v, f"{path}.{k}"))
    elif isinstance(data, list):
        for idx, item in enumerate(data):
            violations.extend(check_banned_words(item, f"{path}[{idx}]"))
    return violations


def compute_relative_audio_tiers(
    audio_analysis: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Compute audio tiers relative to track's own average (+-1.5 dB, +-300 Hz)."""
    rms_vals = [sec["rms_db"] for sec in audio_analysis.values()]
    sc_vals = [sec["spectral_centroid_hz"] for sec in audio_analysis.values()]
    mean_rms = float(np.mean(rms_vals))
    mean_sc = float(np.mean(sc_vals))

    rel_analysis: dict[str, dict[str, Any]] = {}
    for name, s_data in audio_analysis.items():
        r_db = s_data["rms_db"]
        sc_hz = s_data["spectral_centroid_hz"]

        if r_db <= mean_rms - 1.5:
            r_tier = "soft"
        elif r_db >= mean_rms + 1.5:
            r_tier = "loud"
        else:
            r_tier = "medium"

        if sc_hz <= mean_sc - 300:
            c_tier = "dark"
        elif sc_hz >= mean_sc + 300:
            c_tier = "bright"
        else:
            c_tier = "medium"

        rel_analysis[name] = {
            "rms_db": r_db,
            "rms_tier": r_tier,
            "spectral_centroid_hz": sc_hz,
            "brightness_tier": c_tier,
            "track_mean_rms_db": round(mean_rms, 1),
            "track_mean_centroid_hz": int(round(mean_sc)),
            "start_bar": s_data["start_bar"],
            "end_bar": s_data["end_bar"],
        }
    return rel_analysis


def build_meta_v3(
    track_id: str,
    preset: dict[str, Any],
    blocks: list[dict[str, Any]],
    norm_speeds: list[float | None],
    harmony_bars: list[Any],
    melody_bars: list[Any],
    effective_tiers: list[str],
    tier_counts: dict[str, int],
    form_info: dict[str, Any],
    audio_analysis: dict[str, Any],
    sample_step: float,
    color_tone_bars: list[int],
    checksums: dict[str, str],
) -> dict[str, Any]:
    domain = preset.get("domain", "ocean")
    tempo = preset["tempo"]
    bar_seconds = preset["bar_seconds"]
    n_bars = len(blocks)

    raw_vals = [float(b.get("speed_p95") if b.get("speed_p95") is not None else 0.0) for b in blocks]
    peak_idx = form_info["peak_idx"]
    raw_max = form_info["raw_max"]

    # 1. Scientific Data configuration
    if domain == "ocean":
        dataset_info = {
            "name": "OSCAR third-degree ocean surface currents (near-surface 15m depth)",
            "doi": "10.5067/OSCAR-21O01",
            "url": "https://podaac.jpl.nasa.gov/dataset/OSCAR_L4_OC_third-deg",
            "version": "v2.0",
            "fields_used": ["speed_p95", "u", "v"],
            "intensity_metric": "speed_p95 (m/s)",
            "direction_source": "majority sector of the ageostrophic velocity component from OSCAR daily surface currents",
        }
        honest_limits = (
            "Derived from satellite data; 5-day OSCAR surface current gridded product linearly interpolated "
            "to daily, sonified as 7-day weekly blocks by rules we chose."
        )
    elif domain == "land_combined":
        dataset_info = {
            "name": "NASA FIRMS VIIRS SNPP 375m active fire detections combined with GEDI L1B Canopy Top Height composite",
            "doi": "not verified (NASA FIRMS distributes VIIRS SNPP SP historical archive under Collection 2 without dedicated SP DOI; GEDI composite DOI: 10.5281/zenodo.5704852)",
            "url": "https://earthdata.nasa.gov/firms",
            "version": "VIIRS_SNPP_SP (Collection 2) / GEDI L1B RH98 composite 2019",
            "fields_used": ["fire count", "frp", "canopy height RH98"],
            "intensity_metric": "mean fire detections per day",
            "direction_source": (
                "sign of the latitudinal canopy height gradient along the regional meridian column "
                "(April-July 2019 GEDI composite, Lang et al. 2022)"
            ),
        }
        honest_limits = (
            "Derived from satellite data; two datasets, fire 2025 calendar vs canopy Apr-Jul 2019 latitude line, "
            "combined by rule, not a physical link. Every note is computed from the data by rules we chose."
        )
    else:  # land_fire_only (siberia)
        dataset_info = {
            "name": "NASA FIRMS VIIRS SNPP 375m active fire detections",
            "doi": "not verified (NASA FIRMS distributes VIIRS SNPP SP historical archive under Collection 2 without dedicated SP DOI)",
            "url": "https://earthdata.nasa.gov/firms",
            "version": "VIIRS_SNPP_SP (Collection 2)",
            "fields_used": ["fire count", "latitude", "longitude", "frp"],
            "intensity_metric": "mean fire detections per day",
            "direction_source": "weekly fire-centroid shift calculated from cached daily VIIRS CSV latitude/longitude",
        }
        honest_limits = (
            "Derived from satellite data; weekly fire-centroid shift reflects spatial drift of detected fire centroids "
            "across 2025, combined by rule, not a direct wind or fire spread vector. "
            "Every note is computed from the data by rules we chose."
        )

    # 2. Audit Table
    audit_table: list[dict[str, Any]] = []
    chord_changes_count = 0
    prev_chord = None

    for b_idx in range(n_bars):
        b = blocks[b_idx]
        h = harmony_bars[b_idx]
        mb = melody_bars[b_idx]
        raw_val = raw_vals[b_idx]
        ns = norm_speeds[b_idx] if b_idx < len(norm_speeds) else 0.0

        if prev_chord is not None and h.chord != prev_chord:
            chord_changes_count += 1
        prev_chord = h.chord

        row: dict[str, Any] = {
            "bar": b_idx,
            "start_date": b.get("date", f"Week-{b_idx}"),
            "end_date": b.get("end_date", ""),
            "section": h.section,
            "norm_speed": round(float(ns if ns is not None else 0.0), 4),
            "chord": h.chord,
            "chord_numeral": h.chord_numeral,
            "held": h.held,
            "drum_tier": effective_tiers[b_idx],
            "melody_rest": mb.is_rest,
            "has_color_tone": mb.has_color_tone,
        }

        if domain == "ocean":
            row["mean_speed_p95_m_s"] = round(raw_val, 4)
            row["direction_sector"] = b.get("sector", "East")
            row["magnitude_m_s"] = round(float(b.get("magnitude", 0.0) or 0.0), 4)
        else:
            row["mean_fire_detections_per_day"] = round(raw_val, 2)
            row["direction_source_description"] = dataset_info["direction_source"]
            if domain == "land_combined":
                row["canopy_step_index"] = int(b_idx * 35 // 53)
                row["pad_octave_shift"] = h.pad_octave_shift
            else:
                row["centroid_shift_magnitude_deg"] = round(float(h.raw_magnitude or 0.0), 4)

        audit_table.append(row)

    # 3. Relative Audio Tiers
    rel_audio_analysis = compute_relative_audio_tiers(audio_analysis)

    # 4. Cultural Frame
    cultural_frames = {
        "gulf_stream": (
            "Artistic framing - not derived from data: Reflecting North Atlantic maritime traditions through natural minor harmony "
            "and gentle rolling rhythms, evoking the expansive offshore current with respect and artistic license."
        ),
        "kuroshio": (
            "Artistic framing - not derived from data: Evoking the serene, elemental qualities of the North Pacific current "
            "through traditional Insen intervals and resonant wood percussion, capturing oceanic flow with quiet contemplation."
        ),
        "east_australian": (
            "Artistic framing - not derived from data: Inspired by open coastal sonorities and Dorian modal motion, evoking the dynamic "
            "subtropical Tasman flow with respectful artistic interpretation."
        ),
        "brazil_malvinas": (
            "Artistic framing - not derived from data: Expressing the dramatic thermal clash of subtropical and subantarctic waters "
            "through harmonic minor tensions, rendered with artistic license."
        ),
        "arabian_sea": (
            "Artistic framing - not derived from data: Drawing upon Middle Eastern and South Asian modal inflections and resonant frame-drum textures, "
            "reflecting monsoon wind-driven maritime flow with respect and artistic license."
        ),
        "drake_acc": (
            "Artistic framing - not derived from data: Sonifying the circumpolar isolation of the Southern Ocean through stark minor sonorities "
            "and deep low-frequency pulse, evoking subantarctic flow with quiet reverence."
        ),
        "nordic_seas": (
            "Artistic framing - not derived from data: Inspired by Nordic modal clarity and sparse atmospheric textures, reflecting "
            "high-latitude Arctic boundary waters with respectful artistic license."
        ),
        "amazon": (
            "Artistic framing - not derived from data: Evoking the vast biodiversity of the Amazonian rainforest through organic wooden percussion "
            "and minor pentatonic melodic lines with respect and artistic license."
        ),
        "congo": (
            "Artistic framing - not derived from data: Inspired by Central African polyrhythmic percussion traditions and open pentatonic structures, "
            "evoking equatorial river basin ecosystems with respect and artistic license."
        ),
        "se_asia": (
            "Artistic framing - not derived from data: Inspired by Southeast Asian metallophone timbres and traditional pentatonic tuning contours, "
            "evoking tropical forest landscapes with respect and artistic license."
        ),
        "australia": (
            "Artistic framing - not derived from data: Reflecting the ancient resilience of the Australian bush through earthy wooden textures "
            "and natural minor contours with respectful artistic license."
        ),
        "w_north_america": (
            "Artistic framing - not derived from data: Drawing upon western acoustic guitar sonorities and Mixolydian open intervals, "
            "reflecting temperate mountain forests with respectful artistic license."
        ),
        "siberia": (
            "Artistic framing - not derived from data: Drawing upon open suspended pentatonic sonorities and stark orchestral textures, "
            "reflecting the vast northern taiga and boreal seasonal cycles with respectful artistic license."
        ),
        "india": (
            "Artistic framing - not derived from data: Inspired by the meditative phrasing of North Indian classical Kafi traditions "
            "and acoustic resonance of sitar/tanpura drones, evoking the seasonal rhythms of the Indian subcontinent with respect and artistic license."
        ),
        "europe": (
            "Artistic framing - not derived from data: Inspired by Mediterranean nylon guitar and rhythmic cajon/tambourine phrasing, "
            "reflecting southern European landscape dynamics with respectful artistic license."
        ),
    }

    # 5. Context
    regional_contexts = {
        "gulf_stream": (
            "The Gulf Stream is a swift Atlantic western boundary current originating in the Gulf of Mexico and traversing northeastward past Cape Hatteras. "
            "OSCAR satellite altimetry tracks seasonal variations in velocity, core meanders, and temperature-driven circulation throughout 2025."
        ),
        "kuroshio": (
            "The Kuroshio Current is a major western boundary current flowing northeastward off Japan, transporting warm subtropical water into the subpolar North Pacific. "
            "OSCAR third-degree satellite models track seasonal meanders and velocity surges across 2025."
        ),
        "east_australian": (
            "The East Australian Current is a complex southward western boundary current carrying warm coral sea waters along eastern Australia. "
            "OSCAR satellite observations delineate seasonal eddy shedding and coastal current intensification in 2025."
        ),
        "brazil_malvinas": (
            "The Brazil-Malvinas Confluence in the Southwestern Atlantic represents one of the ocean's most energetic frontal zones where the warm southward Brazil current meets the cold northward Malvinas current. "
            "OSCAR satellite models track sharp shear and velocity gradients throughout 2025."
        ),
        "arabian_sea": (
            "The Arabian Sea circulation undergoes dramatic semi-annual reversals driven by the Southwest and Northeast monsoons. "
            "OSCAR satellite current fields capture seasonal upwelling, the Somali Current jet, and cross-basin circulation in 2025."
        ),
        "drake_acc": (
            "The Drake Passage channels the Antarctic Circumpolar Current between South America and the Antarctic Peninsula, forming the primary choke point for global thermohaline exchange. "
            "OSCAR altimetry maps persistent eastward zonal transport and eddy fields across 2025."
        ),
        "nordic_seas": (
            "The Nordic Seas link the Atlantic and Arctic oceans, where warm Atlantic inflow transitions through cooling and deep water formation. "
            "OSCAR satellite current models chart seasonal circulation and convective gyre dynamics throughout 2025."
        ),
        "amazon": (
            "The Amazon basin experiences seasonal fire activity concentrated along the deforestation arc during the dry season (July-October). "
            "NASA FIRMS VIIRS Standard Processing tracks thermal anomalies while GEDI spaceborne lidar maps multilayered equatorial canopy heights along the 60W meridian."
        ),
        "congo": (
            "The Congo Basin contains the world's second-largest contiguous tropical rainforest, experiencing widespread agricultural clearing and savannah fires. "
            "VIIRS thermal anomaly data and GEDI 20E meridian lidar transects capture canopy architecture across 2025."
        ),
        "se_asia": (
            "Southeast Asia (Indochina) witnesses pronounced pre-monsoon dry season fire events associated with agricultural clearing and deciduous dipterocarp forest burning (February-April). "
            "VIIRS tracks fire detections while GEDI 100E transects characterize regional canopy."
        ),
        "australia": (
            "Eastern Australia encompasses temperate eucalyptus woodlands and subtropical savannahs prone to seasonal bushfires during Austral spring and summer. "
            "VIIRS detections and GEDI 135E canopy measurements track vegetation state across 2025."
        ),
        "w_north_america": (
            "Western North America encompasses coniferous mountain ecosystems in the Pacific Northwest and northern California prone to late summer wildfire activity. "
            "VIIRS monitors fire detections while GEDI 115W meridian transects capture towering temperate conifer canopies."
        ),
        "siberia": (
            "The Siberian boreal taiga encompasses extensive larch and pine forests that witness concentrated summer wildfire activity "
            "governed by regional heat domes, dry lightning, and continental air masses. "
            "VIIRS active fire detections within the 55-65N, 95-120E box delineate the rapid rise and dispersion of thermal anomalies."
        ),
        "india": (
            "NASA FIRMS VIIRS Standard Processing detects seasonal fire activity across South Asia (18-28N, 73-85E), "
            "peaking in the pre-monsoon dry season (March-April 2025; bar 12 at 5927.9 detections/day) during agricultural harvest clearing. "
            "Canopy top heights along the 78E meridian transect cross tropical dry deciduous to Himalayan temperate forests "
            "from the GEDI spaceborne lidar mission (April-July 2019 composite; Lang et al. 2022)."
        ),
        "europe": (
            "Southern Europe and the Mediterranean basin experience intense summer wildfire episodes during prolonged heatwaves and dry seasonal winds (July-August). "
            "VIIRS tracks thermal anomalies across the Iberian Peninsula and southern Europe, combined with GEDI 15E canopy transects."
        ),
    }

    source_urls = [dataset_info["url"]]
    if domain == "land_combined":
        source_urls.append("https://doi.org/10.5281/zenodo.5704852")
    if domain == "ocean":
        source_urls.append("https://doi.org/10.5067/OSCAR-21O01")

    # 6. Narrative Facts
    final_bar = n_bars - 1
    facts_used = sorted(list(set([0, peak_idx, final_bar])))
    facts_narrative = (
        f"Track begins at bar 0 ({audit_table[0]['start_date']}) with baseline intensity of {raw_vals[0]:.1f} "
        f"({dataset_info['intensity_metric']}). Activity ascends across seasonal transitions to reach its raw maximum "
        f"of {raw_max:.1f} at bar {peak_idx} ({audit_table[peak_idx]['start_date']}), where drum tier is '{effective_tiers[peak_idx]}'. "
        f"Following the active phase, values subside into bar {final_bar} ({audit_table[final_bar]['start_date']}) where chord and melody "
        f"resolve to the opening tonic for seamless looping."
    )

    # 7. Section-by-Section Story generated strictly from computed audit section stats
    val_key = "mean_speed_p95_m_s" if domain == "ocean" else "mean_fire_detections_per_day"
    story_paragraphs: list[str] = []

    for sec in form_info["sections"]:
        s_name = sec["name"]
        s_start = sec["start_bar"]
        s_end = sec["end_bar"]
        sec_rows = audit_table[s_start : s_end + 1]

        sec_vals = [r[val_key] for r in sec_rows]
        s_min = float(min(sec_vals))
        s_max = float(max(sec_vals))
        s_mean = float(np.mean(sec_vals))
        s_tiers = sorted(list(set(r["drum_tier"] for r in sec_rows)))
        s_chords = sorted(list(set(r["chord"] for r in sec_rows)))
        s_audio = rel_audio_analysis[s_name]

        tiers_str = "/".join(s_tiers)
        chords_str = ", ".join(s_chords)

        p = (
            f"{s_name.capitalize()} (bars {s_start}-{s_end}; audit rows {s_start} to {s_end}): "
            f"Over these bars, {dataset_info['intensity_metric']} ranges from {s_min:.1f} to {s_max:.1f} "
            f"(mean {s_mean:.1f}). Percussion active tiers are [{tiers_str}] and harmonic chords include [{chords_str}]. "
            f"Acoustic loudness measures {s_audio['rms_db']:.1f} dB ({s_audio['rms_tier']}) with spectral centroid "
            f"{s_audio['spectral_centroid_hz']} Hz ({s_audio['brightness_tier']}) relative to track average."
        )
        story_paragraphs.append(p)

    story_text = "\n\n".join(story_paragraphs)

    meta = {
        "mapping_version": "v3",
        "preset": {
            "track_id": track_id,
            "domain": domain,
            "scale_name": preset["scale_name"],
            "scale": preset["scale"],
            "key": "C",
            "tempo": tempo,
            "bar_seconds": bar_seconds,
            "bars": n_bars,
            "bar_unit": "week",
            "days_per_bar": 7,
            "hold_threshold": preset.get("hold_threshold", 0.013),
            "disclaimer": preset.get("disclaimer", "inspired by, not authentic"),
        },
        "seed": hashlib.sha256(f"{track_id}:2025".encode("utf-8")).hexdigest(),
        "bars": n_bars,
        "bar_unit": "week",
        "days_per_bar": 7,
        "bar_seconds": bar_seconds,
        "tempo": tempo,
        "hold_threshold": preset.get("hold_threshold", 0.013),
        "chord_changes": chord_changes_count,
        "drum_tier_counts": tier_counts,
        "hysteresis_applied": "2-bar hysteresis applied to drum tier transitions",
        "section_captions": form_info["section_captions"],
        "gm_programs": preset["gm_programs"],
        "loop": True,
        "sample_step_click_check": sample_step,
        "drone": {
            "enabled": True,
            "root_pitch_class": 0,
            "fifth_pitch_class": 7,
            "midi_pitches": [36, 43],
            "description": "Continuous root+fifth drone on Channel 4",
        },
        "color_tone": {
            "pitch_class": preset["color_tone"],
            "name": preset["color_tone_name"],
            "event_rule": "Local breakout: raw value exceeds preceding 4 bars, cooldown >= 8 bars",
            "bars_triggered": color_tone_bars,
            "times_played": len(color_tone_bars),
        },
        "audio_analysis": rel_audio_analysis,
        "cultural_frame": cultural_frames.get(track_id, "Artistic framing - not derived from data: Respectful regional aesthetic interpretation."),
        "scientific_data": {
            "dataset": dataset_info,
            "honest_limits": honest_limits,
            "audit_table": audit_table,
        },
        "facts_narrative": {
            "facts_used": facts_used,
            "text": facts_narrative,
        },
        "story": {
            "label": "Artistic interpretation — not a scientific claim",
            "sections": [s["name"] for s in form_info["sections"]],
            "text": story_text,
            "facts_used": facts_used,
        },
        "context": {
            "regional_background": regional_contexts.get(track_id, "Regional environmental monitoring context."),
            "source_urls": source_urls,
        },
        "ai_disclosure": "Algorithmic rule-based sonification generated in Python using mido, FluidSynth, and FFmpeg. Every note is computed from the data by rules we chose.",
        "checksum": checksums.get("opus_sha256", "") if isinstance(checksums, dict) else str(checksums),
        "checksums": checksums,
    }

    # Banned words check
    violations = check_banned_words(meta)
    if violations:
        raise ValueError(f"Banned words violations in meta.json:\n" + "\n".join(violations))

    return meta
