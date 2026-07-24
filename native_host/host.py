#!/usr/bin/env python3
"""Chrome Native Messaging host: process orchestration only, no audio.

Chrome launches this process when the extension calls chrome.runtime.connectNative
and pipes it messages over stdin/stdout using length-prefixed JSON framing. This
host's only job is to spawn/stop `python -m server.ws_server` (the actual
WebSocket + PyTorch engine) on request and report readiness — it never touches
audio itself, which still flows over the existing ws://localhost:8765 socket
directly between the extension and that engine process.

Installed once via native_host/install.py; not meant to be run by hand.
"""
import json
import os
import signal
import socket
import struct
import subprocess
import sys
import time
import traceback

HOST_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HOST_DIR, "host_config.json")
LOG_PATH = os.path.join(HOST_DIR, "host.log")
ENGINE_HOST = "127.0.0.1"
ENGINE_PORT = 8765
READY_TIMEOUT_S = 120  # generous: first run may download the ~300MB model

child = None  # subprocess.Popen we spawned, or None if we didn't launch the engine


def log(msg):
    # Chrome doesn't surface a native host's own stderr anywhere visible, so
    # this is the only way to see what actually happened when debugging.
    with open(LOG_PATH, "a") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [pid {os.getpid()}] {msg}\n")


def read_message():
    raw_len = sys.stdin.buffer.read(4)
    if len(raw_len) == 0:
        return None  # EOF: Chrome tore down the port (extension/browser closed)
    msg_len = struct.unpack("<I", raw_len)[0]
    return json.loads(sys.stdin.buffer.read(msg_len).decode("utf-8"))


def send_message(obj):
    data = json.dumps(obj).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("<I", len(data)))
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def port_open():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            s.connect((ENGINE_HOST, ENGINE_PORT))
            return True
        except OSError:
            return False


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def handle_start():
    global child
    log("handle_start: received start request")
    if port_open():
        # Already listening -- e.g. the user launched server/tray_app.py by
        # hand. Don't spawn a second engine on top of it.
        log("handle_start: port 8765 already open, treating as already running")
        send_message({"state": "running"})
        return

    config = load_config()
    log(f"handle_start: spawning {config['python']} -m server.ws_server (cwd={config['repo_root']})")
    child = subprocess.Popen(
        [config["python"], "-m", "server.ws_server"],
        cwd=config["repo_root"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    log(f"handle_start: spawned child pid {child.pid}")

    deadline = time.time() + READY_TIMEOUT_S
    while time.time() < deadline:
        if port_open():
            log("handle_start: port 8765 now open, replying running")
            send_message({"state": "running"})
            return
        if child.poll() is not None:
            log(f"handle_start: child exited early with code {child.returncode}")
            send_message({"state": "error", "message": f"engine exited early (code {child.returncode})"})
            return
        time.sleep(0.5)

    log("handle_start: timed out waiting for port 8765")
    send_message({"state": "error", "message": "timed out waiting for engine to start"})


def handle_stop():
    global child
    if child is not None and child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
    child = None
    send_message({"state": "stopped"})


def cleanup(*_args):
    if child is not None and child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
    sys.exit(0)


def main():
    log(f"main: started, argv={sys.argv}")
    signal.signal(signal.SIGTERM, cleanup)
    while True:
        message = read_message()
        if message is None:
            log("main: stdin EOF, exiting")
            break
        log(f"main: received message: {message}")
        msg_type = message.get("type")
        if msg_type == "start":
            handle_start()
        elif msg_type == "stop":
            handle_stop()
        elif msg_type == "status":
            send_message({"state": "running" if port_open() else "stopped"})
    cleanup()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("main: crashed with exception:\n" + traceback.format_exc())
        raise
