"""
Resolves all runtime paths relative to the USB stick mount point.
Every other module imports from here — no hardcoded paths anywhere else.
"""

import os
import sys

# Candidate mount points in priority order
_MOUNT_CANDIDATES = [
    "/media/pi/FREEZERBOT",
    "/media/FREEZERBOT",
    "/mnt/FREEZERBOT",
]

# Allow override via environment variable (useful for development)
_ENV_OVERRIDE = os.environ.get("FREEZERBOT_ROOT")


def get_usb_root() -> str:
    """Return the absolute path to the FREEZERBOT USB stick root.

    Raises RuntimeError if the USB stick cannot be found.
    """
    if _ENV_OVERRIDE:
        if os.path.isdir(_ENV_OVERRIDE):
            return _ENV_OVERRIDE
        raise RuntimeError(
            f"FREEZERBOT_ROOT env var set to '{_ENV_OVERRIDE}' but directory does not exist."
        )

    for candidate in _MOUNT_CANDIDATES:
        if os.path.isdir(candidate):
            return candidate

    # Last resort: if main.py is running from the USB stick directly,
    # walk up from the app directory to find the root.
    script_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    candidate = os.path.abspath(os.path.join(script_dir, "..", ".."))
    if os.path.isfile(os.path.join(candidate, "config", "config.json")):
        return candidate

    raise RuntimeError(
        "FREEZERBOT USB stick not found. Checked: "
        + ", ".join(_MOUNT_CANDIDATES)
        + ". Set FREEZERBOT_ROOT env var to override."
    )


def get_app_dir() -> str:
    return os.path.join(get_usb_root(), "app")

def get_config_path() -> str:
    return os.path.join(get_usb_root(), "config", "config.json")

def get_db_path() -> str:
    return os.path.join(get_usb_root(), "data", "inventory.db")

def get_log_dir() -> str:
    return os.path.join(get_usb_root(), "logs")

def get_log_path() -> str:
    return os.path.join(get_log_dir(), "freezerbot.log")

def get_wake_words_dir() -> str:
    return os.path.join(get_usb_root(), "wake_words")

def get_wake_word_path(filename: str) -> str:
    return os.path.join(get_wake_words_dir(), filename)

def get_assets_dir() -> str:
    return os.path.join(get_app_dir(), "assets")

def get_font_path(filename: str) -> str:
    return os.path.join(get_assets_dir(), "fonts", filename)

def get_icon_path(filename: str) -> str:
    return os.path.join(get_assets_dir(), "icons", filename)
