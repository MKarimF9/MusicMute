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

    def __init__(self, sample_rate=44100, block_size=4096, max_buffer_size=16000, back=4096, overlap=512,
                 log=None, music_threshold_on=0.35, music_threshold_off=0.20,
                 ema_alpha_attack=0.6, ema_alpha_release=0.15, silence_rms=1e-3):
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
        self.overlap = overlap

        # Music-gating: HDEMUCS already separates drums/bass/other/vocals on every
        # call, so "how much instrumental energy is in this block" is free to
        # compute. When it's low (speech, ambient noise, wind/rain, a cappella
        # vocals) we pass the original audio through untouched instead of running
        # it through the vocal-only filter, which only makes sense when there's
        # actual accompaniment to remove.
        self.music_threshold_on = music_threshold_on    # smoothed ratio must exceed this to start filtering
        self.music_threshold_off = music_threshold_off  # must drop below this (lower) to stop
        # Asymmetric envelope: fast attack (music appearing -> filter on quickly;
        # since the app's whole purpose is blocking music, leaving it unfiltered
        # for a few hundred ms after onset is a correctness bug, not just quality)
        # but slow release (avoid flapping off on a brief dip in accompaniment).
        self.ema_alpha_attack = ema_alpha_attack
        self.ema_alpha_release = ema_alpha_release
        self.silence_rms = silence_rms  # below this, hold state instead of reclassifying off noise floor

        self.reset_buffer()  # allocates self.buffer, computes tapers, sets initial state

    def _validate_sizes(self):
        required = self.block_size + self.back + self.overlap
        if self.max_buffer_size < required:
            raise ValueError(
                f"max_buffer_size ({self.max_buffer_size}) must be >= block_size + back + overlap "
                f"({required})"
            )

    def load_model(self):
        torch.hub.set_dir(self.resource_path("torch_cache"))
        self.log(f"Loading model on {self.device} (please don't start until the model is ready)")
        self.log("if this is first time opening the app the model will be downloaded (!300 MB)")

        bundle = HDEMUCS_HIGH_MUSDB_PLUS
        self.model = bundle.get_model().to(self.device).eval()

        # Warmup: the first real forward pass otherwise eats kernel compilation/
        # autotuning time inside a live audio callback.
        with torch.inference_mode():
            dummy = torch.zeros(1, 2, self.max_buffer_size, device=self.device)
            self.model(dummy)
            self._sync_device()

        self.log("Model loaded successfully.(you can now start the service)")

    def _sync_device(self):
        # GPU ops are async; without this, timing code measures launch time, not
        # actual compute (the .cpu() calls that would force a sync happen after
        # the timer already stopped).
        if self.device == 'mps':
            torch.mps.synchronize()
        elif self.device == 'cuda':
            torch.cuda.synchronize()

    def reset_buffer(self):
        self._validate_sizes()
        self.buffer = np.zeros([self.max_buffer_size, 2], dtype=np.float32)
        self._recompute_tapers()
        self._ola_accum = None
        # Cold-start bias: default to filtering rather than passthrough, since
        # the app's purpose is blocking music — safer to briefly over-filter at
        # stream start than to leak music through before the first classification.
        self._filtering = True
        self._prev_filtering = True
        self._smoothed_ratio = self.music_threshold_on

    def _recompute_tapers(self):
        n = max(1, self.overlap)
        i = np.arange(n, dtype=np.float32)
        denom = max(n - 1, 1)
        fade_in = np.sin(0.5 * np.pi * i / denom) ** 2  # 0 -> 1
        fade_out = 1.0 - fade_in                         # 1 -> 0, complementary (sums to 1 pointwise)
        self._fade_in = fade_in.reshape(-1, 1)
        self._fade_out = fade_out.reshape(-1, 1)

    def _slice_block(self, arr):
        return arr[-self.block_size - self.back: -self.back if self.back > 0 else None, :]

    def _overlap_add_vocals(self, vocals_tensor):
        """Reconstruct this call's block_size output from a wider, tapered extraction
        window so consecutive blocks' independent model predictions blend smoothly at
        the seam, instead of being hard-spliced. Uses only already-buffered history
        (widens the window backward in time, not forward) so this adds no latency.
        """
        overlap = self.overlap
        extended_len = self.block_size + overlap
        start = -extended_len - self.back
        end = -self.back if self.back > 0 else None
        extended = vocals_tensor[:, start:end].cpu().numpy().T.astype(np.float32)  # (extended_len, ch)

        head = extended[:overlap] * self._fade_in
        middle = extended[overlap:self.block_size]
        tail = extended[self.block_size:] * self._fade_out

        if self._ola_accum is None:
            finalized_head = extended[:overlap]  # nothing to blend with yet (stream start)
        else:
            finalized_head = self._ola_accum + head

        self._ola_accum = tail
        return np.concatenate([finalized_head, middle], axis=0)

    def extract_vocals(self, chunk):
        # Update rolling buffer in place (avoids a full reallocation every call).
        n = chunk.shape[0]
        if n >= self.max_buffer_size:
            self.buffer[:] = chunk[-self.max_buffer_size:]
        else:
            self.buffer[:-n] = self.buffer[n:]
            self.buffer[-n:] = chunk

        x = torch.from_numpy(np.ascontiguousarray(self.buffer.T)).unsqueeze(0).to(self.device)

        with torch.inference_mode():
            s = time()
            out = self.model(x)
            self._sync_device()
            e = time()
            processing_ms = (e - s) * 1000
            block_ms = (self.block_size / self.sample_rate) * 1000

        # HDEMUCS_HIGH_MUSDB_PLUS stem order: drums, bass, other, vocals.
        vocals_block = self._overlap_add_vocals(out[0][3])
        # Slice each stem to the needed window on-device *before* summing, not
        # after — summing the full max_buffer_size-length tensors first would
        # do (and transfer) several times more work than necessary.
        accompaniment_start = -self.block_size - self.back
        accompaniment_end = -self.back if self.back > 0 else None
        accompaniment_slice = (
            out[0][0][:, accompaniment_start:accompaniment_end]
            + out[0][1][:, accompaniment_start:accompaniment_end]
            + out[0][2][:, accompaniment_start:accompaniment_end]
        )
        accompaniment_block = accompaniment_slice.cpu().numpy().T.astype(np.float32)
        # .copy(): _slice_block returns a view into self.buffer — must not alias
        # the buffer that future calls read for context.
        original_block = self._slice_block(self.buffer).copy()

        def rms(arr):
            return float(np.sqrt(np.mean(arr ** 2)))

        original_rms = rms(original_block)
        if original_rms < self.silence_rms:
            pass  # near-silence: ratio would be meaningless noise-floor division; hold current state
        else:
            accompaniment_rms = rms(accompaniment_block)
            vocals_rms = rms(vocals_block)
            ratio = accompaniment_rms / (accompaniment_rms + vocals_rms + 1e-8)  # bounded [0, 1]

            alpha = self.ema_alpha_attack if ratio > self._smoothed_ratio else self.ema_alpha_release
            self._smoothed_ratio = alpha * ratio + (1 - alpha) * self._smoothed_ratio

            if not self._filtering and self._smoothed_ratio > self.music_threshold_on:
                self._filtering = True
            elif self._filtering and self._smoothed_ratio < self.music_threshold_off:
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
