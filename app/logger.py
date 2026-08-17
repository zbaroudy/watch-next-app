import logging
from pathlib import Path


def setup_logger(level: str) -> logging.Logger:
    """
    Configure the application logger.
    Logs are written to both the console and logs/app.log.
    """

    # Ensure the logs directory exists
    Path("logs").mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("mdblist")

    # Prevent duplicate handlers if the app is restarted
    if logger.hasHandlers():
        logger.handlers.clear()

    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s"
    )

    # Console output
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    # Log file output
    file_handler = logging.FileHandler(
        "logs/app.log",
        encoding="utf-8"
    )
    file_handler.setFormatter(formatter)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger
