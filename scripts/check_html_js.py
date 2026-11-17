import re
import subprocess
import sys
from pathlib import Path

html_path = Path("web/index.html")
if not html_path.exists():
    print(f"Error: {html_path} does not exist.")
    sys.exit(1)

html = html_path.read_text(encoding="utf-8")
scripts = re.findall(r"<script(?:\s+[^>]*)?>(.*?)</script>", html, re.DOTALL)
print(f"Found {len(scripts)} script block(s) in {html_path}.")

tmp_dir = Path("tmp")
tmp_dir.mkdir(exist_ok=True)

all_ok = True
for idx, code in enumerate(scripts):
    if not code.strip():
        continue
    script_file = tmp_dir / f"block_{idx}.js"
    script_file.write_text(code, encoding="utf-8")
    print(f"Checking script block {idx} ({len(code)} characters)...")
    res = subprocess.run(["node", "--check", str(script_file)], capture_output=True, text=True)
    if res.returncode == 0:
        print(f"Block {idx}: Syntax OK")
    else:
        print(f"Block {idx}: Syntax ERROR:\n{res.stderr}")
        all_ok = False
    script_file.unlink(missing_ok=True)

if not all_ok:
    sys.exit(1)
print("All script blocks in web/index.html passed node --check.")
