import asyncio
import unittest

from COGS.RoleUpdater import AutoRoleUpdater


class FakeResponse:
    """Small aiohttp response stand-in used to test retry behavior."""

    def __init__(self, status, payload=None, headers=None):
        self.status = status
        self.payload = payload
        self.headers = headers or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def json(self):
        return self.payload


class FakeSession:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.urls = []

    def get(self, url):
        self.urls.append(url)
        return next(self.responses)


class RoleUpdaterHabboApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Avoid starting the Discord task loop; these tests target API helpers only.
        self.updater = AutoRoleUpdater.__new__(AutoRoleUpdater)
        self.updater._habbo_request_lock = asyncio.Lock()
        self.updater._next_habbo_request_at = 0.0
        self.updater._habbo_blocked_until = 0.0
        self.updater._habbo_request_interval = 1.0
        self.updater._habbo_success_streak = 0

    async def test_rate_limit_retries_and_honours_retry_after(self):
        session = FakeSession([
            FakeResponse(429, headers={"Retry-After": "3"}),
            FakeResponse(200, {"uniqueId": "hhus-1"}),
        ])
        delays = []

        async def record_delay(delay):
            delays.append(delay)

        async def skip_wait():
            # The retry behavior is under test, not real elapsed time.
            return None

        self.updater._defer_habbo_requests = record_delay
        self.updater._wait_for_habbo_request_slot = skip_wait
        result = await self.updater._get_habbo_json(session, "https://example.test")

        self.assertEqual({"uniqueId": "hhus-1"}, result)
        self.assertEqual([3.0], delays)
        self.assertEqual(2, len(session.urls))
        self.assertEqual(2.0, self.updater._habbo_request_interval)

    async def test_success_window_cautiously_increases_request_rate(self):
        for _ in range(self.updater.HABBO_SUCCESS_WINDOW):
            self.updater._record_habbo_success()

        self.assertEqual(0.8, self.updater._habbo_request_interval)
        self.assertEqual(0, self.updater._habbo_success_streak)

    async def test_adaptive_interval_stays_within_safe_bounds(self):
        self.updater._habbo_request_interval = self.updater.HABBO_MAX_REQUEST_INTERVAL
        self.updater._record_habbo_rate_limit()
        self.assertEqual(
            self.updater.HABBO_MAX_REQUEST_INTERVAL,
            self.updater._habbo_request_interval,
        )

        self.updater._habbo_request_interval = self.updater.HABBO_MIN_REQUEST_INTERVAL
        for _ in range(self.updater.HABBO_SUCCESS_WINDOW):
            self.updater._record_habbo_success()
        self.assertEqual(
            self.updater.HABBO_MIN_REQUEST_INTERVAL,
            self.updater._habbo_request_interval,
        )

    async def test_profile_is_reused_and_name_is_url_encoded(self):
        session = FakeSession([
            FakeResponse(200, {"uniqueId": "hhus-1", "motto": "CDA"}),
            FakeResponse(200, [{"id": "group-1"}]),
        ])

        profile, groups = await self.updater._get_habbo_user_and_groups(
            session, "name with/slash"
        )

        self.assertEqual("CDA", profile["motto"])
        self.assertEqual([{"id": "group-1"}], groups)
        self.assertIn("name%20with%2Fslash", session.urls[0])
        self.assertEqual(2, len(session.urls))


if __name__ == "__main__":
    unittest.main()
