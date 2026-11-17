# THESOUND.EARTH — NASA Earth Observation Sonification & 3D Visualizer

**THESOUND.EARTH** is an interactive 3D Earth sonification platform and accessibility-focused scientific visualization tool that transforms NASA Earth observation datasets and Scientific Visualization Studio (SVS) animations into acoustic soundscapes.

Every note is computed from the data by rules we chose. All sonifications are derived from satellite data.

---

## 1. Overview

THESOUND.EARTH bridges Earth observation science and acoustic perception. Users can explore global ocean currents, wildfire distributions, and planetary dynamics across a WebGL 3D globe, hear the rhythmic and harmonic structures derived from physical measurements, and navigate interactively through an integrated voice assistant powered by Kokoro-82M ONNX neural speech synthesis and the Gemini API.

### Core Principles
- **Derived from satellite data**: Musical parameters directly reflect NASA physical observation metrics.
- **Deterministic and auditable**: Identical input parameters produce bitexact identical acoustic output. Every bar of music corresponds to an audit row detailing raw satellite values, musical notes, and chord structures.
- **Transparent rule-based translation**: We make no claim that Earth naturally creates human scales; every note is computed from the data by rules we chose.
- **Accessibility by design**: Voice navigation, speech prompts, spatial pan audio cues, and automatic music ducking ensure complete accessibility for visually impaired and low-vision users.

---

## 2. Earth Observation Datasets

THESOUND.EARTH sonifies multi-modal NASA datasets across 15 canonical planetary regions:

1. **NASA OSCAR (Ocean Surface Current Analysis Real-time)**:
   - Near-surface ocean currents on a 1/3-degree global grid.
   - Zonal ($u$) and meridional ($v$) velocity fields combined into total velocity magnitude $\sqrt{u^2 + v^2}$.
   - Tracks 7 major ocean current systems: Gulf Stream, Kuroshio Current, East Australian Current, Brazil-Malvinas Confluence, Arabian Sea, Drake Passage / Antarctic Circumpolar Current, and Nordic Seas.

2. **NASA FIRMS (Fire Information for Resource Management System) & GEDI**:
   - Active wildfire detections and Fire Radiative Power (FRP) from the VIIRS SNPP 375m sensor.
   - Latitudinal canopy structure and biomass gradients from the GEDI L1B spaceborne lidar composite.
   - Tracks 8 terrestrial regions: Western North America, Amazon Basin, Congo Basin, Northern India, Southeast Asia, Australian Bush, Siberian Taiga, and Southern Europe.

3. **NASA Scientific Visualization Studio (SVS)**:
   - Hyper-resolution planetary simulations and visual animations (e.g., SVS 3912 *Perpetual Ocean*, SVS 5688 *Global Smoke and Fires*).
   - Ingestion of video frame sequences via GPU frame energy feature extraction (brightness, motion delta, and RGB color ratios) generating new acoustic compositions on demand.

---

## 3. Deterministic Musical Architecture

The sonification pipeline adheres to strict scientific and audio engineering standards:

- **Missing Data Handling**: Missing or masked satellite data is treated as a musical rest (`None`), never forced to zero. Zero fire detections in FIRMS represent a valid `0.0` measurement.
- **Synthesizer Engine**: FluidSynth with `FluidR3_GM.sf2` general MIDI soundfont. Home-made synthesis engines and MIDI CC11 expression events are excluded to prevent audio artifacts and ensure reproducible rendering.
- **Dynamic Hysteresis**: Drum tiers (base, low, medium, high) use a 2-bar hysteresis filter to eliminate rapid percussive fluttering across transition thresholds.
- **Opaque Audio Streaming**: Audio playback uses `/api/stream/{region_id}` streaming with strict security headers (`Cache-Control: no-store`, `X-Content-Type-Options: nosniff`, `Content-Disposition: inline`), eliminating local file path traversal vulnerabilities.
- **Concurrency Control**: A thread-safe job semaphore (`MAX_CONCURRENT_JOBS = 3`) prevents server resource exhaustion during synthesis, returning HTTP 429 with natural voice retry notifications when busy.
- **Gemini Key Rotator**: A thread-safe API key rotator seamlessly switches across configured Gemini keys upon HTTP 429 quota events with automatic fallback from `gemini-3.8-flash` to `gemini-3.5-flash-lite`.
- **Kokoro-82M TTS Pipeline**: Natural female speech synthesis (`af_heart`) running natively via ONNX Runtime at 24 kHz and resampled through high-precision soxr to 48 kHz Opus.

---

## 4. Accessibility Features

- **Two-Stage Welcome Dialog**: On initial entry, the platform presents a high-contrast choice dialog asking: *"Do you want voice assistance? Press Enter for Yes, or Escape for No."*
- **Push-to-Talk Voice Control**: Holding Spacebar activates speech recognition (with native MediaRecorder audio fallback). Releasing Spacebar routes the voice command immediately to the voice pipeline.
- **Automatic Volume Ducking**: When the voice assistant narrates or gives directions, background music volume smoothly ducks to `0.18` gain within 200ms, and ramps back to `1.0` gain upon speech completion.
- **Geographic & Regional Aliases**: Saying any major city, country, or body of water (e.g., *"Go to India"*, *"Go to UAE"*, *"Go to Tokyo"*, *"Go to Brazil"*) instantly resolves to the nearest monitored region and flies the camera to the target.
- **Screen Reader Navigation**: Full keyboard navigation across all controls (`Spacebar`, `Enter`, `Escape`, arrow keys).

---

## 5. Local Setup & Installation

### Prerequisites
- Python **3.12** or **3.11**
- FFmpeg (with `libopus` support)
- FluidSynth and `FluidR3_GM.sf2` soundfont

### Installation Steps

1. **Clone the repository**:
   ```bash
   git clone https://github.com/your-org/thesound-earth.git
   cd thesound-earth
   ```

2. **Create and activate a virtual environment**:
   ```powershell
   # Windows PowerShell
   py -3.12 -m venv venv
   .\venv\Scripts\Activate.ps1
   ```
   ```bash
   # Linux / macOS
   python3.12 -m venv venv
   source venv/bin/activate
   ```

3. **Install dependencies**:
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   pip install -e .
   ```

4. **Configure environment variables (optional)**:
   Create a `.env` file in the root directory:
   ```env
   GEMINI_API_KEYS=your_gemini_api_key_1,your_gemini_api_key_2
   ```

5. **Start the application**:
   ```bash
   uvicorn src.aetherwaves.server:app --host 127.0.0.1 --port 8000
   ```
   Navigate to [http://127.0.0.1:8000](http://127.0.0.1:8000) in your web browser.

---

## 6. Verification & Auditing

Run the test suite and compliance verification tools:

```powershell
# 1. Run full unit and integration tests
.\venv\Scripts\python.exe -m pytest tests/ -v

# 2. Run banned marketing language audit
.\venv\Scripts\python.exe scripts/scan_banned_words.py

# 3. Run security and credential leak audit
.\venv\Scripts\python.exe scripts/security_audit.py
```

---

## 7. Container & Red Hat OpenShift Deployment

### Docker Build & Run

The included `Dockerfile` pre-downloads Kokoro neural voice models and sets up FluidSynth dependencies:

```bash
# Build Docker image
docker build -t thesound-earth:latest .

# Run container locally
docker run -p 8000:8000 -e GEMINI_API_KEYS="your_key" thesound-earth:latest
```

### Red Hat OpenShift (`restricted-v2` SCC) Compliance

The image complies with the Red Hat OpenShift `restricted-v2` security context constraint:
- Runs as an arbitrary non-root UID (`USER 10001` or OpenShift-assigned UID).
- Root group ownership (`chgrp -R 0 /app /tmp && chmod -R g=u /app /tmp`) ensures write access to caches.
- Dynamic cache paths redirected to `/tmp`:
  ```bash
  ENV HOME=/tmp HF_HOME=/tmp/huggingface NUMBA_CACHE_DIR=/tmp/numba
  ```
- All ONNX model files are pre-cached in `/app/models/kokoro/` during the container build stage, requiring zero external egress network calls at container startup.

#### Example OpenShift Manifest (`openshift-deployment.yaml`)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: thesound-earth
  labels:
    app: thesound-earth
spec:
  replicas: 1
  selector:
    matchLabels:
      app: thesound-earth
  template:
    metadata:
      labels:
        app: thesound-earth
    spec:
      containers:
        - name: web
          image: image-registry.openshift-image-registry.svc:5000/earth-sonification/thesound-earth:latest
          ports:
            - containerPort: 8000
              protocol: TCP
          env:
            - name: GEMINI_API_KEYS
              valueFrom:
                secretKeyRef:
                  name: earth-secrets
                  key: gemini-keys
          resources:
            requests:
              cpu: "500m"
              memory: "1Gi"
            limits:
              cpu: "2"
              memory: "2Gi"
          securityContext:
            allowPrivilegeEscalation: false
            capabilities:
              drop:
                - ALL
            runAsNonRoot: true
---
apiVersion: v1
kind: Service
metadata:
  name: thesound-earth-service
spec:
  selector:
    app: thesound-earth
  ports:
    - protocol: TCP
      port: 8000
      targetPort: 8000
---
apiVersion: route.openshift.io/v1
kind: Route
metadata:
  name: thesound-earth-route
spec:
  to:
    kind: Service
    name: thesound-earth-service
  port:
    targetPort: 8000
  tls:
    termination: edge
    insecureEdgeTerminationPolicy: Redirect
```

---

## 8. License & Attribution

- **NASA Earth Observation Data**: Distributed via NASA EOSDIS (Earth Observing System Data and Information System), Physical Oceanography DAAC (PO.DAAC), and FIRMS.
- **Scientific Reference**: OSCAR ocean currents, Lang et al. (2022) GEDI canopy height model, and VIIRS active fire detections.
- **Sound Engine**: FluidSynth software synthesizer using `FluidR3_GM.sf2`.
