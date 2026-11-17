import hashlib
import json
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

BANNED_WORDS = [
    "100%",
    "film-level",
    "advanced tuning",
    "guarantee",
    "live",
    "measured by satellites",
]

FINAL_DIR = REPO_ROOT / "final"
INDEX_PATH = FINAL_DIR / "index.json"


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_determinism_meta_json(tmp_path: Path):
    """Determinism: Running export/meta generation twice for same id+year produces byte-identical meta.json."""
    sample_meta_path = FINAL_DIR / "2025" / "gulf_stream" / "meta.json"
    assert sample_meta_path.exists(), "gulf_stream meta.json must exist"

    # Read original
    orig_bytes = sample_meta_path.read_bytes()
    orig_data = json.loads(orig_bytes.decode("utf-8"))

    # Re-run meta generation using v3 pipeline logic for gulf_stream
    from aetherwaves.adapters.oscar import OscarAdapter
    from aetherwaves.blocks import group_days_into_blocks
    from aetherwaves.rhythm import normalize_series_5_95
    from aetherwaves.engine_v3.form_v3 import compute_form_sections
    from aetherwaves.engine_v3.harmony_v3 import generate_harmony_v3
    from aetherwaves.engine_v3.melody_v3 import generate_melody_v3
    from aetherwaves.engine_v3.rhythm_v3 import generate_drum_events_v3
    from scripts.generate_meta_v3 import build_meta_v3

    presets = json.load(open(REPO_ROOT / "config/presets_v3.json", encoding="utf-8"))["presets"]
    preset = presets["gulf_stream"]
    seed_str = hashlib.sha256(b"gulf_stream:2025").hexdigest()
    seed_int = int(seed_str, 16)

    src = REPO_ROOT / "data/raw_oscar/oscar_2025_daily.json"
    adapter = OscarAdapter(src)
    rows = adapter.rows()
    blocks = group_days_into_blocks(rows, block_size=7)
    norm_speeds, _ = normalize_series_5_95(blocks)
    raw_series = [b.get("speed_p95") for b in blocks]
    form_info = compute_form_sections(raw_series)

    harmony_bars = generate_harmony_v3(blocks, preset, "gulf_stream", form_info)
    rest_bars = [h.is_rest for h in harmony_bars]
    drum_events, effective_tiers, tier_counts = generate_drum_events_v3(norm_speeds, preset, "gulf_stream", seed_int, rest_bars)
    melody_bars, color_tone_bars = generate_melody_v3(blocks, norm_speeds, harmony_bars, preset, seed_int)

    meta_reproduced = build_meta_v3(
        track_id="gulf_stream",
        preset=preset,
        blocks=blocks,
        norm_speeds=norm_speeds,
        harmony_bars=harmony_bars,
        melody_bars=melody_bars,
        effective_tiers=effective_tiers,
        tier_counts=tier_counts,
        form_info=form_info,
        audio_analysis={
            s["name"]: {
                "rms_db": orig_data["audio_analysis"][s["name"]]["rms_db"],
                "spectral_centroid_hz": orig_data["audio_analysis"][s["name"]]["spectral_centroid_hz"],
                "start_bar": s["start_bar"],
                "end_bar": s["end_bar"],
            }
            for s in form_info["sections"]
        },
        sample_step=orig_data["sample_step_click_check"],
        color_tone_bars=color_tone_bars,
        checksums=orig_data["checksums"],
    )

    reproduced_bytes = json.dumps(meta_reproduced, indent=2).encode("utf-8")
    assert reproduced_bytes == orig_bytes, "meta.json is not byte-identical across runs!"


def test_completeness_and_index():
    """Completeness: all 15 tracks exist in index.json, files exist on disk, checksums match, <1.5MB, 53 bars."""
    assert INDEX_PATH.exists(), "final/index.json must exist"
    index_data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    assert len(index_data) == 15, f"Expected 15 tracks in index.json, got {len(index_data)}"

    ids = [entry["id"] for entry in index_data]
    assert len(ids) == len(set(ids)), "Track IDs in index.json must be unique"

    max_bytes = int(1.5 * 1024 * 1024)  # 1.5 MB

    for entry in index_data:
        tid = entry["id"]
        assert entry["bars"] == 53, f"Track {tid} bars must be 53"
        assert entry["year"] == 2025, f"Track {tid} year must be 2025"
        expected_duration = round(53 * entry["bar_seconds"], 1)
        assert entry["duration_s"] == expected_duration, f"Track {tid} duration mismatch: {entry['duration_s']} vs {expected_duration}"

        opus_path = FINAL_DIR / "2025" / tid / "track.opus"
        meta_path = FINAL_DIR / "2025" / tid / "meta.json"

        assert opus_path.exists(), f"File {opus_path} does not exist"
        assert meta_path.exists(), f"File {meta_path} does not exist"

        file_size = opus_path.stat().st_size
        assert file_size < max_bytes, f"Track {tid} file size {file_size} exceeds 1.5 MB"
        assert file_size == entry["bytes"], f"Track {tid} size mismatch with index.json"

        actual_hash = sha256_file(opus_path)
        assert actual_hash == entry["checksum"], f"Track {tid} checksum mismatch in index.json"

        meta_data = json.loads(meta_path.read_text(encoding="utf-8"))
        assert meta_data["checksum"] == actual_hash, f"Track {tid} checksum mismatch in meta.json"


def test_schema_and_zero_banned_words():
    """Schema: all required keys present in meta.json; zero occurrences of banned words anywhere in final/."""
    required_keys = {
        "mapping_version",
        "preset",
        "seed",
        "bars",
        "bar_unit",
        "days_per_bar",
        "bar_seconds",
        "tempo",
        "hold_threshold",
        "chord_changes",
        "drum_tier_counts",
        "hysteresis_applied",
        "section_captions",
        "gm_programs",
        "loop",
        "sample_step_click_check",
        "drone",
        "color_tone",
        "audio_analysis",
        "cultural_frame",
        "scientific_data",
        "facts_narrative",
        "story",
        "context",
        "ai_disclosure",
        "checksum",
    }
    dataset_required_keys = {"name", "doi", "url", "version", "fields_used"}
    scientific_required_keys = {"dataset", "honest_limits", "audit_table"}
    narrative_required_keys = {"text", "facts_used"}
    story_required_keys = {"label", "sections", "text", "facts_used"}
    context_required_keys = {"regional_background", "source_urls"}

    json_files = list(FINAL_DIR.rglob("*.json"))
    assert len(json_files) >= 16  # 1 index.json + 15 meta.json

    for jf in json_files:
        content = jf.read_text(encoding="utf-8")
        lower_content = content.lower()
        for banned in BANNED_WORDS:
            assert banned.lower() not in lower_content, f"Banned word '{banned}' found in {jf}"

        if jf.name == "meta.json":
            data = json.loads(content)
            missing = required_keys - set(data.keys())
            assert not missing, f"Missing required keys in {jf}: {missing}"

            assert scientific_required_keys.issubset(set(data["scientific_data"].keys()))
            assert dataset_required_keys.issubset(set(data["scientific_data"]["dataset"].keys()))
            assert narrative_required_keys.issubset(set(data["facts_narrative"].keys()))
            assert story_required_keys.issubset(set(data["story"].keys()))
            assert context_required_keys.issubset(set(data["context"].keys()))
            assert len(data["facts_narrative"]["facts_used"]) >= 1, f"narrative facts_used empty in {jf}"
            assert len(data["scientific_data"]["audit_table"]) == 53, f"audit_table length != 53 in {jf}"
            assert data["bars"] == 53


def test_contracts_firms_and_ocean():
    """Contracts: fires zero-fire days produce valid:true speed_p95:0.0 rows (not rest); None rows produce silent bars; IDs unique."""
    from aetherwaves.adapters.fires import FIRMSAdapter

    adapter = FIRMSAdapter(west=-65.0, south=-15.0, east=-45.0, north=-3.0, year=2025)

    # Empty CSV parsing -> zero detection day
    parsed_zero = adapter._parse_csv("latitude,longitude,brightness,scan,track,acq_date,acq_time,satellite,confidence,version,bright_t31,frp,daynight\n", "2025-06-01")
    assert parsed_zero["valid"] is True
    assert parsed_zero["speed_p95"] == 0.0
    assert parsed_zero["magnitude"] == 0.0

    # Non-200 / error text -> None (rest)
    parsed_error = adapter._parse_csv("Invalid Key or Bad Request", "2025-06-01")
    assert parsed_error["valid"] is False
    assert parsed_error["speed_p95"] is None

    # Check ocean and fire region ID uniqueness
    ocean_regions = json.load(open(REPO_ROOT / "config/regions.json", encoding="utf-8"))["regions"]
    land_regions = json.load(open(REPO_ROOT / "config/land_regions.json", encoding="utf-8"))["regions"]

    ocean_ids = [r["id"] for r in ocean_regions if r.get("enabled", True)]
    land_ids = [r["id"] for r in land_regions]

    assert len(ocean_ids) == 7
    assert len(land_ids) == 8
    overlap = set(ocean_ids).intersection(set(land_ids))
    assert not overlap, f"Overlapping IDs found between ocean and land: {overlap}"
