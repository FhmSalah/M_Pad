"""Portable config key names shared by the editor and action engine."""

import sys
from dataclasses import dataclass

from pynput.keyboard import Key, KeyCode

MODIFIER_NAMES = ("ctrl", "shift", "alt", "cmd")
MODIFIERS = {name: getattr(Key, name) for name in MODIFIER_NAMES}
SPECIAL_NAMES = (
    "up", "down", "left", "right", "space", "enter", "tab", "escape",
    "backspace", "delete", "home", "end", "page_up", "page_down", "insert",
) + tuple(f"f{number}" for number in range(1, 13))
SPECIAL_KEYS = {name: getattr(Key, name, None) for name in SPECIAL_NAMES}
SPECIAL_KEYS["escape"] = Key.esc
PUNCTUATION = {
    "left_bracket": "[", "right_bracket": "]", "backslash": "\\",
    "semicolon": ";", "apostrophe": "'", "comma": ",", "period": ".",
    "slash": "/", "minus": "-", "equal": "=", "grave": "`",
}
# Windows OEM keys identify physical punctuation positions, even with Shift.
# These backend codes are never written to config.json.
WINDOWS_PUNCTUATION = {
    0xDB: "left_bracket", 0xDD: "right_bracket", 0xDC: "backslash",
    0xBA: "semicolon", 0xDE: "apostrophe", 0xBC: "comma", 0xBE: "period",
    0xBF: "slash", 0xBD: "minus", 0xBB: "equal", 0xC0: "grave",
}
MEDIA_LABELS = {
    "volume_up": "Volume Up", "volume_down": "Volume Down",
    "volume_mute": "Mute", "play_pause": "Play / Pause",
    "scroll_up": "Scroll Up", "scroll_down": "Scroll Down",
}
SCROLL_STEPS = {"scroll_up": 1, "scroll_down": -1}


@dataclass(frozen=True)
class ScrollAction:
    steps: int


MEDIA_KEYS = {
    name: getattr(Key, f"media_{name}", None) for name in MEDIA_LABELS
}
KEY_LABELS = {
    "ctrl": "Ctrl", "shift": "Shift", "alt": "Alt", "cmd": "Win / Cmd",
    "page_up": "Page Up", "page_down": "Page Down", "escape": "Esc",
    **PUNCTUATION,
}


def resolve_key(name):
    if not isinstance(name, str):
        return None
    if name in MODIFIERS:
        return MODIFIERS[name]
    if name in SPECIAL_KEYS:
        return SPECIAL_KEYS[name]
    if name in PUNCTUATION:
        if sys.platform == "win32":
            code = next(code for code, key in WINDOWS_PUNCTUATION.items() if key == name)
            return KeyCode.from_vk(code)
        return PUNCTUATION[name]
    if len(name) == 1 and name in "abcdefghijklmnopqrstuvwxyz0123456789":
        return name
    return None


def resolve_action(action):
    """Return executable keys, [] for Unassigned, or None for an invalid entry."""
    if not isinstance(action, dict):
        return None
    if action.get("type") == "unassigned":
        return []
    if action.get("type") == "media_key":
        name = action.get("key")
        if isinstance(name, str) and name in SCROLL_STEPS:
            return [ScrollAction(SCROLL_STEPS[name])]
        key = MEDIA_KEYS.get(name) if isinstance(name, str) else None
        return [key] if key is not None else None
    if action.get("type") != "hotkey":
        return None
    names = action.get("keys")
    if not isinstance(names, list) or not names or not all(isinstance(n, str) for n in names):
        return None
    if len(set(names)) != len(names):
        return None
    keys = [resolve_key(name) for name in names]
    return keys if all(key is not None for key in keys) else None


def shortcut_label(names):
    return " + ".join(KEY_LABELS.get(name, name.upper() if len(name) == 1 else name.title())
                      for name in names)


def action_label(action):
    if action is None or action == {"type": "unassigned"}:
        return "Unassigned"
    if resolve_action(action) is None:
        return "Invalid or unsupported assignment (preserved)"
    if action["type"] == "hotkey":
        return shortcut_label(action["keys"])
    if action["type"] == "media_key":
        return MEDIA_LABELS[action["key"]]
    return "Unassigned"
