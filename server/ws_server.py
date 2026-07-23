import asyncio
import json
import logging
import os
import time
from collections import deque

import numpy as np
import soundfile as sf
import websockets

from app.vocal_extractor import VocalExtractor

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("ws_server")

HOST = "localhost"
PORT = 8765
CHANNELS = 2
SAMPLE_RATE = 44100
BLOCK_SIZE = 2048
MAX_BUFFER_SIZE = 16000
BACK = 1024
OVERLAP = 512               # overlap-add crossfade width, see vocal_extractor.py
MUSIC_THRESHOLD_ON = 0.35   # smoothed accompaniment/(accompaniment+vocals) must exceed this to start filtering
MUSIC_THRESHOLD_OFF = 0.20  # must drop below this (lower, deadband) to stop — bounded [0,1] scale

# "Flag" feature: the client (extension) can ask the server to dump the last
# ~30s of real audio it processed to WAV files, right when something sounds
# wrong. This is a much better source of test/tuning material than either
# synthetic tones or hunting down generic downloaded clips — it's the actual
# problem moment from real usage, with the classification history attached.
FLAG_WINDOW_S = 30
# Absolute, launch-context-independent path — a relative path would land
# somewhere unpredictable when double-clicked as a packaged .app from Finder
# (working directory isn't the project folder there).
FLAGGED_CLIPS_DIR = os.path.expanduser("~/MusicMute Flagged Clips")

extractor = VocalExtractor(
    sample_rate=SAMPLE_RATE,
    block_size=BLOCK_SIZE,
    max_buffer_size=MAX_BUFFER_SIZE,
    back=BACK,
    overlap=OVERLAP,
    music_threshold_on=MUSIC_THRESHOLD_ON,
    music_threshold_off=MUSIC_THRESHOLD_OFF,
    log=log.info,
)


def _dump_flagged_clip(history):
    """history: list of (original_chunk, processed_block, is_filtering)."""
    if not history:
        log.info("Flag requested but no audio processed yet — nothing to dump")
        return

    os.makedirs(FLAGGED_CLIPS_DIR, exist_ok=True)
    original = np.concatenate([h[0] for h in history], axis=0)
    processed = np.concatenate([h[1] for h in history], axis=0)
    filtering_flags = [h[2] for h in history]

    ts = time.strftime("%Y%m%d-%H%M%S")
    original_path = os.path.join(FLAGGED_CLIPS_DIR, f"{ts}_original.wav")
    processed_path = os.path.join(FLAGGED_CLIPS_DIR, f"{ts}_processed.wav")
    sf.write(original_path, original, SAMPLE_RATE)
    sf.write(processed_path, processed, SAMPLE_RATE)

    filtered_blocks = sum(filtering_flags)
    log.info(
        f"Flagged clip saved: {original_path} / {processed_path} "
        f"({len(history)} blocks, {filtered_blocks} filtered, {len(history) - filtered_blocks} passthrough)"
    )


async def handle(ws):
    log.info("Client connected")
    extractor.reset_buffer()
    loop = asyncio.get_running_loop()
    queue = asyncio.Queue(maxsize=2)
    history_len = max(1, int(FLAG_WINDOW_S / (BLOCK_SIZE / SAMPLE_RATE)))
    history = deque(maxlen=history_len)

    async def receiver():
        async for message in ws:
            if isinstance(message, str):
                try:
                    params = json.loads(message)
                except json.JSONDecodeError:
                    log.info(f"Ignoring non-JSON text frame: {message!r}")
                    continue

                if params.get("type") == "flag":
                    _dump_flagged_clip(list(history))
                else:
                    log.info(f"Handshake: {params}")
                continue

            if queue.full():
                queue.get_nowait()  # drop oldest pending chunk to avoid growing latency
            await queue.put(message)

    async def processor():
        while True:
            message = await queue.get()
            chunk = np.frombuffer(message, dtype=np.float32).reshape(-1, CHANNELS)
            vocals, processing_ms, block_ms, is_filtering = await loop.run_in_executor(
                None, extractor.extract_vocals, chunk
            )
            history.append((chunk.copy(), vocals.copy(), is_filtering))
            rt_factor = processing_ms / block_ms if block_ms > 0 else 0
            log.info(
                f"processing={processing_ms:.1f}ms block={block_ms:.1f}ms rt={rt_factor:.2f} "
                f"filtering={is_filtering}"
            )
            await ws.send(vocals.astype(np.float32).tobytes())

    recv_task = asyncio.create_task(receiver())
    proc_task = asyncio.create_task(processor())
    try:
        await recv_task
    finally:
        proc_task.cancel()
        log.info("Client disconnected")


async def start_server():
    """Start listening. Returns the server handle (pass to stop_server to shut down)."""
    server = await websockets.serve(handle, HOST, PORT, max_size=None)
    log.info(f"Listening on ws://{HOST}:{PORT}")
    return server


async def stop_server(server):
    server.close()
    await server.wait_closed()
    log.info("Stopped listening")


async def main(on_ready=None):
    extractor.load_model()
    server = await start_server()
    try:
        if on_ready:
            on_ready()
        await asyncio.Future()
    finally:
        await stop_server(server)


if __name__ == "__main__":
    asyncio.run(main())
