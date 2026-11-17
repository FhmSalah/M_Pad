"""Focused Qt shortcut recorder; no global keyboard hook or injected keys."""

import sys

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import QLabel

from shortcut_keys import MODIFIER_NAMES, PUNCTUATION, WINDOWS_PUNCTUATION, shortcut_label

QT_KEYS = {
    Qt.Key.Key_Control: "cmd" if sys.platform == "darwin" else "ctrl",
    Qt.Key.Key_Shift: "shift", Qt.Key.Key_Alt: "alt",
    Qt.Key.Key_Meta: "ctrl" if sys.platform == "darwin" else "cmd",
    Qt.Key.Key_Up: "up", Qt.Key.Key_Down: "down",
    Qt.Key.Key_Left: "left", Qt.Key.Key_Right: "right",
    Qt.Key.Key_Space: "space", Qt.Key.Key_Return: "enter", Qt.Key.Key_Enter: "enter",
    Qt.Key.Key_Tab: "tab", Qt.Key.Key_Backtab: "tab", Qt.Key.Key_Escape: "escape",
    Qt.Key.Key_Backspace: "backspace", Qt.Key.Key_Delete: "delete",
    Qt.Key.Key_Home: "home", Qt.Key.Key_End: "end", Qt.Key.Key_PageUp: "page_up",
    Qt.Key.Key_PageDown: "page_down", Qt.Key.Key_Insert: "insert",
    **{getattr(Qt.Key, f"Key_F{n}"): f"f{n}" for n in range(1, 13)},
}
QT_MODIFIERS = {
    Qt.KeyboardModifier.ControlModifier: "cmd" if sys.platform == "darwin" else "ctrl",
    Qt.KeyboardModifier.ShiftModifier: "shift",
    Qt.KeyboardModifier.AltModifier: "alt",
    Qt.KeyboardModifier.MetaModifier: "ctrl" if sys.platform == "darwin" else "cmd",
}
SHIFTED_SYMBOLS = {
    "{": "left_bracket", "}": "right_bracket", "|": "backslash",
    ":": "semicolon", '"': "apostrophe", "<": "comma", ">": "period",
    "?": "slash", "_": "minus", "+": "equal", "~": "grave",
}


def event_key_name(event):
    """Convert backend keyboard events to portable config names."""
    key = event.key()
    if key in QT_KEYS:
        return QT_KEYS[key]
    native = event.nativeVirtualKey()
    if sys.platform == "win32":
        if native in WINDOWS_PUNCTUATION:
            return WINDOWS_PUNCTUATION[native]
        if 0x30 <= native <= 0x39 or 0x41 <= native <= 0x5A:
            return chr(native).lower()
    if ord("A") <= key <= ord("Z") or ord("0") <= key <= ord("9"):
        return chr(key).lower()
    if key < 0x110000:
        symbol = chr(key)
        names = {symbol: name for name, symbol in PUNCTUATION.items()}
        return names.get(symbol, SHIFTED_SYMBOLS.get(symbol))
    return None


class ShortcutRecorder(QLabel):
    recording_changed = Signal(bool)
    recorded = Signal(list)
    cancelled = Signal()

    def __init__(self, parent=None):
        super().__init__("No shortcut", parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setWordWrap(True)
        self.active = False
        self.held = set()
        self.candidate = None
        self.wait_modifiers = set()
        self.invalid_chord = False

    def start(self):
        if self.active:
            return
        self.active = True
        self.held.clear()
        self.candidate = None
        self.wait_modifiers.clear()
        self.invalid_chord = False
        self.recording_changed.emit(True)
        self.setText("Press a shortcut; release all keys to finish. Esc cancels.")
        self.setFocus()
        self.grabKeyboard()

    def finish(self, shortcut=None):
        if not self.active:
            return
        self.active = False
        self.held.clear()
        self.wait_modifiers.clear()
        self.candidate = None
        self.invalid_chord = False
        self.releaseKeyboard()
        if shortcut is None:
            self.cancelled.emit()
        else:
            self.recorded.emit(shortcut)
        self.recording_changed.emit(False)

    def event(self, event):
        if self.active and event.type() == QEvent.Type.ShortcutOverride:
            event.accept()
            return True
        if self.active and event.type() == QEvent.Type.KeyPress:
            self.keyPressEvent(event)
            return True  # Capture Tab too, rather than moving Qt focus.
        if self.active and event.type() == QEvent.Type.KeyRelease:
            self.keyReleaseEvent(event)
            return True
        return super().event(event)

    def keyPressEvent(self, event):
        if not self.active:
            super().keyPressEvent(event)
            return
        event.accept()
        if event.isAutoRepeat():
            return
        name = event_key_name(event)
        if name == "escape":
            self.finish()
            return
        self.held.add(event.nativeVirtualKey() or event.key())
        if name is None:
            self.candidate = None
            self.invalid_chord = True
            self.setText("Unsupported key. Try another shortcut, or Esc to cancel.")
            return
        if name in MODIFIER_NAMES:
            return
        if self.candidate is not None or self.invalid_chord:
            # Only one primary key per shortcut; do not record key sequences.
            self.candidate = None
            self.invalid_chord = True
            self.setText("Use one normal key with modifiers. Esc cancels.")
            return
        modifiers = {name for flag, name in QT_MODIFIERS.items() if event.modifiers() & flag}
        self.wait_modifiers = set(modifiers)
        self.candidate = [name for name in MODIFIER_NAMES if name in modifiers] + [name]
        self.setText(shortcut_label(self.candidate))

    def keyReleaseEvent(self, event):
        if not self.active:
            super().keyReleaseEvent(event)
            return
        event.accept()
        if event.isAutoRepeat():
            return
        self.held.discard(event.nativeVirtualKey() or event.key())
        self.wait_modifiers.discard(event_key_name(event))
        if not self.held and not self.wait_modifiers and self.candidate is not None:
            self.finish(self.candidate)
        elif not self.held and self.invalid_chord:
            self.invalid_chord = False
            self.wait_modifiers.clear()

    def focusOutEvent(self, event):
        self.finish()
        super().focusOutEvent(event)
