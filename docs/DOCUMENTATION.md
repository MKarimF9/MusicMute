# MusicMute Documentation

MusicMute is a desktop application that performs **real-time vocal extraction** from live audio using the [Hybrid Demucs (HDEMUCS)](https://pytorch.org/audio/stable/pipelines.html#torchaudio.pipelines.HDEMUCS_HIGH_MUSDB_PLUS) model. It captures system audio through a virtual cable, isolates vocals with AI, and streams the result to a chosen output device—all while running quietly in the system tray.

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Project Structure](#project-structure)
4. [Requirements](#requirements)
5. [Installation](#installation)
6. [Audio Routing Setup](#audio-routing-setup)
7. [Using the Application](#using-the-application)
8. [Configuration Parameters](#configuration-parameters)
9. [Performance Metrics](#performance-metrics)
10. [Building a Standalone Executable](#building-a-standalone-executable)
11. [Troubleshooting](#troubleshooting)

---

## Overview

MusicMute is designed for scenarios where you want to hear **only the vocals** from music or mixed audio in real time—for example, karaoke-style listening, vocal isolation during streaming, or muting everything except the singer.

**Key characteristics:**

- Runs as a **system tray application** (closing the window minimizes to tray; processing continues)
- Uses **PyTorch + torchaudio** with automatic device selection (CUDA → MPS → CPU)
- Processes audio in fixed-size blocks via **sounddevice** callbacks
- Model inference runs on a **background thread** so the UI stays responsive
- First launch downloads ~300 MB of model weights (cached locally afterward)

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        MainWindow (UI)                       │
│  PyQt6 · device selectors · params · metrics · tray icon   │
└──────────────────────────┬──────────────────────────────────┘
                           │ signals / slots
┌──────────────────────────▼──────────────────────────────────┐
│                   AudioWorker (QThread)                      │
│  load_model() · start_stream() · stop_stream()               │
└──────────────────────────┬──────────────────────────────────┘
                           │
         ┌─────────────────┼─────────────────┐
         ▼                 ▼                 ▼
   sounddevice       HDEMUCS model      numpy buffer
   Stream callback   (torchaudio)       (rolling window)
```

### Data flow

1. **Input** — Audio is captured from a virtual input device (e.g. VB-Cable, BlackHole) at 44.1 kHz stereo.
2. **Buffering** — Each callback appends incoming samples to a rolling buffer capped at `max_buffer_size`.
3. **Inference** — The full buffer is passed to the Demucs model; stem index `3` (vocals) is extracted.
4. **Offset trimming** — A `back` offset removes model lookahead artifacts from the output window.
5. **Output** — The vocal slice corresponding to the current block is written to the selected output device.

### Threading model

| Component | Thread | Responsibility |
|-----------|--------|----------------|
| `MainWindow` | Main (UI) | Device selection, start/stop, metrics display, tray |
| `AudioWorker` | `QThread` | Model loading, stream management, inference |
| `audio_callback` | sounddevice audio thread | Per-block capture → infer → output |

The worker emits three signals back to the UI:

| Signal | Payload | Purpose |
|--------|---------|---------|
| `log_signal` | `str` | Console log messages |
| `timing_signal` | `(processing_ms, block_ms)` | Live performance metrics |
| `model_loaded` | — | Enables the Start Service button |

---

## Project Structure

```
MusicMute/
├── app/
│   ├── __init__.py
│   ├── main.py           # PyQt6 UI, tray, device selection
│   └── audio_worker.py   # Model loading, stream, inference
├── assets/
│   ├── icon.png          # System tray icon
│   └── cover.png         # README cover image
├── torch_cache/          # Bundled / cached model weights
├── docs/
│   └── DOCUMENTATION.md  # This file
├── build.spec            # PyInstaller configuration
├── requirements.txt
└── README.md
```

### `app/main.py`

The entry point. Creates the main window, populates input/output device dropdowns, wires up the `AudioWorker` on a background thread, and manages the system tray lifecycle.

Notable behaviors:

- Auto-selects an input device whose name contains `blackhole` or `cable` (case-insensitive)
- Disables **Start Service** until the model finishes loading
- Overrides `closeEvent` to hide the window instead of quitting (tray persistence)

### `app/audio_worker.py`

Handles all audio and ML work:

- Loads `HDEMUCS_HIGH_MUSDB_PLUS` from torchaudio pipelines
- Patches torchaudio's download helper to disable progress bars (prevents PyQt crashes)
- Manages the `sounddevice.Stream` lifecycle
- Runs vocal extraction in `extract_vocals()` on each callback

---

## Requirements

### System

| Platform | Virtual audio driver |
|----------|---------------------|
| Windows | [VB-Audio Virtual Cable](https://vb-audio.com/Cable/) |
| macOS | [BlackHole](https://existential.audio/blackhole/) (2ch) |

### Python dependencies

Listed in `requirements.txt`:

```
numpy
sounddevice
PyQt6
pyinstaller
```

**PyTorch and torchaudio** are not pinned in `requirements.txt` because the correct build depends on your hardware. Install them separately from [pytorch.org](https://pytorch.org/) before installing the remaining requirements.

Example (macOS, Apple Silicon with MPS):

```bash
pip install torch torchaudio
pip install -r requirements.txt
```

Example (Windows with CUDA):

```bash
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124
pip install -r requirements.txt
```

---

## Installation

### Option 1: Pre-built executable (Windows)

Download a release from the [Releases](https://github.com/AhmedGhazale/HaramMute/releases) page, or use the direct links in the README. Choose the CPU or CUDA build depending on your GPU.

### Option 2: Run from source

```bash
git clone https://github.com/AhmedGhazale/MusicMute
cd MusicMute

python -m venv .venv
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate       # Windows

pip install torch torchaudio     # see pytorch.org for your platform
pip install -r requirements.txt

python -m app.main
```

Always launch as a module (`python -m app.main`), not as a script path, so package imports resolve correctly.

---

## Audio Routing Setup

MusicMute does not change your system audio settings automatically. You must route system output through a virtual cable so the app receives the mixed audio stream.

### Windows

1. Install **VB-Audio Virtual Cable**
2. Open **Settings → System → Sound → Output**
3. Select **CABLE Input (VB-Audio Virtual Cable)** as the system output device
4. In MusicMute, select **CABLE Output** as the **Input Device**
5. Select your speakers/headphones as the **Output Device**

### macOS

1. Install **BlackHole 2ch**
2. Open **Audio MIDI Setup** and create a **Multi-Output Device** that includes both BlackHole and your speakers (so you can still hear unprocessed audio if needed), **or** set BlackHole as the sole system output
3. In **System Settings → Sound → Output**, select BlackHole (or the Multi-Output Device)
4. In MusicMute, select **BlackHole 2ch** as the **Input Device**
5. Select your speakers/headphones as the **Output Device**

> If system audio is not routed through the virtual cable, MusicMute receives silence and produces no output.

---

## Using the Application

### 1. Launch

Run `MusicMute.exe` (pre-built) or `python -m app.main` (from source). The window appears and an icon is placed in the system tray.

### 2. Wait for model load

On first launch, the HDEMUCS model (~300 MB) is downloaded and cached under `torch_cache/`. The **Start Service** button stays disabled until loading completes. Check logs via **Show/Hide Logs** for status.

### 3. Select devices

- **Input Device** — Your virtual cable (auto-selected if BlackHole or VB-Cable is detected)
- **Output Device** — Where processed vocals are played (speakers, headphones, etc.)

### 4. Adjust parameters (optional)

See [Configuration Parameters](#configuration-parameters). Defaults work well on most systems.

### 5. Start the service

Click **Start Service**. Performance metrics update in real time. The button turns red and reads **Stop Service**.

### 6. Run in background

Closing the window minimizes to the tray. Processing continues until you click **Stop Service** or choose **Exit** from the tray menu.

---

## Configuration Parameters

These values are synced to the worker when you click **Start Service**.

| Parameter | Default | Description |
|-----------|---------|-------------|
| **Block Size** | `4048` | Number of samples processed per audio callback. Larger values increase latency but improve stability. Must match `sounddevice` blocksize. |
| **Max Buffer** | `16000` | Maximum rolling buffer length in samples. More context can improve separation quality but increases memory and inference time. |
| **Back Offset** | `1024` | Samples trimmed from the end of the model output to compensate for Demucs lookahead. Reducing this lowers latency but may introduce artifacts. |

Fixed values (not exposed in UI):

| Setting | Value |
|---------|-------|
| Sample rate | 44100 Hz |
| Channels | 2 (stereo) |
| Dtype | float32 |
| Model stem | Index 3 (vocals) |

---

## Performance Metrics

The UI displays three live metrics during processing:

### Processing Time (ms)

Wall-clock time for one model inference pass on the current buffer.

### Block Time (ms)

Duration of one audio block:

```
Block Time = (Block Size / Sample Rate) × 1000
           = (4048 / 44100) × 1000 ≈ 91.8 ms
```

### Real-Time Factor (RTF)

```
RTF = Processing Time / Block Time
```

| RTF | Meaning |
|-----|---------|
| `< 0.7` | Comfortable headroom |
| `0.7 – 0.9` | Borderline; may glitch under load |
| `≥ 1.0` | Cannot keep up; expect dropouts |

**If RTF ≥ 1.0:** increase Block Size, close GPU-heavy apps, or use a CUDA/MPS-capable device.

---

## Building a Standalone Executable

MusicMute uses PyInstaller with `build.spec`:

```bash
pyinstaller build.spec
```

The spec bundles:

- `assets/` — tray icon and other static files
- `torch_cache/` — pre-downloaded model weights (avoids download on first run)

Output: `dist/MusicMute.exe` (Windows) or `dist/MusicMute` (macOS/Linux).

The `resource_path()` helper in both `main.py` and `audio_worker.py` resolves asset paths correctly in both development and PyInstaller (`_MEIPASS`) environments.

---

## Troubleshooting

### No audio output

- Confirm the virtual cable is set as the **system output**
- Verify the correct **Input Device** is selected in MusicMute
- Ensure the service is started and the model has finished loading
- Check logs for stream or callback errors

### Audio glitches or dropouts

- Check RTF — if ≥ 1.0, increase Block Size
- Close other GPU/CPU-intensive applications
- Confirm CUDA or MPS is active (check logs on startup: `Loading model on cuda/mps/cpu`)

### Start Service button is disabled

- The model is still loading or downloading
- Wait for the log message: `Model loaded successfully.`

### High latency

- Reduce Block Size (only if RTF allows)
- Reduce Back Offset
- Ensure sample rate is 44100 Hz throughout the audio chain

### Application "closes" when clicking X

- Expected behavior — the app minimizes to the system tray
- Use the tray icon to restore the window or exit fully

### Model download fails or is slow

- First download is ~300 MB and requires internet
- Weights are cached in `torch_cache/` for subsequent launches
- For offline use, bundle `torch_cache/` with the PyInstaller build

### PyQt crashes during model download

- The worker patches torchaudio's download progress bar for this reason (`_download_no_progress` in `audio_worker.py`)
- If crashes persist, ensure you are on a recent PyQt6 version

---

## License & Credits

- **AI model:** [Hybrid Demucs](https://github.com/facebookresearch/demucs) via torchaudio's `HDEMUCS_HIGH_MUSDB_PLUS` pipeline
- **Audio I/O:** [sounddevice](https://python-sounddevice.readthedocs.io/) (PortAudio)
- **UI:** PyQt6
