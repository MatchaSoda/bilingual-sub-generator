import subprocess
import os
import uuid
import time
from pathlib import Path
from config.settings import BASE_DIR, VENV_PYTHON, HTTP_PROXY, HTTPS_PROXY
from utils.thumbnail_helper import ensure_thumbnail
from utils.pipeline_stages import detect_stage
from utils.child_tmp import child_tmp_env
from api.schemas import STYLE_TEXT_KEYS

class JobExecutionManager:
    def __init__(self):
        self.active_jobs = {}

    def initialize_job_record(self):
        job_identifier = str(uuid.uuid4())
        self.active_jobs[job_identifier] = {
            "kind": "generate",
            "status": "pending",
            "stage": "queued",
            "logs": [],
            "result": None,
            "start_time": time.time()
        }
        return job_identifier

    def execute_subtitle_generation_job(self, job_id, request_parameters):
        self.active_jobs[job_id]["status"] = "processing"
        # 任务面板据此决定进度条里有没有「纠错」这一步
        self.active_jobs[job_id]["proofread"] = bool(request_parameters.should_fix_source_text)
        
        python_interpreter = str(VENV_PYTHON) if VENV_PYTHON.exists() else "python3"
        
        cli_command = [
            python_interpreter, "-u", "entry_cli.py", request_parameters.video_url,
            "--whisper-model", request_parameters.whisper_model, 
            "--gemini-model", request_parameters.gemini_model,
            "--target-language", request_parameters.target_language_code,
            "--segment-mode", request_parameters.segment_mode,
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
        # 字体和颜色：没传的用 entry_cli 的缺省
        for key in STYLE_TEXT_KEYS:
            value = getattr(request_parameters, key)
            if value:
                cli_command += [f"--{key.replace('_', '-')}", value]

        if request_parameters.is_furigana_enabled:
            cli_command.append("--enable-furigana")
        if request_parameters.should_fix_source_text:
            cli_command.append("--fix-source-text")
            if request_parameters.correction_model:
                cli_command += ["--correction-model", request_parameters.correction_model]
        cli_command.append("--translate-title")
        
        execution_environment = os.environ.copy()
        # 代理可能未配置（直连部署），环境变量值必须是 str，不能塞 None。
        if HTTP_PROXY:
            execution_environment["HTTP_PROXY"] = HTTP_PROXY
        if HTTPS_PROXY:
            execution_environment["HTTPS_PROXY"] = HTTPS_PROXY
        execution_environment["PYTHONPATH"] = str(BASE_DIR / "backend")
        
        try:
            # PO Token 插件的 Chromium profile 落在独立 TMPDIR，结束后整个删掉（RUNBOOK §5.15）
            with child_tmp_env(execution_environment) as child_environment:
                subprocess_instance = subprocess.Popen(
                    cli_command, 
                    stdout=subprocess.PIPE, 
                    stderr=subprocess.STDOUT, 
                    text=True, 
                    env=child_environment, 
                    bufsize=1, 
                    cwd=str(BASE_DIR / "backend")
                )
            
                for log_line in iter(subprocess_instance.stdout.readline, ""):
                    stripped_line = log_line.strip()
                    self.active_jobs[job_id]["logs"].append(stripped_line)
                    # 和自动搬运同一张阶段表（utils/pipeline_stages.py），任务面板据此画分阶段进度
                    stage = detect_stage(stripped_line)
                    if stage:
                        self.active_jobs[job_id]["stage"] = stage

                    if "Final video:" in stripped_line: 
                        self.active_jobs[job_id]["result"] = stripped_line.split("Final video:")[1].strip()
            
                subprocess_instance.wait()
            
            if subprocess_instance.returncode == 0:
                self.active_jobs[job_id]["status"] = "completed"
                self.active_jobs[job_id]["stage"] = "done"
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
