"""scripts/replace_bili_video.py：换源的请求体、分P 检查、提交后的时长核对。

创作中心接口换成假的，不碰网络、不真的改稿件。
"""
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "replace_bili_video.py"
_spec = importlib.util.spec_from_file_location("replace_bili_video_under_test", _SCRIPT)
rv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rv)

OLD_PART = {"index": 1, "filename": "n261008txOLD", "title": "标题_bilingual", "desc": "", "duration": 34}
ARCHIVE = {
    "aid": 117404155777504, "bvid": "BV1JNHX6KEeR", "title": "【双语字幕】标题", "tid": 208,
    "tag": "日语学习,双语字幕", "cover": "http://i1.hdslb.com/bfs/archive/x.jpg", "copyright": 1,
    "source": "", "desc": "原始视频: https://www.youtube.com/watch?v=SEmuHNtzM4k", "dtime": 0,
    "desc_format_id": 9999, "state": 0, "state_desc": "开放浏览", "limited_free": False,
}


class BuildStudioTests(unittest.TestCase):
    def test_keeps_archive_fields_and_replaces_the_part(self):
        new = {"title": "标题_bilingual", "filename": "n261008txNEW", "desc": ""}
        studio = rv.build_studio(ARCHIVE, new)
        for key in ("aid", "title", "tid", "tag", "cover", "copyright", "desc", "desc_format_id", "dtime"):
            self.assertEqual(studio[key], ARCHIVE[key], key)
        self.assertEqual(studio["videos"], [new])
        # biliup 的 studio_data 也会去掉它
        self.assertNotIn("limited_free", studio)

    def test_defaults_only_fill_missing_fields(self):
        archive = dict(ARCHIVE, copyright=2, source="https://www.youtube.com/watch?v=x")
        studio = rv.build_studio(archive, {"title": None, "filename": "n1", "desc": ""})
        self.assertEqual(studio["copyright"], 2)
        self.assertEqual(studio["source"], "https://www.youtube.com/watch?v=x")
        self.assertEqual(studio["subtitle"], {"open": 0, "lan": ""})
        self.assertIs(studio["up_close_reply"], False)
        self.assertEqual(studio["dtime"], 0)  # 稿件里有 0 就是 0，不能被缺省的 None 盖掉


class CheckPartsTests(unittest.TestCase):
    def test_single_matching_part_passes(self):
        self.assertIsNone(rv.check_parts([OLD_PART], "n261008txOLD"))

    def test_other_filename_is_refused(self):
        # 重跑时现在的分P 已经是新文件了，必须拒绝
        self.assertIn("n261008txNEW", rv.check_parts([dict(OLD_PART, filename="n261008txNEW")], "n261008txOLD"))

    def test_multi_part_archive_is_refused(self):
        self.assertIn("2 个分P", rv.check_parts([OLD_PART, dict(OLD_PART, index=2)], "n261008txOLD"))


class FakeCenter:
    """依次返回：换之前的稿件、转码后的稿件。记下上传和提交。"""

    def __init__(self, transcoded_duration):
        self.transcoded_duration = transcoded_duration
        self.uploads, self.edits = [], []

    def __call__(self, cookies_path):
        return self

    def view(self, bvid):
        if not self.edits:
            return {"archive": dict(ARCHIVE), "videos": [dict(OLD_PART)]}
        return {"archive": dict(ARCHIVE, state_desc="开放浏览"),
                "videos": [dict(OLD_PART, filename="n261008txNEW", duration=self.transcoded_duration)]}

    def upload(self, path, line):
        self.uploads.append((Path(path).name, line))
        return {"title": Path(path).stem, "filename": "n261008txNEW", "desc": ""}

    def edit(self, studio):
        self.edits.append(studio)
        return {"code": 0, "message": "OK"}


class MainFlowTests(unittest.TestCase):
    def setUp(self):
        fd, path = tempfile.mkstemp(suffix="_bilingual.mp4")
        os.close(fd)
        self.video = path
        self.addCleanup(os.unlink, path)
        # 空的 STATE_DIR：没有 config.json，也不会读到真的 cookies.json
        state = tempfile.TemporaryDirectory(prefix="replace-video-state-")
        self.addCleanup(state.cleanup)
        self.state_dir = Path(state.name)

    def run_main(self, center, expect="n261008txOLD", duration=33.5):
        argv = ["replace_bili_video.py", "BV1JNHX6KEeR", self.video, "--expect-filename", expect, "--line", "tx"]
        with mock.patch.object(rv, "STATE_DIR", self.state_dir), \
                mock.patch.object(rv, "CreativeCenter", center), \
                mock.patch.object(rv, "local_duration", return_value=duration), \
                mock.patch.object(rv.time, "sleep"), \
                mock.patch.object(sys, "argv", argv), \
                mock.patch("builtins.print"):
            rv.main()

    def test_replaces_the_part_and_keeps_the_metadata(self):
        center = FakeCenter(transcoded_duration=34)
        self.run_main(center)
        self.assertEqual(center.uploads, [(Path(self.video).name, "tx")])
        self.assertEqual(len(center.edits), 1)
        studio = center.edits[0]
        self.assertEqual(studio["videos"], [{"title": "标题_bilingual", "filename": "n261008txNEW", "desc": ""}])
        self.assertEqual((studio["title"], studio["tag"], studio["cover"]), (ARCHIVE["title"], ARCHIVE["tag"], ARCHIVE["cover"]))

    def test_wrong_expected_filename_touches_nothing(self):
        center = FakeCenter(transcoded_duration=34)
        with self.assertRaises(SystemExit):
            self.run_main(center, expect="n261008txSOMETHINGELSE")
        self.assertEqual((center.uploads, center.edits), ([], []))

    def test_duration_mismatch_after_transcode_fails_loudly(self):
        # 分块被静默跳过时，B 站转出来的时长会比本地短
        center = FakeCenter(transcoded_duration=20)
        with self.assertRaises(SystemExit) as ctx:
            self.run_main(center)
        self.assertIn("没传完整", str(ctx.exception.code))


if __name__ == "__main__":
    unittest.main()
