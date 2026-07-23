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

    def __init__(self, sample_rate=44100, block_size=4048, max_buffer_size=16000, back=1024, log=None,
                 music_threshold=0.15, hysteresis_on=2, hysteresis_off=6):
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

        # Music-gating: HDEMUCS already separates drums/bass/other/vocals on every
        # call, so "how much instrumental energy is in this block" is free to
        # compute. When it's low (speech, ambient noise, wind/rain, a cappella
        # vocals) we pass the original audio through untouched instead of running
        # it through the vocal-only filter, which only makes sense when there's
        # actual accompaniment to remove.
        self.music_threshold = music_threshold  # accompaniment_rms / mix_rms above this = "music"
        self.hysteresis_on = hysteresis_on    # consecutive music blocks before filtering kicks in
        self.hysteresis_off = hysteresis_off  # consecutive quiet blocks before filtering stops
        self._filtering = False
        self._prev_filtering = False
        self._music_streak = 0
        self._quiet_streak = 0

    def load_model(self):
        torch.hub.set_dir(self.resource_path("torch_cache"))
        self.log(f"Loading model on {self.device} (please don't start until the model is ready)")
        self.log("if this is first time opening the app the model will be downloaded (!300 MB)")

        bundle = HDEMUCS_HIGH_MUSDB_PLUS
        self.model = bundle.get_model().to(self.device).eval()
        self.log("Model loaded successfully.(you can now start the service)")

    def reset_buffer(self):
        self.buffer = np.zeros([self.max_buffer_size, 2]).astype(np.float32)
        self._filtering = False
        self._prev_filtering = False
        self._music_streak = 0
        self._quiet_streak = 0

    def _slice_block(self, arr):
        return arr[-self.block_size - self.back: -self.back if self.back > 0 else None, :]

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

        # HDEMUCS_HIGH_MUSDB_PLUS stem order: drums, bass, other, vocals.
        vocals_block = self._slice_block(out[0][3].cpu().numpy().T.astype(np.float32))
        accompaniment_block = self._slice_block(
            (out[0][0] + out[0][1] + out[0][2]).cpu().numpy().T.astype(np.float32)
        )
        original_block = self._slice_block(self.buffer)

        accompaniment_rms = float(np.sqrt(np.mean(accompaniment_block ** 2)))
        original_rms = float(np.sqrt(np.mean(original_block ** 2))) + 1e-8
        music_ratio = accompaniment_rms / original_rms

        if music_ratio > self.music_threshold:
            self._music_streak += 1
            self._quiet_streak = 0
        else:
            self._quiet_streak += 1
            self._music_streak = 0

        if not self._filtering and self._music_streak >= self.hysteresis_on:
            self._filtering = True
        elif self._filtering and self._quiet_streak >= self.hysteresis_off:
            self._filtering = False

        new_block = vocals_block if self._filtering else original_block

        if self._filtering == self._prev_filtering:
            output_block = new_block
        else:
            # Crossfade across this one block so switching modes doesn't click.
            prev_block = vocals_block if self._prev_filtering else original_block
            ramp = np.linspace(0, 1, new_block.shape[0], dtype=np.float32).reshape(-1, 1)
            output_block = prev_block * (1 - ramp) + new_block * ramp
        self._prev_filtering = self._filtering

        return output_block, processing_ms, block_ms, self._filtering

    def resource_path(self, relative_path):
        """ Get absolute path to resource, works for dev and for PyInstaller """
        try:
            # PyInstaller creates a temp folder and stores path in _MEIPASS
            base_path = sys._MEIPASS
        except Exception:
            base_path = os.path.abspath(".")

        return os.path.join(base_path, relative_path)
