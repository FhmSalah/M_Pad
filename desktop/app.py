"""V1 Macro Pad editor backed by the shared CLI action engine."""

import os
import plistlib
import re
import sys
import weakref
from pathlib import Path
from threading import Event
from xml.parsers.expat import ExpatError

from PySide6.QtCore import QEvent, QObject, QPoint, QRectF, QSize, Qt, QThread, QTimer, QUrl, QVariantAnimation, Signal, Slot
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QMenu, QMessageBox, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget,
)

from app_paths import application_name
from config_store import ConfigStore, application_identifier, executable_identifier, label_event
from foreground_app import (APPLICATION_NAME_ALIASES, MACOS_APPLICATION_ALIASES,
                           ActivationObserver, get_foreground_application, normalize_application_name)
from run_actions import ActionGate, run_engine
from shortcut_keys import MEDIA_LABELS, action_label, resolve_action, shortcut_label
from shortcut_recorder import ShortcutRecorder
from autostart import BACKGROUND_FLAG, platform_autostart
from single_instance import SingleInstance
from tray import TrayIcon

try:
    from PySide6.QtMultimedia import QSoundEffect
except ImportError:
    QSoundEffect = None

def ui_size(value, factor=0.75):
    """Compact macOS layout metrics; retain original values on other platforms."""
    return max(1, round(value * factor * 0.8)) if sys.platform == "darwin" else value


def ui_font_size(value):
    """Keep compact text legible while reducing macOS typography."""
    return max(9, ui_size(value, 0.92)) if sys.platform == "darwin" else value


def ui_stylesheet(stylesheet):
    """Scale only CSS pixel metrics on macOS, with a gentler font reduction."""
    if sys.platform != "darwin":
        return stylesheet

    def declaration(match):
        property_name, values = match.groups()
        scale = ui_font_size if property_name.strip().startswith("font-size:") else ui_size
        values = re.sub(r"(\d+)px", lambda size: f"{scale(int(size[1]))}px", values)
        return property_name + values

    return re.sub(r"([\w-]+\s*:\s*)([^;{}]+)", declaration, stylesheet)


XS, S, M, L = (ui_size(value) for value in (4, 8, 12, 16))
INPUT_HEIGHT = ui_size(30, 0.9)

CONTROLS = [f"KEY:{number}" for number in range(1, 13)] + [
    f"ENC{encoder}:{action}" for encoder in (1, 2) for action in ("CCW", "PRESS", "CW")
]


def resource_path(relative_path):
    """Resolve bundled assets independently of the current working directory."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return str(base / relative_path)


def choose_application_bundle():
    from AppKit import NSOpenPanel, NSModalResponseOK
    from Foundation import NSURL
    panel = NSOpenPanel.openPanel()
    panel.setTitle_("Assign Application")
    panel.setPrompt_("Assign")
    panel.setCanChooseFiles_(True)
    panel.setCanChooseDirectories_(False)
    panel.setAllowsMultipleSelection_(False)
    panel.setTreatsFilePackagesAsDirectories_(False)
    panel.setAllowedFileTypes_(["app"])
    panel.setDirectoryURL_(NSURL.fileURLWithPath_("/Applications"))
    return str(panel.URL().path()) if panel.runModal() == NSModalResponseOK else None


def choose_windows_executable(parent=None):
    start = os.environ.get("ProgramFiles", r"C:\Program Files")
    path, _ = QFileDialog.getOpenFileName(
        parent, "Assign Application", start, "Applications (*.exe)")
    return path or None


def read_windows_executable(path):
    executable = Path(path)
    if not executable.is_file():
        raise ValueError("Select a Windows application (.exe)")
    # Windows foreground detection reports the executable file name only.
    return executable_identifier(executable.name), None


def read_application_bundle(path):
    bundle = Path(path)
    if bundle.suffix.lower() != ".app" or not bundle.is_dir():
        raise ValueError("Select an application bundle (.app)")
    try:
        with (bundle / "Contents" / "Info.plist").open("rb") as source:
            info = plistlib.load(source)
    except (OSError, ValueError, TypeError, ExpatError) as error:
        raise ValueError(f"Cannot read application Info.plist: {error}") from error
    if not isinstance(info, dict):
        raise ValueError("Application Info.plist must contain a dictionary")
    identifier = application_identifier(info.get("CFBundleIdentifier"))
    name = info.get("CFBundleDisplayName") or info.get("CFBundleName") or bundle.stem
    alias = MACOS_APPLICATION_ALIASES.get(identifier)
    if alias is None and isinstance(name, str):
        alias = APPLICATION_NAME_ALIASES.get(normalize_application_name(name))
    return identifier, alias


class ActivityFeedback(QObject):
    """One reusable animation per key/encoder, never a queue of fades."""
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.level = 0.0
        self.label = ""
        self.assigned = False
        self.control_id = ""
        self.animation = QVariantAnimation(self)
        self.animation.setDuration(2200)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.valueChanged.connect(self.advance)
        self.animation.finished.connect(self.clear)

    def advance(self, progress):
        if progress < 0.025:
            self.level = 1 - (1 - progress / 0.025) ** 2
        elif progress < 0.1:
            self.level = 1.0
        else:
            self.level = ((1 - progress) / 0.9) ** 2
        self.changed.emit()

    def flash(self, event, assigned, label):
        self.animation.stop()
        self.control_id, self.assigned, self.label = event, assigned, label
        self.animation.start()
        self.changed.emit()

    def clear(self):
        self.animation.stop()
        self.level, self.label, self.control_id = 0.0, "", ""
        self.changed.emit()

    def color(self):
        return QColor("#f5a34b" if self.assigned else "#d8dce2")


class DeviceControl(QPushButton):
    """A transparent, keyboard-accessible hit target over the physical image."""
    def __init__(self, event, parent=None):
        super().__init__(parent)
        self.control_id = event
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        self.setAccessibleName(event)
        self.show_label = False
        self.feedback = None
        self.target_rect = QRectF()
        self.circular = event.endswith(":ROTATE")

    def active_feedback(self):
        if not self.feedback:
            return None
        event = self.feedback.control_id
        if self.circular:
            return self.feedback if label_event(event) == self.control_id and event != self.control_id else None
        return self.feedback if event == self.control_id else None

    def hitButton(self, position):
        bounds = self.target_rect if not self.target_rect.isEmpty() else QRectF(self.rect())
        if self.circular:
            path = QPainterPath()
            path.addEllipse(bounds)
            return path.contains(position)
        return bounds.contains(position)

    def outline_rect(self, stroke_width):
        bounds = self.target_rect if not self.target_rect.isEmpty() else QRectF(self.rect())
        inset = stroke_width / 2 + 0.5
        return bounds.adjusted(inset, inset, -inset, -inset)

    @staticmethod
    def label_lines(text, metrics, width):
        # Wrap at a word boundary, then elide everything left on the last line.
        words = text.split()
        first = []
        while words and metrics.horizontalAdvance(" ".join(first + words[:1])) <= width:
            first.append(words.pop(0))
        if not first:
            return [metrics.elidedText(text, Qt.TextElideMode.ElideRight, width)]
        lines = [" ".join(first)]
        if words:
            lines.append(metrics.elidedText(" ".join(words), Qt.TextElideMode.ElideRight, width))
        return lines

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        target = self.target_rect if not self.target_rect.isEmpty() else QRectF(self.rect())
        is_key = self.control_id.startswith("KEY:")
        radius = min(self.width(), self.height()) * (0.09 if is_key else 0.22)
        selected = self.isChecked()
        activity = self.active_feedback()
        level = activity.level if activity else 0.0
        if selected or level or self.underMouse() or self.hasFocus():
            color = QColor("#f5a34b" if selected else "#acb5c0")
            if level and not selected:
                color = activity.color()
                color.setAlphaF(level)
            stroke_width = 2 + level if selected else (2 if level else 1)
            painter.setPen(QPen(color, stroke_width))
            fill = activity.color() if level else color
            fill.setAlphaF((24 * level + (16 if selected else 0)) / 255)
            painter.setBrush(fill)
            bounds = self.outline_rect(stroke_width)
            if self.circular:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(bounds)
            else:
                painter.drawRoundedRect(bounds, radius, radius)

        if self.circular:
            return

        label = activity.label if level else self.text()
        if not (self.show_label or level) or not label:
            return
        painter.setOpacity(1.0 if self.show_label else level)

        font = QFont(self.font())
        if is_key:
            font.setPixelSize(ui_font_size(max(10, min(12, round(target.width() * 0.125)))))
            font.setWeight(QFont.Weight.DemiBold)
        else:
            # Press names stay within their small physical pills after resizing.
            font.setPixelSize(ui_font_size(max(9, min(10, int(target.height()) - 2))))
            font.setWeight(QFont.Weight.Normal)
        painter.setFont(font)
        painter.setPen(QColor("#f5f2ed" if self.isEnabled() else "#858b94"))
        if is_key:
            face = QRectF(target.x() + target.width() * 0.17, target.y() + target.height() * 0.15,
                          target.width() * 0.66, target.height() * 0.68)
            metrics = QFontMetrics(font)
            lines = self.label_lines(label, metrics, int(face.width()) - 4)
            text_bounds = QRectF(face.x(), face.center().y() - len(lines) * metrics.height() / 2,
                                 face.width(), len(lines) * metrics.height())
            # A small shadow preserves contrast over both silver and colored caps.
            painter.setPen(QColor(0, 0, 0, 190))
            painter.drawText(text_bounds.translated(0, 1), Qt.AlignmentFlag.AlignCenter, "\n".join(lines))
            painter.setPen(QColor("#f5f2ed" if self.isEnabled() else "#858b94"))
            painter.drawText(text_bounds, Qt.AlignmentFlag.AlignCenter, "\n".join(lines))
        else:
            text = QFontMetrics(font).elidedText(label, Qt.TextElideMode.ElideRight, int(target.width()) - 6)
            painter.drawText(target, Qt.AlignmentFlag.AlignCenter, text)


class DevicePreview(QWidget):
    """Image and hit regions share one aspect-preserving coordinate transform."""
    # Coordinates measured on assets/macropad_device.png (1026 x 1167).
    IMAGE_WIDTH = 1026
    IMAGE_HEIGHT = 1167
    rotation_clicked = Signal(int)

    # Every visible target and label uses this one normalized image space.
    NORMALIZED_REGIONS = {
        **{f"KEY:{index + 1}": QRectF((83 + (index % 4) * 222) / 1026,
                                      (442 + (index // 4) * 223) / 1167, 197 / 1026, 199 / 1167)
           for index in range(12)},
        **{f"ENC{number}:ROTATE": QRectF((94 + (number - 1) * 592) / 1026, 70 / 1167, 246 / 1026, 246 / 1167)
           for number in (1, 2)},
        **{f"ENC{number}:PRESS": QRectF((153 + (number - 1) * 592) / 1026, 390 / 1167, 125 / 1026, 30 / 1167)
           for number in (1, 2)},
    }
    ROTATION_LABEL_REGIONS = {
        number: QRectF((111 + (number - 1) * 592) / 1026, 320 / 1167, 200 / 1026, 53 / 1167)
        for number in (1, 2)
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pixmap = QPixmap(resource_path("assets/macropad_device.png"))
        self.disconnected_pixmap = QPixmap(self.pixmap.size())
        self.disconnected_pixmap.fill(Qt.GlobalColor.transparent)
        if not self.pixmap.isNull():
            # Desaturate once, retaining the source alpha around the device.
            painter = QPainter(self.disconnected_pixmap)
            painter.drawImage(0, 0, self.pixmap.toImage().convertToFormat(QImage.Format.Format_Grayscale8))
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
            painter.drawPixmap(0, 0, self.pixmap)
            painter.end()
        self.connected = False
        self.show_labels = False
        self.encoder_names = {1: "", 2: ""}
        self.regions = {}
        self.knobs = {}
        self.activities = {}
        self.image_rect = QRectF()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(ui_size(300), ui_size(342))

    def sizeHint(self):
        return QSize(ui_size(526), ui_size(599))

    def add_control(self, event, button):
        button.setParent(self)
        target = event if event.startswith("KEY:") else event.split(":")[0]
        if target not in self.activities:
            self.activities[target] = ActivityFeedback(self)
            self.activities[target].changed.connect(self.update)
        button.feedback = self.activities[target]
        button.feedback.changed.connect(button.update)
        if event not in self.NORMALIZED_REGIONS:
            # Logical direction buttons remain wired, with no physical hit boxes.
            button.hide()
            return
        self.regions[event] = (button, self.NORMALIZED_REGIONS[event])

    def add_knob(self, number):
        event = f"ENC{number}:ROTATE"
        button = DeviceControl(event, self)
        button.feedback = self.activities[f"ENC{number}"]
        button.feedback.changed.connect(button.update)
        button.clicked.connect(lambda checked=False: self.rotation_clicked.emit(number))
        button.setAccessibleName("Left encoder" if number == 1 else "Right encoder")
        self.knobs[number] = button
        self.regions[event] = (button, self.NORMALIZED_REGIONS[event])

    def display_rect(self, normalized):
        return QRectF(self.image_rect.x() + normalized.x() * self.image_rect.width(),
                      self.image_rect.y() + normalized.y() * self.image_rect.height(),
                      normalized.width() * self.image_rect.width(), normalized.height() * self.image_rect.height())

    def clear_activity(self):
        for activity in self.activities.values():
            activity.clear()

    def flash_activity(self, event, assigned, label):
        target = event if event.startswith("KEY:") else event.split(":")[0]
        if target in self.activities:
            self.activities[target].flash(event, assigned, label)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        padding = ui_size(8)
        available = QRectF(self.rect()).adjusted(padding, padding, -padding, -padding)
        scale = min(available.width() / self.IMAGE_WIDTH, available.height() / self.IMAGE_HEIGHT)
        width, height = self.IMAGE_WIDTH * scale, self.IMAGE_HEIGHT * scale
        self.image_rect = QRectF(available.center().x() - width / 2,
                                available.center().y() - height / 2, width, height)
        for button, rect in self.regions.values():
            target = self.display_rect(rect)
            geometry = target.toAlignedRect()
            button.setGeometry(geometry)
            button.target_rect = target.translated(-geometry.x(), -geometry.y())
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if not self.pixmap.isNull():
            painter.setOpacity(1.0 if self.connected else 0.55)
            pixmap = self.pixmap if self.connected else self.disconnected_pixmap
            painter.drawPixmap(self.image_rect, pixmap, QRectF(pixmap.rect()))
            painter.setOpacity(1.0)
            font = QFont(self.font())
            font.setPixelSize(ui_font_size(11))
            painter.setFont(font)
            painter.setPen(QColor("#e9e7e3"))
            for number, name in self.encoder_names.items():
                rect = self.display_rect(self.ROTATION_LABEL_REGIONS[number])
                text = QFontMetrics(font).elidedText(name, Qt.TextElideMode.ElideRight, int(rect.width()) - 4)
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        else:
            painter.setPen(QColor("#b4bac4"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             "Device image unavailable\nassets/macropad_device.png")


class EyeButton(QPushButton):
    easter_egg_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(ui_size(32, 0.9), ui_size(28, 0.9))
        self.setAccessibleName("Show control names")
        self.setToolTip("Show control names")

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and event.modifiers() & Qt.KeyboardModifier.AltModifier:
            self.setDown(False)
            if self.rect().contains(event.position().toPoint()):
                self.easter_egg_requested.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(self.width() / 2, self.height() / 2)
        if sys.platform == "darwin":
            painter.scale(0.72, 0.72)
        painter.setPen(QPen(QColor("#f5a34b" if self.isChecked() else "#aab2bd"), 1.2))
        path = QPainterPath()
        if self.isChecked():
            path.moveTo(-7, 0)
            path.cubicTo(-3, -5, 3, -5, 7, 0)
            path.cubicTo(3, 5, -3, 5, -7, 0)
            painter.drawEllipse(QRectF(-1.5, -1.5, 3, 3))
        else:
            path.moveTo(-7, -1)
            path.quadTo(0, 5, 7, -1)
            painter.drawLine(-5, 1, -6, 3)
            painter.drawLine(0, 2, 0, 4)
            painter.drawLine(5, 1, 6, 3)
        painter.drawPath(path)


class EasterOverlay(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.pixmap = QPixmap(resource_path("assets/easter_egg.png"))
        self.hide()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#111318"))
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if not self.pixmap.isNull():
            scale = max(self.width() / self.pixmap.width(), self.height() / self.pixmap.height())
            width, height = self.pixmap.width() * scale, self.pixmap.height() * scale
            painter.drawPixmap(QRectF((self.width() - width) / 2, (self.height() - height) / 2, width, height),
                               self.pixmap, QRectF(self.pixmap.rect()))


def lock_icon():
    pixmap = QPixmap(20, 20)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor("#f5a34b"), 1.7))
    painter.drawArc(QRectF(6, 2, 8, 10), 0, 180 * 16)
    painter.drawRoundedRect(QRectF(4, 8, 12, 10), 2, 2)
    painter.end()
    return QIcon(pixmap)


class MacForegroundMonitor(QObject):
    activated = Signal(object)
    profile_changed = Signal(str)

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.running = False
        self.pending = 0
        self.generation = 0
        self.activated.connect(self.apply_activation, Qt.ConnectionType.QueuedConnection)
        owner = weakref.ref(self)
        def received(application):
            monitor = owner()
            if monitor is not None and monitor.running:
                monitor.pending += 1
                monitor.activated.emit((monitor.generation, application))
        self.observer = ActivationObserver(received)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.reconcile)

    def start(self):
        if self.running:
            return True
        self.generation += 1
        self.running = True
        if not self.observer.start():
            self.stop()
            return False
        try:
            self.reconcile()
            self.timer.start()
            return True
        except Exception:
            self.stop()
            return False

    @Slot(object)
    def apply_activation(self, payload):
        generation, application = payload
        if not self.running or generation != self.generation:
            return
        self.pending = max(0, self.pending - 1)
        self.apply(application, "notification")

    def apply(self, application, source):
        # Always process identities, including transitions sharing a profile name.
        previous = self.store.current_profile()
        profile = self.store.update_foreground_profile(application)
        if profile != previous:
            self.profile_changed.emit(profile)

    @Slot()
    def reconcile(self):
        if not self.running or self.pending:
            # Let queued identity transitions run before taking a newer snapshot.
            return
        application = get_foreground_application()
        if application is not None:
            self.apply(application, "reconcile")

    def stop(self):
        self.running = False
        self.generation += 1
        self.timer.stop()
        self.observer.stop()
        self.pending = 0


class EngineWorker(QThread):
    connection_changed = Signal(bool)
    profile_changed = Signal(str)
    status_changed = Signal(str)
    activity_changed = Signal(str, str, bool, str)

    def __init__(self, store, gate, parent=None):
        super().__init__(parent)
        self.stop = Event()
        self.store = store
        self.gate = gate
        self.watch_foreground = True

    def run(self):
        try:
            run_engine(
                self.stop,
                on_connection=self.connection_changed.emit,
                on_profile=self.profile_changed.emit,
                on_status=self.status_changed.emit,
                reconnect=True,
                config_store=self.store,
                action_gate=self.gate,
                on_activity=self.activity_changed.emit,
                watch_foreground=self.watch_foreground,
            )
        except Exception as error:
            self.connection_changed.emit(False)
            self.status_changed.emit(f"Error: {error}")


class ConfirmationDialog(QDialog):
    """A compact confirmation with explicit actions and safe keyboard defaults."""

    def __init__(self, parent, title, text, action_text):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(ui_size(360))
        self.setStyleSheet(ui_stylesheet("""
            QWidget { color: #f1f0ed; font-family: 'Segoe UI'; font-size: 12px; }
            QDialog { background: transparent; }
            QFrame#confirmationPanel {
                background: #20252d; border: 1px solid #3b424c; border-radius: 12px;
            }
            QLabel { background: transparent; border: none; }
            QLabel#confirmationTitle { font-size: 13px; font-weight: 600; }
            QLabel#confirmationText { color: #b5bdc8; }
            QPushButton {
                background: #262c35; border: 1px solid #444c58;
                border-radius: 8px; padding: 4px 12px;
            }
            QPushButton:hover { background: #303742; border-color: #747f8e; }
            QPushButton:focus { border-color: #f5a34b; }
            QPushButton#confirmAction { border-color: #f5a34b; color: #ffbc74; }
            QPushButton#confirmAction:hover { background: #3a3027; }
        """))
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        panel = QFrame(self)
        panel.setObjectName("confirmationPanel")
        outer.addWidget(panel)
        content = QVBoxLayout(panel)
        content.setContentsMargins(L, L, L, L)
        content.setSpacing(M)
        heading = QLabel(title)
        heading.setObjectName("confirmationTitle")
        heading.setTextFormat(Qt.TextFormat.PlainText)
        heading.setWordWrap(True)
        content.addWidget(heading)
        message = QLabel(text)
        message.setObjectName("confirmationText")
        message.setTextFormat(Qt.TextFormat.PlainText)
        message.setWordWrap(True)
        content.addWidget(message)
        buttons = QHBoxLayout()
        buttons.setSpacing(S)
        buttons.addStretch()
        self.cancel_button = QPushButton("Cancel")
        self.confirm_button = QPushButton(action_text)
        self.confirm_button.setObjectName("confirmAction")
        for button in (self.cancel_button, self.confirm_button):
            button.setFixedHeight(INPUT_HEIGHT)
            button.setAutoDefault(False)
            buttons.addWidget(button)
        self.cancel_button.setDefault(True)
        self.cancel_button.setFocus()
        self.cancel_button.clicked.connect(self.reject)
        self.confirm_button.clicked.connect(self.accept)
        content.addLayout(buttons)

    @classmethod
    def confirm(cls, parent, title, text, action_text):
        dialog = cls(parent, title, text, action_text)
        try:
            return dialog.exec() == QDialog.DialogCode.Accepted
        finally:
            dialog.deleteLater()


class ProfileNameDialog(ConfirmationDialog):
    """Shared Add/Rename input shell; ConfigStore remains the save validator."""

    def __init__(self, parent, store, title, action_text, profile=None):
        super().__init__(parent, title, "Profile name:", action_text)
        self.store = store
        self.original_profile = profile
        self.name_input = QLineEdit(profile or "")
        self.name_input.setFixedHeight(INPUT_HEIGHT)
        self.name_input.setPlaceholderText("Profile name")
        self.name_input.setAccessibleName("Profile name")
        self.error_label = QLabel()
        self.error_label.setObjectName("inputError")
        self.error_label.setTextFormat(Qt.TextFormat.PlainText)
        self.error_label.setWordWrap(True)
        content = self.findChild(QFrame, "confirmationPanel").layout()
        content.insertWidget(2, self.name_input)
        content.insertWidget(3, self.error_label)
        self.name_input.setStyleSheet(ui_stylesheet("""
            QLineEdit {
                background: #191d24; color: #f1f0ed; border: 1px solid #444c58;
                border-radius: 8px; padding: 4px 8px;
            }
            QLineEdit:focus { border-color: #f5a34b; }
        """))
        self.error_label.setStyleSheet(ui_stylesheet("color: #ffbc74; font-size: 11px;"))
        self.confirm_button.setStyleSheet("QPushButton:disabled { color: #626c79; border-color: #343b45; }")
        self.cancel_button.setDefault(False)
        self.confirm_button.setDefault(True)
        self.name_input.textChanged.connect(self.validate_name)
        self.validate_name()
        self.name_input.setFocus()
        self.name_input.selectAll()

    def validate_name(self, *_):
        try:
            name = self.store._profile_name(self.name_input.text())
            with self.store.lock:
                duplicate = name in self.store.data["profiles"] and name != self.original_profile
            if duplicate:
                raise ValueError("A profile with that name already exists")
        except ValueError as error:
            self.error_label.setText(str(error))
            self.confirm_button.setEnabled(False)
            return False
        self.error_label.setText(" ")
        self.confirm_button.setEnabled(True)
        return True

    def accept(self):
        if self.validate_name():
            super().accept()

    @classmethod
    def get_name(cls, parent, store, title, action_text, profile=None):
        dialog = cls(parent, store, title, action_text, profile)
        try:
            accepted = dialog.exec() == QDialog.DialogCode.Accepted
            return dialog.name_input.text().strip(), accepted
        finally:
            dialog.deleteLater()


class MacroPadWindow(QWidget):
    def __init__(self, store=None):
        super().__init__()
        self.store = store if store is not None else ConfigStore()
        self.gate = ActionGate()
        self.closing = False
        self.quit_requested = False
        self.tray = None
        self.loading = False
        self.dirty = False
        self.selected_control = "KEY:1"
        self.shortcut = []
        self.setWindowTitle(application_name())
        self.setWindowIcon(QIcon(resource_path("assets/app_icon.png")))
        if sys.platform == "win32":
            self.resize(800, 576)
            self.setMinimumSize(760, 540)
        elif sys.platform == "darwin":
            self.resize(720, 520)
            self.setMinimumSize(672, 480)
        else:
            self.resize(1000, 720)
            self.setMinimumSize(880, 620)
        self.setObjectName("macroPadWindow")
        self.setFont(QFont("Segoe UI", 10))
        self.setStyleSheet(ui_stylesheet("""
            QWidget { color: #f1f0ed; font-family: 'Segoe UI'; font-size: 12px; }
            QWidget#macroPadWindow { background: #191d23; }
            QFrame#editorPanel {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #252a32, stop:1 #1c2027);
                border: 1px solid #3b424c; border-radius: 20px;
            }
            QLabel { background: transparent; border: none; }
            QLabel#title { font-size: 18px; font-weight: 600; }
            QLabel#subtitle, QLabel#sectionLabel, QLabel#hint, QLabel#statusText,
            QLabel#activeProfile { color: #959eab; }
            QLabel#sectionLabel { font-size: 11px; font-weight: 600; }
            QLabel#selectedControl { color: #f5a34b; font-size: 17px; font-weight: 600; }
            QLineEdit#displayName, QLabel#shortcutPreview {
                background: #191d24; border: 1px solid #3b424d; border-radius: 10px;
            }
            QLineEdit#displayName { padding: 4px 8px; font-size: 12px; }
            QLabel#shortcutPreview { padding: 4px 8px; }
            QFrame#separator { background: #353c46; border: none; max-height: 1px; }
            QFrame#statusBar { background: #15191f; border-top: 1px solid #323944; }
            QLabel#connection { color: #a1a9b5; }
            QLabel#connection[connected="true"] { color: #86ce91; }
            QComboBox, QPushButton {
                background: #262c35; border: 1px solid #444c58;
                border-radius: 8px; padding: 4px 8px;
            }
            QComboBox { padding-right: 30px; min-height: 18px; }
            QComboBox:hover, QPushButton:hover { border-color: #747f8e; background: #303742; }
            QComboBox:focus, QPushButton:focus, QLabel#shortcutPreview:focus { border-color: #f5a34b; }
            QComboBox::drop-down { border: none; width: 24px; }
            QComboBox QAbstractItemView {
                background: #242a33; color: #f1f0ed; border: 1px solid #444c58;
                selection-background-color: #754821; selection-color: #fff4e5;
            }
            QPushButton:pressed { background: #383f4a; }
            QPushButton#typeOption { padding: 4px 8px; }
            QPushButton#typeOption:checked {
                background: #3a3027; border: 1px solid #f5a34b; color: #ffbc74;
            }
            QPushButton#saveButton { background: #df903e; border-color: #f5a34b; color: #191d23; font-weight: 600; }
            QPushButton#saveButton:hover { background: #f5a34b; }
            QPushButton#clearButton { background: #262c35; color: #d0d4da; }
            QPushButton#profileButton { border-color: #b67b3c; text-align: left; }
            QPushButton#eyeButton { background: transparent; border: none; padding: 0; }
            QPushButton#directionButton:checked { border-color: #f5a34b; color: #ffbc74; background: #3a3027; }
            QMenu { background: #242a33; border: 1px solid #444c58; padding: 4px; font-size: 11px; }
            QMenu::item { padding: 4px 12px; border-radius: 4px; }
            QMenu::item:selected { background: #3a3027; color: #ffbc74; }
            QMenu::separator { height: 1px; background: #444c58; margin: 4px; }
            QPushButton:disabled, QComboBox:disabled {
                background: #21262e; border-color: #343b45; color: #626c79;
            }
            QPushButton#saveButton:disabled {
                background: #292d33; border-color: #3b414b; color: #6c7582;
            }
            QToolTip { background: #262c35; color: #f1f0ed; border: 1px solid #586170; padding: 5px; }
        """))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        header = QHBoxLayout()
        header.setContentsMargins(L, M, L, XS)
        header.setSpacing(M)
        title = QLabel(application_name())
        title.setObjectName("title")
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)

        self.device = QLabel("●")
        self.device.setObjectName("connection")
        self.profile = QLabel(self)
        self.profile.hide()
        # Hidden profile model retained for existing editor wiring. It always
        # follows the one active profile used by the engine.
        self.edit_profile = QComboBox(self)
        self.edit_profile.hide()
        _, profiles, _ = self.store.snapshot()
        self.edit_profile.addItems(list(profiles))
        self.edit_profile.setCurrentText(self.store.current_profile())

        self.controls = QButtonGroup(self)
        self.controls.setExclusive(True)
        self.buttons = {}
        self.pad_widget = DevicePreview()
        for control in CONTROLS:
            self.pad_widget.add_control(control, self.control_button(control))
        for number in (1, 2):
            self.pad_widget.add_knob(number)
        self.pad_widget.rotation_clicked.connect(self.select_rotation)
        body = QHBoxLayout()
        body.setContentsMargins(M, XS, L, M)
        body.setSpacing(M)
        preview_column = QVBoxLayout()
        preview_column.setSpacing(XS)
        preview_column.addWidget(self.pad_widget, 1)
        body.addLayout(preview_column, 1)

        assignment = QFrame()
        assignment.setObjectName("editorPanel")
        assignment.setFixedWidth(310 if sys.platform == "win32" else ui_size(350))
        editor = QVBoxLayout(assignment)
        editor.setContentsMargins(L, L, L, L)
        editor.setSpacing(S)
        profile_row = QHBoxLayout()
        self.profile_button = QPushButton()
        self.profile_button.setObjectName("profileButton")
        self.profile_button.setMaximumWidth(assignment.width() - 2 * L)
        self.profile_button.setFixedHeight(INPUT_HEIGHT)
        self.profile_button.clicked.connect(self.open_profile_menu)
        profile_row.addWidget(self.profile_button)
        profile_row.addStretch()
        editor.addLayout(profile_row)
        self.current_assignment = QLabel(self)
        self.current_assignment.hide()
        self.name_field = QLineEdit()
        self.name_field.setObjectName("displayName")
        self.name_field.setFixedHeight(INPUT_HEIGHT)
        self.name_field.textEdited.connect(self.mark_dirty)
        editor.addWidget(self.name_field)
        separator = QFrame()
        separator.setObjectName("separator")
        separator.setFixedHeight(1)
        editor.addWidget(separator)

        # Preserve the existing action-type model/signals behind visible tabs.
        self.action_type = QComboBox(self)
        self.action_type.hide()
        self.type_controls = QWidget()
        type_layout = QHBoxLayout(self.type_controls)
        type_layout.setContentsMargins(0, 0, 0, 0)
        type_layout.setSpacing(S)
        self.type_group = QButtonGroup(self)
        self.type_buttons = {}
        for label, name in (("Hot key", "hotkey"), ("Media key", "media_key"), ("Unassigned", "unassigned")):
            self.action_type.addItem(label, name)
            if name == "unassigned":
                continue
            button = QPushButton(label)
            button.setObjectName("typeOption")
            button.setCheckable(True)
            button.setFixedHeight(INPUT_HEIGHT)
            self.type_group.addButton(button, self.action_type.count() - 1)
            self.type_buttons[name] = button
            type_layout.addWidget(button, 1)
        self.type_group.idClicked.connect(self.action_type.setCurrentIndex)
        editor.addWidget(self.type_controls)

        self.direction_controls = QWidget()
        directions = QHBoxLayout(self.direction_controls)
        directions.setContentsMargins(0, 0, 0, 0)
        directions.setSpacing(S)
        directions.addStretch()
        self.direction_group = QButtonGroup(self)
        self.direction_buttons = {}
        for action, text in (("CCW", "←"), ("CW", "→")):
            button = QPushButton(text)
            button.setObjectName("directionButton")
            button.setCheckable(True)
            button.setFixedSize(ui_size(48), INPUT_HEIGHT)
            button.setToolTip("Turn left" if action == "CCW" else "Turn right")
            button.clicked.connect(lambda checked=False, direction=action: self.select_direction(direction))
            self.direction_group.addButton(button)
            self.direction_buttons[action] = button
            directions.addWidget(button)
        directions.addStretch()
        editor.addWidget(self.direction_controls)

        self.hotkey_widget = QWidget()
        hotkey_layout = QVBoxLayout(self.hotkey_widget)
        hotkey_layout.setContentsMargins(0, 0, 0, 0)
        hotkey_layout.setSpacing(S)
        self.recorder = ShortcutRecorder()
        self.recorder.setObjectName("shortcutPreview")
        self.recorder.setMinimumHeight(INPUT_HEIGHT)
        self.record_button = QPushButton("Record shortcut")
        self.escape_button = QPushButton("Use Esc")
        self.record_button.setFixedHeight(INPUT_HEIGHT)
        self.escape_button.setFixedHeight(INPUT_HEIGHT)
        record_actions = QHBoxLayout()
        record_actions.setSpacing(S)
        record_actions.addWidget(self.record_button, 1)
        record_actions.addWidget(self.escape_button)
        hotkey_layout.addLayout(record_actions)
        hotkey_layout.addWidget(self.recorder)
        editor.addWidget(self.hotkey_widget)

        self.media_widget = QComboBox()
        self.media_widget.setFixedHeight(INPUT_HEIGHT)
        if sys.platform == "darwin":
            # Qt's combo box style otherwise replaces the fixed minimum height.
            content_height = INPUT_HEIGHT - 2 * XS - 2
            self.media_widget.setStyleSheet(f"QComboBox {{ min-height: {content_height}px; }}")
        for name, label in MEDIA_LABELS.items():
            self.media_widget.addItem(label, name)
        editor.addWidget(self.media_widget)
        editor.addStretch(1)
        self.save_button = QPushButton("Save")
        self.save_button.setObjectName("saveButton")
        self.save_button.setMinimumWidth(ui_size(80))
        self.clear_button = QPushButton("Clear / Unassigned")
        self.clear_button.setObjectName("clearButton")
        self.save_button.setFixedHeight(INPUT_HEIGHT)
        self.clear_button.setFixedHeight(INPUT_HEIGHT)
        buttons = QHBoxLayout()
        buttons.setSpacing(S)
        buttons.addWidget(self.clear_button)
        buttons.addStretch()
        buttons.addWidget(self.save_button)
        editor.addLayout(buttons)
        body.addWidget(assignment)
        layout.addLayout(body, 1)

        status_bar = QFrame()
        status_bar.setObjectName("statusBar")
        status_layout = QHBoxLayout(status_bar)
        status_layout.setContentsMargins(L, XS, L, XS)
        status_layout.setSpacing(M)
        status_layout.addWidget(self.device)
        status_layout.addStretch()
        self.status = QLabel(self.store.error or "Searching...", self)
        self.status.hide()
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.eye_button = EyeButton()
        self.eye_button.setObjectName("eyeButton")
        self.eye_button.toggled.connect(self.toggle_show_mode)
        self.eye_button.easter_egg_requested.connect(self.show_easter_egg)
        status_layout.addWidget(self.eye_button)
        layout.addWidget(status_bar)

        self.controls.idClicked.connect(self.select_control)
        self.edit_profile.currentTextChanged.connect(self.choose_profile)
        self.action_type.currentIndexChanged.connect(self.type_changed)
        self.media_widget.currentIndexChanged.connect(self.mark_dirty)
        self.record_button.clicked.connect(self.recorder.start)
        self.escape_button.clicked.connect(lambda: self.set_shortcut(["escape"]))
        self.recorder.recorded.connect(self.set_shortcut)
        self.recorder.cancelled.connect(self.restore_shortcut_preview)
        self.recorder.recording_changed.connect(self.recording_changed)
        self.save_button.clicked.connect(self.save_assignment)
        self.clear_button.clicked.connect(self.clear_assignment)
        self.buttons[self.selected_control].setChecked(True)
        self.load_assignment()
        self.sync_profile()
        self.set_connection(False)

        self.easter_overlay = EasterOverlay(self)
        self.easter_timer = QTimer(self)
        self.easter_timer.setSingleShot(True)
        self.easter_timer.setInterval(1000)
        self.easter_timer.timeout.connect(self.easter_overlay.hide)
        self.easter_sound = None
        self.audio_failed = False

        self.worker = EngineWorker(self.store, self.gate, self)
        self.start_foreground_monitor()
        self.worker.connection_changed.connect(self.set_connection)
        self.worker.profile_changed.connect(self.set_profile)
        self.worker.status_changed.connect(self.set_status)
        self.worker.activity_changed.connect(self.show_activity, Qt.ConnectionType.QueuedConnection)
        self.worker.finished.connect(self.worker_finished)
        QApplication.instance().installEventFilter(self)
        QApplication.instance().aboutToQuit.connect(self.stop_foreground_monitor)
        self.worker.start()

    def start_foreground_monitor(self):
        self.foreground_monitor = None
        if sys.platform == "darwin":
            monitor = MacForegroundMonitor(self.store, self)
            monitor.profile_changed.connect(self.set_profile)
            if monitor.start():
                self.foreground_monitor = monitor
                self.worker.watch_foreground = False
            else:
                monitor.deleteLater()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Wheel:
            # Popup menus/views remain descendants through their QObject parents.
            # Filter only this window's UI; action output and other windows are unaffected.
            current = watched
            while current is not None:
                if current is self:
                    event.accept()
                    return True
                current = current.parent()
        return super().eventFilter(watched, event)

    def control_button(self, event):
        button = DeviceControl(event)
        self.controls.addButton(button, CONTROLS.index(event))
        self.buttons[event] = button
        return button

    @Slot(int)
    def select_control(self, index):
        self.selected_control = CONTROLS[index]
        self.buttons[self.selected_control].setChecked(True)
        self.load_assignment()

    def select_direction(self, direction):
        if self.selected_control.startswith("ENC"):
            encoder = self.selected_control.split(":")[0]
            self.select_control(CONTROLS.index(f"{encoder}:{direction}"))

    def select_rotation(self, number):
        event = self.selected_control
        if event not in (f"ENC{number}:CW", f"ENC{number}:CCW"):
            event = f"ENC{number}:CW"
        self.select_control(CONTROLS.index(event))

    @staticmethod
    def control_name(event):
        if event.startswith("KEY:"):
            return f"Key {event.split(':')[1]}"
        encoder, action = event.split(":")
        name = "Left encoder" if encoder == "ENC1" else "Right encoder"
        return f"{name} — " + {"CCW": "turn left", "CW": "turn right", "PRESS": "click"}[action]

    def toggle_show_mode(self, enabled):
        self.pad_widget.show_labels = enabled
        self.eye_button.setToolTip("Hide key names" if enabled else "Show key names")
        self.refresh_controls()

    @Slot(str, str, bool, str)
    def show_activity(self, profile, event, assigned, label):
        if self.closing or profile != self.store.current_profile() or event not in self.buttons:
            return
        if self.edit_profile.currentText() != profile:
            self.sync_profile()
        self.pad_widget.flash_activity(event, assigned, label)

    def show_easter_egg(self):
        if self.closing:
            return
        self.easter_overlay.setGeometry(self.rect())
        self.easter_overlay.show()
        self.easter_overlay.raise_()
        self.easter_timer.start()
        if self.audio_failed or QSoundEffect is None:
            return
        try:
            if self.easter_sound is None:
                self.easter_sound = QSoundEffect(self)
                self.easter_sound.setLoopCount(1)
                self.easter_sound.setVolume(0.7)
                self.easter_sound.statusChanged.connect(self.check_easter_audio)
                self.easter_sound.setSource(QUrl.fromLocalFile(resource_path("assets/easter_egg.wav")))
            self.easter_sound.play()
        except (OSError, RuntimeError):
            self.audio_failed = True

    def check_easter_audio(self):
        if self.easter_sound is not None and self.easter_sound.status() == QSoundEffect.Status.Error:
            self.audio_failed = True

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "easter_overlay"):
            self.easter_overlay.setGeometry(self.rect())

    def refresh_controls(self):
        profile = self.edit_profile.currentText()
        for event, button in self.buttons.items():
            label = self.store.label(profile, label_event(event))
            button.show_label = self.pad_widget.show_labels if event.startswith("KEY:") else event.endswith(":PRESS")
            button.setText(label if event.startswith("KEY:") or event.endswith(":PRESS") else "")
            name = self.control_name(event)
            button.setAccessibleName(name)
            button.setToolTip(f"{name}: {label}" if label else name)
            button.setAccessibleDescription(label)
            button.update()
        for number in (1, 2):
            name = self.store.label(profile, f"ENC{number}:ROTATE")
            self.pad_widget.encoder_names[number] = name
            knob = self.pad_widget.knobs[number]
            knob.setChecked(self.selected_control in (f"ENC{number}:CW", f"ENC{number}:CCW"))
            knob.setAccessibleDescription(name)
            knob.setToolTip(f"{knob.accessibleName()}: {name}" if name else knob.accessibleName())
        self.pad_widget.update()

    def sync_profile(self):
        active = self.store.current_profile()
        _, profiles, _ = self.store.snapshot()
        changed = self.edit_profile.currentText() != active
        blocked = self.edit_profile.blockSignals(True)
        self.edit_profile.clear()
        self.edit_profile.addItems(list(profiles))
        self.edit_profile.setCurrentText(active)
        self.edit_profile.blockSignals(blocked)
        self.profile.setText(active)
        locked = self.store.locked_profile() is not None
        available = self.profile_button.maximumWidth() - ui_size(54 if locked else 30)
        self.profile_button.setText(self.profile_button.fontMetrics().elidedText(active, Qt.TextElideMode.ElideRight, available))
        self.profile_button.setIcon(lock_icon() if locked else QIcon())
        self.profile_button.setToolTip(f"{active} (locked)" if locked else active)
        if self.tray is not None:
            self.tray.set_profile(active)
        if changed:
            self.pad_widget.clear_activity()
            self.load_assignment()

    def choose_profile(self, profile):
        try:
            # Manual choices expire on app activation; keep the configured fallback intact.
            self.store.select_profile(profile, update_default=False)
        except (OSError, ValueError) as error:
            self.sync_profile()
            self.report_error("Profile not changed", error)
            return
        self.sync_profile()
        self.load_assignment()

    def open_profile_menu(self):
        self.sync_profile()
        menu = QMenu(self.profile_button)
        menu.setMinimumWidth(ui_size(160))
        current = self.store.current_profile()
        for name in self.store.snapshot()[1]:
            item = menu.addAction(name)
            item.setCheckable(True)
            item.setChecked(name == current)
            item.triggered.connect(lambda checked=False, target=name: self.choose_profile(target))
        menu.addSeparator()
        menu.addAction("Add...", self.add_profile)
        menu.addAction("Rename...", self.rename_profile)
        delete = menu.addAction("Delete...", self.delete_profile)
        delete.setEnabled(len(self.store.snapshot()[1]) > 1)
        menu.addAction("Import...", self.import_profile)
        menu.addAction("Export...", self.export_profile)
        if sys.platform in ("darwin", "win32"):
            menu.addAction("Assign Application…", self.assign_application)
            assignments = menu.addMenu("Application Assignments")
            try:
                identifiers = self.store.application_assignments(current)
            except ValueError:
                identifiers = []
            assignments.setEnabled(bool(identifiers) and not self.store.error)
            for identifier in identifiers:
                item = assignments.addAction(f"Remove {identifier}")
                item.triggered.connect(lambda checked=False, target=current, app_id=identifier:
                                       self.remove_application(target, app_id))
        menu.addSeparator()
        menu.addAction("Unlock profile" if self.store.locked_profile() else "Lock profile", self.toggle_profile_lock)
        if self.store.error:
            for action in menu.actions():
                action.setEnabled(False)
        self.profile_menu = menu
        menu.aboutToHide.connect(menu.deleteLater)
        menu.popup(self.profile_button.mapToGlobal(QPoint(0, self.profile_button.height() + 4)))

    def report_error(self, title, error):
        self.set_status(f"{title}: {error}")
        QMessageBox.warning(self, title, str(error))

    def assign_application(self):
        if sys.platform not in ("darwin", "win32"):
            return
        profile = self.store.current_profile()
        try:
            if sys.platform == "win32":
                path = choose_windows_executable(self)
                if not path:
                    return
                identifier, alias = read_windows_executable(path)
            else:
                path = choose_application_bundle()
                if not path:
                    return
                identifier, alias = read_application_bundle(path)
            bindings = self.store.application_bindings(identifier, alias)
            exact = {target for key, target in bindings.items() if key.lower() == identifier}
            owners = exact or set(bindings.values())
            others = sorted(owners - {profile})
            if others and not ConfirmationDialog.confirm(
                    self, "Reassign Application",
                    f'{Path(path).name} is assigned to {", ".join(others)}. '
                    f'Assign it to "{profile}" instead?', "Reassign"):
                return
            self.store.assign_application(profile, identifier, bindings, alias)
            self.reconcile_foreground_profile()
            self.set_status(f"Application assigned to {profile}")
        except (OSError, ValueError, ImportError) as error:
            self.report_error("Application not assigned", error)

    def remove_application(self, profile, identifier):
        if sys.platform not in ("darwin", "win32"):
            return
        try:
            if not ConfirmationDialog.confirm(
                    self, "Remove Application Assignment",
                    f'Remove {identifier} from "{profile}"? Automatic aliases and the default profile will apply.',
                    "Remove"):
                return
            self.store.remove_application(profile, identifier)
            self.reconcile_foreground_profile()
            self.set_status("Application assignment removed")
        except (OSError, ValueError) as error:
            self.report_error("Application assignment not removed", error)

    def add_profile(self):
        name, accepted = ProfileNameDialog.get_name(self, self.store, "Add Profile", "Add")
        if not accepted:
            return
        try:
            name = self.store.add_profile(name)
            self.choose_profile(name)
        except (OSError, ValueError) as error:
            self.report_error("Profile not added", error)

    def delete_profile(self):
        profile = self.store.current_profile()
        if not ConfirmationDialog.confirm(self, "Delete Profile",
                                          f'Delete "{profile}" and its assignments?', "Delete"):
            return
        try:
            self.store.delete_profile(profile)
            self.sync_profile()
            self.load_assignment()
        except (OSError, ValueError) as error:
            self.report_error("Profile not deleted", error)

    def rename_profile(self):
        profile = self.store.current_profile()
        name, accepted = ProfileNameDialog.get_name(self, self.store, "Rename Profile", "Rename", profile)
        if not accepted:
            return
        try:
            self.store.rename_profile(profile, name)
            self.sync_profile()
        except (OSError, ValueError) as error:
            self.report_error("Profile not renamed", error)

    def export_profile(self):
        profile = self.store.current_profile()
        path, _ = QFileDialog.getSaveFileName(self, "Export Profile", f"{profile}.json", "JSON files (*.json)")
        if not path:
            return
        try:
            self.store.export_profile(profile, path, overwrite=True)
            self.set_status("Profile exported")
        except (OSError, ValueError) as error:
            self.report_error("Profile not exported", error)

    def import_profile(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import Profile", "", "JSON files (*.json)")
        if not path:
            return
        try:
            name, _, _ = self.store.read_profile_import(path)
            existing = self.store.snapshot()[1]
            if name in existing:
                suffix = 2
                while f"{name} ({suffix})" in existing:
                    suffix += 1
                name, accepted = QInputDialog.getText(self, "Import Profile", "Choose a new profile name:",
                                                      text=f"{name} ({suffix})")
                if not accepted:
                    return
            name = self.store.import_profile(path, name)
            self.choose_profile(name)
        except (OSError, ValueError) as error:
            self.report_error("Profile not imported", error)

    def toggle_profile_lock(self):
        try:
            self.store.set_locked_profile(None if self.store.locked_profile() else self.store.current_profile())
            self.sync_profile()
        except (OSError, ValueError) as error:
            self.report_error("Profile lock not changed", error)

    def load_assignment(self, *_):
        self.recorder.finish()
        self.loading = True
        action = self.store.mapping(self.edit_profile.currentText(), self.selected_control)
        self.current_assignment.setText(action_label(action))
        self.name_field.setText(self.store.label(self.edit_profile.currentText(), label_event(self.selected_control)))
        self.name_field.setPlaceholderText(f"{self.control_name(self.selected_control)} name")
        self.name_field.setToolTip(self.control_name(self.selected_control))
        self.direction_controls.setVisible(self.selected_control.startswith("ENC") and not self.selected_control.endswith(":PRESS"))
        self.direction_group.setExclusive(False)
        for direction, button in self.direction_buttons.items():
            button.setChecked(self.selected_control.endswith(":" + direction))
        self.direction_group.setExclusive(True)
        action = action if isinstance(action, dict) and resolve_action(action) is not None else {}
        kind = action.get("type", "unassigned")
        self.action_type.setCurrentIndex(self.action_type.findData(kind))
        self.shortcut = list(action.get("keys", [])) if kind == "hotkey" else []
        self.restore_shortcut_preview()
        self.media_widget.setCurrentIndex(max(0, self.media_widget.findData(action.get("key"))))
        self.loading = False
        self.dirty = False
        self.type_changed()
        self.dirty = False
        self.update_save_button()
        self.clear_button.setEnabled(not self.store.error)
        self.refresh_controls()

    def type_changed(self, *_):
        kind = self.action_type.currentData()
        self.type_group.setExclusive(False)
        for name, button in self.type_buttons.items():
            button.setChecked(name == kind)
        self.type_group.setExclusive(True)
        self.hotkey_widget.setVisible(kind == "hotkey")
        self.media_widget.setVisible(kind == "media_key")
        self.mark_dirty()

    def mark_dirty(self, *_):
        if not self.loading:
            self.dirty = True
            self.update_save_button()

    def update_save_button(self):
        valid = self.action_type.currentData() != "hotkey" or bool(self.shortcut)
        self.save_button.setEnabled(self.dirty and valid and not self.store.error and not self.recorder.active)

    @Slot(list)
    def set_shortcut(self, shortcut):
        self.shortcut = list(shortcut)
        self.restore_shortcut_preview()
        self.mark_dirty()

    def restore_shortcut_preview(self):
        self.recorder.setText(shortcut_label(self.shortcut) if self.shortcut else "")

    @Slot(bool)
    def recording_changed(self, recording):
        self.gate.set_paused(recording)
        self.recorder.setMinimumHeight(ui_size(56) if recording else INPUT_HEIGHT)
        for widget in (self.pad_widget, self.edit_profile, self.profile_button, self.action_type,
                       self.type_controls, self.direction_controls, self.name_field, self.record_button,
                       self.escape_button, self.clear_button):
            widget.setEnabled(not recording)
        self.update_save_button()
        if not self.closing:
            self.status.setText("Recording shortcut — Macro Pad actions paused" if recording else "Ready")
            self.device.setToolTip(self.status.text())

    def save_assignment(self):
        # Do not commit a stale draft if an automatic notification is still queued.
        if self.edit_profile.currentText() != self.store.current_profile():
            self.sync_profile()
            self.set_status("Profile changed; select and edit the assignment again")
            return
        kind = self.action_type.currentData()
        action = {"type": kind}
        if kind == "hotkey":
            action["keys"] = list(self.shortcut)
        elif kind == "media_key":
            action["key"] = self.media_widget.currentData()
        try:
            changed = self.store.save_assignment(self.edit_profile.currentText(), self.selected_control,
                                                 action, self.name_field.text())
        except (OSError, ValueError) as error:
            self.report_error("Not saved", error)
            return
        self.load_assignment()
        self.set_status("Saved — active immediately" if changed else "Assignment unchanged")

    def clear_assignment(self):
        self.action_type.setCurrentIndex(self.action_type.findData("unassigned"))
        self.save_assignment()

    @Slot(bool)
    def set_connection(self, connected):
        self.device.setToolTip("Connected" if connected else "Disconnected")
        self.device.setProperty("connected", connected)
        self.device.style().unpolish(self.device)
        self.device.style().polish(self.device)
        self.device.update()
        self.pad_widget.connected = connected
        if not connected:
            self.pad_widget.clear_activity()
        self.pad_widget.update()

    @Slot(str)
    def set_profile(self, profile):
        # Ignore stale queued notifications and display current shared state.
        self.sync_profile()

    @Slot(str)
    def set_status(self, status):
        if not self.closing and not self.recorder.active:
            self.status.setText(status)
            self.device.setToolTip(("Connected" if self.pad_widget.connected else "Disconnected") + f" — {status}")

    @Slot()
    def worker_finished(self):
        if self.closing:
            self.close()
            if self.quit_requested:
                QApplication.quit()

    def attach_tray(self, tray):
        """Run from the tray: closing the window hides it; Quit is in the tray menu."""
        self.tray = tray
        tray.open_requested.connect(self.show_from_tray)
        tray.quit_requested.connect(self.request_quit)
        self.worker.connection_changed.connect(tray.set_connection)
        tray.set_connection(self.pad_widget.connected)
        tray.set_profile(self.store.current_profile())
        tray.show()

    @Slot()
    def show_from_tray(self):
        if self.closing:
            return
        self.showNormal()
        self.raise_()
        self.activateWindow()
        if sys.platform == "darwin":
            # Menu-bar apps have no Dock icon, so bring the app itself forward.
            try:
                from AppKit import NSApp
                NSApp.activateIgnoringOtherApps_(True)
            except Exception:
                pass

    def hide_to_tray(self):
        self.stop_easter_egg()
        self.pad_widget.clear_activity()
        self.recorder.finish()
        self.hide()
        self.tray.show_hidden_hint()

    @Slot()
    def request_quit(self):
        """Really quit: stop the engine, then leave the event loop."""
        self.quit_requested = True
        self.close()  # Starts the engine shutdown; worker_finished() then quits.
        if not self.worker.isRunning():
            QApplication.quit()

    def reconcile_foreground_profile(self):
        if self.foreground_monitor is not None:
            self.foreground_monitor.reconcile()

    @Slot()
    def stop_foreground_monitor(self):
        if self.foreground_monitor is not None:
            self.foreground_monitor.stop()

    def closeEvent(self, event):
        if self.recorder.active and self.recorder.candidate == ["alt", "f4"]:
            # A system close request caused by the shortcut being recorded.
            event.ignore()
        elif self.tray is not None and not self.quit_requested:
            event.ignore()
            self.hide_to_tray()
        elif self.worker.isRunning():
            self.stop_foreground_monitor()
            self.stop_easter_egg()
            self.pad_widget.clear_activity()
            self.closing = True
            self.status.setText("Closing...")
            self.worker.stop.set()
            self.recorder.finish()
            self.setEnabled(False)
            event.ignore()
        else:
            self.stop_foreground_monitor()
            self.stop_easter_egg()
            self.pad_widget.clear_activity()
            self.recorder.finish()
            event.accept()

    def stop_easter_egg(self):
        self.easter_timer.stop()
        self.easter_overlay.hide()
        if self.easter_sound is not None:
            try:
                self.easter_sound.stop()
            except (OSError, RuntimeError):
                pass


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(application_name())
    icon = QIcon(resource_path("assets/app_icon.png"))
    app.setWindowIcon(icon)

    instance = SingleInstance(application_name())
    if not instance.acquire():
        # Already running: bring that copy's window up instead of starting another.
        instance.notify_running()
        return 0
    instance.listen()

    window = MacroPadWindow()
    tray = None
    if TrayIcon.available():
        autostart = platform_autostart()
        if autostart is not None:
            try:
                autostart.refresh()  # Follow the app if its folder was moved.
            except OSError:
                pass
        tray = TrayIcon(icon, application_name(), window, autostart)
        window.attach_tray(tray)
        app.setQuitOnLastWindowClosed(False)
    instance.activation_requested.connect(window.show_from_tray if tray else window.showNormal)
    if tray is None or BACKGROUND_FLAG not in sys.argv[1:]:
        window.show()

    try:
        exit_code = app.exec()
    finally:
        if tray is not None:
            tray.hide()
        instance.release()
        window.stop_foreground_monitor()
        window.worker.stop.set()
        window.recorder.finish()
        window.worker.wait()

        # PyInstaller + macOS: destroy Qt widgets before Python finalization.
        if sys.platform == "darwin" and getattr(sys, "frozen", False):
            import shiboken6
            shiboken6.delete(window)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
