# MusicMute

**Real-time vocal extraction using AI**

![cover](assets/cover.png)

MusicMute is a lightweight desktop app that isolates **vocals from live audio** in real time using the Hybrid Demucs model. It runs in the **system tray**, processes audio through a virtual cable, and can be packaged as a standalone executable with PyInstaller.

Built with **PyQt6**, **sounddevice**, and **PyTorch + torchaudio** (CUDA, MPS, or CPU).

---

## How It Works

1. System audio is routed through a **virtual cable** (VB-Cable on Windows, BlackHole on macOS).
2. MusicMute captures that stream and buffers it in rolling windows.
3. The **HDEMUCS** model extracts the vocal stem.
4. Processed vocals are streamed to your chosen **output device**.
5. Model loading and inference run on a **background thread** so the UI stays responsive.

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
git clone https://github.com/AhmedGhazale/MusicMute
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

## Usage

1. **Launch** the app and wait for the model to load (~300 MB download on first run).
2. **Route system audio** through your virtual cable.
3. Select **Input** (virtual cable) and **Output** (speakers/headphones) devices.
4. Click **Start Service** and monitor the real-time factor (RTF).
5. **Close the window** to minimize to tray — processing continues until you stop or exit.

> Full setup instructions, parameter tuning, and troubleshooting: **[docs/DOCUMENTATION.md](docs/DOCUMENTATION.md)**

---

## Build Executable

```bash
pyinstaller build.spec
```

Output: `dist/MusicMute.exe`

---

## Documentation

| Document | Contents |
|----------|----------|
| [docs/DOCUMENTATION.md](docs/DOCUMENTATION.md) | Architecture, configuration, performance tuning, troubleshooting |
