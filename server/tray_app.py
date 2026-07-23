"""GUI launcher for the MusicMute WebSocket server — no terminal needed.

Double-click (or `python -m server.tray_app`) to launch: shows a window with
adjustable quality/latency settings, a Start/Stop button, and logs, and
minimizes to a tray icon on close (same UX as the main MusicMute desktop app
in app/main.py).
"""
import asyncio
import logging
import os
import sys
import threading

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QAction, QDoubleValidator, QIcon, QIntValidator
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QPlainTextEdit, QSystemTrayIcon, QMenu,
)

from server import ws_server


class QtLogHandler(logging.Handler, QObject):
    message_logged = pyqtSignal(str)

    def __init__(self):
        logging.Handler.__init__(self)
        QObject.__init__(self)

    def emit(self, record):
        self.message_logged.emit(self.format(record))


class MainWindow(QMainWindow):
    model_ready = pyqtSignal()
    # status label text, button text, whether config fields should be editable
    status_changed = pyqtSignal(str, str, bool)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("MusicMute Server")
        self.resize(480, 420)

        self.server = None  # websockets server handle, set while running

        self.init_ui()
        self.setup_tray()

        handler = QtLogHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))
        handler.message_logged.connect(self.log_to_console)
        logging.getLogger().addHandler(handler)
        logging.getLogger().setLevel(logging.INFO)

        self.model_ready.connect(self.on_model_ready)
        self.status_changed.connect(self.on_status_changed)

        # A single persistent event loop, run forever in a background thread.
        # The model loads once at launch; Start/Stop only toggles the listener.
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        asyncio.run_coroutine_threadsafe(self._load_model(), self.loop)

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        layout.addWidget(QLabel(f"<b>Listening on:</b> ws://{ws_server.HOST}:{ws_server.PORT}"))

        self.lbl_status = QLabel("Loading model...")
        layout.addWidget(self.lbl_status)

        # Quality/latency knobs — was "edit ws_server.py and rebuild the app"
        # for every tweak; now these are just fields, applied on Start.
        row1 = QHBoxLayout()
        self.edit_block = self._int_field("Block Size", ws_server.BLOCK_SIZE, row1)
        self.edit_buf = self._int_field("Max Buffer", ws_server.MAX_BUFFER_SIZE, row1)
        self.edit_back = self._int_field("Back Offset", ws_server.BACK, row1)
        self.edit_overlap = self._int_field("Overlap", ws_server.OVERLAP, row1)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        self.edit_threshold_on = self._float_field(
            "Music Threshold On", ws_server.MUSIC_THRESHOLD_ON, row2)
        self.edit_threshold_off = self._float_field(
            "Music Threshold Off", ws_server.MUSIC_THRESHOLD_OFF, row2)
        layout.addLayout(row2)

        self.config_fields = [
            self.edit_block, self.edit_buf, self.edit_back, self.edit_overlap,
            self.edit_threshold_on, self.edit_threshold_off,
        ]

        self.btn_toggle = QPushButton("Start Server")
        self.btn_toggle.setEnabled(False)
        self.btn_toggle.clicked.connect(self.on_toggle_clicked)
        self.btn_toggle.setStyleSheet("background-color: #808080; color: white; font-weight: bold; padding: 10px;")
        layout.addWidget(self.btn_toggle)

        self.btn_logs = QPushButton("Show/Hide Logs")
        self.btn_logs.clicked.connect(self.toggle_logs)
        layout.addWidget(self.btn_logs)

        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setVisible(False)
        layout.addWidget(self.console)

    def _int_field(self, label_text, default_val, parent_layout):
        v_layout = QVBoxLayout()
        v_layout.addWidget(QLabel(label_text))
        line_edit = QLineEdit(str(default_val))
        line_edit.setProperty("default_value", str(default_val))
        line_edit.setValidator(QIntValidator(0, 1000000))
        v_layout.addWidget(line_edit)
        parent_layout.addLayout(v_layout)
        return line_edit

    def _float_field(self, label_text, default_val, parent_layout):
        v_layout = QVBoxLayout()
        v_layout.addWidget(QLabel(label_text))
        line_edit = QLineEdit(str(default_val))
        line_edit.setProperty("default_value", str(default_val))
        line_edit.setValidator(QDoubleValidator(0.0, 1.0, 3))
        v_layout.addWidget(line_edit)
        parent_layout.addLayout(v_layout)
        return line_edit

    def _field_value(self, line_edit, cast):
        """The validators permit an empty string as a valid intermediate state —
        cast("") raises. Fall back to the field's own default instead of crashing."""
        text = line_edit.text()
        if not text:
            default_val = line_edit.property("default_value")
            line_edit.setText(default_val)
            return cast(default_val)
        return cast(text)

    def toggle_logs(self):
        self.console.setVisible(not self.console.isVisible())

    def log_to_console(self, text):
        self.console.appendPlainText(text)

    # ----- Server lifecycle -----

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    async def _load_model(self):
        await self.loop.run_in_executor(None, ws_server.extractor.load_model)
        self.model_ready.emit()

    def on_model_ready(self):
        # Runs on the Qt main thread via the signal/slot queued connection.
        self.btn_toggle.setEnabled(True)
        self.btn_toggle.setStyleSheet("background-color: #2ecc71; color: white; font-weight: bold; padding: 10px;")
        self.lbl_status.setText("Model loaded — stopped")

    def on_toggle_clicked(self):
        if self.server is None:
            # Read fields here, on the Qt thread — QLineEdit isn't safe to touch
            # from the asyncio thread the coroutine below runs on.
            try:
                block_size = self._field_value(self.edit_block, int)
                max_buffer_size = self._field_value(self.edit_buf, int)
                back = self._field_value(self.edit_back, int)
                overlap = self._field_value(self.edit_overlap, int)
                threshold_on = self._field_value(self.edit_threshold_on, float)
                threshold_off = self._field_value(self.edit_threshold_off, float)
            except ValueError as e:
                self.log_to_console(f"Config Error: {e}")
                return
            asyncio.run_coroutine_threadsafe(
                self._start(block_size, max_buffer_size, back, overlap, threshold_on, threshold_off),
                self.loop,
            )
        else:
            asyncio.run_coroutine_threadsafe(self._stop(), self.loop)

    async def _start(self, block_size, max_buffer_size, back, overlap, threshold_on, threshold_off):
        extractor = ws_server.extractor
        extractor.block_size = block_size
        extractor.max_buffer_size = max_buffer_size
        extractor.back = back
        extractor.overlap = overlap
        extractor.music_threshold_on = threshold_on
        extractor.music_threshold_off = threshold_off
        try:
            extractor.reset_buffer()  # also validates block_size+back+overlap <= max_buffer_size
        except ValueError as e:
            self.status_changed.emit(f"Config Error: {e}", "Start Server", True)
            return

        self.server = await ws_server.start_server()
        self.status_changed.emit("Running", "Stop Server", False)

    async def _stop(self):
        await ws_server.stop_server(self.server)
        self.server = None
        self.status_changed.emit("Model loaded — stopped", "Start Server", True)

    def on_status_changed(self, status_text, button_text, fields_enabled):
        # Runs on the Qt main thread via the signal/slot queued connection.
        self.lbl_status.setText(status_text)
        self.btn_toggle.setText(button_text)
        for field in self.config_fields:
            field.setEnabled(fields_enabled)
        running = button_text == "Stop Server"
        color = "#e74c3c" if running else "#2ecc71"
        self.btn_toggle.setStyleSheet(f"background-color: {color}; color: white; font-weight: bold; padding: 10px;")

    # ----- Tray -----

    def setup_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        icon_path = self.resource_path("assets/icon.png")
        if os.path.exists(icon_path):
            self.tray_icon.setIcon(QIcon(icon_path))
        else:
            print(f"Warning: tray icon not found at {icon_path}")

        tray_menu = QMenu()
        show_action = QAction("Show Window", self)
        show_action.triggered.connect(self.showNormal)

        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self.quit)

        tray_menu.addAction(show_action)
        tray_menu.addSeparator()
        tray_menu.addAction(quit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()
        self.tray_icon.activated.connect(self.on_tray_icon_activated)

    def on_tray_icon_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.isVisible():
                self.hide()
            else:
                self.showNormal()

    def closeEvent(self, event):
        """Override close to minimize to tray."""
        if self.tray_icon.isVisible():
            self.hide()
            event.ignore()

    def quit(self):
        # Daemon thread + hard exit is fine here: single-user local dev tool,
        # no persistent state to flush on shutdown.
        os._exit(0)

    def resource_path(self, relative_path):
        try:
            base_path = sys._MEIPASS
        except Exception:
            base_path = os.path.abspath(".")
        return os.path.join(base_path, relative_path)


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
