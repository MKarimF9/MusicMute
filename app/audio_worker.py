from time import monotonic

import numpy as np
from PyQt6.QtCore import pyqtSignal, pyqtSlot, QObject
import sounddevice as sd
from app.vocal_extractor import VocalExtractor

TIMING_SIGNAL_MIN_INTERVAL_S = 1 / 3  # throttle: each cross-thread queued emit allocates


class AudioWorker(QObject):
    """PyQt adapter around VocalExtractor: wires it to a sounddevice Stream and Qt signals.

    Lives on its own QThread (see app/main.py). All entry points below are pyqtSlots so
    callers on the GUI thread must invoke them via signals (queued cross-thread delivery),
    never by calling them or assigning worker attributes directly — see F1 in docs/CHANGES.md.
    """
    log_signal = pyqtSignal(str)
    timing_signal = pyqtSignal(float, float)
    model_loaded = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.stream = None
        self.is_running = False
        self._last_timing_emit = 0.0

        self.extractor = VocalExtractor(
            sample_rate=44100,
            block_size=4096,
            max_buffer_size=16000,
            back=1024,
            log=self.log_signal.emit,
        )

        self.input_device_idx = None
        self.output_device_idx = None

    @property
    def device(self):
        return self.extractor.device

    def load_model(self):
        self.extractor.load_model()
        self.model_loaded.emit()

    def audio_callback(self, indata, outdata, frames, time_info, status):
        if status:
            self.log_signal.emit(f"Status Error: {status}")
        try:
            vocals, processing_ms, block_ms, _is_filtering = self.extractor.extract_vocals(indata)

            now = monotonic()
            if now - self._last_timing_emit >= TIMING_SIGNAL_MIN_INTERVAL_S:
                self.timing_signal.emit(processing_ms, block_ms)
                self._last_timing_emit = now

            if vocals.shape[0] != frames:
                # Should never happen with a correctly-configured stream (blocksize
                # fixed) — surface it instead of silently padding/truncating over a bug.
                self.log_signal.emit(
                    f"Warning: vocals block length {vocals.shape[0]} != frames {frames}"
                )
                if vocals.shape[0] < frames:
                    pad = np.zeros((frames - vocals.shape[0], 2), dtype=np.float32)
                    vocals = np.concatenate([vocals, pad], axis=0)
                else:
                    vocals = vocals[:frames]
            outdata[:] = vocals
        except Exception as e:
            self.log_signal.emit(f"Audio callback Error: {e}")
            outdata[:] = np.zeros_like(indata)

    @pyqtSlot(int, int, int, int, int)
    def start_stream(self, block_size, max_buffer_size, back, input_device_idx, output_device_idx):
        self.extractor.block_size = block_size
        self.extractor.max_buffer_size = max_buffer_size
        self.extractor.back = back
        self.input_device_idx = input_device_idx
        self.output_device_idx = output_device_idx

        try:
            self.extractor.reset_buffer()  # also validates block_size+back+overlap <= max_buffer_size
        except ValueError as e:
            self.log_signal.emit(f"Config Error: {e}")
            return

        try:
            self.stream = sd.Stream(
                device=(self.input_device_idx, self.output_device_idx),
                samplerate=self.extractor.sample_rate,
                channels=2,
                dtype="float32",
                blocksize=self.extractor.block_size,
                callback=self.audio_callback
            )
            self.stream.start()
            self.is_running = True
            self.log_signal.emit("Stream started.")
        except Exception as e:
            self.log_signal.emit(f"Start Error: {e}")

    @pyqtSlot()
    def stop_stream(self):
        if self.stream:
            self.stream.stop()
            self.stream.close()
        self.is_running = False
        self.log_signal.emit("Stream stopped.")
