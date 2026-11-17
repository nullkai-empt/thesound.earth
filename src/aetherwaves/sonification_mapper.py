from __future__ import annotations
from .models import NormalizedControls, NoteEvent


def midi_to_hz(midi_note: float) -> float:
    return 440.0 * (2.0 ** ((midi_note - 69.0) / 12.0))


def _lerp(a: float, b: float, t: float) -> float:
    return a + t * (b - a)


def map_controls_to_events(
    controls_series: list[NormalizedControls],
    son_cfg: dict,
) -> list[NoteEvent]:
    if not controls_series:
        return []

    total_dur = float(son_cfg["phrase_duration_sec"])
    slot_dur = total_dur / len(controls_series)
    events: list[NoteEvent] = []

    rate_min = float(son_cfg["event_rate_per_min"]["min"])
    rate_max = float(son_cfg["event_rate_per_min"]["max"])

    for idx, ctrl in enumerate(controls_series):
        slot_start = idx * slot_dur
        if ctrl.speed_norm is None or ctrl.u_abs_norm is None or ctrl.v_abs_norm is None:
            events.append(
                NoteEvent(
                    start_sec=slot_start,
                    duration_sec=slot_dur,
                    voice="rest",
                    midi_note=None,
                    frequency_hz=None,
                    amplitude=0.0,
                    pan=0.0,
                    sign=0,
                    is_rest=True,
                )
            )
            continue

        events_per_min = _lerp(rate_min, rate_max, ctrl.speed_norm)
        step_sec = 60.0 / events_per_min

        # Voice A (u - Eastward): sustained pad voice; positive = higher octave band
        u_band = son_cfg["voice_u_positive_midi"] if ctrl.u_sign >= 0 else son_cfg["voice_u_negative_midi"]
        u_midi = round(_lerp(u_band["min"], u_band["max"], ctrl.u_abs_norm))
        events.append(
            NoteEvent(
                start_sec=slot_start,
                duration_sec=slot_dur * 0.95,
                voice="voice_u",
                midi_note=u_midi,
                frequency_hz=midi_to_hz(u_midi),
                amplitude=0.35 + 0.20 * ctrl.u_abs_norm,
                pan=-0.25 if ctrl.u_sign < 0 else 0.25,
                sign=ctrl.u_sign,
            )
        )

        # Voice B (v - Northward): plucked pulse whose rate scales monotonically with speed
        v_band = son_cfg["voice_v_positive_midi"] if ctrl.v_sign >= 0 else son_cfg["voice_v_negative_midi"]
        v_midi = round(_lerp(v_band["min"], v_band["max"], ctrl.v_abs_norm))
        t = slot_start
        while t < slot_start + slot_dur - 0.05:
            note_dur = min(step_sec * 0.8, (slot_start + slot_dur) - t)
            events.append(
                NoteEvent(
                    start_sec=t,
                    duration_sec=note_dur,
                    voice="voice_v",
                    midi_note=v_midi,
                    frequency_hz=midi_to_hz(v_midi),
                    amplitude=0.40 + 0.25 * ctrl.speed_norm,
                    pan=0.30 if ctrl.v_sign >= 0 else -0.30,
                    sign=ctrl.v_sign,
                )
            )
            t += step_sec

    return events


def map_visual_features_to_events(
    feature_series: list[dict],
    visual_cfg: dict,
    duration_sec: float,
) -> list[NoteEvent]:
    """Map image-derived features with a separate rule set from scientific OSCAR values."""
    if not feature_series:
        return []
    slot = duration_sec / len(feature_series)
    events: list[NoteEvent] = []
    for idx, feature in enumerate(feature_series):
        brightness = max(0.0, min(1.0, float(feature["brightness"])))
        saturation = max(0.0, min(1.0, float(feature["saturation"])))
        edge_density = max(0.0, min(1.0, float(feature["edge_density"])))
        motion = max(0.0, min(1.0, float(feature["motion"])))
        low, high = visual_cfg["pitch_midi_range"]
        midi = round(low + saturation * (high - low) + motion * visual_cfg["motion_pitch_span"])
        amplitude_bounds = visual_cfg["brightness_to_amplitude"]
        events.append(NoteEvent(
            start_sec=idx * slot,
            duration_sec=slot * 0.92,
            voice="voice_u",
            midi_note=midi,
            frequency_hz=midi_to_hz(midi),
            amplitude=amplitude_bounds[0] + (amplitude_bounds[1] - amplitude_bounds[0]) * brightness,
            pan=0.0,
            sign=1,
        ))
        event_rate = visual_cfg["edge_density_event_rate"]
        step = 60 / max(1, event_rate[0] + edge_density * (event_rate[1] - event_rate[0]))
        pulse = idx * slot
        motion_bounds = visual_cfg["motion_to_pulse_amplitude"]
        while pulse < (idx + 1) * slot - 0.04:
            events.append(NoteEvent(
                start_sec=pulse,
                duration_sec=min(step * 0.65, (idx + 1) * slot - pulse),
                voice="voice_v",
                midi_note=midi,
                frequency_hz=midi_to_hz(midi),
                amplitude=motion_bounds[0] + (motion_bounds[1] - motion_bounds[0]) * motion,
                pan=0.0,
                sign=1,
            ))
            pulse += step
    return events