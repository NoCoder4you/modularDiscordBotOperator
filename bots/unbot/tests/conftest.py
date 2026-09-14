"""Make the independently installable UNBOT source tree importable in tests."""

from pathlib import Path
import sys

SRC = Path(__file__).resolve().parents[1] / "src"
REPOSITORY = Path(__file__).resolve().parents[3]
for path in (REPOSITORY, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
