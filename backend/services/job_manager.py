import subprocess
import os
import uuid
import time
from pathlib import Path
from config.settings import BASE_DIR, VENV_PYTHON, HTTP_PROXY, HTTPS_PROXY
from utils.thumbnail_helper import ensure_thumbnail

class JobExecutionManager:
    def __init__(self):
        self.active_jobs = {}

    def initialize_job_record(self):
        job_identifier = str(uuid.uuid4())
        self.active_jobs[job_identifier] = {
            "status": "pending",
            "logs": [],
            "result": None,
            "start_time": time.time()
        }
        return job_identifier

    def execute_subtitle_generation_job(self, job_id, request_parameters):
        self.active_jobs[job_id]["status"] = "processing"
        
        python_interpreter = str(VENV_PYTHON) if VENV_PYTHON.exists() else "python3"
        
        cli_command = [
            python_interpreter, "-u", "entry_cli.py", request_parameters.video_url,
            "--whisper-model", request_parameters.whisper_model, 
            "--gemini-model", request_parameters.gemini_model,
            "--target-language", request_parameters.target_language_code,
            "--font-size-main", str(request_parameters.font_size_main),
            "--main-bottom", str(request_parameters.main_subtitle_bottom_margin),
            "--font-alpha", str(request_parameters.main_font_opacity),
            "--outline-alpha", str(request_parameters.main_outline_opacity),
            "--font-weight", str(request_parameters.main_font_weight),
            "--outline-main", str(request_parameters.main_outline_thickness),
            "--shadow-main", str(request_parameters.main_shadow_depth),
            "--font-size-sub", str(request_parameters.font_size_sub),
            "--sub-bottom", str(request_parameters.secondary_subtitle_bottom_margin),
            "--sub-alpha", str(request_parameters.secondary_font_opacity),
            "--outline-sub-alpha", str(request_parameters.secondary_outline_opacity),
            "--font-weight-sub", str(request_parameters.secondary_font_weight),
            "--outline-sub", str(request_parameters.secondary_outline_thickness),
            "--shadow-sub", str(request_parameters.secondary_shadow_depth)
        ]
        
        if request_parameters.is_furigana_enabled:
            cli_command.append("--enable-furigana")
        if request_parameters.should_fix_source_text:
            cli_command.append("--fix-source-text")
        cli_command.append("--translate-title")
        
        execution_environment = os.environ.copy()
        execution_environment["HTTP_PROXY"] = HTTP_PROXY
        execution_environment["HTTPS_PROXY"] = HTTPS_PROXY
        execution_environment["PYTHONPATH"] = str(BASE_DIR / "backend")
        
        try:
            subprocess_instance = subprocess.Popen(
                cli_command, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.STDOUT, 
                text=True, 
                env=execution_environment, 
                bufsize=1, 
                cwd=str(BASE_DIR / "backend")
            )
            
            for log_line in iter(subprocess_instance.stdout.readline, ""):
                stripped_line = log_line.strip()
                self.active_jobs[job_id]["logs"].append(stripped_line)
                
                if "Final video:" in stripped_line: 
                    self.active_jobs[job_id]["result"] = stripped_line.split("Final video:")[1].strip()
            
            subprocess_instance.wait()
            
            if subprocess_instance.returncode == 0:
                self.active_jobs[job_id]["status"] = "completed"
                # Trigger thumbnail generation or synchronization
                video_result_path = self.active_jobs[job_id].get("result")
                if video_result_path:
                    absolute_video_path = Path(video_result_path)
                    if not absolute_video_path.is_absolute():
                        absolute_video_path = BASE_DIR / "backend" / absolute_video_path
                    
                    # Fallback: if yt-dlp already downloaded a thumbnail, use it
                    # The CLI might have already renamed it, but we check just in case
                    # or generate one from video if it's not a YouTube source
                    ensure_thumbnail(absolute_video_path)
            else:
                self.active_jobs[job_id]["status"] = "failed"
                
        except Exception as execution_error:
            self.active_jobs[job_id]["status"] = "failed"
            self.active_jobs[job_id]["logs"].append(f"❌ Execution Error: {str(execution_error)}")

    def retrieve_job_status(self, job_id):
        return self.active_jobs.get(job_id)

global_job_manager = JobExecutionManager()
