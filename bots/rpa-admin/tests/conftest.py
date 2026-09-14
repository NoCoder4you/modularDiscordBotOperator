"""Make RPA Admin and repository shared packages importable in tests."""
from pathlib import Path
import importlib.util
import sys

SRC = Path(__file__).resolve().parents[1] / "src"
REPOSITORY = Path(__file__).resolve().parents[3]
for path in (REPOSITORY, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

_HAS_DISCORD = importlib.util.find_spec("discord") is not None
_NO_DISCORD_TESTS = {
    path.name
    for path in Path(__file__).parent.glob("test_*_cog.py")
}
_NO_DISCORD_TESTS.add("test_verify_restrictions.py")


def pytest_ignore_collect(collection_path: Path, config: object) -> bool:
    """Avoid source test stubs contaminating collection when discord.py is unavailable."""
    del config
    return not _HAS_DISCORD and collection_path.name in _NO_DISCORD_TESTS
