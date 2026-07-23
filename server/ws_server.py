import asyncio
import json
import logging

import numpy as np
import websockets

from app.vocal_extractor import VocalExtractor

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("ws_server")

HOST = "localhost"
PORT = 8765
CHANNELS = 2
SAMPLE_RATE = 44100
BLOCK_SIZE = 2048
MAX_BUFFER_SIZE = 9000
BACK = 512

extractor = VocalExtractor(
    sample_rate=SAMPLE_RATE,
    block_size=BLOCK_SIZE,
    max_buffer_size=MAX_BUFFER_SIZE,
    back=BACK,
    log=log.info,
)


async def handle(ws):
    log.info("Client connected")
    extractor.reset_buffer()
    loop = asyncio.get_running_loop()
    queue = asyncio.Queue(maxsize=2)

    async def receiver():
        async for message in ws:
            if isinstance(message, str):
                try:
                    params = json.loads(message)
                    log.info(f"Handshake: {params}")
                except json.JSONDecodeError:
                    log.info(f"Ignoring non-JSON text frame: {message!r}")
                continue

            if queue.full():
                queue.get_nowait()  # drop oldest pending chunk to avoid growing latency
            await queue.put(message)

    async def processor():
        while True:
            message = await queue.get()
            chunk = np.frombuffer(message, dtype=np.float32).reshape(-1, CHANNELS)
            vocals, processing_ms, block_ms = await loop.run_in_executor(
                None, extractor.extract_vocals, chunk
            )
            rt_factor = processing_ms / block_ms if block_ms > 0 else 0
            log.info(f"processing={processing_ms:.1f}ms block={block_ms:.1f}ms rt={rt_factor:.2f}")
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
