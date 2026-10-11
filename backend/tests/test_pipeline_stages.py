import os
import sys
import unittest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from utils.pipeline_stages import STAGES, detect_stage


def stages_of(log_lines):
    seen = []
    for line in log_lines:
        stage = detect_stage(line)
        if stage and (not seen or seen[-1] != stage):
            seen.append(stage)
    return seen


class TestDetectStage(unittest.TestCase):
    def test_stages_only_move_forward_with_proofreading(self):
        log = [
            "🚀 Starting process for: https://www.youtube.com/watch?v=x",
            "🔄 Loading Whisper model: large-v3-turbo...",
            "✂️ Segmentation mode: rule (offline)",
            "🩹 Proofreading ASR text with Gemini (gemini-3.5-flash), 12 lines...",
            "🤖 Requesting Gemini AI (gemini-3.1-flash-lite) for 12 segments...",
            "🎬 Executing FFmpeg...",
        ]
        self.assertEqual(stages_of(log), ["download", "transcribe", "proofread", "translate", "encode"])
        order = [key for key, _ in STAGES]
        self.assertEqual(stages_of(log), sorted(stages_of(log), key=order.index))

    def test_proofreading_is_skipped_when_off(self):
        log = ["✂️ Segmentation mode: rule (offline)", "🤖 Requesting Gemini AI (m) for 3 segments..."]
        self.assertEqual(stages_of(log), ["transcribe", "translate"])

    def test_cached_translation_skips_proofreading(self):
        self.assertEqual(detect_stage("📦 Loading cached translations from: x.translated.json"), "translate")


if __name__ == "__main__":
    unittest.main()
