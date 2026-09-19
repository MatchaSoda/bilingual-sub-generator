import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from utils.setup_checks import (
    inspect_netscape_cookies, normalize_cookie_text, proxy_candidates,
    read_env_file, write_env_file, parse_api_keys,
)


def _row(domain, name, value="v"):
    return f"{domain}\tTRUE\t/\tTRUE\t2000000000\t{name}\t{value}"


class CookieInspectionTests(unittest.TestCase):
    def test_full_login_export_passes(self):
        rows = [_row(".youtube.com", f"c{i}") for i in range(30)]
        rows += [_row(".youtube.com", "LOGIN_INFO"), _row(".youtube.com", "SID")]
        text = "# Netscape HTTP Cookie File\n" + "\n".join(rows) + "\n"
        report = inspect_netscape_cookies(text)
        self.assertEqual(report["problems"], [])
        self.assertIn("LOGIN_INFO", report["login_cookies"])
        self.assertEqual(report["youtube"], 32)

    def test_partial_export_without_login_info_is_flagged(self):
        text = "\n".join(_row(".youtube.com", f"c{i}") for i in range(16))
        report = inspect_netscape_cookies(text)
        self.assertTrue(any("LOGIN_INFO" in p for p in report["problems"]))
        self.assertTrue(any("疑似导出不全" in p for p in report["problems"]))

    def test_json_export_is_rejected(self):
        report = inspect_netscape_cookies('[{"name": "LOGIN_INFO"}]')
        self.assertEqual(report["total"], 0)
        self.assertTrue(any("Netscape" in p for p in report["problems"]))

    def test_crlf_detected_and_normalized(self):
        text = "# Netscape\r\n" + _row(".youtube.com", "LOGIN_INFO") + "\r\n"
        report = inspect_netscape_cookies(text)
        self.assertTrue(report["had_crlf"])
        self.assertNotIn("\r", normalize_cookie_text(text))
        self.assertIn("LOGIN_INFO", report["login_cookies"])

    def test_non_youtube_cookies_only(self):
        report = inspect_netscape_cookies(_row(".google.com", "SID"))
        self.assertTrue(any("youtube.com" in p for p in report["problems"]))


class ProxyCandidateTests(unittest.TestCase):
    def test_empty_means_direct(self):
        self.assertEqual(proxy_candidates("", "host.docker.internal"), [])
        self.assertEqual(proxy_candidates("   ", "h"), [])

    def test_port_only_uses_default_host_and_both_schemes(self):
        self.assertEqual(
            proxy_candidates("7890", "host.docker.internal"),
            ["http://host.docker.internal:7890", "socks5h://host.docker.internal:7890"],
        )

    def test_host_port_kept(self):
        self.assertEqual(
            proxy_candidates("192.168.1.5:10808", "ignored"),
            ["http://192.168.1.5:10808", "socks5h://192.168.1.5:10808"],
        )

    def test_full_url_kept_verbatim(self):
        self.assertEqual(proxy_candidates("socks5://127.0.0.1:1080", "h"), ["socks5://127.0.0.1:1080"])
        self.assertEqual(proxy_candidates("HTTP://x:1", "h"), ["HTTP://x:1"])


class EnvFileTests(unittest.TestCase):
    def test_roundtrip_preserves_comments_and_order(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".env"
            p.write_text("# keys\nGOOGLE_API_KEYS=old\n\n# proxy\nHTTP_PROXY=\n", encoding="utf-8")
            write_env_file(p, {"GOOGLE_API_KEYS": "a,b", "NEW_KEY": "1", "HTTP_PROXY": None})
            text = p.read_text(encoding="utf-8")
            self.assertEqual(text.splitlines()[0], "# keys")
            self.assertIn("GOOGLE_API_KEYS=a,b", text)
            self.assertNotIn("HTTP_PROXY", text)
            self.assertTrue(text.endswith("NEW_KEY=1\n"))
            self.assertEqual(read_env_file(p), {"GOOGLE_API_KEYS": "a,b", "NEW_KEY": "1"})

    def test_read_strips_quotes(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".env"
            p.write_text('A="x y"\nB=\'z\'\n# C=ignored\n', encoding="utf-8")
            self.assertEqual(read_env_file(p), {"A": "x y", "B": "z"})

    def test_write_creates_missing_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "sub" / ".env"
            write_env_file(p, {"K": "v"})
            self.assertEqual(read_env_file(p), {"K": "v"})


class ApiKeyParsingTests(unittest.TestCase):
    def test_mixed_separators_and_dupes(self):
        self.assertEqual(parse_api_keys("k1, k2\nk3 k1"), ["k1", "k2", "k3"])
        self.assertEqual(parse_api_keys(""), [])


if __name__ == "__main__":
    unittest.main()
