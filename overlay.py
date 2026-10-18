import sys
import ctypes
import hashlib
import json
import logging
import os
from pathlib import Path
import tempfile
import time
import warnings
from ctypes import wintypes
import psutil
import pynvml
warnings.filterwarnings("ignore")

SETTINGS_PATH = Path(__file__).with_name("settings.json")
LOG_PATH = Path(__file__).with_name("overlay.log")
logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    encoding="utf-8",
)
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSystemTrayIcon, QMenu, QFrame, QProgressBar, QGraphicsDropShadowEffect, QSizePolicy
from PyQt6.QtCore import Qt, QTimer, QPoint
from PyQt6.QtGui import QFont, QColor, QPainter, QBrush, QPen, QIcon, QPixmap, QAction, QLinearGradient

GWL_EXSTYLE       = -20
WS_EX_LAYERED     = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
ERROR_ALREADY_EXISTS = 183
GA_ROOT = 2
POSITION_MERGE_TOLERANCE = 4

user32 = ctypes.windll.user32
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
user32.GetAncestor.restype = wintypes.HWND
user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
user32.GetWindowRect.restype = wintypes.BOOL
user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
user32.GetClassNameW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
user32.GetWindowTextW.restype = ctypes.c_int
kernel32 = ctypes.windll.kernel32
kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = (
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
)
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
kernel32.CloseHandle.restype = wintypes.BOOL
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def acquire_single_instance_lock():
    kernel32 = ctypes.windll.kernel32
    kernel32.SetLastError(0)
    handle = kernel32.CreateMutexW(None, False, "Local\\WnoutOverlaySingleton")
    if not handle:
        return None
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return None
    return handle

def set_clickthrough(hwnd, enabled):
    style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    style |= WS_EX_LAYERED
    if enabled:
        style |= WS_EX_TRANSPARENT
    else:
        style &= ~WS_EX_TRANSPARENT
    ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)


def build_tray_icon():
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(24, 24, 24))
    painter.setPen(QPen(QColor(80, 80, 80), 2))
    painter.drawRoundedRect(3, 3, 58, 58, 14, 14)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(76, 255, 145))
    painter.drawRoundedRect(14, 34, 8, 16, 3, 3)
    painter.setBrush(QColor(76, 168, 255))
    painter.drawRoundedRect(28, 24, 8, 26, 3, 3)
    painter.setBrush(QColor(255, 153, 68))
    painter.drawRoundedRect(42, 16, 8, 34, 3, 3)
    painter.end()

    return QIcon(pixmap)

class Overlay(QWidget):
    def __init__(self):
        super().__init__()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._move_enabled = False
        self._drag_offset = None
        self._settings = self.load_settings()
        self._active_window = None
        self._active_window_key = None
        self._active_application_key = None
        self._active_window_rect = None
        self._window_identity_cache = None
        self._move_target_hwnd = None
        self._move_target_window_key = None
        self._move_target_application_key = None
        self._move_target_rect = None
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowOpacity(1.0)
        self.setFixedWidth(230)

        try:
            pynvml.nvmlInit()
            self._gpu_handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            self._gpu_ok = True
        except Exception:
            self._gpu_ok = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(19, 20, 19, 20)
        layout.setSpacing(0)

        font_val = QFont("Segoe UI", 10, QFont.Weight.DemiBold)
        font_label = QFont("Segoe UI", 9, QFont.Weight.Medium)

        self.rows = []
        self.meters = []
        for index, name in enumerate(("CPU", "RAM", "GPU", "VRAM", "NET ↓", "NET ↑", "UPTIME")):
            lbl = QLabel(name)
            lbl.setFont(font_label)
            lbl.setStyleSheet("color: #e3f0fc;")
            lbl.setFixedWidth(46)

            val = QLabel("—")
            val.setFont(font_val)
            val.setStyleSheet("color: #43e5ee;")
            val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            val.setFixedWidth(72)
            value_glow = QGraphicsDropShadowEffect(val)
            value_glow.setBlurRadius(6)
            value_glow.setColor(QColor(36, 218, 247, 120))
            value_glow.setOffset(0, 0)
            val.setGraphicsEffect(value_glow)

            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.setSpacing(3)
            rl.addWidget(lbl)
            if index < 6:
                meter = QProgressBar()
                meter.setRange(0, 100)
                meter.setTextVisible(False)
                meter.setMinimumWidth(0)
                meter.setFixedHeight(5)
                meter.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
                meter.setStyleSheet(
                    "QProgressBar { background-color: #0b2943; border: 1px solid #123d5d; border-radius: 4px; }"
                    "QProgressBar::chunk { background-color: #32e2ef; border: none; border-radius: 4px; }"
                )
                meter_glow = QGraphicsDropShadowEffect(meter)
                meter_glow.setBlurRadius(5)
                meter_glow.setColor(QColor(35, 216, 242, 95))
                meter_glow.setOffset(0, 0)
                meter.setGraphicsEffect(meter_glow)
                rl.addWidget(meter, 1)
                self.meters.append(meter)
            else:
                rl.addStretch(1)
            rl.addWidget(val)
            row.setStyleSheet("background: transparent;")
            row.setFixedHeight(30)

            layout.addWidget(row)
            self.rows.append(val)
            if index < 6:
                separator = QFrame()
                separator.setFixedHeight(1)
                separator.setStyleSheet("background-color: rgba(35, 126, 184, 145); border: none;")
                layout.addWidget(separator)
        net = psutil.net_io_counters()
        self._prev_recv = net.bytes_recv
        self._prev_sent = net.bytes_sent

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_stats)
        self.timer.start(1000)

        self.window_timer = QTimer(self)
        self.window_timer.timeout.connect(self.follow_active_window)
        self.window_timer.start(250)

        self.update_stats()

        screen = QApplication.primaryScreen().geometry()
        default_position = QPoint(screen.width() - self.width() - 20, 20)
        self.move(self._settings.get("x", default_position.x()), self._settings.get("y", default_position.y()))

        self.tray_icon = QSystemTrayIcon(build_tray_icon(), self)
        self.tray_icon.setToolTip("Overlay monitor")

        tray_menu = QMenu()
        visibility_action = QAction("Показывать оверлей", self)
        visibility_action.setCheckable(True)
        visibility_action.setChecked(True)
        visibility_action.toggled.connect(self.setVisible)
        tray_menu.addAction(visibility_action)

        self.move_action = QAction("Переместить оверлей", self)
        self.move_action.setCheckable(True)
        self.move_action.toggled.connect(self.set_move_enabled)
        tray_menu.addAction(self.move_action)
        tray_menu.addSeparator()
        quit_action = QAction("Выход", self)
        quit_action.triggered.connect(QApplication.instance().quit)
        tray_menu.addAction(quit_action)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()

    def showEvent(self, event):
        super().showEvent(event)
        set_clickthrough(int(self.winId()), not self._move_enabled)

    def set_move_enabled(self, enabled):
        if enabled:
            if self._active_window is None or not self._active_window_key:
                self.follow_active_window()
            self._move_target_hwnd = self._active_window
            self._move_target_window_key = self._active_window_key
            self._move_target_application_key = self._active_application_key
            self._move_target_rect = self._get_window_rect(self._active_window) or self._active_window_rect
            self._move_enabled = True
            set_clickthrough(int(self.winId()), False)
            self.activateWindow()
            self.setFocus()
        else:
            self._move_enabled = False
            set_clickthrough(int(self.winId()), True)
            if self.move_action.isChecked():
                self.move_action.blockSignals(True)
                self.move_action.setChecked(False)
                self.move_action.blockSignals(False)
            self.save_position()
            self._move_target_hwnd = None
            self._move_target_window_key = None
            self._move_target_application_key = None
            self._move_target_rect = None

    def load_settings(self):
        try:
            if SETTINGS_PATH.exists():
                with SETTINGS_PATH.open("r", encoding="utf-8") as file:
                    settings = json.load(file)
                if isinstance(settings, dict) and isinstance(settings.get("x"), int) and isinstance(settings.get("y"), int):
                    return settings
        except Exception:
            logging.exception("Не удалось загрузить настройки")
        return {}

    def save_position(self):
        try:
            settings = dict(self._settings)
            settings["x"] = self.x()
            settings["y"] = self.y()
            window_key = self._move_target_window_key or self._active_window_key
            application_key = self._move_target_application_key or self._active_application_key
            window_rect = self._move_target_rect or self._active_window_rect
            if window_key and window_rect:
                positions = settings.get("window_positions")
                positions = dict(positions) if isinstance(positions, dict) else {}
                offset = {
                    "x": self.x() - window_rect.left,
                    "y": self.y() - window_rect.top,
                }
                positions[window_key] = offset
                settings["window_positions"] = positions
                if application_key:
                    app_positions = settings.get("application_positions")
                    app_positions = dict(app_positions) if isinstance(app_positions, dict) else {}
                    app_positions[application_key] = offset
                    settings["application_positions"] = app_positions
            temporary_path = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    dir=SETTINGS_PATH.parent,
                    prefix=f"{SETTINGS_PATH.name}.",
                    suffix=".tmp",
                    delete=False,
                ) as file:
                    temporary_path = Path(file.name)
                    json.dump(settings, file, ensure_ascii=False, indent=2)
                os.replace(temporary_path, SETTINGS_PATH)
                self._settings = settings
            finally:
                if temporary_path is not None and temporary_path.exists():
                    temporary_path.unlink()
        except Exception:
            logging.exception("Не удалось сохранить позицию оверлея")

    def _window_identities(self, hwnd):
        """Return exact-window and application identities across restarts."""
        pid = wintypes.DWORD()
        if not user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)) or not pid.value:
            return None

        class_buffer = ctypes.create_unicode_buffer(256)
        title_buffer = ctypes.create_unicode_buffer(1024)
        user32.GetClassNameW(hwnd, class_buffer, len(class_buffer))
        user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))
        signature = (int(hwnd), pid.value, class_buffer.value, title_buffer.value)
        cached = self._window_identity_cache
        if cached and cached[0] == signature:
            return cached[1]

        process = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not process:
            return None
        try:
            path_buffer = ctypes.create_unicode_buffer(32768)
            path_length = wintypes.DWORD(len(path_buffer))
            if not kernel32.QueryFullProcessImageNameW(process, 0, path_buffer, ctypes.byref(path_length)):
                return None
            app_identity = "\0".join((path_buffer.value.casefold(), class_buffer.value))
            window_identity = "\0".join((app_identity, title_buffer.value))
            identities = (
                hashlib.sha256(window_identity.encode("utf-8", errors="replace")).hexdigest(),
                hashlib.sha256(app_identity.encode("utf-8", errors="replace")).hexdigest(),
            )
            self._window_identity_cache = (signature, identities)
            return identities
        finally:
            kernel32.CloseHandle(process)

    def _get_window_rect(self, hwnd):
        rect = wintypes.RECT()
        if not hwnd or not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
        return rect

    def follow_active_window(self):
        if self._move_enabled:
            rect = self._get_window_rect(self._move_target_hwnd)
            if rect:
                self._move_target_rect = rect
            return

        overlay_hwnd = int(self.winId())
        foreground = user32.GetForegroundWindow()
        if foreground and int(foreground) != overlay_hwnd:
            root = user32.GetAncestor(foreground, GA_ROOT) or foreground
            overlay_pid = wintypes.DWORD()
            root_pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(overlay_hwnd, ctypes.byref(overlay_pid))
            user32.GetWindowThreadProcessId(root, ctypes.byref(root_pid))
            if int(root) != overlay_hwnd and root_pid.value != overlay_pid.value:
                rect = self._get_window_rect(root)
                identities = self._window_identities(root) if rect else None
                if identities:
                    self._active_window = root
                    self._active_window_key, self._active_application_key = identities
                    self._active_window_rect = rect

        if not self._active_window_key or not self._active_window_rect:
            return

        rect = self._get_window_rect(self._active_window)
        if not rect:
            return

        if self._active_window_key != getattr(self, "_positioned_window_key", None):
            positions = self._settings.get("window_positions", {})
            saved = positions.get(self._active_window_key) if isinstance(positions, dict) else None
            if not (isinstance(saved, dict) and isinstance(saved.get("x"), int) and isinstance(saved.get("y"), int)):
                app_positions = self._settings.get("application_positions", {})
                saved = app_positions.get(self._active_application_key) if isinstance(app_positions, dict) else None
            if isinstance(saved, dict) and isinstance(saved.get("x"), int) and isinstance(saved.get("y"), int):
                x, y = rect.left + saved["x"], rect.top + saved["y"]
            else:
                x, y = self.x(), self.y()
            if (abs(x - self.x()) <= POSITION_MERGE_TOLERANCE and
                    abs(y - self.y()) <= POSITION_MERGE_TOLERANCE):
                x, y = self.x(), self.y()
            self.move(x, y)
            self._positioned_window_key = self._active_window_key
        elif rect.left != self._active_window_rect.left or rect.top != self._active_window_rect.top:
            self.move(self.x() + rect.left - self._active_window_rect.left,
                      self.y() + rect.top - self._active_window_rect.top)

        self._active_window_rect = rect

    def mousePressEvent(self, event):
        if self._move_enabled and event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._move_enabled and self._drag_offset is not None:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = None
            if self._move_enabled:
                self.save_position()
        super().mouseReleaseEvent(event)

    def focusOutEvent(self, event):
        if self._move_enabled:
            self.set_move_enabled(False)
        super().focusOutEvent(event)

    def closeEvent(self, event):
        self.save_position()
        if self._gpu_ok:
            try:
                pynvml.nvmlShutdown()
            except Exception:
                logging.exception("Не удалось завершить NVML")
        super().closeEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        panel = self.rect().adjusted(5, 5, -6, -6)
        for width, alpha in ((10, 14), (6, 28), (3, 48)):
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(35, 196, 245, alpha), width))
            painter.drawRoundedRect(panel, 14, 14)

        gradient = QLinearGradient(0.0, 0.0, float(self.width()), float(self.height()))
        gradient.setColorAt(0, QColor(10, 39, 67, 195))
        gradient.setColorAt(0.52, QColor(5, 21, 40, 180))
        gradient.setColorAt(1, QColor(8, 30, 53, 195))
        painter.setBrush(QBrush(gradient))
        border = QLinearGradient(0.0, 0.0, float(self.width()), float(self.height()))
        border.setColorAt(0, QColor(61, 232, 255, 255))
        border.setColorAt(0.5, QColor(25, 127, 225, 255))
        border.setColorAt(1, QColor(56, 218, 255, 255))
        painter.setPen(QPen(QBrush(border), 2))
        painter.drawRoundedRect(panel, 14, 14)

        inner = panel.adjusted(8, 8, -8, -8)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(57, 177, 222, 85), 1))
        painter.drawRoundedRect(inner, 11, 11)

    def update_stats(self):
        cpu = psutil.cpu_percent(interval=None)
        ram = psutil.virtual_memory()
        net = psutil.net_io_counters()

        recv_speed = max(0, net.bytes_recv - self._prev_recv)
        sent_speed = max(0, net.bytes_sent - self._prev_sent)
        self._prev_recv = net.bytes_recv
        self._prev_sent = net.bytes_sent

        def fmt_bytes(b):
            if b < 1024:      return f"{b} B/s"
            elif b < 1024**2: return f"{b/1024:.0f} KB/s"
            else:             return f"{b/1024**2:.1f} MB/s"

        self.rows[0].setText(f"{cpu:.0f}%")
        self._set_meter(0, cpu)

        self.rows[1].setText(f"{ram.percent:.0f}%")
        self._set_meter(1, ram.percent)

        if self._gpu_ok:
            try:
                util = pynvml.nvmlDeviceGetUtilizationRates(self._gpu_handle)
                mem  = pynvml.nvmlDeviceGetMemoryInfo(self._gpu_handle)
                vram_pct = mem.used / mem.total * 100

                self.rows[2].setText(f"{util.gpu:.0f}%")
                self._set_meter(2, util.gpu)

                self.rows[3].setText(f"{vram_pct:.0f}%")
                self._set_meter(3, vram_pct)
            except Exception:
                self.rows[2].setText("—")
                self.rows[3].setText("—")
                self._set_meter(2, 0)
                self._set_meter(3, 0)
        else:
            self.rows[2].setText("N/A")
            self.rows[3].setText("N/A")
            self._set_meter(2, 0)
            self._set_meter(3, 0)

        self.rows[4].setText(fmt_bytes(recv_speed))
        self._set_meter(4, min(100, max(2 if recv_speed else 0, round(recv_speed / (25 * 1024**2) * 100))))

        self.rows[5].setText(fmt_bytes(sent_speed))
        self._set_meter(5, min(100, max(2 if sent_speed else 0, round(sent_speed / (384 * 1024) * 100))))

        uptime = max(0, int(time.time() - psutil.boot_time()))
        hours, remainder = divmod(uptime, 3600)
        minutes, seconds = divmod(remainder, 60)
        self.rows[6].setText(f"{hours:02d}:{minutes:02d}:{seconds:02d}")

    @staticmethod
    def _load_color(value):
        if value <= 60:
            return "#4cff91"
        if value <= 85:
            return "#ffd166"
        return "#ff5c6c"

    def _set_meter(self, index, value):
        value = min(100, max(0, round(value)))
        color = self._load_color(value)
        self.meters[index].setValue(value)
        self.meters[index].setStyleSheet(
            "QProgressBar { background-color: #0b2943; border: 1px solid #123d5d; border-radius: 4px; }"
            f"QProgressBar::chunk {{ background-color: {color}; border: none; border-radius: 4px; }}"
        )
        if index < 4:
            self.rows[index].setStyleSheet(f"color: {color};")
            glow = self.rows[index].graphicsEffect()
            if glow:
                glow.setColor(QColor(color))
        glow = self.meters[index].graphicsEffect()
        if glow:
            glow.setColor(QColor(color))


if __name__ == "__main__":
    _instance_lock = acquire_single_instance_lock()
    if _instance_lock is None:
        sys.exit(0)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    w = Overlay()
    w.show()
    sys.exit(app.exec())
