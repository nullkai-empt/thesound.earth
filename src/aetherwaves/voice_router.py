from __future__ import annotations

from .ssl_config import configure_global_ssl, get_ssl_context
configure_global_ssl()

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any, Literal, Optional

import numpy as np
from pydantic import BaseModel, Field

# -----------------------------------------------------------------------------
# Data Models & Schemas
# -----------------------------------------------------------------------------

class VoiceActionResponse(BaseModel):
    action: Literal[
        "navigate_region",
        "play_music",
        "pause_music",
        "explain_story",
        "explain_science",
        "explain_more",
        "search_svs",
        "set_month",
        "refuse_out_of_scope",
    ] = Field(description="Action to perform in the application")
    region_id: Optional[str] = Field(default=None, description="Target region id if navigating or explaining")
    svs_query: Optional[str] = Field(default=None, description="SVS query string if searching SVS visualizations")
    svs_id: Optional[str] = Field(default=None, description="SVS visualization ID if matched or requested")
    month: Optional[int] = Field(default=None, description="Month number 1 to 12 if setting month")
    spoken_reply: str = Field(description="Engaging narration or concise response grounded ONLY in NASA satellite and SVS data")
    out_of_scope: bool = Field(default=False, description="True if query was outside project scope")


# -----------------------------------------------------------------------------
# Banned Words Scrubber & Fixed Strings
# -----------------------------------------------------------------------------

BANNED_SUBSTITUTIONS = [
    (r"\b100\s*%", "every note"),
    (r"\bfilm-level\b", "expressive"),
    (r"\badvanced tuning\b", "calibrated mapping"),
    (r"\bguarantee\b", "ensure"),
    (r"\blive\b", "near real-time"),
    (r"\bmeasured by satellites\b", "derived from satellite data"),
]

REFUSAL_REPLY = "I don't have that data. I am only capable within my NASA satellite and SVS data."

WELCOME_PROMPT = "Do you want voice assistance? Press Enter for Yes, or Escape for No."
STAGE2_GUIDE_PROMPT = "Hello, this is The Sound of Earth assistance. I will help you navigate. Hold Spacebar and say Go to any region or country like India or UAE, or say Search followed by a NASA SVS topic to auto-pair visuals and generate music."


def scrub_banned_words(text: str) -> str:
    """Scrub forbidden marketing terms and enforce verified project terminology."""
    cleaned = text
    for pattern, replacement in BANNED_SUBSTITUTIONS:
        cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)
    return cleaned


# -----------------------------------------------------------------------------
# Canonical Region Mapping (Strict Prioritization)
# -----------------------------------------------------------------------------

CANONICAL_REGION_ALIASES: list[tuple[list[str], str]] = [
    # Multi-word Ocean Current Systems & Geographic Aliases (Must match before single-word land regions)
    (["uae", "united arab emirates", "dubai", "sharjah", "abu dhabi", "oman", "persian gulf", "arabian gulf", "arabian sea", "arabian", "indian ocean"], "arabian_sea"),
    (["japan", "tokyo", "kuroshio current", "kuroshio", "north pacific"], "kuroshio"),
    (["south pacific", "east australian current", "east australian", "east australia"], "east_australian"),
    (["gulf stream", "north atlantic", "florida"], "gulf_stream"),
    (["south atlantic", "brazil malvinas", "brazil current", "malvinas current", "malvinas", "brazil", "rio", "argentina", "buenos aires"], "brazil_malvinas"),
    (["antarctica", "drake passage", "drake acc", "drake", "southern ocean", "acc"], "drake_acc"),
    (["nordic seas", "nordic", "norway", "iceland", "greenland sea", "arctic"], "nordic_seas"),
    # Terrestrial Regions & Geographic Aliases
    (["usa", "united states", "california", "seattle", "west coast", "western north america", "west north america", "north america", "pacific northwest"], "w_north_america"),
    (["india", "mumbai", "delhi", "bangalore", "bay of bengal", "south asia"], "india"),
    (["amazon basin", "amazon rainforest", "amazon", "south america"], "amazon"),
    (["congo basin", "congo rainforest", "congo", "central africa", "africa"], "congo"),
    (["southeast asia", "se asia", "thailand", "vietnam", "indochina", "indonesia", "bangkok"], "se_asia"),
    (["australia", "sydney", "melbourne", "australian continent", "outback"], "australia"),
    (["siberia", "boreal", "russia", "moscow", "northern asia"], "siberia"),
    (["europe", "european", "uk", "united kingdom", "london", "mediterranean", "spain", "france", "italy", "germany", "southern europe"], "europe"),
]

MONTH_MAP = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}


def match_region_alias(raw_text: str) -> str | None:
    """Resolve user transcript against canonical aliases using strict phrase boundaries."""
    text = raw_text.lower()
    for phrases, rid in CANONICAL_REGION_ALIASES:
        for phrase in phrases:
            pattern = rf"\b{re.escape(phrase)}\b"
            if re.search(pattern, text):
                return rid
    return None


# -----------------------------------------------------------------------------
# Knowledge Base & Grounding Context Loader
# -----------------------------------------------------------------------------

def load_grounded_knowledge() -> tuple[dict[str, dict[str, Any]], str]:
    """Load all 15 region metadata profiles and compile prompt summary."""
    region_profiles: dict[str, dict[str, Any]] = {}
    index_path = Path("final/index.json")
    if not index_path.exists():
        return {}, ""

    try:
        tracks = json.loads(index_path.read_text(encoding="utf-8"))
    except Exception:
        tracks = []

    lines = [
        "VERIFIED REGIONS & SCIENTIFIC SONIFICATIONS (Derived from satellite data. Every note is computed from the data by rules we chose):"
    ]

    for t in tracks:
        rid = t["id"]
        meta_p = Path(f"final/2025/{rid}/meta.json")
        meta_data: dict[str, Any] = {}
        if meta_p.exists():
            try:
                meta_data = json.loads(meta_p.read_text(encoding="utf-8"))
            except Exception:
                meta_data = {}

        name = t.get("region", rid)
        domain = t.get("domain", "ocean")
        scale = t.get("scale", "")
        key = t.get("key", "C")
        tempo = t.get("tempo", 60)
        cult = meta_data.get("cultural_frame", "")
        sci = meta_data.get("scientific_data", {})
        ds_name = sci.get("dataset", {}).get("name", "NASA Earth observation data")
        fields = ", ".join(sci.get("dataset", {}).get("fields_used", ["surface velocity"]))
        facts_narrative_text = meta_data.get("facts_narrative", {}).get("text", "")
        story_text = meta_data.get("story", {}).get("text", "")

        profile = {
            "id": rid,
            "name": name,
            "domain": domain,
            "scale": scale,
            "key": key,
            "tempo": tempo,
            "cultural_frame": cult,
            "dataset_name": ds_name,
            "fields_used": fields,
            "facts_narrative": facts_narrative_text,
            "story": story_text,
            "honest_limits": meta_data.get("honest_limits", "Derived from satellite data."),
            "section_captions": meta_data.get("section_captions", {}),
            "audit_table": meta_data.get("scientific_data", {}).get("audit_table", []),
        }
        region_profiles[rid] = profile

        lines.append(
            f"- [{rid}] '{name}' ({domain}): Key {key} {scale}, tempo {tempo} BPM. "
            f"Dataset: {ds_name} ({fields}). Cultural frame: {cult}."
        )

    summary_text = "\n".join(lines)
    return region_profiles, summary_text


REGION_PROFILES, GROUNDED_SUMMARY_TEXT = load_grounded_knowledge()


def build_region_narration(region_id: str, deep: bool = False) -> str:
    """Build rich, clear 3-4 sentence narration directly from region's meta.json."""
    if region_id not in REGION_PROFILES:
        return REFUSAL_REPLY

    prof = REGION_PROFILES[region_id]
    name = prof["name"]
    scale = prof["scale"]
    key = prof["key"]
    cult = prof["cultural_frame"]
    ds_name = prof["dataset_name"]
    fields = prof["fields_used"]
    facts = prof.get("facts_narrative", "")
    honest = prof.get("honest_limits", "Derived from satellite data.")

    # 1. Artistic story interpretation
    story_clean = cult
    if ":" in story_clean:
        story_clean = story_clean.split(":", 1)[1].strip()
    if story_clean:
        story_clean = story_clean.split(".")[0].strip() + "."
    else:
        story_clean = "Artistic framing draws from regional traditions."

    s1 = f"Navigating to {name}, artistically framed with {scale} in key {key}: {story_clean}"

    # 2. Scientific explanation (facts_narrative + dataset)
    s2 = f"Scientifically, the soundscape is derived from {ds_name}, mapping {fields} directly into rhythm, harmony, and contour."

    # 3. Facts narrative seasonal arc
    if facts:
        facts_first = facts.split(".")[0].strip() + "."
        s3 = f"{facts_first}"
    else:
        s3 = "Seasonal dynamics track planetary transitions across 53 weekly bars."

    # 4. Honest limits & rule confirmation
    s4 = "Every note is computed from the data by rules we chose."

    sentences = [s1, s2, s3, s4]
    if deep:
        captions = prof.get("section_captions", {})
        peak_desc = captions.get("peak", "seasonal peak activity")
        sentences.insert(2, f"Seasonal dynamics track {peak_desc} with zero CC11 events.")

    full_narration = " ".join(sentences)
    return scrub_banned_words(full_narration)


# -----------------------------------------------------------------------------
# NASA SVS Search & Pairing Helper
# -----------------------------------------------------------------------------

def detect_svs_intent(raw_text: str) -> tuple[str, str, str] | None:
    """Detect if user query is targeting NASA SVS animations and extract query and ID."""
    raw = raw_text.lower()
    has_svs_keyword = bool(
        re.search(r"\b(svs|visualization|visualizations|perpetual ocean|animation)\b", raw) or
        re.search(r"\b(smoke|wildfire|fire|aerosol|ocean current)\s+(data|visual|video)\b", raw) or
        re.search(r"^(?:search|find|show|look for|pair with|generate)\b", raw)
    )
    if not has_svs_keyword:
        return None

    # Determine topic / query
    if re.search(r"\b(smoke|fire|wildfire|burn|aerosol)\b", raw):
        query = "smoke"
    elif re.search(r"\b(ocean|perpetual|ecco|current)\b", raw):
        query = "ocean"
    else:
        m = re.search(r"^(?:search|find|show|look for)\s+(?:for\s+)?(.+)", raw)
        if m:
            extracted = m.group(1).strip()
            cleaned_q = re.sub(r"\b(svs|visualization|visualizations|data|video|nasa)\b", "", extracted).strip()
            query = cleaned_q or extracted
        else:
            cleaned_q = re.sub(r"\b(go to|show|find|search|play|svs|nasa|data|visualization|video)\b", "", raw).strip()
            query = cleaned_q or "ocean"

    if query == "smoke" or "smoke" in query or "fire" in query or "burn" in query or "wildfire" in query:
        query = "smoke"
        svs_id = "5688"
        title = "NASA Global Smoke and Fires"
    elif query == "ocean" or "ocean" in query:
        query = "ocean"
        svs_id = "3912"
        title = "NASA SVS 3912 Perpetual Ocean"
    else:
        svs_id = "5476"
        title = f"NASA SVS {svs_id}"

    return query, svs_id, title


# -----------------------------------------------------------------------------
# Gemini Key Rotator
# -----------------------------------------------------------------------------

class GeminiKeyRotator:
    """Thread-safe round-robin API key rotator with immediate 429 failover."""

    def __init__(self, keys: list[str] | None = None):
        if keys is None:
            raw = os.getenv("GEMINI_API_KEYS", "")
            if raw.strip():
                self.keys = [k.strip() for k in raw.split(",") if k.strip()]
            else:
                single = os.getenv("GEMINI_API_KEY", "").strip()
                self.keys = [single] if single else []
        else:
            self.keys = [k.strip() for k in keys if k.strip()]

        self._index = 0
        self._lock = threading.Lock()
        self._clients: dict[str, Any] = {}

    def reload_keys(self):
        with self._lock:
            raw = os.getenv("GEMINI_API_KEYS", "")
            if raw.strip():
                self.keys = [k.strip() for k in raw.split(",") if k.strip()]
            else:
                single = os.getenv("GEMINI_API_KEY", "").strip()
                self.keys = [single] if single else []

    @property
    def key_count(self) -> int:
        return len(self.keys)

    def advance_key(self) -> str | None:
        with self._lock:
            if not self.keys:
                return None
            k = self.keys[self._index % len(self.keys)]
            self._index = (self._index + 1) % len(self.keys)
            return k

    def generate_content(
        self,
        contents: str,
        system_instruction: str | None = None,
        model: str = "gemini-3.8-flash",
    ) -> VoiceActionResponse | None:
        """Call Gemini with Structured Outputs, rotating keys on 429 and falling back models."""
        with self._lock:
            if not self.keys:
                return None
            num_keys = len(self.keys)
            start_idx = self._index
            self._index = (self._index + 1) % num_keys

        from google import genai
        from google.genai import types

        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=VoiceActionResponse,
            temperature=0.2,
            max_output_tokens=220,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            system_instruction=system_instruction,
        )

        models_to_try = [model]
        if "gemini-3.5-flash-lite" not in models_to_try:
            models_to_try.append("gemini-3.5-flash-lite")

        attempts = 0
        idx = start_idx
        last_exc: Exception | None = None

        while attempts < num_keys:
            slot_num = (idx % num_keys) + 1
            key = self.keys[idx % num_keys]

            for m in models_to_try:
                try:
                    with self._lock:
                        if key not in self._clients:
                            self._clients[key] = genai.Client(api_key=key)
                        client = self._clients[key]

                    print(f"[Gemini] Requesting key slot {slot_num}/{num_keys} (model: {m})...")
                    resp = client.models.generate_content(
                        model=m,
                        contents=contents,
                        config=config,
                    )
                    if resp.text:
                        parsed = json.loads(resp.text)
                        print(f"[Gemini] Call succeeded with key slot {slot_num}/{num_keys} (model: {m})")
                        return VoiceActionResponse.model_validate(parsed)
                    return None
                except Exception as exc:
                    last_exc = exc
                    err_str = str(exc).lower()
                    if "429" in err_str or "quota" in err_str or "resource_exhausted" in err_str:
                        next_slot = ((idx + 1) % num_keys) + 1
                        print(f"[Gemini] Key slot {slot_num}/{num_keys} hit quota/429. Rotating to key slot {next_slot}/{num_keys}...")
                        break
                    elif "not found" in err_str or "no longer available" in err_str or "404" in err_str:
                        print(f"[Gemini] Model {m} unavailable on key slot {slot_num}/{num_keys}. Trying fallback model...")
                        continue
                    else:
                        print(f"[Gemini] Error on key slot {slot_num}/{num_keys} (model: {m}): {exc}")
                        break

            idx = (idx + 1) % num_keys
            attempts += 1

        if last_exc:
            print(f"[Gemini] All {num_keys} key(s) exhausted or failed. Last error: {last_exc}")
        return None


# -----------------------------------------------------------------------------
# Kokoro-82M TTS Synthesizer (Warm Female voice: af_heart, 24kHz -> 48kHz soxr)
# -----------------------------------------------------------------------------

def _download_kokoro_file(url: str, dest_path: Path) -> bool:
    """Download a Kokoro model file streaming to a .tmp file first."""
    import urllib.request
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_suffix(dest_path.suffix + ".tmp")
    try:
        print(f"[Kokoro] Downloading {dest_path.name} from {url}...")
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
        )
        with urllib.request.urlopen(req, timeout=180, context=get_ssl_context()) as resp, open(tmp_path, "wb") as f_out:
            while chunk := resp.read(1024 * 1024):
                f_out.write(chunk)
        if tmp_path.exists() and tmp_path.stat().st_size > 1000:
            if dest_path.exists():
                dest_path.unlink()
            tmp_path.rename(dest_path)
            print(f"[Kokoro] Successfully downloaded {dest_path.name} ({dest_path.stat().st_size:,} bytes).")
            return True
        return False
    except Exception as exc:
        import traceback
        print(f"[Kokoro] Download failed for {dest_path.name}: {exc}")
        traceback.print_exc()
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass
        return False


def ensure_kokoro_model_files(model_path: Path, voices_path: Path) -> bool:
    """Ensure kokoro-v1.0.onnx and voices-v1.0.bin exist in models/kokoro/."""
    url_base = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
    model_url = f"{url_base}/kokoro-v1.0.onnx"
    voices_url = f"{url_base}/voices-v1.0.bin"

    success = True
    if not voices_path.exists() or voices_path.stat().st_size < 1000:
        if not _download_kokoro_file(voices_url, voices_path):
            success = False

    if not model_path.exists() or model_path.stat().st_size < 1000:
        if not _download_kokoro_file(model_url, model_path):
            success = False

    return success


class KokoroSynthesizer:
    """Kokoro-82M ONNX TTS synthesizer with natural warm female prosody (af_heart)."""

    def __init__(
        self,
        model_path: str = "models/kokoro/kokoro-v1.0.onnx",
        voices_path: str = "models/kokoro/voices-v1.0.bin",
    ):
        self.model_path = Path(model_path)
        self.voices_path = Path(voices_path)
        self.cache_dir = Path("models/kokoro/audio_cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self._kokoro = None
        self._voice: str | None = None
        self._lock = threading.Lock()
        self._ready = False
        self._cache: dict[str, str] = {}
        self.init_kokoro()

    def init_kokoro(self):
        try:
            # Auto-download model files if missing into models/kokoro/
            if not self.model_path.exists() or not self.voices_path.exists():
                ensure_kokoro_model_files(self.model_path, self.voices_path)

            if not self.model_path.exists() or not self.voices_path.exists():
                print(
                    f"[Kokoro] Error: Model files missing at {self.model_path} and {self.voices_path}. kokoro_ready=False"
                )
                self._ready = False
                return

            from kokoro_onnx import Kokoro
            print(f"[Kokoro] Loading ONNX model from {self.model_path} and voices from {self.voices_path}...")
            self._kokoro = Kokoro(str(self.model_path), str(self.voices_path))
            voices = self._kokoro.get_voices()
            if "af_heart" in voices:
                self._voice = "af_heart"
            elif "af_bella" in voices:
                self._voice = "af_bella"
            elif voices:
                self._voice = voices[0]
            else:
                self._voice = "af_heart"

            # Synthesize a test sample to verify the model is functional
            test_samples, test_sr = self._kokoro.create("The Sound of Earth", voice=self._voice, speed=1.0, lang="en-us")
            if test_samples is not None and len(test_samples) > 0:
                self._ready = True
                print(f"[Kokoro] Initialized successfully with voice='{self._voice}' (native {test_sr}Hz). kokoro_ready=True")
            else:
                print("[Kokoro] Warning: Test sample generation returned empty.")
                self._ready = False
                return

            # Pre-cache standard audio clips so response is instantaneous
            self.synthesize_opus_base64(WELCOME_PROMPT)
            self.synthesize_opus_base64(STAGE2_GUIDE_PROMPT)
            self.synthesize_opus_base64(REFUSAL_REPLY)
            self.synthesize_opus_base64(
                "Many people are using the music generator right now. Please try again in a few seconds."
            )
        except Exception as exc:
            import traceback
            print(f"[Kokoro] Initialization failed with exception: {exc}")
            traceback.print_exc()
            self._ready = False

    @property
    def is_ready(self) -> bool:
        return self._ready

    def get_cached_audio(self, text: str) -> str | None:
        return self._cache.get(text)

    def get_cached_welcome_audio(self) -> str | None:
        return self._cache.get(WELCOME_PROMPT)

    def get_cached_guide_audio(self) -> str | None:
        return self._cache.get(STAGE2_GUIDE_PROMPT)

    def get_cached_refusal_audio(self) -> str | None:
        return self._cache.get(REFUSAL_REPLY)

    def get_cached_429_audio(self) -> str | None:
        msg = "Many people are using the music generator right now. Please try again in a few seconds."
        return self._cache.get(msg)

    def synthesize_opus_base64(self, text: str) -> str | None:
        """Synthesize text via Kokoro, resample using high-quality soxr to 48kHz Opus."""
        if not self._ready or self._kokoro is None or not self._voice:
            return None
        text = text.strip()
        if not text:
            return None

        with self._lock:
            if text in self._cache:
                return self._cache[text]

            # Check disk cache
            text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
            cache_file = self.cache_dir / f"{text_hash}.b64"
            if cache_file.exists():
                try:
                    b64 = cache_file.read_text(encoding="ascii").strip()
                    if b64:
                        self._cache[text] = b64
                        return b64
                except Exception:
                    pass

            try:
                samples, sr = self._kokoro.create(text, voice=self._voice, speed=1.0, lang="en-us")
                pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16).tobytes()

                ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
                proc = subprocess.Popen(
                    [
                        ffmpeg_bin,
                        "-y",
                        "-f", "s16le",
                        "-ar", str(sr),
                        "-ac", "1",
                        "-i", "pipe:0",
                        "-af", "aresample=resampler=soxr:precision=28:osr=48000",
                        "-c:a", "libopus",
                        "-b:a", "96k",
                        "-f", "opus",
                        "pipe:1",
                    ],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                opus_bytes, _ = proc.communicate(input=pcm, timeout=30)
                if proc.returncode == 0 and opus_bytes:
                    b64 = base64.b64encode(opus_bytes).decode("ascii")
                    self._cache[text] = b64
                    try:
                        cache_file.write_text(b64, encoding="ascii")
                    except Exception:
                        pass
                    return b64
                return None
            except Exception as exc:
                print("TTS synthesis failed:", exc)
                return None


# -----------------------------------------------------------------------------
# Whisper Local STT (faster-whisper base.en int8)
# -----------------------------------------------------------------------------

WHISPER_INITIAL_PROMPT = (
    "Go to India, UAE, Dubai, Arabian Sea, North America, Gulf Stream, "
    "Kuroshio, Amazon, Congo, Siberia, Australia, Europe, Southeast Asia, "
    "Nordic Seas, Drake Passage, Search smoke, wildfire, ocean, El Nino, play, pause."
)


def ensure_whisper_model_files(model_dir: Path) -> bool:
    """Ensure base.en int8 model files exist in models/whisper/base.en/."""
    model_dir.mkdir(parents=True, exist_ok=True)
    files = ["config.json", "model.bin", "tokenizer.json", "vocabulary.txt"]
    base_url = "https://huggingface.co/Systran/faster-whisper-base.en/resolve/main"
    import urllib.request
    success = True
    for f in files:
        target = model_dir / f
        if not target.exists() or target.stat().st_size < 100:
            url = f"{base_url}/{f}"
            print(f"[Whisper] Downloading {f} from {url}...")
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                tmp = target.with_suffix(target.suffix + ".tmp")
                with urllib.request.urlopen(req, timeout=120, context=get_ssl_context()) as resp, open(tmp, "wb") as f_out:
                    while chunk := resp.read(1024 * 1024):
                        f_out.write(chunk)
                if tmp.exists() and tmp.stat().st_size > 100:
                    if target.exists():
                        target.unlink()
                    tmp.rename(target)
            except Exception as e:
                print(f"[Whisper] Download error for {f}:", e)
                success = False
    return success


class WhisperTranscriber:
    """Fast local STT using faster-whisper base.en int8 model (~0.05-0.2s CPU latency)."""

    def __init__(self, model_dir: str = "models/whisper/base.en"):
        self.model_dir = Path(model_dir)
        self._model = None
        self._lock = threading.Lock()
        self._ready = False
        self.init_whisper()

    def init_whisper(self):
        try:
            if not (self.model_dir / "model.bin").exists():
                ensure_whisper_model_files(self.model_dir)

            if (self.model_dir / "model.bin").exists():
                from faster_whisper import WhisperModel
                self._model = WhisperModel(str(self.model_dir), device="cpu", compute_type="int8")
                self._ready = True
                print("[Whisper] Initialized base.en int8 model successfully. whisper_ready=True")
            else:
                # Fallback to tiny.en if present
                tiny_dir = Path("models/whisper/tiny.en")
                if (tiny_dir / "model.bin").exists():
                    from faster_whisper import WhisperModel
                    self._model = WhisperModel(str(tiny_dir), device="cpu", compute_type="int8")
                    self._ready = True
                    print("[Whisper] Initialized tiny.en int8 model fallback. whisper_ready=True")
                else:
                    print(f"[Whisper] Warning: Model files missing in {self.model_dir}.")
                    self._ready = False
        except Exception as exc:
            print("[Whisper] Initialization error:", exc)
            self._ready = False

    @property
    def is_ready(self) -> bool:
        return self._ready

    def transcribe_base64(self, audio_base64: str) -> str:
        """Decode base64 audio and transcribe with WhisperModel."""
        if not self._ready or not self._model or not audio_base64:
            return ""
        try:
            audio_bytes = base64.b64decode(audio_base64)
            return self.transcribe_bytes(audio_bytes)
        except Exception as e:
            print("[Whisper] base64 decode error:", e)
            return ""

    def transcribe_bytes(self, audio_bytes: bytes) -> str:
        if not self._ready or not self._model or not audio_bytes:
            return ""
        try:
            ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
            proc = subprocess.Popen(
                [ffmpeg_bin, "-y", "-i", "pipe:0", "-f", "s16le", "-ar", "16000", "-ac", "1", "pipe:1"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            pcm_bytes, _ = proc.communicate(input=audio_bytes, timeout=10)
            if proc.returncode != 0 or not pcm_bytes:
                return ""
            arr = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            if len(arr) == 0:
                return ""
            with self._lock:
                segments, _ = self._model.transcribe(
                    arr,
                    beam_size=1,
                    language="en",
                    initial_prompt=WHISPER_INITIAL_PROMPT,
                    vad_filter=True,
                )
                text = " ".join([s.text for s in segments]).strip()
                return text
        except Exception as exc:
            print("[Whisper] Transcription exception:", exc)
            return ""


# Global singletons
ROTATOR = GeminiKeyRotator()
KOKORO = KokoroSynthesizer()
WHISPER = WhisperTranscriber()


# -----------------------------------------------------------------------------
# Rule-Based Intent Fallback (Strict Grounding & Offline Mode)
# -----------------------------------------------------------------------------

def rule_based_intent_fallback(transcript: str, active_region_id: str | None = None) -> VoiceActionResponse:
    """Strictly grounded rule-based intent parser for offline/no-key reliability."""
    raw = transcript.strip().lower()

    # 0. Out of scope queries (weather forecasts, trivia, jokes, coding, general questions)
    out_of_scope_patterns = [
        r"\b(weather|forecast|tomorrow|yesterday|temperature|rain|sunny|cloudy)\b",
        r"\b(capital\s+of|president\s+of|population\s+of|currency|flag|language\s+of)\b",
        r"\b(joke|riddle|poem|song|story\s+about\s+(?:cats|dogs|animals|people))\b",
        r"\b(who\s+won|score\s+of|world\s+cup|match|game|super\s+bowl|olympics)\b",
        r"\b(python|javascript|code|script|program|function|write\s+me)\b",
    ]
    if any(re.search(pat, raw) for pat in out_of_scope_patterns):
        return VoiceActionResponse(
            action="refuse_out_of_scope",
            region_id=None,
            month=None,
            spoken_reply=REFUSAL_REPLY,
            out_of_scope=True,
        )

    # 1. SVS Search / Pairing intent
    svs_info = detect_svs_intent(raw)
    if svs_info:
        q, s_id, title = svs_info
        reply = f"Loading NASA SVS {s_id} for {q}. Pairing visual animation with soundscape derived from satellite data."
        return VoiceActionResponse(
            action="search_svs",
            region_id=None,
            svs_query=q,
            svs_id=s_id,
            month=None,
            spoken_reply=reply,
            out_of_scope=False,
        )

    # 2. Transport controls
    if re.search(r"\b(pause|stop|mute|quiet|shut off)\b", raw):
        return VoiceActionResponse(
            action="pause_music",
            region_id=active_region_id,
            month=None,
            spoken_reply="Pausing music.",
            out_of_scope=False,
        )
    if re.search(r"\b(play|resume|start|unmute|sound)\b", raw) and not re.search(r"\b(how|why|what|explain|story)\b", raw):
        return VoiceActionResponse(
            action="play_music",
            region_id=active_region_id,
            month=None,
            spoken_reply="Playing music derived from satellite data.",
            out_of_scope=False,
        )

    # 3. Month selection
    for mname, mnum in MONTH_MAP.items():
        if re.search(rf"\b{mname}\b", raw) or re.search(rf"\bmonth\s+{mnum}\b", raw):
            return VoiceActionResponse(
                action="set_month",
                region_id=active_region_id,
                month=mnum,
                spoken_reply=f"Setting time to month {mnum}.",
                out_of_scope=False,
            )

    # 4. Canonical region resolution (Strict alias matching)
    matched_rid = match_region_alias(raw)
    effective_rid = matched_rid or active_region_id

    # 5. Explain deep story or science ("Explain more", "Tell me the story", "Explain science")
    if re.search(r"\b(explain\s+more|deeper|details|tell\s+me\s+more)\b", raw):
        if effective_rid and effective_rid in REGION_PROFILES:
            narration = build_region_narration(effective_rid, deep=True)
            return VoiceActionResponse(
                action="explain_more",
                region_id=effective_rid,
                month=None,
                spoken_reply=narration,
                out_of_scope=False,
            )

    if re.search(r"\b(explain|science|story|dataset|data|tell me about|what is|how was)\b", raw):
        if effective_rid and effective_rid in REGION_PROFILES:
            narration = build_region_narration(effective_rid, deep=False)
            return VoiceActionResponse(
                action="explain_story" if "story" in raw else "explain_science",
                region_id=effective_rid,
                month=None,
                spoken_reply=narration,
                out_of_scope=False,
            )

    # 6. Navigate to region
    if matched_rid:
        narration = build_region_narration(matched_rid, deep=False)
        return VoiceActionResponse(
            action="navigate_region",
            region_id=matched_rid,
            month=None,
            spoken_reply=narration,
            out_of_scope=False,
        )

    # 7. Strict refusal for anything outside verified NASA satellite & SVS data
    return VoiceActionResponse(
        action="refuse_out_of_scope",
        region_id=None,
        month=None,
        spoken_reply=REFUSAL_REPLY,
        out_of_scope=True,
    )


# -----------------------------------------------------------------------------
# Main Voice Navigation Router
# -----------------------------------------------------------------------------

def process_voice_navigation(
    transcript: str | None = None,
    active_region_id: str | None = None,
    audio_base64: str | None = None,
    mime_type: str = "audio/webm",
) -> dict[str, Any]:
    """Execute complete voice navigation with Gemini rotation, native audio parts, grounding, and Kokoro TTS."""
    clean_transcript = (transcript or "").strip()

    system_prompt = (
        "You are the voice assistant for THESOUND.EARTH, an interactive 3D Earth sonification platform. "
        "Your knowledge is STRICTLY LIMITED to the 15 verified Earth observation regions and NASA SVS data.\n"
        "Every note is computed from the data by rules we chose. All sonifications are derived from satellite data.\n\n"
        "CANONICAL REGION ALIAS MAPPING & GEOGRAPHIC RESOLUTION:\n"
        "- UAE, Dubai, Sharjah, Abu Dhabi, Oman, Persian Gulf, Arabian Sea, Indian Ocean -> 'arabian_sea'\n"
        "- India, Mumbai, Delhi, Bangalore, Bay of Bengal, South Asia -> 'india'\n"
        "- Japan, Tokyo, Kuroshio, North Pacific -> 'kuroshio'\n"
        "- USA, California, Seattle, West Coast, Western North America -> 'w_north_america'\n"
        "- Brazil, Rio, Argentina, Buenos Aires, South Atlantic, Malvinas -> 'brazil_malvinas'\n"
        "- Australia, Sydney, Melbourne, Outback -> 'australia' (land) or 'east_australian' (ocean current)\n"
        "- UK, London, Europe, Mediterranean, Spain, France, Italy, Germany -> 'europe'\n"
        "- Russia, Siberia, Moscow, Boreal -> 'siberia'\n"
        "- Amazon, South America, Rainforest -> 'amazon'\n"
        "- Congo, Central Africa, Africa -> 'congo'\n"
        "- Southeast Asia, Thailand, Vietnam, Bangkok, Indonesia, Indochina -> 'se_asia'\n"
        "- Norway, Iceland, Arctic, Nordic Seas -> 'nordic_seas'\n"
        "- Antarctica, Drake Passage, Southern Ocean, ACC -> 'drake_acc'\n"
        "- Gulf Stream, North Atlantic, Florida -> 'gulf_stream'\n\n"
        "SVS INTENT:\n"
        "- For NASA SVS requests (e.g. 'Go to smoke SVS data', 'Find wildfire visualization'): "
        "action='search_svs', svs_query='smoke', svs_id='5688'.\n\n"
        "STRICT GROUNDING & REFUSAL RULE:\n"
        "If the user asks about ANYTHING ELSE outside of these 15 regions and NASA SVS data (general knowledge, "
        "weather in outside cities, code, sports, recipes), you MUST set action='refuse_out_of_scope', "
        "region_id=null, svs_query=null, svs_id=null, month=null, out_of_scope=true, and spoken_reply to EXACTLY:\n"
        f"\"{REFUSAL_REPLY}\"\n\n"
        "BANNED WORDS: Never use '100%', 'film-level', 'advanced tuning', 'guarantee', 'live', 'measured by satellites'. "
        "Always say 'derived from satellite data' and 'every note is computed from the data by rules we chose'.\n\n"
        f"{GROUNDED_SUMMARY_TEXT}\n"
    )

    clean_transcript = (transcript or "").strip()

    # Step 1: Fast local speech-to-text using faster-whisper if audio is provided
    if not clean_transcript and audio_base64:
        clean_transcript = WHISPER.transcribe_base64(audio_base64)
        if clean_transcript:
            print(f"[VoiceRouter] Whisper transcribed: {clean_transcript!r}")

    decision: VoiceActionResponse | None = None

    # Step 2: Route directly against in-memory knowledge base (sub-millisecond latency)
    if clean_transcript:
        decision = rule_based_intent_fallback(clean_transcript, active_region_id)

    # Step 3: Fallback to Gemini if Whisper/rules yielded no decision and audio was provided
    if decision is None and audio_base64 and ROTATOR.key_count > 0:
        try:
            audio_bytes = base64.b64decode(audio_base64)
            from google.genai import types
            part_mime = mime_type.split(";")[0].strip() or "audio/webm"
            audio_part = types.Part.from_bytes(data=audio_bytes, mime_type=part_mime)
            instruction_text = (
                f"Listen carefully to the user's spoken voice command in the attached audio.\n"
                f"Determine their intent according to the system instructions.\n"
                f"Active Region: \"{active_region_id or 'none'}\""
            )
            contents = [audio_part, instruction_text]
            decision = ROTATOR.generate_content(
                contents=contents,
                system_instruction=system_prompt,
                model="gemini-3.8-flash",
            )
        except Exception as exc:
            print("[VoiceRouter] Gemini fallback exception:", exc)
            decision = None

    if decision is None:
        if not clean_transcript and not audio_base64:
            return {
                "action": "refuse_out_of_scope",
                "region_id": None,
                "svs_query": None,
                "svs_id": None,
                "month": None,
                "spoken_reply": REFUSAL_REPLY,
                "audio_base64": KOKORO.get_cached_refusal_audio() or KOKORO.synthesize_opus_base64(REFUSAL_REPLY),
                "out_of_scope": True,
            }
        decision = VoiceActionResponse(
            action="refuse_out_of_scope",
            region_id=None,
            month=None,
            spoken_reply=REFUSAL_REPLY,
            out_of_scope=True,
        )

    # Server-side regex scrub on spoken_reply
    cleaned_reply = scrub_banned_words(decision.spoken_reply)
    if decision.out_of_scope:
        cleaned_reply = REFUSAL_REPLY

    # Synthesize Kokoro Opus audio
    audio_b64 = KOKORO.synthesize_opus_base64(cleaned_reply)

    return {
        "action": decision.action,
        "region_id": decision.region_id,
        "svs_query": decision.svs_query,
        "svs_id": decision.svs_id,
        "month": decision.month,
        "spoken_reply": cleaned_reply,
        "audio_base64": audio_b64,
        "out_of_scope": decision.out_of_scope,
    }
