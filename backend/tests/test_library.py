import os
import tempfile
import time
import unittest
from pathlib import Path

from utils.library import collect_library, delete_library_video, resolve_library_video


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.web = root / "downloads"
        self.auto = root / "outputs"
        self.web.mkdir()
        self.auto.mkdir()
        self.sources = {"web": (self.web, "/downloads"), "auto": (self.auto, "/outputs")}

    def tearDown(self):
        self._tmp.cleanup()

    def make(self, directory, name, size=10, age=0):
        path = directory / name
        path.write_bytes(b"x" * size)
        if age:
            t = time.time() - age
            os.utime(path, (t, t))
        return path

    def test_lists_both_sources_newest_first_with_raw_fields(self):
        self.make(self.web, "网页_bilingual.mp4", size=100, age=3600)
        self.make(self.auto, "搬运_bilingual.mp4", size=200)
        self.make(self.web, "源标题.f399.mp4")  # 下载缓存不是成品，不该出现
        items = collect_library(self.sources)
        self.assertEqual([i["name"] for i in items], ["搬运_bilingual.mp4", "网页_bilingual.mp4"])
        auto, web = items
        self.assertEqual((auto["source"], auto["path"], auto["thumbnail"]),
                         ("auto", "/outputs/搬运_bilingual.mp4", "/outputs/搬运_bilingual.jpg"))
        self.assertEqual((web["source"], web["path"]), ("web", "/downloads/网页_bilingual.mp4"))
        self.assertEqual(web["size_bytes"], 100)
        self.assertGreater(auto["mtime"], web["mtime"])

    def test_missing_directory_is_skipped(self):
        self.make(self.web, "网页_bilingual.mp4")
        sources = dict(self.sources, auto=(Path(self._tmp.name) / "nope", "/outputs"))
        self.assertEqual(len(collect_library(sources)), 1)

    def test_resolve_rejects_anything_outside_the_directory(self):
        good = self.make(self.auto, "搬运_bilingual.mp4")
        self.assertEqual(resolve_library_video(self.auto, "搬运_bilingual.mp4"), good)
        for bad in ("../downloads/网页_bilingual.mp4", "..", ".hidden_bilingual.mp4",
                    "搬运.f399.mp4", "不存在_bilingual.mp4"):
            self.assertIsNone(resolve_library_video(self.auto, bad), bad)

    def test_delete_removes_video_cover_and_subtitle_only(self):
        video = self.make(self.web, "网页_bilingual.mp4")
        cover = self.make(self.web, "网页_bilingual.jpg")
        other = self.make(self.web, "别的视频.ass")
        self.assertEqual(delete_library_video(video), 2)
        self.assertFalse(video.exists() or cover.exists())
        self.assertTrue(other.exists())


if __name__ == "__main__":
    unittest.main()
