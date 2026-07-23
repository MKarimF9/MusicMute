# Changes from the original repo

The original repo (`AhmedGhazale/MusicMute`, commit `013089b`) was a single PyQt6 desktop app that captured **all system audio** through a virtual cable (VB-Cable/BlackHole), ran it through the HDEMUCS vocal-isolation model, and played the processed audio back — system-wide, one fixed input device.

This branch adds a second, narrower mode: isolating vocals for **just one browser tab** (e.g. Instagram Reels, YouTube Shorts) via a browser extension talking to a local model server, without touching any other audio on the machine. The original desktop app is left working as-is.

---

## 1. Desktop app (`app/`) — device selection + Apple Silicon support

- **`app/main.py`**: the input device was previously hardcoded to a Windows-only string (`"CABLE Output (VB-Audio Virtual , MME"`). Replaced with a live dropdown (`populate_input_devices`) that lists all input devices and auto-selects one containing "blackhole" or "cable" in its name — works on both macOS and Windows.
- **`app/audio_worker.py`**: device selection now tries `cuda` → **`mps`** → `cpu` (was `cuda` → `cpu` only), so it uses the GPU on Apple Silicon Macs instead of falling back to CPU.
- **`app/vocal_extractor.py`** *(new)*: the model-loading and rolling-buffer inference logic (`load_model`, `extract_vocals`, buffer/back-offset handling) was extracted out of `AudioWorker` into a plain `VocalExtractor` class with no PyQt/sounddevice dependency. `AudioWorker` is now a thin adapter that owns a `VocalExtractor` and wires it to Qt signals and a `sounddevice.Stream`. This is a behavior-preserving refactor — done so the same inference logic could be reused by the new WebSocket server below without duplicating it. Verified `python -m app.main` behaves identically after the change.

## 2. Local WebSocket server (`server/`) — new

Reuses `VocalExtractor` outside of PyQt/sounddevice, so a browser extension can stream one tab's audio to it instead of routing all system audio through a virtual cable.

- **`server/ws_server.py`**: an `asyncio` + `websockets` server on `ws://localhost:8765`. Loads the model once at startup. Wire protocol: an optional one-time JSON handshake, then raw binary frames of interleaved float32 PCM (stereo, fixed block size). Inference runs via `run_in_executor` so the event loop keeps draining the socket; a bounded `asyncio.Queue(maxsize=2)` drops the oldest pending chunk under load instead of letting latency grow unbounded. Logs `processing_ms` / `block_ms` / RT factor per chunk.
- Retuned the model config for this path: `block_size=2048`, `max_buffer_size=9000`, `back=512` (vs. the desktop app's `4048`/`16000`/`1024`, which was measured to be too slow for real time on this hardware — overflow/underflow errors). Measured RT factor ≈ 0.35–0.65 on MPS with the new settings — comfortably real-time.
- **`server/test_client_sine.py`**: a standalone test harness — streams a synthetic clip to the server and writes the processed response to a WAV, used to verify the model/wire-protocol in isolation before any browser code existed.

## 3. Browser extension (`extension/`) — new

Manifest V3 Chromium extension. Captures only the active tab's audio (not system-wide) and routes it through the local server.

- **`manifest.json`**: `tabCapture`, `offscreen`, `activeTab` permissions; `host_permissions` for the local WebSocket.
- **`background.js`**: service worker — gets a `tabCapture` stream id for the active tab (`targetTabId`, not `consumerTabId` — a capture-target vs. capture-consumer mixup that initially caused `AbortError: Error starting tab capture`) and creates/manages the offscreen document. Tracks start/stop state and the toolbar badge; only marks "on" after the offscreen document confirms capture actually succeeded (previously it optimistically marked "on" immediately, masking failures).
- **`offscreen.html` / `offscreen.js`**: owns the actual `MediaStream`/`AudioContext` (required — MV3 service workers can't touch media APIs directly). Forces the capture `AudioContext` to 44100 Hz so Chromium resamples the tab's native ~48kHz once, in-browser, matching the model's trained sample rate. Sends captured audio to the WebSocket server and schedules the returned processed audio for gapless, in-sync playback via `AudioBufferSourceNode`, with a ~150ms prebuffer added to absorb network/inference jitter (fixed audible choppiness on YouTube Shorts). A dropped WebSocket now cleans up the tab capture instead of leaving it dangling (which previously caused `Cannot capture a tab with an active stream` on retry).
- **`worklet-capture.js`**: an `AudioWorkletNode` (not the deprecated `ScriptProcessorNode`) that chunks captured audio into fixed-size blocks for sending. Routed through a muted `GainNode` to the audio destination — required so the browser's render graph actually pulls/processes the node at all; the original (unprocessed) tab audio itself is never audible since `tabCapture` diverts it from the tab's own output once captured.
- **`popup.html` / `popup.js`**: minimal Start/Stop toggle UI.

## 4. Server GUI (`server/tray_app.py`, `build_server.spec`) — new

A GUI launcher for `ws_server.py` so it doesn't require a terminal, matching the desktop app's UX in `app/main.py`: a window with a Start/Stop Server button, status label, and log console, plus a tray icon that minimizes the window instead of quitting.

- Loads the model once at launch (in a background thread running a persistent asyncio event loop); the Start/Stop button only toggles whether the server is accepting connections (`ws_server.start_server()` / `stop_server()`), added specifically for this. All cross-thread UI updates go through Qt signals (`model_ready`, `status_changed`) — an earlier version touched widgets directly from the asyncio thread, which is invalid in Qt and triggered `QBasicTimer::start: Timers cannot be started from another thread`.
- **`build_server.spec`**: PyInstaller spec (mirrors the existing `build.spec` for the desktop app) that produces `MusicMuteServer.app`. Uses `BUNDLE(...)` to produce an actual `.app` bundle with an `Info.plist` — without it, PyInstaller only emits a raw Mach-O binary, which macOS Finder runs by opening a Terminal window instead of launching it as a normal GUI app.

## 5. `requirements.txt`

Added `websockets` (server wire protocol) and `soundfile` (WAV I/O for the test client).

---

## Known limitations / not yet done

- The browser extension's stream/model config (`block_size=2048` etc.) is a first-pass tuning, not exhaustively optimized — further chunk-size tuning or a lighter/faster separation model is the next lever if quality or latency needs improvement.
- `MusicMuteServer.app` is unsigned/not notarized — first launch requires right-click → Open to bypass Gatekeeper.
- No auto-start-at-login wiring yet (discussed, not implemented) — currently the server app must be launched manually before using the extension.
