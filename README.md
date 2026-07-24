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

**One-time setup:**

1. Load the extension (Chrome, Brave, or any Chromium browser): go to `chrome://extensions`, enable **Developer mode**, click **Load unpacked**, select the `extension/` folder.
2. Register the native messaging host, so the extension can start/stop the server itself (run this with the same interpreter that has `torch`/`websockets` installed — e.g. your activated `.venv` — since that's the interpreter the extension will launch the server with):
   ```bash
   source .venv/bin/activate
   python native_host/install.py
   ```

That's it — no separate server app to launch by hand from here on.

**Daily use:** open a tab (e.g. a Reels/Shorts video), click the extension icon, hit **Start**. The extension launches the server itself on first use (a few seconds — longer on the very first run while the model downloads), keeps it running across Start/Stop toggles for fast reconnects, and shuts it down automatically when the browser closes.

The popup's **Filtering mode** dropdown lets you override the auto-detector: "Always play original" is useful for content it wrongly filters (a cappella vocals, nasheed, Quran recitation — reverb can get misread as background music). "Auto" is the default. Applies the next time you click Start.

Click **Advanced settings** in the popup to tune quality/latency live — Block Size, Max Buffer, Back Offset, Overlap, and the two Music Threshold sliders (same knobs `server/tray_app.py` exposes) — changes apply the next time you click Start. Raising **Music Threshold On** makes the detector less trigger-happy if it's false-positiving on your content. There's also a **Stop server** button in there if you want to reclaim GPU/RAM without closing the browser.

If you skip the one-time native-messaging setup, the extension falls back to the old behavior: manually run `python -m server.tray_app` (or the packaged `MusicMuteServer.app`, see below) and click **Start Server** yourself before using the extension.

---

## Run without a terminal (optional)

Package either mode as a standalone app you can launch from Finder/Applications:

```bash
pyinstaller build.spec           # -> dist/MusicMute.app (desktop app)
pyinstaller build_server.spec    # -> dist/MusicMuteServer.app (extension's server)
```

Move either `.app` to `/Applications` if you want it there. First launch: **right-click → Open** to bypass Gatekeeper (they aren't code-signed/notarized) — only needed once.

---

## Documentation

| Document | Contents |
|----------|----------|
| [docs/DOCUMENTATION.md](docs/DOCUMENTATION.md) | Desktop app: architecture, configuration, performance tuning, troubleshooting |
| [docs/CHANGES.md](docs/CHANGES.md) | Full changelog of this fork vs. the original repo |
