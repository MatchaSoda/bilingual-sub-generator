"""scripts/migrate.sh：裸机 / Docker 两种部署之间互相导出导入用户数据。

每个用例在临时目录里搭一个只含 scripts/migrate.sh 的假仓库，不碰真实数据。
"""
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "migrate.sh"

ENV = (
    "GOOGLE_API_KEYS=k1,k2\n"
    "HTTP_PROXY=http://127.0.0.1:10808\n"
    "HTTPS_PROXY=http://127.0.0.1:10808\n"
    "GEMINI_PROXY=socks5h://127.0.0.1:10808\n"
    "NO_PROXY=localhost,127.0.0.1,.bilibili.com\n"
    "ENABLE_AUTOMATION=1\n"
)
HISTORY = ["a1", "b2", "c3"]


def make_repo(root: Path) -> Path:
    (root / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, root / "scripts" / "migrate.sh")
    return root


def run(repo: Path, *args, check=True):
    p = subprocess.run(["bash", str(repo / "scripts" / "migrate.sh"), *args],
                       cwd=repo, capture_output=True, text=True)
    if check and p.returncode != 0:
        raise AssertionError(f"migrate.sh {args} failed:\n{p.stdout}\n{p.stderr}")
    return p


def fill_bare(repo: Path):
    (repo / ".env").write_text(ENV)
    (repo / "cookies.txt").write_text("# Netscape\n.youtube.com\tTRUE\t/\tTRUE\t0\tLOGIN_INFO\tx\n")
    auto = repo / "automation"
    auto.mkdir(exist_ok=True)
    (auto / "cookies.json").write_text('{"bili": 1}')
    (auto / "config.json").write_text('{"channels": []}')
    (auto / "history.json").write_text(json.dumps(HISTORY))
    (auto / "history.lock").write_text("")
    (auto / "data").mkdir()
    (auto / "data" / "video.mp4").write_text("big")


def fill_docker(repo: Path):
    ud = repo / "userdata"
    ud.mkdir()
    (ud / ".env").write_text(ENV.replace("127.0.0.1:10808", "host.docker.internal:7897"))
    (ud / "cookies.txt").write_text("# Netscape\nLOGIN_INFO\n")
    (ud / "cookies.json").write_text('{"bili": 2}')
    (ud / "config.json").write_text('{"channels": [1]}')
    (ud / "history.json").write_text(json.dumps(HISTORY))
    (ud / "state.json").write_text('{"first_start_at": "2026-09-19T00:00:00+00:00"}')
    (ud / ".setup-done").write_text("x")
    (ud / "data").mkdir()


class MigrateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.pkg = self.tmp / "pkg.tar.gz"
        self.old = make_repo(self.tmp / "old")
        self.new = make_repo(self.tmp / "new")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def members(self):
        with tarfile.open(self.pkg) as t:
            return sorted(t.getnames())

    def test_bare_export_has_userdata_layout_and_skips_runtime_files(self):
        fill_bare(self.old)
        out = run(self.old, "export", str(self.pkg)).stdout
        self.assertIn("裸机", out)
        self.assertEqual(self.members(), [
            "userdata", "userdata/.env", "userdata/config.json", "userdata/cookies.json",
            "userdata/cookies.txt", "userdata/history.json",
        ])
        self.assertEqual(oct(self.pkg.stat().st_mode & 0o777), "0o600")

    def test_docker_export_skips_setup_marker_and_videos(self):
        fill_docker(self.old)
        run(self.old, "export", str(self.pkg))
        names = self.members()
        self.assertIn("userdata/state.json", names)
        self.assertNotIn("userdata/.setup-done", names)
        self.assertFalse(any("data" in n.split("/")[1:2] for n in names if n.count("/")))

    def test_bare_to_docker(self):
        fill_bare(self.old)
        run(self.old, "export", str(self.pkg))
        run(self.new, "import", str(self.pkg), "--to", "docker")
        ud = self.new / "userdata"
        self.assertEqual(json.loads((ud / "history.json").read_text()), HISTORY)
        env = (ud / ".env").read_text()
        self.assertIn("HTTP_PROXY=http://host.docker.internal:10808", env)
        self.assertIn("GEMINI_PROXY=socks5h://host.docker.internal:10808", env)
        # NO_PROXY 里的 127.0.0.1 是「本机不走代理」，不能跟着换
        self.assertIn("NO_PROXY=localhost,127.0.0.1,", env)
        self.assertIn("ENABLE_AUTOMATION=0", env)
        self.assertEqual(oct((ud / ".env").stat().st_mode & 0o777), "0o600")

    def test_docker_to_bare(self):
        fill_docker(self.old)
        run(self.old, "export", str(self.pkg))
        run(self.new, "import", str(self.pkg), "--to", "bare")
        self.assertEqual(json.loads((self.new / "automation" / "history.json").read_text()), HISTORY)
        self.assertTrue((self.new / "automation" / "state.json").is_file())
        self.assertTrue((self.new / "cookies.txt").is_file())
        self.assertFalse((self.new / "userdata").exists())
        env = (self.new / ".env").read_text()
        self.assertIn("HTTP_PROXY=http://127.0.0.1:7897", env)

    def test_bare_to_bare_detected_by_venv(self):
        fill_bare(self.old)
        run(self.old, "export", str(self.pkg))
        (self.new / "venv" / "bin").mkdir(parents=True)
        py = self.new / "venv" / "bin" / "python3"
        py.write_text("#!/bin/sh\n")
        py.chmod(0o755)
        out = run(self.new, "import", str(self.pkg)).stdout
        self.assertIn("裸机", out)
        self.assertEqual((self.new / ".env").read_text(), ENV)

    def test_import_refuses_to_overwrite_without_force(self):
        fill_bare(self.old)
        run(self.old, "export", str(self.pkg))
        fill_bare(self.new)
        (self.new / "automation" / "history.json").write_text('["only-here"]')
        p = run(self.new, "import", str(self.pkg), "--to", "bare", check=False)
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual((self.new / "automation" / "history.json").read_text(), '["only-here"]')

        run(self.new, "import", str(self.pkg), "--to", "bare", "--force")
        self.assertEqual(json.loads((self.new / "automation" / "history.json").read_text()), HISTORY)
        backups = list((self.new / "automation").glob("history.json.bak-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), '["only-here"]')

    def test_export_refuses_when_both_layouts_have_data(self):
        fill_bare(self.old)
        fill_docker(self.old)
        p = run(self.old, "export", str(self.pkg), check=False)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("--from", p.stderr)
        run(self.old, "export", str(self.pkg), "--from", "docker")
        self.assertIn("userdata/state.json", self.members())

    def test_placeholder_userdata_does_not_count_as_docker_data(self):
        # docker-start.sh 会预先放一个空 key 的 .env 和空 cookies.txt
        fill_bare(self.old)
        ud = self.old / "userdata"
        ud.mkdir()
        (ud / ".env").write_text("GOOGLE_API_KEYS=\n")
        (ud / "cookies.txt").write_text("")
        run(self.old, "export", str(self.pkg))
        self.assertIn("userdata/history.json", self.members())


if __name__ == "__main__":
    unittest.main()
