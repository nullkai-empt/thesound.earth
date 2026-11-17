import re
from pathlib import Path

banned = [
    r"\b100%\b",
    r"\bfilm-level\b",
    r"\badvanced tuning\b",
    r"\bguarantee\b",
    r"\blive\b",
    r"\bmeasured by satellites\b",
]

targets = list(Path("web").glob("*.*")) + [Path("src/aetherwaves/server.py"), Path("README.md")]
found_any = False

print("=== SCANNING FOR BANNED WORDS ===")
for p in targets:
    if p.is_dir() or p.suffix.lower() in [".mp4", ".png", ".jpg", ".jpeg", ".opus", ".mp3"]:
        continue
    txt = p.read_text(encoding="utf-8", errors="ignore")
    for b in banned:
        matches = list(re.finditer(b, txt, re.IGNORECASE))
        if matches:
            found_any = True
            print(f"FAIL: Found {len(matches)} match(es) for pattern {b} in {p}")
            for m in matches[:3]:
                start = max(0, m.start() - 30)
                end = min(len(txt), m.end() + 30)
                print(f"   ...{txt[start:end]!r}...")

if not found_any:
    print("PASS: Zero banned words found across web/, README.md, and src/aetherwaves/server.py!")
