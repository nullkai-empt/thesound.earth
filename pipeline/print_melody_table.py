from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure repo root and src/ are on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from aetherwaves.blocks import group_days_into_blocks
from aetherwaves.harmony import compute_section_counts, generate_harmony, get_section_for_bar
from aetherwaves.melody import generate_melody
from aetherwaves.rhythm import normalize_series_5_95


def main() -> None:
    json_path = REPO_ROOT / "data" / "raw_oscar" / "oscar_2025_daily.json"
    if not json_path.exists():
        raise FileNotFoundError(f"OSCAR data not found: {json_path}")

    daily_records = json.loads(json_path.read_text(encoding="utf-8"))
    blocks = group_days_into_blocks(daily_records, block_size=7)
    norm_speeds, _ = normalize_series_5_95(blocks)
    harmony_bars = generate_harmony(blocks, norm_speeds, hold_threshold=0.013)
    events = generate_melody(blocks, harmony_bars, norm_speeds, seed=42)

    sec_counts = compute_section_counts(len(blocks))

    # Map melody notes per bar
    notes_by_bar: dict[int, list[int]] = {}
    for ev in events:
        notes_by_bar.setdefault(ev.bar, []).append(ev.midi_note)

    # Print markdown table
    print("| Bar | Section | Norm Speed | Delta vs Prev | Chord | Melody Note(s) |")
    print("|---|---|---|---|---|---|")

    active_bars_data: list[tuple[float, list[int]]] = []

    for i in range(len(blocks)):
        sec = get_section_for_bar(i, sec_counts)
        s = norm_speeds[i]
        spd_str = f"{s:.3f}" if s is not None else "None"

        if i == 0 or norm_speeds[i - 1] is None or s is None:
            delta_str = "N/A"
        else:
            delta_str = f"{s - norm_speeds[i - 1]:+.3f}"

        chord = harmony_bars[i].chord
        notes = notes_by_bar.get(i)
        notes_str = str(notes) if notes else "REST"

        print(f"| {i:2d} | {sec:5s} | {spd_str} | {delta_str} | {chord:2s} | {notes_str} |")

        if notes and s is not None:
            active_bars_data.append((s, notes))

    # Check if two different bars with different norm speed give different melody notes
    different_notes_found = any(
        c1[0] != c2[0] and c1[1] != c2[1]
        for c1 in active_bars_data
        for c2 in active_bars_data
    )
    answer = "yes" if different_notes_found else "no"
    print(f"\ndo two different bars with different norm speed give different melody notes? {answer}")


if __name__ == "__main__":
    main()
