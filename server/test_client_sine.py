"""Stage-1 verification: exercise ws_server.py without any browser/extension involved.

Generates a synthetic stereo clip (a "vocal" tone + a "music" tone), streams it
to the server chunk-by-chunk at realistic pacing, and writes the processed
response to a WAV file so it can be listened to.
"""
import asyncio
import json
import sys

import numpy as np
import soundfile as sf
import websockets

SAMPLE_RATE = 44100
CHANNELS = 2
BLOCK_SIZE = 2048
DURATION_S = 6
URI = "ws://localhost:8765"
OUT_PATH = "server/test_output.wav"


def make_test_clip():
    t = np.linspace(0, DURATION_S, int(SAMPLE_RATE * DURATION_S), endpoint=False)
    vocal = 0.3 * np.sin(2 * np.pi * 440 * t)  # A4, stands in for "vocals"
    music = 0.3 * np.sin(2 * np.pi * 110 * t)  # low tone, stands in for "music"
    mono = (vocal + music).astype(np.float32)
    return np.stack([mono, mono], axis=1)  # stereo


async def main():
    clip = make_test_clip()
    n_blocks = len(clip) // BLOCK_SIZE
    print(f"Streaming {n_blocks} blocks of {BLOCK_SIZE} frames ({DURATION_S}s clip)")

    async with websockets.connect(URI, max_size=None) as ws:
        await ws.send(json.dumps({
            "sample_rate": SAMPLE_RATE, "channels": CHANNELS, "block_size": BLOCK_SIZE,
        }))

        received = []

        async def receiver():
            async for message in ws:
                chunk = np.frombuffer(message, dtype=np.float32).reshape(-1, CHANNELS)
                received.append(chunk)

        recv_task = asyncio.create_task(receiver())

        block_duration = BLOCK_SIZE / SAMPLE_RATE
        for i in range(n_blocks):
            block = clip[i * BLOCK_SIZE:(i + 1) * BLOCK_SIZE]
            await ws.send(block.astype(np.float32).tobytes())
            await asyncio.sleep(block_duration)  # simulate real-time pacing

        await asyncio.sleep(1.0)  # let stragglers arrive
        recv_task.cancel()

    if not received:
        print("No audio received back — check the server log.")
        sys.exit(1)

    out = np.concatenate(received, axis=0)
    sf.write(OUT_PATH, out, SAMPLE_RATE)
    print(f"Wrote {len(out)} frames ({len(out) / SAMPLE_RATE:.1f}s) to {OUT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
