"""tests/__init__.py — adds src/ to sys.path for all tests."""
import sys, os
_src = os.path.join(os.path.dirname(__file__), "..", "src")
if _src not in sys.path:
    sys.path.insert(0, _src)
