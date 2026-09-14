from __future__ import annotations

import sys
from pathlib import Path

BOT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BOT_ROOT / "src"))
sys.path.insert(0, str(BOT_ROOT.parents[1]))
