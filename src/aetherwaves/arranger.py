from __future__ import annotations
from dataclasses import replace
from typing import Literal
from .models import NoteEvent
from .sonification_mapper import midi_to_hz


def quantize_to_scale(midi_note: int, root_midi: int, intervals: list[int]) -> int:
    pitch_classes = {(root_midi + iv) % 12 for iv in intervals}
    best_note = midi_note
    best_dist = 999
    for candidate in range(midi_note - 6, midi_note + 7):
        if (candidate % 12) in pitch_classes:
            dist = abs(candidate - midi_note)
            if dist < best_dist:
                best_dist = dist
                best_note = candidate
    return best_note


def arrange_events(
    events: list[NoteEvent],
    son_cfg: dict,
    mode: Literal["diagnostic", "musical"] = "musical",
) -> list[NoteEvent]:
    if mode == "diagnostic":
        return events

    root = int(son_cfg["scale_root_midi"])
    intervals = [int(x) for x in son_cfg["scale_intervals"]]

    arranged: list[NoteEvent] = []
    for ev in events:
        if ev.is_rest or ev.midi_note is None:
            arranged.append(ev)
            continue
        q_midi = quantize_to_scale(ev.midi_note, root, intervals)
        arranged.append(
            replace(ev, midi_note=q_midi, frequency_hz=midi_to_hz(q_midi))
        )
    return arranged