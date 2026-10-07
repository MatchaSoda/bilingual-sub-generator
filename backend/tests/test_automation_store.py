import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from utils import automation_store as store

# 生产 config.json 的样子（userdata/config.json，2026-10-07），校验必须原样放行
PRODUCTION_CONFIG = {
    "channels": [{
        "name": "日テレNEWS",
        "url": "https://www.youtube.com/@ntv_news/videos",
        "keyword": "#newsevery",
        "exclude": ["死", "火災", "殺", "害", "児", "遺棄", "遺体", "逮捕", "議員", "党", "天皇", "every"],
        "bili_tid": 208,
        "tags": "日语学习,双语字幕,日本,日本新闻,日常",
    }],
    "check_interval_seconds": 1800,
    "playlist_items": 300,
    "description_fetch_interval_seconds": 4,
    "max_uploads_per_cycle": 3,
    "processing": {
        "whisper_model": "large-v3-turbo",
        "segment_mode": "rule",
        "gemini_model": "gemini-3.1-flash-lite",
        "translation_batch_size": 100,
        "enable_furigana": True,
        "translate_title": True,
        "fix_source_text": True,
    },
    "upload": {"line": "tx", "retries": 3, "retry_delay_seconds": 60},
    "cleanup": {"keep_days": 7},
}


class StoreTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.paths = store.Paths(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()


class NormalizeConfigTests(unittest.TestCase):
    def test_production_config_passes_unchanged(self):
        config, errors = store.normalize_config(PRODUCTION_CONFIG)
        self.assertEqual(errors, [])
        self.assertEqual(config, PRODUCTION_CONFIG)

    def test_unknown_keys_are_kept(self):
        raw = dict(PRODUCTION_CONFIG, future_option={"a": 1})
        raw["channels"] = [dict(PRODUCTION_CONFIG["channels"][0], note="手写的备注")]
        config, errors = store.normalize_config(raw)
        self.assertEqual(errors, [])
        self.assertEqual(config["future_option"], {"a": 1})
        self.assertEqual(config["channels"][0]["note"], "手写的备注")

    def test_bad_channel_url_is_reported_with_its_path(self):
        raw = {"channels": [{"name": "a", "url": "www.youtube.com/@x"}, {"name": "b", "url": ""}]}
        _, errors = store.normalize_config(raw)
        self.assertEqual([e["path"] for e in errors], ["channels[0].url", "channels[1].url"])

    def test_exclude_accepts_comma_string_and_dedupes(self):
        raw = {"channels": [{"url": "https://x", "exclude": "死, 火災，死,,every"}]}
        config, errors = store.normalize_config(raw)
        self.assertEqual(errors, [])
        self.assertEqual(config["channels"][0]["exclude"], ["死", "火災", "every"])
        # 名字留空时用地址顶上，日志里总得有个名字
        self.assertEqual(config["channels"][0]["name"], "https://x")

    def test_tags_are_trimmed_and_fullwidth_commas_split(self):
        raw = {"channels": [{"url": "https://x", "tags": " 日语学习， 双语字幕 ,,日本 "}]}
        config, _ = store.normalize_config(raw)
        self.assertEqual(config["channels"][0]["tags"], "日语学习,双语字幕,日本")

    def test_numbers_are_range_checked(self):
        _, errors = store.normalize_config({"check_interval_seconds": 10, "playlist_items": "abc",
                                            "max_uploads_per_cycle": 2.5, "cleanup": {"keep_days": -1}})
        self.assertEqual(sorted(e["path"] for e in errors),
                         ["check_interval_seconds", "cleanup.keep_days", "max_uploads_per_cycle", "playlist_items"])

    def test_integral_floats_stay_integers(self):
        config, errors = store.normalize_config({"description_fetch_interval_seconds": 4.0,
                                                 "cleanup": {"keep_days": 7.0}, "check_interval_seconds": "1800"})
        self.assertEqual(errors, [])
        self.assertIsInstance(config["description_fetch_interval_seconds"], int)
        self.assertIsInstance(config["cleanup"]["keep_days"], int)
        self.assertEqual(config["check_interval_seconds"], 1800)
        config, _ = store.normalize_config({"description_fetch_interval_seconds": 2.5})
        self.assertEqual(config["description_fetch_interval_seconds"], 2.5)

    def test_booleans_are_not_numbers(self):
        _, errors = store.normalize_config({"playlist_items": True, "paused": "yes"})
        self.assertEqual(sorted(e["path"] for e in errors), ["paused", "playlist_items"])

    def test_enums(self):
        _, errors = store.normalize_config({
            "backfill": {"mode": "everything"},
            "processing": {"whisper_model": "huge", "segment_mode": "ai"},
            "upload": {"line": "nope"},
        })
        self.assertEqual(sorted(e["path"] for e in errors),
                         ["backfill.mode", "processing.segment_mode", "processing.whisper_model", "upload.line"])

    def test_empty_upload_line_means_auto(self):
        config, errors = store.normalize_config({"upload": {"line": ""}})
        self.assertEqual(errors, [])
        self.assertIsNone(config["upload"]["line"])

    def test_title_template_must_keep_the_title(self):
        _, errors = store.normalize_config({"upload": {"title_template": "【双语字幕】固定标题"}})
        self.assertEqual([e["path"] for e in errors], ["upload.title_template"])

    def test_style_is_typed_for_entry_cli_and_unknown_keys_dropped(self):
        config, errors = store.normalize_config({"processing": {"style": {
            "font_size_main": 96.0, "main_bottom": "1.5", "shadow_sub": 2, "color": "red"}}})
        self.assertEqual(errors, [])
        style = config["processing"]["style"]
        self.assertEqual(style, {"font_size_main": 96, "main_bottom": 1.5, "shadow_sub": 2})
        self.assertIsInstance(style["font_size_main"], int)

    def test_style_out_of_range(self):
        _, errors = store.normalize_config({"processing": {"style": {"font_weight": 950}}})
        self.assertEqual([e["path"] for e in errors], ["processing.style.font_weight"])


class EffectiveConfigTests(unittest.TestCase):
    def test_missing_sections_use_code_defaults(self):
        effective = store.effective_config({"channels": [{"url": "https://x"}]})
        self.assertEqual(effective["check_interval_seconds"], 300)
        self.assertEqual(effective["backfill"]["mode"], "all")
        self.assertEqual(effective["upload"]["title_template"], "【双语字幕】{title}")
        self.assertEqual(effective["channels"][0]["bili_tid"], 171)
        self.assertFalse(effective["paused"])

    def test_file_values_win(self):
        effective = store.effective_config(PRODUCTION_CONFIG)
        self.assertEqual(effective["processing"]["fix_source_text"], True)
        self.assertEqual(effective["upload"]["line"], "tx")
        self.assertEqual(effective["playlist_items"], 300)


class SaveConfigTests(StoreTestCase):
    def test_save_load_round_trip_and_backup(self):
        version = store.save_config(self.paths, {"channels": []})
        config, loaded_version = store.load_config(self.paths)
        self.assertEqual(config, {"channels": []})
        self.assertEqual(version, loaded_version)
        store.save_config(self.paths, {"channels": [], "paused": True}, expected_version=version)
        self.assertEqual(json.loads(self.paths.config_backup.read_text()), {"channels": []})

    def test_conflict_when_file_changed_since_it_was_read(self):
        version = store.save_config(self.paths, {"channels": []})
        self.paths.config.write_text('{"channels": [], "edited": "by hand"}')
        with self.assertRaises(store.ConfigConflict):
            store.save_config(self.paths, {"channels": []}, expected_version=version)
        self.assertIn("by hand", self.paths.config.read_text())

    def test_missing_file_version(self):
        self.assertEqual(store.config_version(self.paths.config), "missing")
        self.assertEqual(store.load_config(self.paths), (None, "missing"))
        store.save_config(self.paths, {"channels": []}, expected_version="missing")
        self.assertTrue(self.paths.config.is_file())

    def test_update_config_keeps_other_keys(self):
        store.save_config(self.paths, PRODUCTION_CONFIG)
        config, _ = store.update_config(self.paths, lambda c: c.update(paused=True))
        self.assertTrue(config["paused"])
        on_disk = json.loads(self.paths.config.read_text())
        self.assertEqual(on_disk["channels"], PRODUCTION_CONFIG["channels"])
        self.assertTrue(on_disk["paused"])

    def test_save_keeps_file_permissions(self):
        self.paths.config.write_text("{}")
        os.chmod(self.paths.config, 0o644)
        store.save_config(self.paths, {"channels": []})
        self.assertEqual(self.paths.config.stat().st_mode & 0o777, 0o644)


class TemplateTests(unittest.TestCase):
    def test_known_placeholders_only(self):
        text = store.render_template("【双语字幕】{title} {unknown} {} {url}", title="标题", url="https://y")
        self.assertEqual(text, "【双语字幕】标题 {unknown} {} https://y")

    def test_default_templates_reproduce_the_old_strings(self):
        title = store.render_template(store.DEFAULT_TITLE_TEMPLATE, title="中文标题")
        desc = store.render_template(store.DEFAULT_DESCRIPTION_TEMPLATE, url="https://www.youtube.com/watch?v=x")
        self.assertEqual(title, "【双语字幕】中文标题")
        self.assertEqual(desc, "原始视频: https://www.youtube.com/watch?v=x\n使用 AI 自动生成双语字幕和假名标注。")


class YoutubeUrlTests(unittest.TestCase):
    def test_variants(self):
        expected = ("https://www.youtube.com/watch?v=T3VwdAhbbQg", "T3VwdAhbbQg")
        for url in (
            "https://www.youtube.com/watch?v=T3VwdAhbbQg",
            "https://youtube.com/watch?feature=share&v=T3VwdAhbbQg&t=12s",
            "https://m.youtube.com/watch?v=T3VwdAhbbQg",
            "https://youtu.be/T3VwdAhbbQg?si=abc",
            "https://www.youtube.com/shorts/T3VwdAhbbQg",
            "https://www.youtube.com/live/T3VwdAhbbQg?feature=shared",
            "youtu.be/T3VwdAhbbQg",
            "  https://www.youtube.com/watch?v=T3VwdAhbbQg  ",
        ):
            self.assertEqual(store.parse_youtube_url(url), expected, url)

    def test_rejects_non_video_links(self):
        for url in ("", "https://www.youtube.com/@ntv_news/videos", "https://www.bilibili.com/video/BV1WJpN65EEH",
                    "https://www.youtube.com/watch?v=T3VwdAhbbQgX", "https://example.com/watch?v=T3VwdAhbbQg"):
            self.assertEqual(store.parse_youtube_url(url), (None, None), url)


class JobTests(StoreTestCase):
    def test_create_claim_finish(self):
        job = store.create_job(self.paths, "https://www.youtube.com/watch?v=aaaaaaaaaaa", "aaaaaaaaaaa", {"tid": 21})
        self.assertTrue(store.is_job_id(job["id"]))
        self.assertEqual(store.load_job(self.paths, job["id"])["status"], "queued")
        claimed = store.claim_next_job(self.paths, worker="test")
        self.assertEqual(claimed["id"], job["id"])
        self.assertEqual(claimed["status"], "running")
        self.assertIsNone(store.claim_next_job(self.paths, worker="test"))
        store.update_job(self.paths, job["id"], status="done", result={"bvid": "BV1xxxxxxxxx"})
        self.assertEqual(store.load_job(self.paths, job["id"])["result"]["bvid"], "BV1xxxxxxxxx")

    def test_claim_order_is_first_in_first_out(self):
        first = store.create_job(self.paths, "u1", "aaaaaaaaaaa", now=1000)
        second = store.create_job(self.paths, "u2", "bbbbbbbbbbb", now=2000)
        self.assertEqual(store.claim_next_job(self.paths, "t")["id"], first["id"])
        self.assertEqual(store.claim_next_job(self.paths, "t")["id"], second["id"])

    def test_only_queued_jobs_can_be_cancelled(self):
        queued = store.create_job(self.paths, "u1", "aaaaaaaaaaa", now=1000)
        running = store.create_job(self.paths, "u2", "bbbbbbbbbbb", now=2000)
        store.update_job(self.paths, running["id"], status="running")
        self.assertEqual(store.cancel_job(self.paths, queued["id"])["status"], "cancelled")
        self.assertIsNone(store.cancel_job(self.paths, running["id"]))
        self.assertIsNone(store.claim_next_job(self.paths, "t"))

    def test_active_job_for_video(self):
        job = store.create_job(self.paths, "u1", "aaaaaaaaaaa")
        self.assertEqual(store.active_job_for(self.paths, "aaaaaaaaaaa")["id"], job["id"])
        store.update_job(self.paths, job["id"], status="failed")
        self.assertIsNone(store.active_job_for(self.paths, "aaaaaaaaaaa"))

    def test_interrupted_running_jobs_fail_instead_of_rerunning(self):
        job = store.create_job(self.paths, "u1", "aaaaaaaaaaa")
        store.claim_next_job(self.paths, "t")
        self.assertEqual(store.fail_interrupted_jobs(self.paths, "restarted"), 1)
        failed = store.load_job(self.paths, job["id"])
        self.assertEqual((failed["status"], failed["error"]), ("failed", "restarted"))
        self.assertIsNone(store.claim_next_job(self.paths, "t"))

    def test_prune_keeps_newest_finished_and_all_active(self):
        jobs = [store.create_job(self.paths, f"u{i}", "aaaaaaaaaaa", now=1000 + i) for i in range(6)]
        for job in jobs[:5]:
            store.update_job(self.paths, job["id"], status="done")
            store.job_log_path(self.paths, job["id"]).write_text("log")
        store.prune_jobs(self.paths, keep=3)
        remaining = {job["id"] for job in store.list_jobs(self.paths)}
        # 1 个排队中 + 最新的 2 个已完成
        self.assertEqual(remaining, {jobs[5]["id"], jobs[4]["id"], jobs[3]["id"]})
        self.assertFalse(store.job_log_path(self.paths, jobs[0]["id"]).exists())

    def test_job_ids_cannot_escape_the_jobs_directory(self):
        self.assertIsNone(store.load_job(self.paths, "../config"))
        with self.assertRaises(ValueError):
            store.job_path(self.paths, "pub-../../x")


class StatusTests(StoreTestCase):
    def test_offline_without_status_file(self):
        self.assertFalse(store.read_status(self.paths)["online"])

    def test_online_follows_heartbeat_age(self):
        store.write_status(self.paths, {"phase": "idle", "heartbeat_at": 1000})
        self.assertTrue(store.read_status(self.paths, now=1010)["online"])
        self.assertFalse(store.read_status(self.paths, now=1000 + store.ONLINE_GRACE_SECONDS + 1)["online"])

    def test_scan_request_is_consumed_once(self):
        self.assertFalse(store.scan_requested(self.paths))
        store.request_scan(self.paths)
        self.assertTrue(store.scan_requested(self.paths))
        self.assertTrue(store.consume_scan_request(self.paths))
        self.assertFalse(store.consume_scan_request(self.paths))


class EventAndUploadTests(StoreTestCase):
    def test_events_newest_first_and_summary(self):
        store.append_event(self.paths, "skip", now=100, reason="keyword", video_id="a")
        store.append_event(self.paths, "skip", now=200, reason="exclude", video_id="b")
        store.append_event(self.paths, "uploaded", now=300, video_id="c", bvid="BV1aaaaaaaaa")
        store.append_event(self.paths, "failed", now=400, video_id="d")
        events = store.read_events(self.paths)
        self.assertEqual([e["video_id"] for e in events], ["d", "c", "b", "a"])
        summary = store.summarize_events(events, since=150)
        self.assertEqual((summary["uploaded"], summary["failed"]), (1, 1))
        self.assertEqual(summary["skipped"]["exclude"], 1)
        self.assertEqual(summary["skipped"]["keyword"], 0)

    def test_corrupt_lines_are_skipped(self):
        store.append_event(self.paths, "skip", now=1, video_id="a")
        with open(self.paths.events, "a") as f:
            f.write('{"broken": \n')
        store.append_event(self.paths, "skip", now=2, video_id="b")
        self.assertEqual([e["video_id"] for e in store.read_events(self.paths)], ["b", "a"])

    def test_trim_keeps_the_newest_half(self):
        for i in range(100):
            store.append_event(self.paths, "skip", now=i, video_id=str(i))
        store.trim_events(self.paths, max_bytes=1000)
        events = store.read_events(self.paths, limit=None)
        self.assertEqual(events[0]["video_id"], "99")
        self.assertLess(len(events), 100)

    def test_uploads(self):
        store.append_upload(self.paths, {"video_id": "a", "bvid": "BV1aaaaaaaaa"}, now=1)
        store.append_upload(self.paths, {"video_id": "b", "bvid": "BV1bbbbbbbbb"}, now=2)
        self.assertEqual([u["video_id"] for u in store.read_uploads(self.paths)], ["b", "a"])
        self.assertEqual(store.find_upload(self.paths, "a")["bvid"], "BV1aaaaaaaaa")
        self.assertIsNone(store.find_upload(self.paths, "zzz"))

    def test_history_contains(self):
        self.assertFalse(store.history_contains(self.paths, "a"))
        self.paths.history.write_text(json.dumps(["a", "b"]))
        self.assertTrue(store.history_contains(self.paths, "a"))
        self.assertFalse(store.history_contains(self.paths, "c"))


class TailTextTests(StoreTestCase):
    def test_tail_returns_last_lines(self):
        path = Path(self._tmp.name) / "log.txt"
        path.write_text("\n".join(f"line {i}" for i in range(1000)))
        self.assertEqual(store.tail_text(path, max_lines=2), ["line 998", "line 999"])
        lines = store.tail_text(path, max_lines=0, max_bytes=30)
        self.assertEqual(lines[-1], "line 999")
        self.assertTrue(all(line.startswith("line ") for line in lines))

    def test_missing_file(self):
        self.assertEqual(store.tail_text(Path(self._tmp.name) / "nope"), [])


if __name__ == "__main__":
    unittest.main()
