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
- Retuned the model config for this path (`block_size=2048`, `back=1024`) for lower latency than the desktop app's original `4048`/`1024`, which was measured to overflow/underflow on this hardware. `max_buffer_size` is `16000` in both, matching the desktop app — see section 6 for the later quality pass that changed these defaults further. Measured RT factor ≈ 0.35–0.65 on MPS — comfortably real-time.
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
- **`build_server.spec`**: PyInstaller spec that produces `MusicMuteServer.app`, using `COLLECT()` + `BUNDLE(...)` (onedir, not onefile) to produce a real `.app` bundle with an `Info.plist` — onefile mode unpacks itself via an extra wrapper process at launch, which combined with a macOS `.app` bundle spawned a second GUI shell (duplicate menu-bar icon) / caused Finder to open it via Terminal instead of launching it directly. `build.spec` (desktop app) was later updated to the same pattern for the same reason.

## 5. `requirements.txt`

Added `websockets` (server wire protocol) and `soundfile` (WAV I/O for the test client and flagged clips).

## 6. Quality/correctness pass, GUI adjustables, and a "Flag" debugging feature

Based on a detailed review of the pipeline:

- **`app/vocal_extractor.py`**: fixed a `block_size` typo (`4048`→`4096`), raised `back` for more stable model edges, added a genuine zero-latency overlap-add (widens extraction into already-buffered history instead of hard-splicing consecutive blocks — fixed an audible periodic buzz), fixed GPU timing to sync before measuring (RT factor was previously underreported on MPS/CUDA), added a model warmup pass, switched to `inference_mode()`, sliced tensors on-device before transfer, replaced full buffer reallocation with in-place shifting, and reworked music detection: a bounded `[0,1]` ratio, asymmetric fast-attack/slow-release smoothing, a silence gate, and upfront config validation (`max_buffer_size >= block_size + back + overlap`).
- **`app/audio_worker.py` + `app/main.py`**: fixed a real cross-thread data race — config/start/stop now go through Qt signals instead of direct calls/attribute assignment from the GUI thread — disabled config fields while running, made Quit actually stop the stream, removed dead code, guarded empty input fields, throttled the timing signal.
- **`server/tray_app.py`**: added editable fields (block size, max buffer, back offset, overlap, music thresholds) applied on Start with clear error messages instead of crashes — replaces "edit `ws_server.py` and rebuild" with "type a number and click Start" for every quality knob.
- **`server/ws_server.py` + `extension/`**: added a **"Flag last 30s"** button in the extension popup. The server keeps a rolling buffer of recently processed audio (original + filtered + classification history) and dumps it to WAV in `~/MusicMute Flagged Clips/` on flag — a real-content test corpus from actual usage instead of synthetic tones or manually hunted-down clips.
- **Follow-up fixes from a second review pass**: the server now rejects a second simultaneous connection instead of silently corrupting an already-active session's buffer/state (the `extractor` is a single shared, stateful instance); the WebSocket handshake now validates the client's `block_size` against the server's and closes the connection with a clear error on mismatch, instead of silently desyncing — this matters more now that the server's block size is GUI-editable while the extension's is still a fixed constant in `offscreen.js`; the accompaniment-energy calculation now slices each stem on-device before summing instead of after (was doing several times more work than needed); flagged-clip WAV writes now run off the event loop so they don't stutter live audio; and `build.spec` (desktop app) got the same onedir/`BUNDLE` fix `build_server.spec` needed.

## 7. Auto-launch via Native Messaging + settings sliders in the extension

Using the extension previously required manually launching a separate server app (or `tray_app.py`) and clicking Start there *before* opening the extension. This adds a [Chrome Native Messaging](https://developer.chrome.com/docs/apps/nativeMessaging) host so the extension can start/stop the server itself, plus moves the quality/latency knobs into the extension popup so they're adjustable without touching the tray app at all.

- **`native_host/host.py`** (new): a small stdlib-only native-messaging host. Its only job is process orchestration — spawn/stop `python -m server.ws_server` and report readiness — it never touches audio; the extension's offscreen document still talks to the engine over `ws://localhost:8765` exactly as before. Checks whether port 8765 is already accepting connections before spawning (so a manually-launched `tray_app.py` server isn't duplicated), and cleans up the child process on stdin EOF (Chrome tearing down the port) or `SIGTERM`, so closing the browser doesn't leave an orphaned GPU-resident process. Logs its own lifecycle to a `host.log` next to itself, since Chrome gives no other visibility into a native host's stderr.
- **`native_host/install.py`** (new): one-time setup — computes the extension's ID from the fixed `key` now committed in `extension/manifest.json` (Chrome's SHA-256-of-public-key algorithm, done this way so the ID is stable and the installer never needs to mutate the extension source), copies `host.py` to a per-user app-support directory (`~/Library/Application Support/MusicMute/` on macOS) rather than launching it from inside the repo — macOS restricts browsers from spawning executables under TCC-protected folders like Desktop/Documents, which fails silently with no way for the script to even log why (Chrome just reports "Native host has exited."); this sidesteps that regardless of where the repo happens to be checked out. Writes the native-messaging host manifest to every Chromium-based browser it finds installed (Chrome, Brave, Edge, Chromium), plus `host_config.json` (the Python interpreter + repo path to launch the engine with).
- **`extension/manifest.json`**: added the `nativeMessaging` and `storage` permissions and a fixed `key` (needed for the installer to compute a stable extension ID ahead of time, and required for `chrome.storage` to exist at all).
- **`extension/background.js`**: owns the native-messaging connection and loads settings from `chrome.storage` (via `importScripts("settings.js")`), passing both through to the offscreen document in the `start-capture` message — offscreen documents turn out to only have access to a restricted subset of extension APIs and can't use `chrome.storage` or `chrome.runtime.connectNative` directly, so this couldn't live in `offscreen.js` as originally structured. Falls back to the previous behavior (attempt the WS connection directly, assuming something else started the server) if the native host isn't installed or fails to respond, so this doesn't break anyone still running the tray app manually.
- **`extension/offscreen.js`**: the previously-hardcoded `BLOCK_SIZE` constant (and the AudioWorklet's chunking) is now driven by the popup's slider value instead, so the audio pipeline's actual chunk size and the value declared in the WS handshake can never silently drift apart.
- **`extension/popup.html` / `popup.js` / `settings.js`** (new): a collapsible "Advanced settings" section with range sliders for Block Size, Max Buffer, Back Offset, Overlap, and both Music Thresholds — the same 6 parameters `tray_app.py` exposes — persisted via `chrome.storage.local`, with a client-side check of the `max_buffer >= block_size + back + overlap` invariant (server-side validation remains the authoritative check). Also adds a "Stop server" action for reclaiming GPU/RAM without closing the browser.
- **`server/ws_server.py`**: the WS handshake now *applies* the incoming settings to the shared `extractor` (via `reset_buffer()`, the same pattern `tray_app.py::_start()` uses) instead of comparing `block_size` against a fixed server value and closing on mismatch — this intentionally supersedes the section 6 mismatch-rejection behavior, since the extension is now allowed to configure the server rather than just needing to match it.

## 8. Manual filtering-mode override (`force_mode`)

The auto-detector can false-positive on reverb-heavy a cappella content — nasheed, Quran recitation, or any pure-vocal audio where room echo gets picked up as "accompaniment" energy — running it through the vocals-only stem (and sounding duller/muffled) even though there's no real music to remove. Rather than trying to perfect the detector for every case, added a manual override: `extension/popup.html`'s new "Filtering mode" dropdown (Auto / Always play original / Always filter), synced through the same settings channel as the other knobs.

- **`app/vocal_extractor.py`**: new `force_mode` constructor param (`"auto"` / `"passthrough"` / `"filter"`, default `"auto"`). In `extract_vocals()`, non-auto modes skip the ratio/hysteresis calculation entirely and pin `self._filtering` directly — the existing crossfade-on-mode-switch logic still applies, so flipping the dropdown mid-stream doesn't click.
- **`server/ws_server.py`**: `force_mode` added to the handshake's settings keys, applied the same way as the rest.
- **`extension/settings.js` / `popup.html` / `popup.js`**: the dropdown, defaulting to `"auto"`, persisted alongside the other settings.

---

## Known limitations / not yet done

- Only one client (one browser tab, via the extension) can be connected to the local server at a time — a second connection is rejected, not queued or multiplexed.
- `MusicMuteServer.app` / `MusicMute.app` are unsigned/not notarized — first launch requires right-click → Open to bypass Gatekeeper.
- The native messaging installer covers macOS/Linux only (Windows uses the registry instead of a manifest directory, not yet supported). On macOS/Linux it installs to every Chromium-based browser it finds on disk (Chrome, Brave, Edge, Chromium).
- No automated quality measurement harness (SI-SDR vs. an offline "quality ceiling," discontinuity energy, detector confusion matrix) — quality changes are still judged by ear, including via the Flag feature's real-content clips.
