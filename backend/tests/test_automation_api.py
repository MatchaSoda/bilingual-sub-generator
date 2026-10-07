"""「自动搬运」页面和「生成并投稿」的接口（api/automation_routes.py），以及 /api/status 对投稿任务的转发。"""
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import automation_routes
from api.routes import api_router
from utils import automation_store as store

VIDEO_URL = "https://www.youtube.com/watch?v=T3VwdAhbbQg"
CONFIG = {
    "channels": [{"name": "日テレNEWS", "url": "https://www.youtube.com/@ntv_news/videos", "keyword": "#newsevery",
                  "exclude": ["every"], "bili_tid": 208, "tags": "日语学习,日本"}],
    "check_interval_seconds": 1800,
    "upload": {"line": "tx", "retries": 3, "retry_delay_seconds": 60},
}


class ApiTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.state = Path(self._tmp.name)
        self.paths = store.Paths(self.state)
        patcher = mock.patch.object(automation_routes, "PATHS", self.paths)
        patcher.start()
        self.addCleanup(patcher.stop)
        app = FastAPI()
        app.include_router(api_router, prefix="/api")
        app.include_router(automation_routes.automation_router, prefix="/api/automation")
        self.client = TestClient(app)

    def tearDown(self):
        self._tmp.cleanup()

    def write_config(self, config=CONFIG):
        return store.save_config(self.paths, config)


class ConfigApiTests(ApiTestCase):
    def test_missing_config(self):
        data = self.client.get("/api/automation/config").json()
        self.assertFalse(data["exists"])
        self.assertEqual(data["version"], "missing")
        self.assertEqual(data["effective"]["check_interval_seconds"], 300)
        self.assertIn("tx", data["options"]["upload_lines"])

    def test_save_round_trip(self):
        version = self.client.get("/api/automation/config").json()["version"]
        response = self.client.put("/api/automation/config", json={"config": CONFIG, "version": version})
        self.assertEqual(response.status_code, 200, response.text)
        data = self.client.get("/api/automation/config").json()
        self.assertEqual(data["config"], CONFIG)
        self.assertEqual(data["version"], response.json()["version"])

    def test_invalid_values_are_listed(self):
        bad = dict(CONFIG, check_interval_seconds=5, channels=[dict(CONFIG["channels"][0], url="nope")])
        response = self.client.put("/api/automation/config", json={"config": bad, "version": "missing"})
        self.assertEqual(response.status_code, 422)
        paths = sorted(e["path"] for e in response.json()["errors"])
        self.assertEqual(paths, ["channels[0].url", "check_interval_seconds"])
        self.assertFalse(self.paths.config.exists())

    def test_stale_version_is_rejected(self):
        version = self.write_config()
        self.paths.config.write_text(json.dumps(dict(CONFIG, playlist_items=50)))
        response = self.client.put("/api/automation/config", json={"config": CONFIG, "version": version})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(json.loads(self.paths.config.read_text())["playlist_items"], 50)

    def test_corrupt_config_is_reported_not_crashed(self):
        self.paths.config.write_text("{broken")
        data = self.client.get("/api/automation/config").json()
        self.assertIn("读不了", data["error"])
        self.assertIn("读不了", self.client.get("/api/automation/status").json()["config_error"])

    def test_pause_only_touches_paused(self):
        self.write_config()
        self.assertEqual(self.client.post("/api/automation/pause", json={"paused": True}).status_code, 200)
        on_disk = json.loads(self.paths.config.read_text())
        self.assertTrue(on_disk["paused"])
        self.assertEqual(on_disk["channels"], CONFIG["channels"])
        self.assertTrue(self.client.get("/api/automation/status").json()["paused"])

    def test_style_is_validated_and_saved(self):
        self.write_config()
        response = self.client.put("/api/automation/style", json={"style": {"font_size_main": 96, "sub_bottom": 90.5}})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(json.loads(self.paths.config.read_text())["processing"]["style"],
                         {"font_size_main": 96, "sub_bottom": 90.5})
        self.assertEqual(self.client.put("/api/automation/style", json={"style": {"font_size_main": 999}}).status_code,
                         422)
        self.client.put("/api/automation/style", json={"style": None})
        self.assertEqual(json.loads(self.paths.config.read_text())["processing"]["style"], {})


class JobApiTests(ApiTestCase):
    def test_only_youtube_video_links(self):
        for url in ("https://www.bilibili.com/video/BV1WJpN65EEH", "https://www.youtube.com/@ntv_news", "abc"):
            self.assertEqual(self.client.post("/api/automation/jobs", json={"url": url}).status_code, 400, url)

    def test_create_and_poll_through_the_generic_status_endpoint(self):
        response = self.client.post("/api/automation/jobs",
                                    json={"url": "https://youtu.be/T3VwdAhbbQg", "channel": 0, "tags": "a， b"})
        self.assertEqual(response.status_code, 200, response.text)
        task_id = response.json()["task_id"]
        job = store.load_job(self.paths, task_id)
        self.assertEqual((job["url"], job["video_id"]), (VIDEO_URL, "T3VwdAhbbQg"))
        self.assertEqual(job["options"]["tags"], "a,b")
        status = self.client.get(f"/api/status/{task_id}").json()
        self.assertEqual((status["kind"], status["status"], status["job"]["queue_position"]),
                         ("publish", "queued", 1))
        self.assertFalse(status["mover_online"])

    def test_same_video_twice_returns_the_existing_job(self):
        first = self.client.post("/api/automation/jobs", json={"url": VIDEO_URL}).json()
        second = self.client.post("/api/automation/jobs", json={"url": VIDEO_URL}).json()
        self.assertTrue(second["duplicate"])
        self.assertEqual(first["task_id"], second["task_id"])

    def test_history_and_upload_records_need_force(self):
        self.paths.history.write_text(json.dumps(["T3VwdAhbbQg"]))
        response = self.client.post("/api/automation/jobs", json={"url": VIDEO_URL})
        self.assertEqual((response.status_code, response.json()["reason"]), (409, "history"))
        store.append_upload(self.paths, {"video_id": "T3VwdAhbbQg", "bvid": "BV1WJpN65EEH"})
        response = self.client.post("/api/automation/jobs", json={"url": VIDEO_URL})
        self.assertEqual(response.json()["reason"], "uploaded")
        self.assertIn("BV1WJpN65EEH", response.json()["detail"])
        self.assertEqual(self.client.post("/api/automation/jobs", json={"url": VIDEO_URL, "force": True}).status_code,
                         200)

    def test_videos_the_scanner_skipped_need_no_confirmation(self):
        self.paths.history.write_text(json.dumps(["T3VwdAhbbQg"]))
        store.append_event(self.paths, "skip", reason="exclude", video_id="T3VwdAhbbQg", word="every")
        response = self.client.post("/api/automation/jobs", json={"url": VIDEO_URL})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("命中排除词", response.json()["note"])

    def test_a_later_upload_wins_over_an_earlier_skip(self):
        self.paths.history.write_text(json.dumps(["T3VwdAhbbQg"]))
        store.append_event(self.paths, "skip", now=1, reason="keyword", video_id="T3VwdAhbbQg")
        store.append_event(self.paths, "uploaded", now=2, video_id="T3VwdAhbbQg", bvid="BV1aaaaaaaaa")
        response = self.client.post("/api/automation/jobs", json={"url": VIDEO_URL})
        self.assertEqual((response.status_code, response.json()["reason"]), (409, "history"))

    def test_title_and_tid_are_checked(self):
        self.assertEqual(self.client.post("/api/automation/jobs", json={"url": VIDEO_URL, "title": "长" * 81})
                         .status_code, 400)
        self.assertEqual(self.client.post("/api/automation/jobs", json={"url": VIDEO_URL, "tid": 0}).status_code, 400)

    def test_cancel_and_retry(self):
        task_id = self.client.post("/api/automation/jobs", json={"url": VIDEO_URL}).json()["task_id"]
        self.assertEqual(self.client.post(f"/api/automation/jobs/{task_id}/cancel").status_code, 200)
        self.assertEqual(self.client.get(f"/api/status/{task_id}").json()["status"], "cancelled")
        self.assertEqual(self.client.post(f"/api/automation/jobs/{task_id}/cancel").status_code, 409)
        retry = self.client.post(f"/api/automation/jobs/{task_id}/retry").json()
        self.assertNotEqual(retry["task_id"], task_id)
        self.assertEqual(store.load_job(self.paths, retry["task_id"])["options"]["retry_of"], task_id)

    def test_running_job_cannot_be_cancelled(self):
        task_id = self.client.post("/api/automation/jobs", json={"url": VIDEO_URL}).json()["task_id"]
        store.claim_next_job(self.paths, "test")
        self.assertEqual(self.client.post(f"/api/automation/jobs/{task_id}/cancel").status_code, 409)
        self.assertEqual(self.client.post(f"/api/automation/jobs/{task_id}/retry").status_code, 409)
        self.assertEqual(self.client.get(f"/api/status/{task_id}").json()["status"], "processing")

    def test_job_log_is_returned(self):
        task_id = self.client.post("/api/automation/jobs", json={"url": VIDEO_URL}).json()["task_id"]
        store.job_log_path(self.paths, task_id).write_text("10-07 15:00:00 🚀 开始处理\n10-07 15:00:01 [CLI] x\n")
        logs = self.client.get(f"/api/status/{task_id}").json()["logs"]
        self.assertEqual(logs, ["10-07 15:00:00 🚀 开始处理", "10-07 15:00:01 [CLI] x"])

    def test_unknown_ids(self):
        self.assertEqual(self.client.get("/api/status/pub-20261007-150000-abcdef").status_code, 404)
        self.assertEqual(self.client.get("/api/automation/jobs/pub-20261007-150000-abcdef").status_code, 404)
        self.assertEqual(self.client.get("/api/status/not-a-job").status_code, 404)

    def test_list_jobs_with_positions(self):
        first = self.client.post("/api/automation/jobs", json={"url": VIDEO_URL}).json()["task_id"]
        second = self.client.post("/api/automation/jobs", json={"url": "https://youtu.be/aaaaaaaaaaa"}).json()["task_id"]
        jobs = {job["id"]: job for job in self.client.get("/api/automation/jobs").json()["jobs"]}
        self.assertEqual((jobs[first]["queue_position"], jobs[second]["queue_position"]), (1, 2))


class StatusApiTests(ApiTestCase):
    def test_offline_mover_and_counts(self):
        self.write_config()
        self.client.post("/api/automation/jobs", json={"url": VIDEO_URL})
        store.append_event(self.paths, "uploaded", video_id="x")
        store.append_event(self.paths, "skip", reason="exclude", video_id="y")
        store.append_event(self.paths, "uploaded", now=time.time() - 2 * 86400, video_id="old")
        data = self.client.get("/api/automation/status").json()
        self.assertFalse(data["mover"]["online"])
        self.assertEqual(data["queue"]["queued"], 1)
        self.assertEqual(data["channels"], 1)
        self.assertEqual(data["stats_24h"]["uploaded"], 1)
        self.assertEqual(data["stats_24h"]["skipped"]["exclude"], 1)

    def test_online_mover(self):
        store.write_status(self.paths, {"phase": "idle", "heartbeat_at": time.time(), "next_scan_at": time.time() + 60})
        self.assertTrue(self.client.get("/api/automation/status").json()["mover"]["online"])

    def test_scan_request(self):
        self.assertTrue(self.client.post("/api/automation/scan").json()["requested"])
        self.assertTrue(store.scan_requested(self.paths))

    def test_logs_events_uploads(self):
        self.paths.runtime.mkdir(parents=True, exist_ok=True)
        self.paths.log.write_text("a\nb\nc\n")
        self.assertEqual(self.client.get("/api/automation/logs?lines=2").json()["lines"], ["b", "c"])
        store.append_event(self.paths, "skip", reason="keyword", video_id="a")
        self.assertEqual(self.client.get("/api/automation/events").json()["events"][0]["video_id"], "a")
        store.append_upload(self.paths, {"video_id": "a", "bvid": "BV1aaaaaaaaa"})
        self.assertEqual(self.client.get("/api/automation/uploads").json()["uploads"][0]["bvid"], "BV1aaaaaaaaa")


if __name__ == "__main__":
    unittest.main()
