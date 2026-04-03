"""
Application-wide logger.
Call setup_logger() once at startup before importing any other module that logs.
Then use: from app.services.logger import get_logger
"""

import logging
import os
from logging.handlers import RotatingFileHandler
from typing import Optional

_root_logger_name = "freezerbot"
_configured = False


def setup_logger(
    log_path: str,
    level: str = "INFO",
    max_bytes: int = 5_242_880,
    backup_count: int = 3,
) -> None:
    """Configure the root freezerbot logger. Call once at app startup."""
    global _configured

    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    logger = logging.getLogger(_root_logger_name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    if not logger.handlers:
        # Rotating file handler
        fh = RotatingFileHandler(
            log_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        fh.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        logger.addHandler(fh)

        # Console handler (helpful during development)
        ch = logging.StreamHandler()
        ch.setFormatter(logging.Formatter(
            "[%(levelname)s] %(name)s: %(message)s"
        ))
        logger.addHandler(ch)

    _configured = True


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Return a child logger under the freezerbot namespace.

    Usage:
        log = get_logger(__name__)
        log.info("started")
    """
    if not _configured:
        # Fallback: console-only logger so imports don't crash before setup_logger()
        logging.basicConfig(level=logging.DEBUG)

    if name:
        # Strip leading 'app.' for cleaner log names
        clean = name.replace("app.", "", 1)
        return logging.getLogger(f"{_root_logger_name}.{clean}")
    return logging.getLogger(_root_logger_name)
