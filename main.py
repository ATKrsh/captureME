import sys
import os
import time
import math
import json
import threading

IS_WIN = sys.platform == 'win32'
IS_MAC = sys.platform == 'darwin'
IS_LINUX = sys.platform.startswith('linux')

if IS_WIN:
    try:
        import winreg
        import ctypes
    except ImportError:
        winreg = None
        ctypes = None
else:
    winreg = None
    ctypes = None

from PyQt5.QtWidgets import (
    QApplication, QWidget, QSystemTrayIcon, QMenu, QAction, QActionGroup,
    QVBoxLayout, QHBoxLayout, QSlider, QWidgetAction, QLabel
)
from PyQt5.QtCore import (
    Qt, QPoint, QRectF, QTimer, pyqtSignal, QObject, QEvent
)
from PyQt5.QtGui import (
    QPainter, QColor, QPen, QBrush, QIcon, QPixmap, QCursor, QRadialGradient
)

import mss
import mss.tools
import cv2
import numpy as np

# Startup configuration path
REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "captureME"

# Target user's standard Pictures directory for persistent saves
PICTURES_DIR = os.path.join(os.path.expanduser("~"), "Pictures")
if IS_WIN:
    APP_DATA_DIR = os.path.join(os.getenv('APPDATA', os.path.expanduser('~')), "captureME")
elif IS_MAC:
    APP_DATA_DIR = os.path.join(os.path.expanduser('~'), "Library", "Application Support", "captureME")
else:
    APP_DATA_DIR = os.path.join(os.path.expanduser('~'), ".config", "captureME")

os.makedirs(APP_DATA_DIR, exist_ok=True)
CONFIG_FILE = os.path.join(APP_DATA_DIR, "config.json")
CAPTURES_DIR = os.path.join(PICTURES_DIR, "captureME")
os.makedirs(CAPTURES_DIR, exist_ok=True)
os.makedirs(os.path.join(CAPTURES_DIR, "Screenshots"), exist_ok=True)
os.makedirs(os.path.join(CAPTURES_DIR, "Recordings"), exist_ok=True)

DEFAULT_CONFIG = {
    "opacity": 0.9,
    "glow_opacity": 0.9,
    "glow_size_pct": 50,
    "hue": 190,
    "glow_enabled": True,
    "size": "Medium",
    "size_percent": 50,
    "always_on_top": True,
    "lock_position": False,
    "clickthrough": False,
    "start_with_windows": False,
    "breathing": True,
    "pos_x": 100,
    "pos_y": 100
}

SIZES = {
    "Small": 60,
    "Medium": 80,
    "Large": 100
}

def load_config():
    cfg = DEFAULT_CONFIG.copy()
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                data = json.load(f)
                cfg.update(data)
        except Exception:
            pass

    sz_pct = cfg.get("size_percent", 50)
    SIZES["Custom"] = int(40 + (120 * (sz_pct / 100.0)))

    # Sanitize screen coordinates so widget is never lost off-screen
    try:
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(sys.argv)
        screen = app.primaryScreen()
        if screen:
            screen_geo = screen.availableGeometry()
            if cfg["pos_x"] < 0 or cfg["pos_x"] > screen_geo.width() - 100:
                cfg["pos_x"] = max(100, screen_geo.width() - 300)
            if cfg["pos_y"] < 0 or cfg["pos_y"] > screen_geo.height() - 100:
                cfg["pos_y"] = max(100, screen_geo.height() - 300)
    except Exception:
        cfg["pos_x"] = 200
        cfg["pos_y"] = 200

    if cfg.get("opacity", 0.9) < 0.3:
        cfg["opacity"] = 0.95

    return cfg

def save_config(cfg):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass

def get_launch_agent_plist():
    exe_path = sys.executable
    if getattr(sys, 'frozen', False):
        exe_path = os.path.abspath(sys.argv[0])
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.captureme.app</string>
    <key>ProgramArguments</key>
    <array>
        <string>{exe_path}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>"""
    return plist

def set_startup(enable):
    if IS_WIN and winreg:
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_ALL_ACCESS)
            if enable:
                exe_path = f'"{sys.executable}"'
                if getattr(sys, 'frozen', False):
                    exe_path = f'"{os.path.abspath(sys.argv[0])}"'
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, exe_path)
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                except FileNotFoundError:
                    pass
            winreg.CloseKey(key)
        except Exception as e:
            print("Registry error:", e)
    elif IS_MAC:
        try:
            launch_agents_dir = os.path.expanduser("~/Library/LaunchAgents")
            os.makedirs(launch_agents_dir, exist_ok=True)
            plist_path = os.path.join(launch_agents_dir, "com.captureme.app.plist")
            if enable:
                with open(plist_path, "w") as f:
                    f.write(get_launch_agent_plist())
            else:
                if os.path.exists(plist_path):
                    os.remove(plist_path)
        except Exception as e:
            print("macOS launch agent error:", e)

def check_startup():
    if IS_WIN and winreg:
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_READ)
            winreg.QueryValueEx(key, APP_NAME)
            winreg.CloseKey(key)
            return True
        except Exception:
            return False
    elif IS_MAC:
        plist_path = os.path.expanduser("~/Library/LaunchAgents/com.captureme.app.plist")
        return os.path.exists(plist_path)
    return False


class VideoRecorder(QObject):
    recording_finished = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._is_recording = False
        self._thread = None
        self.output_filepath = ""

    def start_recording(self):
        if self._is_recording:
            return
        self._is_recording = True
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        self.output_filepath = os.path.join(CAPTURES_DIR, "Recordings", f"recording_{timestamp}.mp4")
        self._thread = threading.Thread(target=self._record_loop, daemon=True)
        self._thread.start()

    def stop_recording(self):
        if not self._is_recording:
            return
        self._is_recording = False
        if self._thread:
            self._thread.join(timeout=3.0)

    def _record_loop(self):
        try:
            with mss.mss() as sct:
                monitor = sct.monitors[0]
                width = monitor["width"]
                height = monitor["height"]
                
                width = width if width % 2 == 0 else width - 1
                height = height if height % 2 == 0 else height - 1

                fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                fps = 20.0
                out = cv2.VideoWriter(self.output_filepath, fourcc, fps, (width, height))

                while self._is_recording:
                    t0 = time.time()
                    sct_img = sct.grab({"top": monitor["top"], "left": monitor["left"], "width": width, "height": height})
                    frame = np.array(sct_img)
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
                    out.write(frame)
                    
                    elapsed = time.time() - t0
                    sleep_time = max(0.001, (1.0 / fps) - elapsed)
                    time.sleep(sleep_time)

                out.release()
                self.recording_finished.emit(self.output_filepath)
        except Exception as e:
            print("Recording error:", e)


import sounddevice as sd

class AudioMonitor(QObject):
    def __init__(self):
        super().__init__()
        self._running = False
        self._thread = None
        self.current_volume = 0.0      # RMS Volume Amplitude -> BG Glow Intensity
        self.current_frequency = 0.0   # Dominant Frequency (Hz) -> BG Glow Radius / Size

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._audio_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _audio_loop(self):
        sr = 44100
        blocksize = 256

        def process_signal(signal):
            # 1. Instantaneous RMS Volume Amplitude calculation
            rms = np.sqrt(np.mean(signal**2))
            target_vol = min(1.0, float(rms * 12.0))
            # Fast attack, snappy release
            if target_vol > self.current_volume:
                self.current_volume = target_vol
            else:
                self.current_volume += (target_vol - self.current_volume) * 0.45

            # 2. FFT Spectral Analysis for Dominant Frequency
            fft_data = np.abs(np.fft.rfft(signal * np.hanning(len(signal))))
            freqs = np.fft.rfftfreq(len(signal), 1.0 / sr)
            
            valid_idx = np.where(freqs >= 40.0)[0]
            if len(valid_idx) > 0 and np.max(fft_data[valid_idx]) > 0.0002:
                peak_idx = valid_idx[np.argmax(fft_data[valid_idx])]
                dom_freq = freqs[peak_idx]
                norm_freq = min(1.0, max(0.0, (dom_freq - 50.0) / 3950.0))
            else:
                norm_freq = 0.0

            if norm_freq > self.current_frequency:
                self.current_frequency = norm_freq
            else:
                self.current_frequency += (norm_freq - self.current_frequency) * 0.40

        # Primary Approach: Native WASAPI Desktop Loopback via soundcard
        try:
            import soundcard as sc
            default_spk = sc.default_speaker()
            loopback_mic = sc.get_microphone(id=str(default_spk.name), include_loopback=True)
            with loopback_mic.recorder(samplerate=sr, blocksize=blocksize) as recorder:
                while self._running:
                    data = recorder.record(numframes=blocksize)
                    signal = data[:, 0] if data.ndim > 1 else data
                    process_signal(signal)
            return
        except Exception as err:
            with open(os.path.join(os.path.expanduser("~"), "captureME_error.log"), "a") as f:
                f.write(f"Soundcard loopback fallback to sounddevice: {err}\n")

        # Fallback Approach: sounddevice input stream
        def sd_callback(indata, frames, time_info, status):
            if not self._running:
                return
            process_signal(indata[:, 0])

        try:
            input_device = None
            devices = sd.query_devices()
            for idx, dev in enumerate(devices):
                if dev.get('max_input_channels', 0) > 0:
                    name_lower = dev.get('name', '').lower()
                    if 'stereo mix' in name_lower or 'loopback' in name_lower or 'what u hear' in name_lower:
                        input_device = idx
                        break
            
            if input_device is None:
                default_dev = sd.default.device[0]
                if default_dev != -1 and default_dev is not None:
                    input_device = default_dev

            if input_device is not None:
                with sd.InputStream(device=input_device, callback=sd_callback, channels=1, samplerate=sr, blocksize=2048):
                    while self._running:
                        time.sleep(0.02)
            else:
                while self._running:
                    time.sleep(0.1)
        except Exception as e:
            with open(os.path.join(os.path.expanduser("~"), "captureME_error.log"), "a") as f:
                f.write(f"Audio input disabled/failed: {e}\n")
            while self._running:
                time.sleep(0.1)


class CaptureCanvas(QWidget):
    def __init__(self, parent_widget):
        super().__init__(parent_widget)
        self.parent_widget = parent_widget
        self.setMouseTracking(True)

    def paintEvent(self, event):
        pw = self.parent_widget
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        base_size = SIZES.get(pw.config.get("size", "Medium"), 80)
        cx = self.width() / 2.0
        cy = self.height() / 2.0
        
        d_size = base_size + pw.current_icon_scale_factor
        rect = QRectF(cx - d_size/2.0, cy - d_size/2.0, d_size, d_size)

        intensity = min(1.0, max(0.0, pw.current_glow_intensity))
        glow_user_op = pw.config.get("glow_opacity", 0.9)
        glow_alpha = int((60 + 185 * intensity) * glow_user_op)
        glow_alpha = min(245, max(0, glow_alpha))

        freq_factor = min(1.0, max(0.0, pw.current_glow_size_factor))
        glow_sz_scale = pw.config.get("glow_size_pct", 50) / 100.0
        glow_base_ext = 4.0 + 36.0 * glow_sz_scale   # 4..40 px base extension
        glow_audio_ext = freq_factor * (4.0 + 56.0 * glow_sz_scale)  # 0..60 audio-reactive
        glow_radius = (d_size / 2.0) + glow_base_ext + glow_audio_ext

        if pw.is_recording:
            glow_color = QColor(255, 40, 40, glow_alpha)
            outer_color = QColor(255, 40, 40, int(glow_alpha * 0.45))
        else:
            custom_h = pw.config.get("hue", 190)
            glow_color = QColor.fromHsv(custom_h, 255, 255, glow_alpha)
            outer_color = QColor.fromHsv(custom_h, 255, 255, int(glow_alpha * 0.45))

        if pw.config.get("glow_enabled", True):
            # Outer Glow
            radial_outer = QRadialGradient(cx, cy, glow_radius + 16.0)
            radial_outer.setColorAt(0.0, outer_color)
            radial_outer.setColorAt(0.6, QColor(outer_color.red(), outer_color.green(), outer_color.blue(), int(glow_alpha * 0.15)))
            radial_outer.setColorAt(1.0, QColor(0, 0, 0, 0))
            painter.setBrush(QBrush(radial_outer))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QRectF(cx - (glow_radius + 16.0), cy - (glow_radius + 16.0), (glow_radius + 16.0)*2.0, (glow_radius + 16.0)*2.0))

            # Core Glow
            radial = QRadialGradient(cx, cy, glow_radius)
            radial.setColorAt(0.0, glow_color)
            radial.setColorAt(0.65, QColor(glow_color.red(), glow_color.green(), glow_color.blue(), int(glow_alpha * 0.45)))
            radial.setColorAt(1.0, QColor(0, 0, 0, 0))
            painter.setBrush(QBrush(radial))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QRectF(cx - glow_radius, cy - glow_radius, glow_radius * 2.0, glow_radius * 2.0))

        # Main Card Body with custom App Opacity
        app_user_op = pw.config.get("opacity", 0.9)
        body_alpha = int(220 * app_user_op)
        body_bg = QColor(20, 24, 34, body_alpha)
        border_alpha = int((60 + 175 * intensity) * app_user_op)
        border_pen = QPen(QColor(255, 255, 255, border_alpha), 1.8)

        if pw.screenshot_flash > 0:
            flash_v = int(255 * pw.screenshot_flash)
            body_bg = QColor(255, 255, 255, min(240, int((180 + flash_v) * app_user_op)))
            border_pen = QPen(QColor(0, 230, 255, int(255 * app_user_op)), 2.5)

        painter.setBrush(QBrush(body_bg))
        painter.setPen(border_pen)
        painter.drawEllipse(rect)

        # Center Checkbox
        chk_radius = d_size * 0.18
        chk_rect = QRectF(cx - chk_radius, cy - chk_radius, chk_radius * 2.0, chk_radius * 2.0)

        if pw.is_recording:
            chk_fill = QColor(255, 40, 40, int(255 * app_user_op))
            chk_border = QColor(255, 180, 180, int(255 * app_user_op))
        else:
            chk_fill = QColor(35, 42, 58, int(200 * app_user_op))
            custom_h = pw.config.get("hue", 190)
            c_border = QColor.fromHsv(custom_h, 255, 255)
            chk_border = QColor(c_border.red(), c_border.green(), c_border.blue(), int(180 * app_user_op))

        painter.setBrush(QBrush(chk_fill))
        painter.setPen(QPen(chk_border, 2))
        painter.drawEllipse(chk_rect)

        if pw.is_recording:
            sq_w = chk_radius * 0.8
            painter.setBrush(QBrush(QColor(255, 255, 255, int(255 * app_user_op))))
            painter.setPen(Qt.NoPen)
            painter.drawRect(QRectF(cx - sq_w/2.0, cy - sq_w/2.0, sq_w, sq_w))
        else:
            dot_r = chk_radius * 0.35
            custom_h = pw.config.get("hue", 190)
            c_dot = QColor.fromHsv(custom_h, 255, 255)
            dot_color = QColor(c_dot.red(), c_dot.green(), c_dot.blue(), int((150 + 105 * intensity) * app_user_op))
            painter.setBrush(QBrush(dot_color))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QRectF(cx - dot_r, cy - dot_r, dot_r * 2.0, dot_r * 2.0))

    def mousePressEvent(self, event):
        pw = self.parent_widget
        if event.button() == Qt.LeftButton:
            # Left-click used ONLY for positioning when Clickthrough is NOT selected (and not locked)
            if not pw.config.get("clickthrough", False) and not pw.config.get("lock_position", False):
                pw.dragging = True
                pw.drag_start_pos = event.globalPos() - pw.frameGeometry().topLeft()
                pw.click_press_pos = event.globalPos()
                pw.is_drag_moved = False
        elif event.button() == Qt.RightButton:
            base_size = SIZES.get(pw.config.get("size", "Medium"), 80)
            d_size = base_size + pw.current_icon_scale_factor
            cx = self.width() / 2.0
            cy = self.height() / 2.0
            chk_radius = d_size * 0.18

            click_pos = event.pos()
            dist = math.sqrt((click_pos.x() - cx)**2 + (click_pos.y() - cy)**2)

            if dist <= chk_radius * 1.5:
                # Right click in center starts/stops recording
                pw.toggle_recording()
            else:
                # Right click outside center takes a screenshot
                pw.take_screenshot()

    def mouseMoveEvent(self, event):
        pw = self.parent_widget
        if not pw.config.get("clickthrough", False) and pw.dragging and (event.buttons() & Qt.LeftButton):
            delta = event.globalPos() - pw.click_press_pos
            if delta.manhattanLength() > 4:
                pw.is_drag_moved = True
            
            new_pos = event.globalPos() - pw.drag_start_pos
            pw.move(new_pos)
            pw.config["pos_x"] = new_pos.x()
            pw.config["pos_y"] = new_pos.y()
            save_config(pw.config)

    def mouseReleaseEvent(self, event):
        pw = self.parent_widget
        if event.button() == Qt.LeftButton:
            pw.dragging = False
            pw.is_drag_moved = False


class CaptureMeWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.config = load_config()
        self.config["start_with_windows"] = check_startup()

        self.recorder = VideoRecorder()
        self.is_recording = False

        self.audio_mon = AudioMonitor()
        self.audio_mon.start()

        self.dragging = False
        self.drag_start_pos = QPoint()
        self.click_press_pos = QPoint()
        self.is_drag_moved = False

        self.mouse_speed = 0.0
        self.last_mouse_speed = 0.0
        self.mouse_accel = 0.0
        self.smooth_accel = 0.0
        self.last_mouse_pos = QCursor.pos()
        self.last_mouse_time = time.time()
        self.breath_phase = 0.0
        self.current_glow_intensity = 0.0
        self.current_glow_size_factor = 0.0
        self.current_icon_scale_factor = 0.0
        self.screenshot_flash = 0.0

        self.init_ui()

        self.anim_timer = QTimer(self)
        self.anim_timer.setInterval(20)
        self.anim_timer.timeout.connect(self.update_animation)
        self.anim_timer.start()

    def enforce_always_on_top(self):
        if not self.config.get("always_on_top", True):
            return
        if IS_WIN and ctypes:
            try:
                hwnd = int(self.winId())
                ctypes.windll.user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010 | 0x0040)
            except Exception:
                pass
        self.raise_()

    def showEvent(self, event):
        super().showEvent(event)
        if self.config.get("always_on_top", True):
            self.enforce_always_on_top()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.WindowStateChange, QEvent.ActivationChange, QEvent.ZOrderChange):
            if self.config.get("always_on_top", True):
                self.enforce_always_on_top()

    def init_ui(self):
        flags = Qt.FramelessWindowHint | Qt.Tool
        if self.config.get("always_on_top", True):
            flags |= Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMouseTracking(True)

        base_sz = SIZES.get(self.config.get("size", "Medium"), 80)
        size_px = base_sz + 180
        self.setFixedSize(size_px, size_px)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.canvas = CaptureCanvas(self)
        layout.addWidget(self.canvas)

        screen_geo = QApplication.primaryScreen().geometry()
        default_x = screen_geo.width() - size_px - 50
        default_y = screen_geo.height() - size_px - 100

        pos_x = self.config.get("pos_x", default_x)
        pos_y = self.config.get("pos_y", default_y)
        self.move(pos_x, pos_y)

        self.create_tray_icon()
        self.show()
        if self.config.get("always_on_top", True):
            self.enforce_always_on_top()

    def create_tray_icon(self):
        self.tray_icon = QSystemTrayIcon(self)
        
        icon_pixmap = QPixmap(32, 32)
        icon_pixmap.fill(Qt.transparent)
        painter = QPainter(icon_pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor(0, 210, 255), 2))
        painter.setBrush(QBrush(QColor(25, 30, 45)))
        painter.drawEllipse(3, 3, 26, 26)
        painter.setBrush(QBrush(QColor(0, 210, 255)))
        painter.drawEllipse(12, 12, 8, 8)
        painter.end()

        self.tray_icon.setIcon(QIcon(icon_pixmap))
        self.tray_icon.setToolTip("captureME Widget")

        self.tray_menu = QMenu()
        self.tray_menu.setStyleSheet("""
            QMenu {
                background-color: #1e222b;
                color: #e1e4ea;
                border: 1px solid #3a4253;
                border-radius: 8px;
                padding: 6px;
                font-family: 'Segoe UI', sans-serif;
                font-size: 13px;
            }
            QMenu::item {
                padding: 6px 24px 6px 12px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #2c3444;
                color: #00d2ff;
            }
            QMenu::separator {
                height: 1px;
                background: #3a4253;
                margin: 4px 6px;
            }
        """)

        self.action_ontop = QAction("Always on Top", self, checkable=True)
        self.action_ontop.setChecked(self.config.get("always_on_top", True))
        self.action_ontop.triggered.connect(self.toggle_always_on_top)
        self.tray_menu.addAction(self.action_ontop)

        self.action_lock = QAction("Lock Position", self, checkable=True)
        self.action_lock.setChecked(self.config.get("lock_position", False))
        self.action_lock.triggered.connect(self.toggle_lock_position)
        self.tray_menu.addAction(self.action_lock)

        self.action_clickthrough = QAction("Clickthrough", self, checkable=True)
        self.action_clickthrough.setChecked(self.config.get("clickthrough", False))
        self.action_clickthrough.triggered.connect(self.toggle_clickthrough)
        self.tray_menu.addAction(self.action_clickthrough)

        self.action_breathing = QAction("Breathing (Tri-Modulated)", self, checkable=True)
        self.action_breathing.setChecked(self.config.get("breathing", True))
        self.action_breathing.triggered.connect(self.toggle_breathing)
        self.tray_menu.addAction(self.action_breathing)

        self.action_glow = QAction("Enable Ambient Glow", self, checkable=True)
        self.action_glow.setChecked(self.config.get("glow_enabled", True))
        self.action_glow.triggered.connect(self.toggle_glow)
        self.tray_menu.addAction(self.action_glow)

        startup_label = "Start with Windows" if IS_WIN else "Start at Login"
        self.action_startup = QAction(startup_label, self, checkable=True)
        self.action_startup.setChecked(self.config.get("start_with_windows", False))
        self.action_startup.triggered.connect(self.toggle_startup)
        self.tray_menu.addAction(self.action_startup)

        self.tray_menu.addSeparator()

        # --- App Opacity Slider (0% - 100%) ---
        opacity_container = QWidget()
        op_layout = QHBoxLayout(opacity_container)
        op_layout.setContentsMargins(12, 4, 12, 4)
        op_label_title = QLabel("App Opacity:")
        op_label_title.setStyleSheet("color: #d1d5db; font-size: 11px; font-weight: bold;")
        self.op_label_val = QLabel(f"{int(self.config.get('opacity', 0.9) * 100)}%")
        self.op_label_val.setStyleSheet("color: #00d2ff; font-size: 11px; font-weight: bold;")
        
        self.op_slider = QSlider(Qt.Horizontal)
        self.op_slider.setRange(0, 100)
        self.op_slider.setValue(int(self.config.get("opacity", 0.9) * 100))
        self.op_slider.setFixedWidth(100)
        self.op_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 4px;
                background: #374151;
                border-radius: 2px;
            }
            QSlider::sub-page:horizontal {
                background: #00d2ff;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #ffffff;
                width: 12px;
                height: 12px;
                margin: -4px 0;
                border-radius: 6px;
            }
        """)
        self.op_slider.valueChanged.connect(self.on_opacity_slider_changed)

        op_layout.addWidget(op_label_title)
        op_layout.addWidget(self.op_slider)
        op_layout.addWidget(self.op_label_val)

        op_action = QWidgetAction(self)
        op_action.setDefaultWidget(opacity_container)
        self.tray_menu.addAction(op_action)

        # --- Outer Glow Opacity Slider (0% - 100%) ---
        glow_op_container = QWidget()
        glow_op_layout = QHBoxLayout(glow_op_container)
        glow_op_layout.setContentsMargins(12, 4, 12, 4)
        glow_op_label_title = QLabel("Glow Opacity:")
        glow_op_label_title.setStyleSheet("color: #d1d5db; font-size: 11px; font-weight: bold;")
        self.glow_op_label_val = QLabel(f"{int(self.config.get('glow_opacity', 0.9) * 100)}%")
        self.glow_op_label_val.setStyleSheet("color: #00d2ff; font-size: 11px; font-weight: bold;")
        
        self.glow_op_slider = QSlider(Qt.Horizontal)
        self.glow_op_slider.setRange(0, 100)
        self.glow_op_slider.setValue(int(self.config.get("glow_opacity", 0.9) * 100))
        self.glow_op_slider.setFixedWidth(100)
        self.glow_op_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 4px;
                background: #374151;
                border-radius: 2px;
            }
            QSlider::sub-page:horizontal {
                background: #8a2be2;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #ffffff;
                width: 12px;
                height: 12px;
                margin: -4px 0;
                border-radius: 6px;
            }
        """)
        self.glow_op_slider.valueChanged.connect(self.on_glow_opacity_slider_changed)

        glow_op_layout.addWidget(glow_op_label_title)
        glow_op_layout.addWidget(self.glow_op_slider)
        glow_op_layout.addWidget(self.glow_op_label_val)

        glow_op_action = QWidgetAction(self)
        glow_op_action.setDefaultWidget(glow_op_container)
        self.tray_menu.addAction(glow_op_action)

        # --- Glow Size Slider (0% - 100%) ---
        glow_sz_container = QWidget()
        glow_sz_layout = QHBoxLayout(glow_sz_container)
        glow_sz_layout.setContentsMargins(12, 4, 12, 4)
        glow_sz_label_title = QLabel("Glow Size:")
        glow_sz_label_title.setStyleSheet("color: #d1d5db; font-size: 11px; font-weight: bold;")
        current_glow_sz = self.config.get("glow_size_pct", 50)
        self.glow_sz_label_val = QLabel(f"{current_glow_sz}%")
        self.glow_sz_label_val.setStyleSheet("color: #00d2ff; font-size: 11px; font-weight: bold;")

        self.glow_sz_slider = QSlider(Qt.Horizontal)
        self.glow_sz_slider.setRange(0, 100)
        self.glow_sz_slider.setValue(current_glow_sz)
        self.glow_sz_slider.setFixedWidth(100)
        self.glow_sz_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 4px;
                background: #374151;
                border-radius: 2px;
            }
            QSlider::sub-page:horizontal {
                background: #8a2be2;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #ffffff;
                width: 12px;
                height: 12px;
                margin: -4px 0;
                border-radius: 6px;
            }
        """)
        self.glow_sz_slider.valueChanged.connect(self.on_glow_size_slider_changed)

        glow_sz_layout.addWidget(glow_sz_label_title)
        glow_sz_layout.addWidget(self.glow_sz_slider)
        glow_sz_layout.addWidget(self.glow_sz_label_val)

        glow_sz_action = QWidgetAction(self)
        glow_sz_action.setDefaultWidget(glow_sz_container)
        self.tray_menu.addAction(glow_sz_action)

        # --- Color (Hue) Slider (0 - 360°) ---
        hue_container = QWidget()
        hue_layout = QHBoxLayout(hue_container)
        hue_layout.setContentsMargins(12, 4, 12, 4)
        hue_label_title = QLabel("Color Hue:")
        hue_label_title.setStyleSheet("color: #d1d5db; font-size: 11px; font-weight: bold;")
        current_hue = self.config.get("hue", 190)
        self.hue_label_val = QLabel(f"{current_hue}°")
        
        # Style label with initial color preview
        preview_color = QColor.fromHsv(current_hue, 255, 255).name()
        self.hue_label_val.setStyleSheet(f"color: {preview_color}; font-size: 11px; font-weight: bold;")

        self.hue_slider = QSlider(Qt.Horizontal)
        self.hue_slider.setRange(0, 360)
        self.hue_slider.setValue(current_hue)
        self.hue_slider.setFixedWidth(100)
        self.hue_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 6px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop: 0 #ff0000, stop: 0.17 #ffff00, stop: 0.33 #00ff00,
                    stop: 0.50 #00ffff, stop: 0.67 #0000ff, stop: 0.83 #ff00ff, stop: 1.0 #ff0000);
                border-radius: 3px;
            }
            QSlider::sub-page:horizontal {
                background: transparent;
            }
            QSlider::handle:horizontal {
                background: #ffffff;
                width: 12px;
                height: 12px;
                margin: -3px 0;
                border-radius: 6px;
                border: 1px solid #111;
            }
        """)
        self.hue_slider.valueChanged.connect(self.on_hue_slider_changed)

        hue_layout.addWidget(hue_label_title)
        hue_layout.addWidget(self.hue_slider)
        hue_layout.addWidget(self.hue_label_val)

        hue_action = QWidgetAction(self)
        hue_action.setDefaultWidget(hue_container)
        self.tray_menu.addAction(hue_action)

        # --- Size Slider (0% - 100%) ---
        size_container = QWidget()
        sz_layout = QHBoxLayout(size_container)
        sz_layout.setContentsMargins(12, 4, 12, 4)
        sz_label_title = QLabel("Size:")
        sz_label_title.setStyleSheet("color: #d1d5db; font-size: 11px; font-weight: bold;")
        
        current_sz_pct = self.config.get("size_percent", 50)
        self.sz_label_val = QLabel(f"{current_sz_pct}%")
        self.sz_label_val.setStyleSheet("color: #00d2ff; font-size: 11px; font-weight: bold;")
        
        self.sz_slider = QSlider(Qt.Horizontal)
        self.sz_slider.setRange(0, 100)
        self.sz_slider.setValue(current_sz_pct)
        self.sz_slider.setFixedWidth(100)
        self.sz_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 4px;
                background: #374151;
                border-radius: 2px;
            }
            QSlider::sub-page:horizontal {
                background: #00d2ff;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #ffffff;
                width: 12px;
                height: 12px;
                margin: -4px 0;
                border-radius: 6px;
            }
        """)
        self.sz_slider.valueChanged.connect(self.on_size_slider_changed)

        sz_layout.addWidget(sz_label_title)
        sz_layout.addWidget(self.sz_slider)
        sz_layout.addWidget(self.sz_label_val)

        sz_action = QWidgetAction(self)
        sz_action.setDefaultWidget(size_container)
        self.tray_menu.addAction(sz_action)

        self.tray_menu.addSeparator()

        action_exit = QAction("Exit", self)
        action_exit.triggered.connect(QApplication.quit)
        self.tray_menu.addAction(action_exit)

        self.tray_icon.setContextMenu(self.tray_menu)
        self.tray_icon.show()

    def update_animation(self):
        self.top_counter = (getattr(self, 'top_counter', 0) + 1) % 50
        if self.top_counter == 0 and self.config.get("always_on_top", True):
            self.enforce_always_on_top()

        now = time.time()
        dt = max(0.001, now - self.last_mouse_time)
        cur_pos = QCursor.pos()
        dx = cur_pos.x() - self.last_mouse_pos.x()
        dy = cur_pos.y() - self.last_mouse_pos.y()
        current_speed = math.sqrt(dx*dx + dy*dy) / dt
        
        # Calculate Mouse Acceleration (dv / dt)
        accel = abs(current_speed - self.last_mouse_speed) / dt
        self.last_mouse_speed = current_speed
        self.last_mouse_pos = cur_pos
        self.last_mouse_time = now

        # Smooth mouse acceleration (0.0 to 1.0)
        norm_accel = min(1.0, accel / 120000.0)
        self.smooth_accel += (norm_accel - self.smooth_accel) * 0.12

        w_center = self.mapToGlobal(QPoint(self.width() // 2, self.height() // 2))
        dist_to_mouse = math.sqrt((cur_pos.x() - w_center.x())**2 + (cur_pos.y() - w_center.y())**2)

        vol_amplitude = self.audio_mon.current_volume       # Audio Volume (0.0 - 1.0)
        audio_frequency = self.audio_mon.current_frequency   # Audio Frequency (0.0 - 1.0)

        if self.config.get("breathing", True):
            # Smooth sine breathing baseline
            self.breath_phase += 0.04
            sine_val = (math.sin(self.breath_phase) + 1.0) / 2.0

            # 1. Glow Intensity linked to System Volume Amplitude
            target_glow_intensity = 0.25 + (sine_val * 0.25) + (vol_amplitude * 0.85)

            # 2. Glow Size / Radius linked to System Volume Frequency
            target_glow_size = 0.20 + (sine_val * 0.15) + (audio_frequency * 0.80)

            # 3. Widget Icon Size linked to Mouse Acceleration
            target_icon_scale = (sine_val * 2.0) + (self.smooth_accel * 18.0)
        else:
            target_glow_intensity = 0.2 + (vol_amplitude * 0.8)
            target_glow_size = 0.2 + (audio_frequency * 0.8)
            target_icon_scale = self.smooth_accel * 12.0

        # Fast attack and snappy response for audio glow
        if target_glow_intensity > self.current_glow_intensity:
            self.current_glow_intensity = target_glow_intensity
        else:
            self.current_glow_intensity += (target_glow_intensity - self.current_glow_intensity) * 0.40

        if target_glow_size > self.current_glow_size_factor:
            self.current_glow_size_factor = target_glow_size
        else:
            self.current_glow_size_factor += (target_glow_size - self.current_glow_size_factor) * 0.40

        self.current_icon_scale_factor += (target_icon_scale - self.current_icon_scale_factor) * 0.25

        if self.screenshot_flash > 0:
            self.screenshot_flash -= 0.1
            if self.screenshot_flash < 0:
                self.screenshot_flash = 0.0

        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        base_size = SIZES.get(self.config.get("size", "Medium"), 80)
        
        cx = self.width() / 2.0
        cy = self.height() / 2.0
        
        # Icon Size linked to Mouse Acceleration
        d_size = base_size + self.current_icon_scale_factor
        rect = QRectF(cx - d_size/2.0, cy - d_size/2.0, d_size, d_size)

        # 1. BG Glow Intensity linked to System Volume Amplitude
        intensity = min(1.0, max(0.0, self.current_glow_intensity))
        glow_user_op = self.config.get("glow_opacity", 0.9)
        glow_alpha = int((40 + 200 * intensity) * glow_user_op)
        glow_alpha = min(245, max(0, glow_alpha))

        # 2. BG Glow Size linked to System Volume Frequency + user slider
        freq_factor = min(1.0, max(0.0, self.current_glow_size_factor))
        glow_sz_scale = self.config.get("glow_size_pct", 50) / 100.0
        glow_base_ext = 5.0 + 45.0 * glow_sz_scale   # 5..50 px base extension
        glow_audio_ext = freq_factor * (5.0 + 65.0 * glow_sz_scale)  # 0..70 audio-reactive
        glow_radius = (d_size / 2.0) + glow_base_ext + glow_audio_ext

        if self.is_recording:
            glow_color = QColor(255, 40, 40, glow_alpha)
            outer_color = QColor(255, 40, 40, int(glow_alpha * 0.45))
        else:
            custom_h = self.config.get("hue", 190)
            glow_color = QColor.fromHsv(custom_h, 255, 255, glow_alpha)
            outer_color = QColor.fromHsv(custom_h, 255, 255, int(glow_alpha * 0.45))

        if self.config.get("glow_enabled", True):
            # Outer Ambient Aura (Glow Size linked to Audio Frequency)
            radial_outer = QRadialGradient(cx, cy, glow_radius + 18.0)
            radial_outer.setColorAt(0.0, outer_color)
            radial_outer.setColorAt(0.6, QColor(outer_color.red(), outer_color.green(), outer_color.blue(), int(glow_alpha * 0.15)))
            radial_outer.setColorAt(1.0, QColor(0, 0, 0, 0))

            painter.setBrush(QBrush(radial_outer))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QRectF(cx - (glow_radius + 18.0), cy - (glow_radius + 18.0), (glow_radius + 18.0)*2.0, (glow_radius + 18.0)*2.0))

            # Inner Core Radial Glow
            radial = QRadialGradient(cx, cy, glow_radius)
            radial.setColorAt(0.0, glow_color)
            radial.setColorAt(0.65, QColor(glow_color.red(), glow_color.green(), glow_color.blue(), int(glow_alpha * 0.45)))
            radial.setColorAt(1.0, QColor(0, 0, 0, 0))

            painter.setBrush(QBrush(radial))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QRectF(cx - glow_radius, cy - glow_radius, glow_radius * 2.0, glow_radius * 2.0))

        # Main Card Body with custom App Opacity
        app_user_op = self.config.get("opacity", 0.9)
        body_alpha = int(220 * app_user_op)
        body_bg = QColor(20, 24, 34, body_alpha)
        border_alpha = int((60 + 175 * intensity) * app_user_op)
        border_pen = QPen(QColor(255, 255, 255, border_alpha), 1.8)

        if self.screenshot_flash > 0:
            flash_v = int(255 * self.screenshot_flash)
            body_bg = QColor(255, 255, 255, min(240, int((180 + flash_v) * app_user_op)))
            border_pen = QPen(QColor(0, 230, 255, int(255 * app_user_op)), 2.5)

        painter.setBrush(QBrush(body_bg))
        painter.setPen(border_pen)
        painter.drawEllipse(rect)

        chk_radius = d_size * 0.18
        chk_rect = QRectF(cx - chk_radius, cy - chk_radius, chk_radius * 2.0, chk_radius * 2.0)

        if self.is_recording:
            chk_fill = QColor(255, 40, 40, int(255 * app_user_op))
            chk_border = QColor(255, 180, 180, int(255 * app_user_op))
        else:
            chk_fill = QColor(35, 42, 58, int(200 * app_user_op))
            custom_h = self.config.get("hue", 190)
            c_border = QColor.fromHsv(custom_h, 255, 255)
            chk_border = QColor(c_border.red(), c_border.green(), c_border.blue(), int(180 * app_user_op))

        painter.setBrush(QBrush(chk_fill))
        painter.setPen(QPen(chk_border, 2))
        painter.drawEllipse(chk_rect)

        if self.is_recording:
            sq_w = chk_radius * 0.8
            painter.setBrush(QBrush(QColor(255, 255, 255, int(255 * app_user_op))))
            painter.setPen(Qt.NoPen)
            painter.drawRect(QRectF(cx - sq_w/2.0, cy - sq_w/2.0, sq_w, sq_w))
        else:
            dot_r = chk_radius * 0.35
            custom_h = self.config.get("hue", 190)
            c_dot = QColor.fromHsv(custom_h, 255, 255)
            dot_color = QColor(c_dot.red(), c_dot.green(), c_dot.blue(), int((150 + 105 * self.current_glow_intensity) * app_user_op))
            painter.setBrush(QBrush(dot_color))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QRectF(cx - dot_r, cy - dot_r, dot_r * 2.0, dot_r * 2.0))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            # Left mouse button used ONLY for positioning when Clickthrough is NOT selected (and not locked)
            if not self.config.get("clickthrough", False) and not self.config.get("lock_position", False):
                self.dragging = True
                self.drag_start_pos = event.globalPos() - self.frameGeometry().topLeft()
                self.click_press_pos = event.globalPos()
                self.is_drag_moved = False

        elif event.button() == Qt.RightButton:
            base_size = SIZES.get(self.config.get("size", "Medium"), 80)
            d_size = base_size + self.current_icon_scale_factor
            cx = self.width() / 2.0
            cy = self.height() / 2.0
            chk_radius = d_size * 0.18

            click_pos = event.pos()
            dist = math.sqrt((click_pos.x() - cx)**2 + (click_pos.y() - cy)**2)

            if dist <= chk_radius * 1.5:
                # Right click in center starts/stops recording
                self.toggle_recording()
            else:
                # Right click outside center takes a screenshot
                self.take_screenshot()

    def mouseMoveEvent(self, event):
        if not self.config.get("clickthrough", False) and self.dragging and (event.buttons() & Qt.LeftButton):
            delta = event.globalPos() - self.click_press_pos
            if delta.manhattanLength() > 4:
                self.is_drag_moved = True
            
            new_pos = event.globalPos() - self.drag_start_pos
            self.move(new_pos)
            self.config["pos_x"] = new_pos.x()
            self.config["pos_y"] = new_pos.y()
            save_config(self.config)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.dragging = False
            self.is_drag_moved = False

    def take_screenshot(self):
        self.screenshot_flash = 1.0
        self.update()
        
        self.hide()
        QApplication.processEvents()

        try:
            with mss.mss() as sct:
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                filename = os.path.join(CAPTURES_DIR, "Screenshots", f"screenshot_{timestamp}.png")
                sct.shot(mon=-1, output=filename)
                
                self.tray_icon.showMessage("captureME", f"Screenshot saved to:\n{os.path.basename(filename)}", QSystemTrayIcon.Information, 2000)
        except Exception as e:
            print("Screenshot error:", e)
        finally:
            self.show()

    def toggle_recording(self):
        if not self.is_recording:
            self.is_recording = True
            self.recorder.start_recording()
            self.tray_icon.showMessage("captureME", "Video recording started...", QSystemTrayIcon.Information, 1500)
        else:
            self.is_recording = False
            self.recorder.stop_recording()
            self.tray_icon.showMessage("captureME", "Saving video recording...", QSystemTrayIcon.Information, 2000)
        self.update()

    def toggle_always_on_top(self, checked):
        self.config["always_on_top"] = checked
        save_config(self.config)
        flags = Qt.FramelessWindowHint | Qt.Tool
        if checked:
            flags |= Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.show()
        if checked:
            self.enforce_always_on_top()
        else:
            if IS_WIN and ctypes:
                try:
                    hwnd = int(self.winId())
                    ctypes.windll.user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)
                except Exception:
                    pass

    def toggle_clickthrough(self, checked):
        self.config["clickthrough"] = checked
        save_config(self.config)

    def toggle_lock_position(self, checked):
        self.config["lock_position"] = checked
        save_config(self.config)

    def toggle_breathing(self, checked):
        self.config["breathing"] = checked
        save_config(self.config)

    def toggle_glow(self, checked):
        self.config["glow_enabled"] = checked
        save_config(self.config)
        self.update()

    def toggle_startup(self, checked):
        self.config["start_with_windows"] = checked
        set_startup(checked)
        save_config(self.config)

    def on_opacity_slider_changed(self, value):
        val_float = value / 100.0
        self.config["opacity"] = val_float
        if hasattr(self, "op_label_val"):
            self.op_label_val.setText(f"{value}%")
        save_config(self.config)
        self.update()

    def on_glow_opacity_slider_changed(self, value):
        val_float = value / 100.0
        self.config["glow_opacity"] = val_float
        if hasattr(self, "glow_op_label_val"):
            self.glow_op_label_val.setText(f"{value}%")
        save_config(self.config)
        self.update()

    def on_glow_size_slider_changed(self, value):
        self.config["glow_size_pct"] = value
        if hasattr(self, "glow_sz_label_val"):
            self.glow_sz_label_val.setText(f"{value}%")
        save_config(self.config)
        self.update()

    def on_hue_slider_changed(self, value):
        self.config["hue"] = value
        if hasattr(self, "hue_label_val"):
            self.hue_label_val.setText(f"{value}°")
            color_hex = QColor.fromHsv(value, 255, 255).name()
            self.hue_label_val.setStyleSheet(f"color: {color_hex}; font-size: 11px; font-weight: bold;")
        save_config(self.config)
        self.update()

    def on_size_slider_changed(self, value):
        self.config["size_percent"] = value
        if hasattr(self, "sz_label_val"):
            self.sz_label_val.setText(f"{value}%")
        # 0% -> 40px, 100% -> 160px
        base_size = int(40 + (120 * (value / 100.0)))
        SIZES["Custom"] = base_size
        self.config["size"] = "Custom"
        self.setFixedSize(base_size + 180, base_size + 180)
        save_config(self.config)
        self.update()

    def set_widget_opacity(self, val):
        self.config["opacity"] = val
        self.update()
        save_config(self.config)

    def set_widget_size(self, size_name):
        self.config["size"] = size_name
        base_size = SIZES.get(size_name, 80)
        self.setFixedSize(base_size + 180, base_size + 180)
        save_config(self.config)


main_widget = None

if __name__ == "__main__":
    log_path = os.path.join(os.path.expanduser("~"), "captureME_error.log")
    try:
        with open(log_path, "a") as f:
            f.write(f"--- Launching captureME at {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
        app = QApplication(sys.argv)
        app.setQuitOnLastWindowClosed(False)
        main_widget = CaptureMeWidget()
        with open(log_path, "a") as f:
            f.write("Widget initialized, starting event loop...\n")
        res = app.exec_()
        with open(log_path, "a") as f:
            f.write(f"Event loop exited with code {res}\n")
        sys.exit(res)
    except Exception as e:
        import traceback
        with open(log_path, "a") as f:
            f.write("Uncaught Exception:\n" + traceback.format_exc())
        raise e
