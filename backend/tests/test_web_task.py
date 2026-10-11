import io
import os
import sys
import unittest
from unittest import mock

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


if __name__ == "__main__":
    unittest.main()
