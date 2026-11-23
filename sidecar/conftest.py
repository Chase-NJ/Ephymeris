"""Wire-shape validation for every test, wherever it lives: a feature's own
tests sit in its package folder, outside `tests/` (`tests/conftest.py` says
what the validation is)."""

import os

os.environ.setdefault("EPHYMERIS_WIRE_VALIDATE", "1")
