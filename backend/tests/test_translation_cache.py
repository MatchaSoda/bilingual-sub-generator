"""entry_cli 的翻译缓存（`.translated.json`）和 AI 原文纠错。

开着纠错时，没纠错过的缓存（纠错关着时生成的、或纠错还在翻译里的旧版生成的）不能直接用：
那样纠错这一步被跳过，界面上却显示「纠错」已完成（RUNBOOK §5.12）。
"""
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def write_cache(directory, segments):
    path = Path(directory) / "video.translated.json"
    path.write_text(json.dumps(segments, ensure_ascii=False), encoding="utf-8")
    return path


class TranslationCacheTests(unittest.TestCase):
    def setUp(self):
        import entry_cli
        self.entry_cli = entry_cli
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def load(self, path, needs_proofread):
        with mock.patch("sys.stdout", new_callable=io.StringIO) as output:
            segments = self.entry_cli.load_translation_cache(path, needs_proofread)
        return segments, output.getvalue()

    def test_no_cache_file(self):
        segments, _ = self.load(Path(self.tmp.name) / "missing.translated.json", True)
        self.assertIsNone(segments)

    def test_unproofread_cache_is_redone_when_correction_is_on(self):
        path = write_cache(self.tmp.name, [{"text": "曽愛さん", "translation": "曾爱先生"}])
        segments, output = self.load(path, True)
        self.assertIsNone(segments)
        self.assertIn("without ASR correction", output)
        # 这一行不能被当成进入「翻译」阶段（pipeline_stages 认 "Loading cached translations"）
        self.assertNotIn("Loading cached translations", output)

    def test_unproofread_cache_is_used_when_correction_is_off(self):
        cached = [{"text": "曽愛さん", "translation": "曾爱先生"}]
        segments, output = self.load(write_cache(self.tmp.name, cached), False)
        self.assertEqual(segments, cached)
        self.assertIn("Loading cached translations", output)

    def test_proofread_cache_is_used_either_way(self):
        cached = [{"text": "硤合さん", "translation": "硤合先生", "source_proofread": True}]
        path = write_cache(self.tmp.name, cached)
        for needs_proofread in (True, False):
            segments, _ = self.load(path, needs_proofread)
            self.assertEqual(segments, cached)


class ProofreadResultTests(unittest.TestCase):
    """只有纠错真的失败（Gemini 连不上）才返回 False，缓存不打标记，下次重试。"""

    def setUp(self):
        import entry_cli
        self.entry_cli = entry_cli
        self.media = {"original_title": "t", "description": ""}

    def run_with(self, correct):
        with mock.patch.object(self.entry_cli.AsrSourceCorrector, "correct", correct), \
                mock.patch.object(self.entry_cli.AsrSourceCorrector, "__init__", lambda self, **kw: None), \
                mock.patch("sys.stdout", new_callable=io.StringIO):
            return self.entry_cli.proofread_source_text([], "ja", self.media, "t", "m")

    def test_gemini_failure_returns_false(self):
        def fail(*args, **kwargs):
            raise RuntimeError("unreachable")
        self.assertFalse(self.run_with(fail))

    def test_skipped_language_counts_as_done(self):
        self.assertTrue(self.run_with(lambda *args, **kwargs: None))


if __name__ == "__main__":
    unittest.main()
