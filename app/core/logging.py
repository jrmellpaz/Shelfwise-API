"""
Structured logging configuration.
"""

import logging
import sys


def setup_logging(debug: bool = False) -> None:
    """Configure application-wide logging format and level."""
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
