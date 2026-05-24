"""This module provides logging configuration for the service."""

import logging
import os
from logging import Logger


def get_logger(logger_name: str) -> Logger:
    """Configures logging in the app."""
    # If Application Insights is enabled in app logging telemetry will be collected
    # from logging calls made with this logger and all of it's children loggers.
    logger = logging.getLogger(logger_name)

    # Set the logging level for the logger. Defaults to INFO
    logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))

    # Create log formatter
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] [%(filename)s:%(lineno)d] - %(message)s"
    )

    # Add stream handler to output to console
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger
