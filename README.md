# MusicMute

**Real-time vocal extraction using AI**

![cover](assets/cover.png)

Removes background music from live audio in real time using the Hybrid Demucs (HDEMUCS) model, leaving speech/vocals. Two modes:

- **Desktop app** — processes all system audio (via a virtual cable). Good for a general "karaoke everywhere" setup.
- **Browser extension** — mutes music in just one browser tab (e.g. Instagram Reels, YouTube Shorts), without touching anything else.

---

## 1. Setup (once, either mode)

Requires Python 3.10+.

```bash
git clone https://github.com/MKarimF9/MusicMute
cd MusicMute
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install torch torchaudio        # https://pytorch.org — pick your platform/CUDA version
pip install -r requirements.txt
```

First run of either mode downloads the model (~300 MB), cached locally afterward.

---

## 2. Desktop app (system-wide)

**Install a virtual audio cable first:**
- macOS: [BlackHole 2ch](https://existential.audio/blackhole/)
- Windows: [VB-Audio Virtual Cable](https://vb-audio.com/Cable/)

Route your system audio output through it, then:

```bash
python -m app.main
```

In the app: select the virtual cable as **Input**, your speakers/headphones as **Output**, click **Start Service**. Closing the window minimizes to tray — it keeps running until you stop it or quit from the tray menu.

> More detail (config tuning, troubleshooting): [docs/DOCUMENTATION.md](docs/DOCUMENTATION.md)

---

## 3. Browser extension (single tab)

**Step 1 — start the local server** (loads the model, listens on `ws://localhost:8765`):

```bash
python -m server.tray_app
```

A window opens with adjustable quality settings (block size, buffer, thresholds, etc.) and a **Start Server** button — click it.

**Step 2 — load the extension** (Chrome, Brave, or any Chromium browser):

1. Go to `chrome://extensions` (or `brave://extensions`)
2. Enable **Developer mode**
3. Click **Load unpacked**, select the `extension/` folder

**Step 3 — use it**: open a tab (e.g. a Reels/Shorts video), click the extension icon, hit **Start**. The tab's audio is replaced with the music-filtered stream from the local server. The server must stay running for this to work.

---

## Run without a terminal (optional)

Package either mode as a standalone app you can launch from Finder/Applications:

```bash
pyinstaller build.spec           # -> dist/MusicMute (desktop app)
pyinstaller build_server.spec    # -> dist/MusicMuteServer.app (extension's server)
```

Move `MusicMuteServer.app` to `/Applications` if you want it there. First launch: **right-click → Open** to bypass Gatekeeper (it isn't code-signed/notarized) — only needed once.

---

## Documentation

| Document | Contents |
|----------|----------|
| [docs/DOCUMENTATION.md](docs/DOCUMENTATION.md) | Desktop app: architecture, configuration, performance tuning, troubleshooting |
| [docs/CHANGES.md](docs/CHANGES.md) | Full changelog of this fork vs. the original repo |
