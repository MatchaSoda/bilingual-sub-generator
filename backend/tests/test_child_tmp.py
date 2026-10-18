import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from utils.child_tmp import child_tmp_env, sweep_stale_browser_tmp


class ChildTmpEnvTests(unittest.TestCase):
    def test_child_writes_land_in_a_dir_that_is_removed_afterwards(self):
        with child_tmp_env() as env:
            tmpdir = env["TMPDIR"]
            subprocess.run([sys.executable, "-c",
                            "import tempfile, os; d = tempfile.mkdtemp(prefix='uc_');"
                            "open(os.path.join(d, 'x'), 'w').write('y')"], env=env, check=True)
            self.assertEqual(len(os.listdir(tmpdir)), 1)
        self.assertFalse(os.path.exists(tmpdir))

    def test_dir_is_removed_when_the_child_is_killed(self):
        with child_tmp_env() as env:
            tmpdir = env["TMPDIR"]
            proc = subprocess.Popen([sys.executable, "-c",
                                     "import tempfile, time; tempfile.mkdtemp(prefix='uc_'); time.sleep(30)"],
                                    env=env)
            deadline = time.time() + 5
            while not os.listdir(tmpdir) and time.time() < deadline:
                time.sleep(0.05)
            proc.kill()
            proc.wait()
            self.assertEqual(proc.returncode, -9)
        self.assertFalse(os.path.exists(tmpdir))

    def test_base_env_is_copied_not_mutated(self):
        base = {"PATH": "/bin", "TMPDIR": "/somewhere"}
        with child_tmp_env(base) as env:
            self.assertEqual(env["PATH"], "/bin")
            self.assertNotEqual(env["TMPDIR"], "/somewhere")
        self.assertEqual(base["TMPDIR"], "/somewhere")


class SweepTests(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.root = Path(self._dir.name)
        self.addCleanup(self._dir.cleanup)

    def make(self, name, age_seconds, is_dir=True):
        path = self.root / name
        if is_dir:
            path.mkdir()
            (path / "Default").mkdir()
            (path / "Default" / "Cache").write_bytes(b"x" * 1000)
        else:
            path.write_bytes(b"video")
        old = time.time() - age_seconds
        os.utime(path, (old, old))
        return path

    def test_removes_only_old_browser_dirs(self):
        old_profile = self.make("uc_abc123", 7 * 3600)
        old_chromium = self.make("org.chromium.Chromium.Xy12", 7 * 3600)
        young_profile = self.make("uc_live01", 60)
        other_dir = self.make("bsg-child-old", 7 * 3600)
        video = self.make("uc_named_file.mp4", 7 * 3600, is_dir=False)

        removed, freed = sweep_stale_browser_tmp(str(self.root))

        self.assertEqual(removed, 2)
        self.assertEqual(freed, 2000)
        self.assertFalse(old_profile.exists())
        self.assertFalse(old_chromium.exists())
        self.assertTrue(young_profile.exists())
        self.assertTrue(other_dir.exists())
        self.assertTrue(video.exists())

    def test_symlinks_are_not_followed(self):
        target = self.make("keep_me", 7 * 3600)
        link = self.root / "uc_link"
        link.symlink_to(target)
        removed, _ = sweep_stale_browser_tmp(str(self.root), max_age_seconds=0)
        self.assertEqual(removed, 0)
        self.assertTrue((target / "Default" / "Cache").exists())


if __name__ == "__main__":
    unittest.main()
