"""Test package bootstrap for delpro_backend."""

import logging
import sys
import warnings
from pathlib import Path

SRC_PATH = Path(__file__).resolve().parents[1] / "src"

if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

# Disable logging during tests for cleaner output
# Logs are still generated and tested, but not displayed in terminal
logging.disable(logging.CRITICAL)

# Suppress common warnings that appear during tests
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)
