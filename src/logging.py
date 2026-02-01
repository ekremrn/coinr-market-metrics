"""
Centralized Logging
===================

Lightweight stdout logging with env-configurable levels.
"""

import sys
import time
import logging
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from dataclasses import dataclass

from src.config import LoggingConfig


@dataclass
class LogContext:
    """Additional context for structured logging."""
    symbol: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None


class Logger:
    """
    Centralized stdout logger with structured context support.
    """

    _instances: Dict[str, "Logger"] = {}

    def __new__(cls, service_name: str) -> "Logger":
        if service_name not in cls._instances:
            instance = super().__new__(cls)
            cls._instances[service_name] = instance
        return cls._instances[service_name]

    @staticmethod
    def _resolve_level(level_name: Optional[str]) -> int:
        level = getattr(logging, (level_name or "INFO").upper(), None)
        return level if isinstance(level, int) else logging.INFO

    def __init__(self, service_name: str):
        level_name = LoggingConfig().level
        level = self._resolve_level(level_name)

        if hasattr(self, "_initialized"):
            self._log_level_name = level_name
            self._logger.setLevel(level)
            for handler in self._logger.handlers:
                handler.setLevel(level)
            return

        self.service_name = service_name
        self._log_level_name = level_name
        self._log_level = level
        self._logger = logging.getLogger(service_name)
        self._logger.setLevel(self._log_level)
        self._logger.propagate = False

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(self._log_level)
        console_format = logging.Formatter(
            fmt="%(asctime)sZ | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        console_format.converter = time.gmtime
        console_handler.setFormatter(console_format)
        self._logger.addHandler(console_handler)

        self._initialized = True

    def _format_message(self, message: str, context: Optional[LogContext] = None) -> str:
        if context is None:
            return message

        parts = [message]
        if context.symbol:
            parts.append(f"[{context.symbol}]")
        if context.extra:
            for key, value in context.extra.items():
                parts.append(f"{key}={value}")

        return " | ".join(parts)

    def _get_extra(self, context: Optional[LogContext] = None) -> Dict[str, Any]:
        extra = {
            "service": self.service_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if context:
            if context.symbol:
                extra["symbol"] = context.symbol
            if context.extra:
                extra.update(context.extra)
        return extra

    def debug(self, message: str, context: Optional[LogContext] = None) -> None:
        self._logger.debug(
            self._format_message(message, context),
            extra=self._get_extra(context),
        )

    def info(self, message: str, context: Optional[LogContext] = None) -> None:
        self._logger.info(
            self._format_message(message, context),
            extra=self._get_extra(context),
        )

    def warning(self, message: str, context: Optional[LogContext] = None) -> None:
        self._logger.warning(
            self._format_message(message, context),
            extra=self._get_extra(context),
        )

    def error(self, message: str, context: Optional[LogContext] = None, exc_info: bool = False) -> None:
        extra = self._get_extra(context)
        if exc_info:
            extra["traceback"] = traceback.format_exc()
        self._logger.error(
            self._format_message(message, context),
            extra=extra,
            exc_info=exc_info,
        )

    def critical(self, message: str, context: Optional[LogContext] = None, exc_info: bool = True) -> None:
        extra = self._get_extra(context)
        if exc_info:
            extra["traceback"] = traceback.format_exc()
        self._logger.critical(
            self._format_message(message, context),
            extra=extra,
            exc_info=exc_info,
        )


def get_logger(service_name: str) -> Logger:
    """Factory function to get a logger instance."""
    return Logger(service_name)
