import sys
import os
import logging
import numpy as np
import torch
from torchaudio.pipelines import HDEMUCS_HIGH_MUSDB_PLUS
from time import time
import torchaudio.utils.download as ta_download

# disable progress bar as it causes pyqt to crash
_original_download = ta_download._download
def _download_no_progress(key, path, progress=False):
    return _original_download(key, path, progress=False)
ta_download._download = _download_no_progress

_default_logger = logging.getLogger("vocal_extractor")


class VocalExtractor:
    """Model loading + rolling-buffer vocal separation. No PyQt/sounddevice dependency."""

    def __init__(self, sample_rate=44100, block_size=4048, max_buffer_size=16000, back=1024, log=None):
        self.log = log or _default_logger.info

        if torch.cuda.is_available():
            self.device = 'cuda'
        elif torch.backends.mps.is_available():
            self.device = 'mps'
        else:
            self.device = 'cpu'
        self.model = None

        self.sample_rate = sample_rate
        self.block_size = block_size
        self.max_buffer_size = max_buffer_size
        self.back = back
        self.buffer = np.zeros([self.max_buffer_size, 2]).astype(np.float32)

    def load_model(self):
        torch.hub.set_dir(self.resource_path("torch_cache"))
        self.log(f"Loading model on {self.device} (please don't start until the model is ready)")
        self.log("if this is first time opening the app the model will be downloaded (!300 MB)")

        bundle = HDEMUCS_HIGH_MUSDB_PLUS
        self.model = bundle.get_model().to(self.device).eval()
        self.log("Model loaded successfully.(you can now start the service)")

    def reset_buffer(self):
        self.buffer = np.zeros([self.max_buffer_size, 2]).astype(np.float32)

    def extract_vocals(self, chunk):
        # Update buffer
        self.buffer = np.concatenate([self.buffer, chunk], axis=0)
        self.buffer = self.buffer[-self.max_buffer_size:, :]

        x = torch.from_numpy(self.buffer.T).unsqueeze(0).to(self.device)

        with torch.no_grad():
            s = time()
            out = self.model(x)
            e = time()
            processing_ms = (e - s) * 1000
            block_ms = (self.block_size / self.sample_rate) * 1000

        vocals = out[0][3].cpu().numpy().T.astype(np.float32)
        # Apply the BACK offset logic
        vocals = vocals[-self.block_size - self.back: -self.back if self.back > 0 else None, :]
        return vocals, processing_ms, block_ms

    def resource_path(self, relative_path):
        """ Get absolute path to resource, works for dev and for PyInstaller """
        try:
            # PyInstaller creates a temp folder and stores path in _MEIPASS
            base_path = sys._MEIPASS
        except Exception:
            base_path = os.path.abspath(".")

        return os.path.join(base_path, relative_path)
