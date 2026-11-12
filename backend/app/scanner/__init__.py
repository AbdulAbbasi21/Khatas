"""PayPal receipt scanner (CLIP + EasyOCR). Models load lazily on the first scan."""

import threading

_engines = None
_lock = threading.Lock()


def get_engines():
    """Load the ML models once. Raises ImportError if torch/easyocr aren't installed."""
    global _engines
    if _engines is None:
        with _lock:
            if _engines is None:
                from app.scanner.engines import Engines

                _engines = Engines.load()
    return _engines


def set_engines(engines):  # used by tests
    global _engines
    _engines = engines
