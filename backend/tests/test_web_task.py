import io
import os
import sys
import unittest
from unittest import mock

from pydantic import ValidationError

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from api.schemas import SubtitleRequest
from services import job_manager


class FakePopen:
    """Stands in for entry_cli: records the command and prints a finished run."""
    command = None

    def __init__(self, command, **kwargs):
        FakePopen.command = command
        self.stdout = io.StringIO("🩹 Proofreading ASR text with Gemini (m), 3 lines...\n"
                                  "🎉 All done! Final video: /tmp/x_bilingual.mp4\n")
        self.returncode = 0

    def wait(self):
        return 0


def run_web_task(request):
    manager = job_manager.JobExecutionManager()
    job_id = manager.initialize_job_record()
    with mock.patch.object(job_manager.subprocess, "Popen", FakePopen), \
            mock.patch.object(job_manager, "ensure_thumbnail"):
        manager.execute_subtitle_generation_job(job_id, request)
    return manager.active_jobs[job_id]


class TestWebTaskProofreading(unittest.TestCase):
    def test_proofreading_is_on_unless_the_form_turns_it_off(self):
        # Web「仅生成」和自动搬运一样默认纠错（RUNBOOK §5.12）
        job = run_web_task(SubtitleRequest(url="https://www.youtube.com/watch?v=T3VwdAhbbQg"))
        self.assertIn("--fix-source-text", FakePopen.command)
        self.assertTrue(job["proofread"])
        self.assertEqual(job["status"], "completed")

        job = run_web_task(SubtitleRequest(url="https://www.youtube.com/watch?v=T3VwdAhbbQg", fix_source=False))
        self.assertNotIn("--fix-source-text", FakePopen.command)
        self.assertFalse(job["proofread"])

    def test_correction_model_is_passed_only_when_chosen(self):
        run_web_task(SubtitleRequest(url="https://www.youtube.com/watch?v=T3VwdAhbbQg"))
        self.assertNotIn("--correction-model", FakePopen.command)   # entry_cli's default
        run_web_task(SubtitleRequest(url="https://www.youtube.com/watch?v=T3VwdAhbbQg",
                                     correction_model="gemini-3.1-pro-preview"))
        self.assertEqual(FakePopen.command[FakePopen.command.index("--correction-model") + 1], "gemini-3.1-pro-preview")


class TestWebTaskStyle(unittest.TestCase):
    def test_fonts_and_colors_reach_entry_cli(self):
        run_web_task(SubtitleRequest(url="https://www.youtube.com/watch?v=T3VwdAhbbQg",
                                     font_main="Klee One", color_sub="#ffe16b"))
        command = FakePopen.command
        self.assertEqual(command[command.index("--font-main") + 1], "Klee One")
        self.assertEqual(command[command.index("--color-sub") + 1], "#FFE16B")
        self.assertNotIn("--font-sub", command)   # 没传的用 entry_cli 的缺省

    def test_wrong_language_font_or_bad_color_is_rejected(self):
        with self.assertRaises(ValidationError):
            SubtitleRequest(url="https://www.youtube.com/watch?v=T3VwdAhbbQg", font_main="LXGW WenKai")
        with self.assertRaises(ValidationError):
            SubtitleRequest(url="https://www.youtube.com/watch?v=T3VwdAhbbQg", color_main="red")


if __name__ == "__main__":
    unittest.main()
