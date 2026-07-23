import numpy as np
from PyQt6.QtCore import pyqtSignal, QObject
import sounddevice as sd
from app.vocal_extractor import VocalExtractor


class AudioWorker(QObject):
    """PyQt adapter around VocalExtractor: wires it to a sounddevice Stream and Qt signals."""
    finished = pyqtSignal()
    log_signal = pyqtSignal(str)
    timing_signal = pyqtSignal(float, float)
    model_loaded = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.stream = None
        self.is_running = False

        self.extractor = VocalExtractor(
            sample_rate=44100,
            block_size=4048,
            max_buffer_size=16000,
            back=1024,
            log=self.log_signal.emit,
        )

        self.input_device_idx = None
        self.output_device_idx = None

    # Expose config as pass-through properties so app/main.py keeps working unchanged
    @property
    def block_size(self):
        return self.extractor.block_size

    @block_size.setter
    def block_size(self, value):
        self.extractor.block_size = value

    @property
    def max_buffer_size(self):
        return self.extractor.max_buffer_size

    @max_buffer_size.setter
    def max_buffer_size(self, value):
        self.extractor.max_buffer_size = value

    @property
    def back(self):
        return self.extractor.back

    @back.setter
    def back(self, value):
        self.extractor.back = value

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
            vocals, processing_ms, block_ms = self.extractor.extract_vocals(indata)
            self.timing_signal.emit(processing_ms, block_ms)
            if vocals.shape[0] < frames:
                pad = np.zeros((frames - vocals.shape[0], 2), dtype=np.float32)
                vocals = np.concatenate([vocals, pad], axis=0)
            else:
                vocals = vocals[:frames]
            outdata[:] = vocals
        except Exception as e:
            self.log_signal.emit(f"Audio callback Error: {e}")
            outdata[:] = np.zeros_like(indata)

    def start_stream(self):
        self.extractor.reset_buffer()
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

    def stop_stream(self):
        if self.stream:
            self.stream.stop()
            self.stream.close()
        self.is_running = False
        self.log_signal.emit("Stream stopped.")
