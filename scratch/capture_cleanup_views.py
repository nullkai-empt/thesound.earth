import os
import subprocess
import sys
import tempfile
import time
import urllib.request

def main():
    print("Starting server on port 8009...")
    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "src.aetherwaves.server:app", "--port", "8009"])
    
    # Wait for server
    for _ in range(20):
        try:
            with urllib.request.urlopen("http://127.0.0.1:8009/") as resp:
                if resp.status == 200:
                    print("Server is up!")
                    break
        except Exception:
            time.sleep(0.5)

    edge_paths = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"
    ]
    edge_exe = next((p for p in edge_paths if os.path.exists(p)), None)
    if not edge_exe:
        print("Edge not found.")
        server.terminate()
        return

    tmp_dir = tempfile.mkdtemp()
    
    # 1. Normal View (After Cleanup)
    out_img1 = os.path.abspath("web/screenshot_after_cleanup.png")
    cmd1 = [
        edge_exe,
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        f"--user-data-dir={tmp_dir}",
        "--window-size=1280,800",
        f"--screenshot={out_img1}",
        "http://127.0.0.1:8009/"
    ]
    print("Capturing normal view...")
    time.sleep(2)
    subprocess.run(cmd1, timeout=30)
    print("View 1 size:", os.path.getsize(out_img1) if os.path.exists(out_img1) else "missing")

    server.terminate()

if __name__ == "__main__":
    main()
