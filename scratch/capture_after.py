import os
import subprocess
import sys
import tempfile
import time
import urllib.request

def main():
    print("Starting server...")
    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "src.aetherwaves.server:app", "--port", "8008"])
    
    # Wait for server
    for _ in range(20):
        try:
            with urllib.request.urlopen("http://127.0.0.1:8008/") as resp:
                if resp.status == 200:
                    print("Server is up!")
                    break
        except Exception:
            time.sleep(0.5)
            
    # Capture screenshot
    edge_paths = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"
    ]
    edge_exe = next((p for p in edge_paths if os.path.exists(p)), None)
    if not edge_exe:
        print("Edge executable not found.")
        server.terminate()
        return

    tmp_dir = tempfile.mkdtemp()
    out_img = os.path.abspath("web/screenshot_after_1280.png")
    
    cmd = [
        edge_exe,
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        f"--user-data-dir={tmp_dir}",
        "--window-size=1280,800",
        f"--screenshot={out_img}",
        "http://127.0.0.1:8008/"
    ]
    
    print("Launching Edge to capture screenshot...")
    # Give webgl and textures 3 seconds
    time.sleep(2)
    subprocess.run(cmd, timeout=30)
    
    print("Screenshot captured. Checking file...")
    if os.path.exists(out_img):
        size = os.path.getsize(out_img)
        print(f"Success! {out_img} size: {size} bytes")
    else:
        print("Failed to capture screenshot!")

    server.terminate()

if __name__ == "__main__":
    main()
