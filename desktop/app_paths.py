"""Locate writable app files without relying on the working directory."""

import json
import os
from pathlib import Path
import shutil
import sys
import tempfile


def application_name():
    if sys.platform == "darwin" and not getattr(sys, "frozen", False):
        return "Macro Pad DEV"
    return "Macro Pad"


def windows_app_data():
    return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")


def config_path():
    if getattr(sys, "frozen", False):
        if sys.platform == "darwin":
            app_support = Path.home() / "Library" / "Application Support" / "Macro Pad"
            app_support.mkdir(parents=True, exist_ok=True)
            return app_support / "config.json"
        # Per-user settings; the installed program folder (Program Files) is read-only.
        return windows_app_data() / "Macro Pad" / "config.json"

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / application_name() / "config.json"

    return Path(__file__).resolve().parent / "config.json"


def legacy_config_path():
    """Where portable Windows builds before the installer kept their settings."""
    if getattr(sys, "frozen", False) and sys.platform == "win32":
        return Path(sys.executable).resolve().parent / "config.json"
    return None


def ensure_config(path=None, legacy=None, platform=None):
    """Create the config on first run: reuse an old portable config, else the starter set.

    Never touches an existing file. Returns what happened: "existing", "migrated" or "created".
    """
    path = Path(path) if path is not None else config_path()
    legacy = legacy if legacy is not None else legacy_config_path()
    if path.exists():
        return "existing"
    path.parent.mkdir(parents=True, exist_ok=True)
    if legacy is not None and Path(legacy).is_file():
        shutil.copy2(legacy, path)
        return "migrated"
    from starter_config import starter_config
    data = json.dumps(starter_config(platform), indent=4).encode("utf-8")
    descriptor, temporary = tempfile.mkstemp(prefix=".config-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as target:
            target.write(data)
            target.flush()
            os.fsync(target.fileno())
        if path.exists():  # Another copy created it meanwhile; keep theirs.
            return "existing"
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.remove(temporary)
    return "created"
