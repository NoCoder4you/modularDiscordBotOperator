from __future__ import annotations

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "JSON"


def data_path(filename: str) -> Path:
    path = Path(filename)
    if path.is_absolute():
        return path
    if path.parts and path.parts[0] == "JSON":
        return BASE_DIR / path
    return DATA_DIR / path
