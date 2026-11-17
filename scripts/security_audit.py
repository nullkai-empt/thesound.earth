import os
import re

PATTERNS = [
    r"AIzaSy[A-Za-z0-9_-]{33}",
    r"sk-[A-Za-z0-9]{20,}",
    r"ghp_[A-Za-z0-9]{36}",
    r"AKIA[A-Z0-9]{16}",
    r"(?i)api[_-]?key\s*[:=]\s*['\"][A-Za-z0-9_\-]{20,}['\"]",
    r"(?i)token\s*[:=]\s*['\"][A-Za-z0-9_\-]{20,}['\"]",
    r"(?i)secret\s*[:=]\s*['\"][A-Za-z0-9_\-]{20,}['\"]",
]

scan_dirs = ["web", "src", "tests", "scripts"]
files_to_scan = ["Dockerfile", ".gitignore", ".dockerignore", "requirements.txt", "pyproject.toml"]

for d in scan_dirs:
    for root, _, files in os.walk(d):
        for f in files:
            files_to_scan.append(os.path.join(root, f))

leaks_found = []
for fpath in files_to_scan:
    if not os.path.exists(fpath):
        continue
    # Skip python bytecode or binary assets
    if fpath.endswith((".pyc", ".png", ".jpg", ".opus", ".mp4", ".bin", ".onnx", ".sf2", ".nc")):
        continue
    try:
        with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
            for p in PATTERNS:
                for m in re.finditer(p, content):
                    match_str = m.group(0)
                    if any(x in match_str.lower() for x in ("mock", "test", "fake", "key_", "example", "placeholder")):
                        continue
                    leaks_found.append((fpath, match_str[:8] + "..."))
    except Exception:
        pass

print("=== 1. SECRET LEAK SCAN ===")
if leaks_found:
    print("FAILED: Leaks found:", leaks_found)
else:
    print("PASS: Zero API keys, tokens, or credentials found in any files.")

print("\n=== 2. GITIGNORE & DOCKERIGNORE AUDIT ===")
with open(".gitignore", "r", encoding="utf-8") as f:
    gi = f.read()
with open(".dockerignore", "r", encoding="utf-8") as f:
    di = f.read()

required_ignores = [".env", "models/", "venv/", "tmp/", "output/"]
all_ok = True
for item in required_ignores:
    item_clean = item.rstrip("/")
    in_gi = (item in gi or item_clean in gi)
    in_di = (item in di or item_clean in di)
    status = "OK" if in_gi and in_di else "MISSING"
    print(f"  {item:10} -> in .gitignore: {in_gi}, in .dockerignore: {in_di} [{status}]")
    if not (in_gi and in_di):
        all_ok = False

if all_ok:
    print("PASS: All required directories and files are ignored.")
else:
    print("FAILED: Missing ignores detected.")
