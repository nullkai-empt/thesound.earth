import time
from aetherwaves.voice_router import (
    KOKORO,
    REGION_PROFILES,
    REFUSAL_REPLY,
    STAGE2_GUIDE_PROMPT,
    WELCOME_PROMPT,
    build_region_narration,
)

print(f"Kokoro ready: {KOKORO.is_ready}")
print(f"Cache dir: {KOKORO.cache_dir}")

prompts = [
    ("welcome_stage1", WELCOME_PROMPT),
    ("welcome_stage2", STAGE2_GUIDE_PROMPT),
    ("refusal", REFUSAL_REPLY),
]

for name, p in prompts:
    t0 = time.perf_counter()
    b64 = KOKORO.synthesize_opus_base64(p)
    dt = time.perf_counter() - t0
    print(f"[{name}] cached: {len(b64) if b64 else 0} chars in {dt:.2f}s")

for rid in REGION_PROFILES:
    narr = build_region_narration(rid)
    t0 = time.perf_counter()
    b64 = KOKORO.synthesize_opus_base64(narr)
    dt = time.perf_counter() - t0
    print(f"[{rid}] cached ({len(narr.split())} words): {len(b64) if b64 else 0} chars in {dt:.2f}s")

print("All narrations pre-cached successfully!")
