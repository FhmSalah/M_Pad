"""Locate writable app files without relying on the working directory."""

from pathlib import Path
import sys


def application_name():
    if sys.platform == "darwin" and not getattr(sys, "frozen", False):
        return "Macro Pad DEV"
    return "Macro Pad"


def config_path():
    if getattr(sys, "frozen", False):
        if sys.platform == "darwin":
            app_support = Path.home() / "Library" / "Application Support" / "Macro Pad"
            app_support.mkdir(parents=True, exist_ok=True)
            return app_support / "config.json"

        return Path(sys.executable).resolve().parent / "config.json"

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / application_name() / "config.json"

    return Path(__file__).resolve().parent / "config.json"
