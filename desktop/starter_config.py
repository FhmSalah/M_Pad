"""The key mappings a brand-new user starts with (written once, on first run).

Windows uses Ctrl shortcuts; macOS uses the Cmd equivalents. Apps are matched to the
Browser profile by the built-in application names, so no "applications" are needed.
"""

import sys


def _hotkey(*keys):
    return {"type": "hotkey", "keys": list(keys)}


def _media(key):
    return {"type": "media_key", "key": key}


def _knobs():
    return {
        "ENC1:CW": _media("volume_up"), "ENC1:CCW": _media("volume_down"),
        "ENC1:PRESS": _media("play_pause"),
        "ENC2:CW": _media("scroll_up"), "ENC2:CCW": _media("scroll_down"),
        "ENC2:PRESS": _media("volume_mute"),
    }


KNOB_LABELS = {"ENC1:ROTATE": "Volume", "ENC1:PRESS": "Play/Pause",
               "ENC2:ROTATE": "Scroll", "ENC2:PRESS": "Mute"}

# (label, Windows keys, macOS keys) for KEY:1 .. KEY:12
GENERAL_KEYS = [
    ("Copy", ("ctrl", "c"), ("cmd", "c")),
    ("Paste", ("ctrl", "v"), ("cmd", "v")),
    ("Cut", ("ctrl", "x"), ("cmd", "x")),
    ("Undo", ("ctrl", "z"), ("cmd", "z")),
    ("Redo", ("ctrl", "y"), ("cmd", "shift", "z")),
    ("Save", ("ctrl", "s"), ("cmd", "s")),
    ("Select all", ("ctrl", "a"), ("cmd", "a")),
    ("Find", ("ctrl", "f"), ("cmd", "f")),
    ("New tab", ("ctrl", "t"), ("cmd", "t")),
    ("Close tab", ("ctrl", "w"), ("cmd", "w")),
    ("Reopen tab", ("ctrl", "shift", "t"), ("cmd", "shift", "t")),
    ("Screenshot", ("cmd", "shift", "s"), ("cmd", "shift", "4")),  # Win+Shift+S on Windows
]

BROWSER_KEYS = [
    ("Back", ("alt", "left"), ("cmd", "left_bracket")),
    ("Forward", ("alt", "right"), ("cmd", "right_bracket")),
    ("Reload", ("ctrl", "r"), ("cmd", "r")),
    ("Address bar", ("ctrl", "l"), ("cmd", "l")),
    ("Prev tab", ("ctrl", "shift", "tab"), ("ctrl", "shift", "tab")),
    ("Next tab", ("ctrl", "tab"), ("ctrl", "tab")),
    ("New tab", ("ctrl", "t"), ("cmd", "t")),
    ("Close tab", ("ctrl", "w"), ("cmd", "w")),
    ("Reopen tab", ("ctrl", "shift", "t"), ("cmd", "shift", "t")),
    ("Find", ("ctrl", "f"), ("cmd", "f")),
    ("Zoom in", ("ctrl", "equal"), ("cmd", "equal")),
    ("Zoom out", ("ctrl", "minus"), ("cmd", "minus")),
]


def _profile(keys, mac):
    actions = _knobs()
    labels = dict(KNOB_LABELS)
    for number, (label, windows, macos) in enumerate(keys, start=1):
        actions[f"KEY:{number}"] = _hotkey(*(macos if mac else windows))
        labels[f"KEY:{number}"] = label
    return actions, labels


def starter_config(platform=None):
    mac = (platform or sys.platform) == "darwin"
    general, general_labels = _profile(GENERAL_KEYS, mac)
    browser, browser_labels = _profile(BROWSER_KEYS, mac)
    return {
        "default_profile": "General",
        "locked_profile": None,
        "applications": {},
        "profiles": {"General": general, "Browser": browser},
        "labels": {"General": general_labels, "Browser": browser_labels},
    }
