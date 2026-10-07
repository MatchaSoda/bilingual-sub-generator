import importlib.util
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

# mover.py 在 import 时就按 AUTOMATION_STATE_DIR 建目录，所以先把它指到临时目录再加载
_STATE_TMP = tempfile.mkdtemp(prefix="mover-cleanup-state-")
os.environ["AUTOMATION_STATE_DIR"] = _STATE_TMP
_MOVER_PATH = Path(__file__).resolve().parents[2] / "automation" / "mover.py"
_spec = importlib.util.spec_from_file_location("mover_cleanup_under_test", _MOVER_PATH)
mover = importlib.util.module_from_spec(_spec)
sys.modules["mover_cleanup_under_test"] = mover
_spec.loader.exec_module(mover)

DAY = 86400


class KeepDaysTests(unittest.TestCase):
    def test_missing_section_defaults_to_seven(self):
        self.assertEqual(mover.resolve_keep_days({}), 7)

    def test_explicit_value(self):
        self.assertEqual(mover.resolve_keep_days({"cleanup": {"keep_days": 3}}), 3)

    def test_zero_disables(self):
        self.assertEqual(mover.resolve_keep_days({"cleanup": {"keep_days": 0}}), 0)

    def test_garbage_falls_back_to_default(self):
        self.assertEqual(mover.resolve_keep_days({"cleanup": {"keep_days": "a week"}}), 7)
        self.assertEqual(mover.resolve_keep_days({"cleanup": None}), 7)


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.downloads = root / "downloads"
        self.output = root / "output"
        self.downloads.mkdir()
        self.output.mkdir()
        self.targets = [(self.downloads, True), (self.output, False)]

    def tearDown(self):
        self._tmp.cleanup()

    def touch(self, directory, name, size=10):
        path = directory / name
        path.write_bytes(b"x" * size)
        return path

    def test_fresh_files_are_kept(self):
        self.touch(self.downloads, "title.f399.mp4")
        self.touch(self.output, "中文标题_bilingual.mp4")
        removed, _ = mover.cleanup_old_media(7, targets=self.targets)
        self.assertEqual(removed, 0)

    def test_expired_files_are_removed_and_counted(self):
        a = self.touch(self.downloads, "title.f399.mp4", size=100)
        b = self.touch(self.downloads, "title.wav", size=50)
        c = self.touch(self.output, "中文标题_bilingual.mp4", size=200)
        removed, freed = mover.cleanup_old_media(7, now=time.time() + 8 * DAY, targets=self.targets)
        self.assertEqual((removed, freed), (3, 350))
        self.assertFalse(a.exists() or b.exists() or c.exists())

    def test_web_ui_outputs_in_downloads_survive(self):
        video = self.touch(self.downloads, "网页做的_bilingual.mp4")
        cover = self.touch(self.downloads, "网页做的_bilingual.jpg")
        cache = self.touch(self.downloads, "源标题.asr.json")
        mover.cleanup_old_media(7, now=time.time() + 8 * DAY, targets=self.targets)
        self.assertTrue(video.exists() and cover.exists())
        self.assertFalse(cache.exists())

    def test_backdated_mtime_does_not_make_a_new_file_old(self):
        # 抽出来的 .wav 会继承源视频的 mtime；ctime 才反映它刚被写过
        wav = self.touch(self.downloads, "title.wav")
        two_years_ago = time.time() - 730 * DAY
        os.utime(wav, (two_years_ago, two_years_ago))
        removed, _ = mover.cleanup_old_media(7, targets=self.targets)
        self.assertEqual(removed, 0)
        self.assertTrue(wav.exists())

    def test_disabled_removes_nothing(self):
        path = self.touch(self.downloads, "title.f399.mp4")
        removed, _ = mover.cleanup_old_media(0, now=time.time() + 30 * DAY, targets=self.targets)
        self.assertEqual(removed, 0)
        self.assertTrue(path.exists())

    def test_subdirectories_and_missing_dirs_are_ignored(self):
        sub = self.downloads / "nested"
        sub.mkdir()
        inner = self.touch(sub, "inside.mp4")
        targets = self.targets + [(Path(self._tmp.name) / "does-not-exist", False)]
        mover.cleanup_old_media(7, now=time.time() + 8 * DAY, targets=targets)
        self.assertTrue(sub.is_dir() and inner.exists())


if __name__ == "__main__":
    unittest.main()
