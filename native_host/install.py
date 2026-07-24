#!/usr/bin/env python3
"""One-time setup: registers the native messaging host with Chrome and writes
its runtime config. Run this once after cloning/building the project:

    python3 native_host/install.py

After this, the extension can auto-launch and auto-stop the server itself --
no more manually opening a separate server app before using the extension.
"""
import base64
import hashlib
import json
import os
import shutil
import stat
import sys

REPO_HOST_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(REPO_HOST_DIR)
HOST_NAME = "com.musicmute.host"


def install_dir():
    """Where the *launched* host.py actually lives -- deliberately NOT inside
    the repo. macOS restricts browsers from spawning executables located
    under TCC-protected folders (Desktop/Documents/Downloads/etc.), which
    silently fails with no way for the script itself to even log anything
    (Chrome just reports "Native host has exited."). Installing to a
    standard per-user app-support directory avoids that entirely, regardless
    of where the repo itself happens to be checked out."""
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/MusicMute/native_host")
    if sys.platform.startswith("linux"):
        return os.path.expanduser("~/.local/share/musicmute/native_host")
    raise RuntimeError(f"Unsupported platform: {sys.platform}")

# Must match the "key" field committed in extension/manifest.json -- that's
# what fixes the extension's ID so this installer can compute it without
# needing Chrome to already be running / the extension already loaded.
MANIFEST_PUBLIC_KEY_B64 = (
    "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA2331dHkuFt/WxtGKT/gaVYOrMTTdvGF"
    "fbU3cZvPYmrjBwBiaxmIFE2bNpK3WYrglC5VWpynExtFaxZMyOWnjUozzjf7hOftHsfl1XDT5K2"
    "yAWdcByqtnueFQZMcLMJeknqQbQ3Q22iW27kZv0XGQg6jCIiayG6A8la/BMo4MPK9vMfImJOpBI"
    "qQYBfSdl37z7sa+vC0Arn25A3aa12JjJEHQj9qDS/e2ujVIHmOWf0S5F4DU7k6FLDLASVj62GwT"
    "FbntTzUobnBhcxrz2RdaUv8BZbIL+CmOJgAiUyp/EKa3yZNbcgdlo7BtB/vSa8EdpIQtkayku6M"
    "Mu5QxHRevTQIDAQAB"
)


def compute_extension_id():
    """Chrome derives the extension ID from SHA-256(DER public key), taking the
    first 16 bytes and mapping each nibble to a letter a-p."""
    der = base64.b64decode(MANIFEST_PUBLIC_KEY_B64)
    digest = hashlib.sha256(der).digest()[:16]
    return "".join(chr(ord("a") + (b >> 4)) + chr(ord("a") + (b & 0xF)) for b in digest)


def native_messaging_hosts_dirs():
    """All Chromium-based browsers use the same native-messaging manifest
    format, just under different per-browser profile directories -- install
    to every one that's actually present on disk, so this doesn't silently
    only work for whichever browser happens to be first in the list."""
    if sys.platform == "darwin":
        candidates = {
            "Chrome": "~/Library/Application Support/Google/Chrome",
            "Brave": "~/Library/Application Support/BraveSoftware/Brave-Browser",
            "Edge": "~/Library/Application Support/Microsoft Edge",
            "Chromium": "~/Library/Application Support/Chromium",
        }
    elif sys.platform.startswith("linux"):
        candidates = {
            "Chrome": "~/.config/google-chrome",
            "Brave": "~/.config/BraveSoftware/Brave-Browser",
            "Edge": "~/.config/microsoft-edge",
            "Chromium": "~/.config/chromium",
        }
    else:
        raise RuntimeError(f"Unsupported platform: {sys.platform} (native messaging install path unknown)")

    found = {
        name: os.path.join(os.path.expanduser(path), "NativeMessagingHosts")
        for name, path in candidates.items()
        if os.path.isdir(os.path.expanduser(path))
    }
    if not found:
        # Fall back to Chrome's path even if not detected, rather than installing nowhere.
        found["Chrome"] = os.path.join(os.path.expanduser(candidates["Chrome"]), "NativeMessagingHosts")
    return found


def main():
    extension_id = compute_extension_id()

    target_dir = install_dir()
    os.makedirs(target_dir, exist_ok=True)
    host_script = os.path.join(target_dir, "host.py")
    shutil.copy2(os.path.join(REPO_HOST_DIR, "host.py"), host_script)
    os.chmod(host_script, os.stat(host_script).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    manifest = {
        "name": HOST_NAME,
        "description": "MusicMute server process orchestration",
        "path": host_script,
        "type": "stdio",
        "allowed_origins": [f"chrome-extension://{extension_id}/"],
    }

    print(f"Extension ID: {extension_id}")
    print(f"Host installed to: {host_script}")
    for browser_name, hosts_dir in native_messaging_hosts_dirs().items():
        os.makedirs(hosts_dir, exist_ok=True)
        manifest_path = os.path.join(hosts_dir, f"{HOST_NAME}.json")
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)
        print(f"  {browser_name}: {manifest_path}")

    host_config = {"python": sys.executable, "repo_root": REPO_ROOT}
    with open(os.path.join(target_dir, "host_config.json"), "w") as f:
        json.dump(host_config, f, indent=2)

    print(f"Engine will be launched with: {host_config['python']} -m server.ws_server")
    print(f"  (cwd={host_config['repo_root']})")
    print(f"Host log (if anything goes wrong): {os.path.join(target_dir, 'host.log')}")
    print()
    print("Setup complete. Load the extension (chrome://extensions -> Load unpacked)")
    print("and its ID should match the one above. The extension can now start/stop")
    print("the server itself -- no more manually launching a separate server app.")


if __name__ == "__main__":
    main()
