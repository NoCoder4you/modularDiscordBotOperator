import asyncio
import pytest

pytest.importorskip("fastapi")
from portal.app import health  # noqa: E402


def test_health_endpoint_payload():
    assert asyncio.run(health()) == {"status": "ok", "component": "portal"}
