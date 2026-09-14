import sys
from pathlib import Path

BOT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(BOT_SRC) not in sys.path:
    sys.path.insert(0, str(BOT_SRC))

