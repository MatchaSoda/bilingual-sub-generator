"""mover 的投稿链路：生成 → 投稿 → 记账，以及 Web 投稿任务和自动扫描怎么排队、怎么避免重复投稿。

entry_cli 和 biliup 都换成临时目录里的假脚本，不碰网络、不真的投稿。
"""
import importlib.util
import io
import json
import os
import stat
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from unittest import mock

# mover.py 在 import 时就按 AUTOMATION_STATE_DIR 建目录，所以先把它指到临时目录再加载
_STATE_TMP = tempfile.mkdtemp(prefix="mover-publish-state-")
os.environ["AUTOMATION_STATE_DIR"] = _STATE_TMP
_MOVER_PATH = Path(__file__).resolve().parents[2] / "automation" / "mover.py"
_spec = importlib.util.spec_from_file_location("mover_publish_under_test", _MOVER_PATH)
mover = importlib.util.module_from_spec(_spec)
sys.modules["mover_publish_under_test"] = mover
_spec.loader.exec_module(mover)

store = mover.store

# 假的 entry_cli：打印几行阶段标志和译名，在 --output 指定的位置生成成品和封面
FAKE_CLI = textwrap.dedent("""\
    import sys
    from pathlib import Path
    args = sys.argv[1:]
    out = Path(args[args.index("--output") + 1])
    print("🚀 Starting process for: " + args[0], flush=True)
    print("📡 Loading Whisper model: large-v3-turbo (cpu/int8)...", flush=True)
    print("✂️ Segmentation mode: rule (offline)", flush=True)
    print("🌐 Translated title: 中文标题", flush=True)
    print("🎬 Executing FFmpeg command: ffmpeg ...", flush=True)
    if "FAIL" in args[0]:
        print("❌ Error: something broke", flush=True)
        sys.exit(3)
    out.write_bytes(b"video")
    out.with_suffix(".jpg").write_bytes(b"jpg")
    print("🎉 All done! Final video: " + str(out), flush=True)
""")

# 假的 biliup：把参数记下来，按 BILIUP_MODE 决定成功（打印带 bvid 的返回）还是失败
FAKE_BILIUP = textwrap.dedent("""\
    #!/bin/sh
    printf '%s\\n' "$@" > "$(dirname "$0")/biliup-args.txt"
    if [ "$(cat "$(dirname "$0")/mode")" = fail ]; then
        echo "error sending request" >&2
        echo "╰─▶ invalid peer certificate: certificate expired" >&2
        exit 1
    fi
    printf '\\033[32m INFO\\033[0m ResponseData { code: 0, data: Some(Object {"aid": Number(1), "bvid": String("BV1WJpN65EEH")}) }\\n'
    echo "Web 接口投稿成功"
""")


class PublishTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.state = root / "state"
        self.output = self.state / "data"
        self.output.mkdir(parents=True)
        self.bin = root / "bin"
        self.bin.mkdir()
        (self.bin / "cli.py").write_text(FAKE_CLI)
        biliup = self.bin / "biliup"
        biliup.write_text(FAKE_BILIUP)
        biliup.chmod(biliup.stat().st_mode | stat.S_IEXEC)
        (self.bin / "mode").write_text("ok")
        (self.state / "cookies.json").write_text("{}")
        self.paths = store.Paths(self.state)
        self.config = {
            "channels": [{"name": "日テレNEWS", "url": "https://www.youtube.com/@ntv_news/videos",
                          "keyword": "", "exclude": ["火災"], "bili_tid": 208, "tags": "日语学习,日本"}],
            "upload": {"retries": 1, "retry_delay_seconds": 0},
            "processing": {},
        }
        store.save_config(self.paths, self.config)
        patches = {
            "STATE_DIR": self.state, "OUTPUT_DIR": self.output, "PATHS": self.paths,
            "CONFIG_FILE": self.paths.config, "HISTORY_FILE": self.paths.history,
            "BILI_SESSION": self.state / "cookies.json",
            "PYTHON_PATH": Path(sys.executable), "CLI_PATH": self.bin / "cli.py", "BILIUP_PATH": biliup,
            "TEE": None, "REPORTER": None,
        }
        for name, value in patches.items():
            patcher = mock.patch.object(mover, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        # 业务代码的 print 很多，测试里收掉
        silence = mock.patch("sys.stdout", new_callable=io.StringIO)
        self.stdout = silence.start()
        self.addCleanup(silence.stop)

    def tearDown(self):
        self._tmp.cleanup()

    def biliup_args(self):
        return (self.bin / "biliup-args.txt").read_text().splitlines()


class PublishVideoTests(PublishTestCase):
    def test_success_renames_uploads_and_records(self):
        result = mover.publish_video("T3VwdAhbbQg", "https://www.youtube.com/watch?v=T3VwdAhbbQg",
                                     "日本語タイトル", self.config["channels"][0], {}, full_config=self.config)
        self.assertTrue(result["ok"])
        self.assertEqual(result["bvid"], "BV1WJpN65EEH")
        self.assertEqual(result["output"].name, "中文标题_bilingual.mp4")
        self.assertTrue((self.output / "中文标题_bilingual.jpg").exists())
        args = self.biliup_args()
        self.assertEqual(args[args.index("--title") + 1], "【双语字幕】中文标题")
        self.assertEqual(args[args.index("--tid") + 1], "208")
        self.assertIn("原始视频: https://www.youtube.com/watch?v=T3VwdAhbbQg", args[args.index("--desc") + 1])
        record = store.find_upload(self.paths, "T3VwdAhbbQg")
        self.assertEqual((record["bvid"], record["output"], record["source"], record["origin"]),
                         ("BV1WJpN65EEH", "中文标题_bilingual.mp4", "auto", "auto"))
        self.assertEqual(store.read_events(self.paths)[0]["type"], "uploaded")

    def test_upload_settings_and_templates_are_read_at_upload_time(self):
        store.save_config(self.paths, dict(self.config, upload={
            "retries": 1, "retry_delay_seconds": 0, "line": "tx",
            "title_template": "[中日字幕] {title}", "description_template": "来源 {url}"}))
        mover.publish_video("T3VwdAhbbQg", "https://y/T3VwdAhbbQg", "日本語", self.config["channels"][0], {},
                            full_config=self.config)
        args = self.biliup_args()
        self.assertEqual(args[args.index("--title") + 1], "[中日字幕] 中文标题")
        self.assertEqual(args[args.index("--desc") + 1], "来源 https://y/T3VwdAhbbQg")
        self.assertEqual(args[args.index("--line") + 1], "tx")

    def test_title_override_wins(self):
        result = mover.publish_video("T3VwdAhbbQg", "https://y", "日本語", {}, {}, full_config=self.config,
                                     title_override="我自己起的标题")
        self.assertEqual(result["bili_title"], "我自己起的标题")
        args = self.biliup_args()
        self.assertEqual(args[args.index("--title") + 1], "我自己起的标题")

    def test_cli_failure_reports_the_error_line(self):
        result = mover.publish_video("FAILFAILFAI", "https://y/FAIL", "日本語", {}, {}, full_config=self.config)
        self.assertFalse(result["ok"])
        self.assertEqual(result["stage"], "cli")
        self.assertIn("Code 3", result["error"])
        self.assertIn("something broke", result["error"])
        self.assertFalse((self.bin / "biliup-args.txt").exists())
        self.assertEqual(store.read_events(self.paths)[0]["type"], "failed")
        self.assertIsNone(store.find_upload(self.paths, "FAILFAILFAI"))

    def test_upload_failure_keeps_the_last_line_of_the_error(self):
        (self.bin / "mode").write_text("fail")
        result = mover.publish_video("T3VwdAhbbQg", "https://y", "日本語", {}, {}, full_config=self.config)
        self.assertFalse(result["ok"])
        self.assertEqual(result["stage"], "upload")
        self.assertIn("certificate expired", result["error"])
        self.assertIsNone(store.find_upload(self.paths, "T3VwdAhbbQg"))

    def test_missing_bilibili_login(self):
        (self.state / "cookies.json").unlink()
        result = mover.publish_video("T3VwdAhbbQg", "https://y", "日本語", {}, {}, full_config=self.config)
        self.assertEqual((result["ok"], result["stage"]), (False, "upload"))
        self.assertIn("cookies.json", result["error"])


class CliCommandTests(unittest.TestCase):
    def test_defaults_match_the_old_command(self):
        cmd = mover.build_cli_command("https://y", Path("/out/x_bilingual.mp4"), {})
        self.assertEqual(cmd[2:], [
            "https://y", "--segment-mode", "rule", "--whisper-model", "large-v3-turbo",
            "--gemini-model", "gemini-3.1-flash-lite", "--translation-batch-size", "100",
            "--output", "/out/x_bilingual.mp4", "--enable-furigana", "--translate-title",
        ])

    def test_style_becomes_entry_cli_flags(self):
        cmd = mover.build_cli_command("https://y", Path("/o.mp4"), {
            "fix_source_text": True, "style": {"font_size_main": 96.0, "sub_bottom": 90, "bogus": 1}})
        self.assertIn("--fix-source-text", cmd)
        self.assertEqual(cmd[cmd.index("--font-size-main") + 1], "96")
        self.assertEqual(cmd[cmd.index("--sub-bottom") + 1], "90")
        self.assertNotIn("--bogus", cmd)

    def test_invalid_style_values_are_dropped_not_passed(self):
        with mock.patch("sys.stdout", new_callable=io.StringIO):
            cmd = mover.build_cli_command("https://y", Path("/o.mp4"), {"style": {"font_weight": "bold"}})
        self.assertNotIn("--font-weight", cmd)


class DefaultsTests(unittest.TestCase):
    """界面显示的「当前生效值」（automation_store.DEFAULTS）必须就是 mover 真正用的值。"""

    def test_mover_constants_come_from_the_store(self):
        self.assertEqual(mover.DEFAULT_KEEP_DAYS, store.DEFAULTS["cleanup"]["keep_days"])
        self.assertEqual(mover.DEFAULT_LOOKBACK_HOURS, store.DEFAULTS["backfill"]["lookback_hours"])
        self.assertEqual(mover.resolve_keep_days({}), store.DEFAULTS["cleanup"]["keep_days"])

    def test_empty_processing_equals_effective_defaults(self):
        effective = store.effective_config({})["processing"]
        self.assertEqual(mover.build_cli_command("u", Path("/o.mp4"), {}),
                         mover.build_cli_command("u", Path("/o.mp4"), effective))


class BvidTests(unittest.TestCase):
    def test_parses_debug_response_with_ansi(self):
        text = '\x1b[32m INFO\x1b[0m ResponseData { data: Some(Object {"bvid": String("BV1WJpN65EEH")}) }'
        self.assertEqual(mover.parse_bvid(text), "BV1WJpN65EEH")

    def test_none_when_absent(self):
        self.assertIsNone(mover.parse_bvid("投稿成功"))

    def test_tail_message_keeps_the_end(self):
        text = "\n".join(f"line {i}" for i in range(10)) + "\n\x1b[31m╰─▶ certificate expired\x1b[0m\n"
        message = mover.tail_message(text)
        self.assertTrue(message.endswith("╰─▶ certificate expired"))
        self.assertNotIn("line 0", message)


class ChannelProfileTests(unittest.TestCase):
    CONFIG = {"channels": [{"name": "a", "bili_tid": 208, "tags": "x"}, {"name": "b", "bili_tid": 21, "tags": "y"}]}

    def test_index_default_and_overrides(self):
        self.assertEqual(mover.resolve_channel_profile(self.CONFIG, {"channel": 1})["bili_tid"], 21)
        self.assertEqual(mover.resolve_channel_profile(self.CONFIG, {})["name"], "a")
        self.assertEqual(mover.resolve_channel_profile(self.CONFIG, {"channel": 9})["name"], "a")
        profile = mover.resolve_channel_profile(self.CONFIG, {"channel": 1, "tid": "17", "tags": "z"})
        self.assertEqual((profile["bili_tid"], profile["tags"]), (17, "z"))

    def test_no_channels(self):
        self.assertEqual(mover.resolve_channel_profile({}, {}), {"name": "Web 投稿"})


class RunJobTests(PublishTestCase):
    def test_job_runs_to_done_and_lands_in_history(self):
        job = store.create_job(self.paths, "https://www.youtube.com/watch?v=T3VwdAhbbQg", "T3VwdAhbbQg",
                               {"channel": 0, "tags": "自定义"})
        history = set()
        with mock.patch.object(mover, "fetch_id_and_title", return_value=("T3VwdAhbbQg", "日本語タイトル")):
            mover.run_pending_jobs(history)
        done = store.load_job(self.paths, job["id"])
        self.assertEqual(done["status"], "done")
        self.assertEqual(done["title"], "日本語タイトル")
        self.assertEqual(done["result"]["bvid"], "BV1WJpN65EEH")
        self.assertEqual(done["result"]["output"], "中文标题_bilingual.mp4")
        self.assertIn("T3VwdAhbbQg", history)
        self.assertIn("T3VwdAhbbQg", json.loads(self.paths.history.read_text()))
        args = self.biliup_args()
        self.assertEqual(args[args.index("--tag") + 1], "自定义")
        self.assertEqual(store.find_upload(self.paths, "T3VwdAhbbQg")["origin"], "manual")

    def test_job_log_gets_the_output(self):
        mover.TEE = mover.LogTee(io.StringIO(), self.paths.log)
        self.addCleanup(mover.TEE.close)
        job = store.create_job(self.paths, "https://www.youtube.com/watch?v=T3VwdAhbbQg", "T3VwdAhbbQg")
        with mock.patch.object(mover, "fetch_id_and_title", return_value=("T3VwdAhbbQg", "日本語")), \
                mock.patch("sys.stdout", mover.TEE):
            mover.run_pending_jobs(set())
        log = store.job_log_path(self.paths, job["id"]).read_text()
        self.assertIn("[CLI] 🎬 Executing FFmpeg", log)
        self.assertIn("B 站投稿成功", log)
        self.assertIn("B 站投稿成功", self.paths.log.read_text())

    def test_failed_title_lookup_fails_the_job(self):
        job = store.create_job(self.paths, "https://www.youtube.com/watch?v=T3VwdAhbbQg", "T3VwdAhbbQg")
        history = set()
        with mock.patch.object(mover, "fetch_id_and_title", return_value=(None, None)):
            mover.run_pending_jobs(history)
        failed = store.load_job(self.paths, job["id"])
        self.assertEqual(failed["status"], "failed")
        self.assertIn("拿不到视频标题", failed["error"])
        self.assertEqual(history, set())

    def test_pipeline_failure_records_the_stage(self):
        job = store.create_job(self.paths, "https://www.youtube.com/watch?v=FAILFAILFAI", "FAILFAILFAI")
        with mock.patch.object(mover, "fetch_id_and_title", return_value=("FAILFAILFAI", "日本語")):
            mover.run_pending_jobs(set())
        failed = store.load_job(self.paths, job["id"])
        self.assertEqual((failed["status"], failed["failed_stage"]), ("failed", "cli"))


class ScanTests(PublishTestCase):
    def videos(self):
        return [
            {"id": "aaaaaaaaaaa", "timestamp": None, "url": "https://y/a", "title": "普通のニュース"},
            {"id": "bbbbbbbbbbb", "timestamp": None, "url": "https://y/b", "title": "住宅火災のニュース"},
            {"id": "ccccccccccc", "timestamp": None, "url": "https://y/c", "title": "Webで投稿中"},
            {"id": "ddddddddddd", "timestamp": None, "url": "https://y/d", "title": "もう処理済み"},
        ]

    def test_scan_skips_videos_that_a_web_job_owns(self):
        store.create_job(self.paths, "https://www.youtube.com/watch?v=ccccccccccc", "ccccccccccc")
        processed = []

        def fake_publish(video_id, *args, **kwargs):
            processed.append(video_id)
            return {"ok": True, "stage": "done", "bvid": None}

        history = {"ddddddddddd"}
        with mock.patch.object(mover, "get_video_list", return_value=self.videos()), \
                mock.patch.object(mover, "publish_video", side_effect=fake_publish), \
                mock.patch.object(mover, "run_pending_jobs"):
            stats = mover.scan_channels(self.config, history, cutoff=None)
        self.assertEqual(processed, ["aaaaaaaaaaa"])
        self.assertEqual(history, {"aaaaaaaaaaa", "bbbbbbbbbbb", "ddddddddddd"})
        self.assertEqual((stats["found"], stats["new"], stats["matched"], stats["uploaded"]), (4, 3, 1, 1))
        self.assertEqual(stats["skipped"]["exclude"], 1)
        kinds = [(e["type"], e.get("reason")) for e in store.read_events(self.paths)]
        self.assertIn(("skip", "exclude"), kinds)
        self.assertIn(("match", None), kinds)

    def test_description_failure_is_reported_separately(self):
        config = dict(self.config, channels=[dict(self.config["channels"][0], keyword="#newsevery")])
        with mock.patch.object(mover, "get_video_list", return_value=self.videos()[:1]), \
                mock.patch.object(mover, "fetch_video_description", return_value=None), \
                mock.patch.object(mover, "publish_video") as publish:
            stats = mover.scan_channels(config, set(), cutoff=None)
        publish.assert_not_called()
        self.assertEqual(stats["skipped"]["description_failed"], 1)
        self.assertEqual(store.read_events(self.paths)[0]["reason"], "description_failed")

    def test_no_channels_is_fine(self):
        stats = mover.scan_channels({}, set(), cutoff=None)
        self.assertEqual(stats["channels"], 0)


class WaitTests(PublishTestCase):
    def test_wake_request_ends_the_wait(self):
        store.request_scan(self.paths)
        started = time.time()
        mover.wait_until(time.time() + 60, set())
        self.assertLess(time.time() - started, 2)
        self.assertTrue(store.scan_requested(self.paths))  # 由下一轮开头消费

    def test_queued_job_runs_during_the_wait(self):
        store.create_job(self.paths, "https://www.youtube.com/watch?v=T3VwdAhbbQg", "T3VwdAhbbQg")
        with mock.patch.object(mover, "run_pending_jobs") as run:
            run.side_effect = lambda history: store.update_job(
                self.paths, store.queued_jobs(self.paths)[0]["id"], status="done")
            mover.wait_until(time.time() + 1.5, set())
        run.assert_called_once()

    def test_disk_history_is_merged(self):
        self.paths.history.write_text(json.dumps(["x", "y"]))
        history = {"a"}
        mover.merge_disk_history(history)
        self.assertEqual(history, {"a", "x", "y"})


class LogTeeTests(unittest.TestCase):
    def test_lines_are_stamped_and_rotated(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "runtime" / "mover.log"
            console = io.StringIO()
            tee = mover.LogTee(console, log, max_bytes=200)
            print("第一行", file=tee)
            tee.write("半行")
            tee.write("接上\n")
            self.assertEqual(console.getvalue(), "第一行\n半行接上\n")
            lines = log.read_text().splitlines()
            self.assertEqual(len(lines), 2)
            self.assertRegex(lines[1], r"^\d\d-\d\d \d\d:\d\d:\d\d 半行接上$")
            for i in range(20):
                print(f"line {i}", file=tee)
            tee.close()
            self.assertTrue(log.with_name("mover.log.1").exists())
            self.assertLess(log.stat().st_size, 400)


if __name__ == "__main__":
    unittest.main()
