"""Session log widget; mirrors writes to the cache directory."""

from __future__ import annotations

import logging
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from rich.text import Text
from textual.message import Message
from textual.widgets import RichLog

from ...cache import default_cache_path


class LogErrorCountChanged(Message):
    """Posted when the count of error-level entries changes."""

    def __init__(self, count: int) -> None:
        self.count = count
        super().__init__()


class LogPane(RichLog):
    """Session log; writes to widget and, if possible, to session.log."""

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id, markup=False, wrap=True)
        self._error_count = 0
        self._logger: logging.Logger | None = None
        self._log_file: Path | None = None

    @property
    def error_count(self) -> int:
        return self._error_count

    @property
    def log_file(self) -> Path | None:
        return self._log_file

    def on_mount(self) -> None:
        self._setup_logging()

    def _setup_logging(self) -> None:
        if self._logger is not None:
            return
        logger = logging.getLogger("sift")
        try:
            log_dir = default_cache_path().parent
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / "session.log"
            # Defensive: don't double-register if a handler already targets
            # this file (e.g. widget re-mounted in a test).
            for existing in logger.handlers:
                if (
                    isinstance(existing, RotatingFileHandler)
                    and Path(existing.baseFilename) == log_file
                ):
                    self._log_file = log_file
                    self._logger = logger
                    return
            handler = RotatingFileHandler(
                log_file,
                maxBytes=1_000_000,
                backupCount=3,
                encoding="utf-8",
            )
            handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s %(levelname)s %(message)s",
                )
            )
            logger.addHandler(handler)
            logger.setLevel(logging.DEBUG)
            self._log_file = log_file
        except OSError:
            self._log_file = None
        self._logger = logger

    def log_message(self, message: str, *, level: str = "info") -> None:
        """Append a timestamped entry; bump error count on ``level='error'``."""
        logger = self._logger or logging.getLogger("sift")
        log_method = {
            "info": logger.info,
            "warn": logger.warning,
            "error": logger.error,
        }.get(level, logger.info)
        log_method(message)

        ts = datetime.now().strftime("%H:%M:%S")
        style = {"info": "", "warn": "yellow", "error": "red bold"}.get(level, "")
        self.write(Text(f"[{ts}] {message}", style=style))

        if level == "error":
            self._error_count += 1
            self.post_message(LogErrorCountChanged(self._error_count))
