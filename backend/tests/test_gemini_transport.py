import unittest
from unittest import mock

from utils import gemini_transport as transport


class RouteDemotionTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(transport, "GEMINI_PROXY", "socks5://127.0.0.1:1")
        patcher.start()
        self.addCleanup(patcher.stop)
        transport._rejected_routes.clear()
        self.addCleanup(transport._rejected_routes.clear)

    def _fail_inside(self, attempt, message, route=None):
        with self.assertRaises(RuntimeError):
            with transport.gemini_network_route(attempt, route=route):
                raise RuntimeError(message)

    def test_routes_alternate_while_both_are_alive(self):
        self.assertEqual([transport.route_for_attempt(a) for a in range(4)],
                         ["direct-v4", "default", "direct-v4", "default"])

    def test_location_rejection_drops_route_for_later_attempts(self):
        self._fail_inside(0, "400 POST ...: User location is not supported for the API use.")
        self.assertEqual(transport.last_route(), "direct-v4")
        self.assertEqual([transport.route_for_attempt(a) for a in range(1, 5)], ["default"] * 4)

    def test_other_errors_do_not_drop_the_route(self):
        self._fail_inside(0, "Translation count mismatch")
        self._fail_inside(0, "504 Deadline Exceeded")
        self.assertEqual(transport.route_for_attempt(2), "direct-v4")

    def test_all_routes_rejected_falls_back_to_full_rotation(self):
        self._fail_inside(0, "User location is not supported")
        self._fail_inside(1, "User location is not supported")
        self.assertEqual([transport.route_for_attempt(a) for a in range(2)], ["direct-v4", "default"])

    def test_explicit_route_ignores_demotion(self):
        self._fail_inside(0, "User location is not supported")
        with transport.gemini_network_route(5, route="direct-v4") as used:
            self.assertEqual(used, "direct-v4")


if __name__ == "__main__":
    unittest.main()
