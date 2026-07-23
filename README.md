# MusicMute

**Real-time vocal extraction using AI**

![cover](assets/cover.png)

MusicMute isolates **vocals from live audio** in real time using the Hybrid Demucs (HDEMUCS) model. Built with **PyTorch + torchaudio** (CUDA, MPS, or CPU), it comes in two modes:

- **Desktop app** — a PyQt6 system-tray app that processes **all system audio** through a virtual cable (VB-Cable on Windows, BlackHole on macOS). Good for a general "karaoke everywhere" setup.
- **Browser extension** — captures audio from **just one browser tab** (e.g. muting background music on Instagram Reels / YouTube Shorts) and streams it to a small local model server, without touching any other audio on your machine.

Both modes share the same model/inference code (`app/vocal_extractor.py`), just with different capture/playback front ends.

---

## How It Works

### Desktop app (system-wide)

1. System audio is routed through a **virtual cable** (VB-Cable on Windows, BlackHole on macOS).
2. MusicMute captures that stream and buffers it in rolling windows.
3. The **HDEMUCS** model extracts the vocal stem.
4. Processed vocals are streamed to your chosen **output device**.
5. Model loading and inference run on a **background thread** so the UI stays responsive.

### Browser extension (one tab)

```
Browser tab  ──tabCapture──▶  extension (offscreen doc)  ──WebSocket──▶  local server (server/ws_server.py)
                                       ▲                                          │
                                       └──────────── processed audio ◀────────────┘
```

1. The extension captures only the **active tab's** audio via `chrome.tabCapture` — no virtual cable, no system-wide routing.
2. Captured audio streams over a local WebSocket to `server/ws_server.py`, which runs the same HDEMUCS model.
3. Processed (vocals-only) audio streams back and plays in place of the original, scheduled to stay in sync with the video.
4. The server can be launched from a terminal or as a standalone GUI app (`server/tray_app.py`, packaged via `build_server.spec`) with a Start/Stop button — no terminal needed day-to-day.

---

## Quick Start

### Windows

Install [VB-Audio Virtual Cable](https://vb-audio.com/Cable/), then either download a pre-built executable or run from source.

**Pre-built downloads:**

- [CPU version](https://drive.google.com/file/d/181IzkqJ5JZ43DNLj9uik6N5hjEUjwTtg/view?usp=sharing)
- [CUDA version](https://drive.google.com/file/d/10q4QrfysxY_IyCx8zr0Z3iHJuDUUVEj6/view?usp=sharing)

Or see [Releases](https://github.com/AhmedGhazale/HaramMute/releases).

### macOS

Install [BlackHole 2ch](https://existential.audio/blackhole/), route system audio through it, then run from source:

```bash
git clone https://github.com/MKarimF9/MusicMute
cd MusicMute
python -m venv .venv && source .venv/bin/activate
pip install torch torchaudio
pip install -r requirements.txt
python -m app.main
```

### Run from source (all platforms)

```bash
pip install torch torchaudio   # https://pytorch.org for your platform
pip install -r requirements.txt
python -m app.main
```

---

## Usage — Desktop App

1. **Launch** the app and wait for the model to load (~300 MB download on first run).
2. **Route system audio** through your virtual cable.
3. Select **Input** (virtual cable) and **Output** (speakers/headphones) devices.
4. Click **Start Service** and monitor the real-time factor (RTF).
5. **Close the window** to minimize to tray — processing continues until you stop or exit.

> Full setup instructions, parameter tuning, and troubleshooting: **[docs/DOCUMENTATION.md](docs/DOCUMENTATION.md)**

---

## Usage — Browser Extension

**1. Start the local server** (loads the model, listens on `ws://localhost:8765`):

```bash
python -m server.tray_app        # GUI, with a Start/Stop button — see below
# or
python -m server.ws_server       # headless, starts listening immediately
```

**2. Load the extension** (Chrome/Brave/any Chromium browser):

- Go to `chrome://extensions` (or `brave://extensions`), enable **Developer mode**, click **Load unpacked**, and select the `extension/` folder.

**3. Use it**: open a tab (e.g. Instagram Reels, YouTube Shorts), click the extension icon, and hit **Start**. The tab's original audio is captured and replaced with the vocals-only stream from the local server.

> The extension only works while the local server is running. Package the server as a standalone double-clickable app with `pyinstaller build_server.spec` (see below) if you don't want to launch it from a terminal each time.

---

## Build Executable

**Desktop app:**

```bash
pyinstaller build.spec
```

Output: `dist/MusicMute` (Windows: `dist/MusicMute.exe`)

**Local server (for the browser extension):**

```bash
pyinstaller build_server.spec
```

Output: `dist/MusicMuteServer.app` (macOS). First launch: right-click → **Open** to bypass Gatekeeper, since it isn't code-signed/notarized.

---

## Documentation

| Document | Contents |
|----------|----------|
| [docs/DOCUMENTATION.md](docs/DOCUMENTATION.md) | Desktop app: architecture, configuration, performance tuning, troubleshooting |
| [docs/CHANGES.md](docs/CHANGES.md) | Full changelog of the browser-extension mode vs. the original repo |
