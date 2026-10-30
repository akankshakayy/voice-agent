"""Centralized logging configuration with file rotation for production."""
import logging
import logging.handlers
import os
from pathlib import Path


def setup_logging(name: str = "eko", level: str | None = None) -> logging.Logger:
    """
    Configure logging with:
    - File output with rotation (max 10MB per file, keep 5 backups)
    - Console output for development/debugging
    - Configurable via LOG_LEVEL env var (default: INFO in prod, DEBUG in dev)

    Args:
        name: Logger name (default: "eko")
        level: Override log level (DEBUG/INFO/WARNING/ERROR). If None, reads LOG_LEVEL env var or defaults to INFO.

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)

    # Avoid duplicate handlers if called multiple times
    if logger.handlers:
        return logger

    # Determine log level
    if level is None:
        level = os.environ.get("LOG_LEVEL", "INFO").upper()
    numeric_level = getattr(logging, level, logging.INFO)
    logger.setLevel(numeric_level)

    # Create logs directory next to database (writable in container)
    data_dir = Path(os.environ.get("DATA_DIR", "data"))
    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file = log_dir / f"{name}.log"

    # Format: timestamp | level | logger | message
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # File handler with rotation: 10MB per file, keep 5 backups
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(numeric_level)
    logger.addHandler(file_handler)

    # Console handler (for development and stdout capture in production)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(numeric_level)
    logger.addHandler(console_handler)

    # Suppress overly verbose third-party loggers
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)

    return logger
