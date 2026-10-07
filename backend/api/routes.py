from fastapi import APIRouter, BackgroundTasks, HTTPException
import time
import os
from pathlib import Path
from dotenv import set_key
from api.schemas import SubtitleRequest
from services.job_manager import global_job_manager
from config.settings import DOWNLOADS_DIR, AUTOMATION_OUTPUT_DIR, ENV_FILE
from config.keys import key_manager, read_google_api_keys
from utils.thumbnail_helper import ensure_thumbnail
from utils.library import collect_library, resolve_library_video, delete_library_video
from utils.automation_store import is_job_id
from api.automation_routes import job_status_payload

api_router = APIRouter()
# 裸机 = 仓库根 .env；Docker = userdata/.env（AUTOMATION_STATE_DIR），见 config/settings.py
ENVIRONMENT_VARIABLES_FILE = ENV_FILE

@api_router.get("/config")
async def fetch_current_configuration():
    raw_api_keys_string = read_google_api_keys()
    
    masked_keys_for_display = []
    for individual_key in raw_api_keys_string.split(","):
        trimmed_key = individual_key.strip()
        if len(trimmed_key) > 8:
            masked_keys_for_display.append(f"{trimmed_key[:4]}...{trimmed_key[-4:]}")
        elif trimmed_key:
            masked_keys_for_display.append("****")
            
    return {
        "google_api_keys": raw_api_keys_string, 
        "masked_keys": ",".join(masked_keys_for_display)
    }

@api_router.post("/config")
async def update_google_api_keys(configuration_update: dict):
    new_api_keys_string = configuration_update.get("google_api_keys", "").strip()
    try:
        set_key(str(ENVIRONMENT_VARIABLES_FILE), "GOOGLE_API_KEYS", new_api_keys_string, quote_mode="never")
        # entry_cli.py 子进程继承 os.environ（job_manager 用 os.environ.copy()），所以这里必须同步更新
        os.environ["GOOGLE_API_KEYS"] = new_api_keys_string

        key_manager.active_api_keys = [key.strip() for key in new_api_keys_string.split(",") if key.strip()]
        key_manager.next_key_index = 0

        return {"status": "updated", "count": len(key_manager.active_api_keys)}
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Failed to persist configuration: {str(error)}")

@api_router.post("/tasks")
async def submit_new_subtitle_generation_task(request: SubtitleRequest, background_worker: BackgroundTasks):
    new_job_id = global_job_manager.initialize_job_record()
    background_worker.add_task(global_job_manager.execute_subtitle_generation_job, new_job_id, request)
    return {"task_id": new_job_id}

@api_router.get("/status/{task_id}")
def check_task_execution_status(task_id: str):
    # 「生成并投稿」的任务由 mover 执行，状态在共享的 jobs/ 目录里；字段和 Web 任务对齐，前端用同一套轮询
    if is_job_id(task_id):
        payload = job_status_payload(task_id)
        if payload is None:
            raise HTTPException(status_code=404, detail="Requested task not found in active records")
        return payload
    job_details = global_job_manager.retrieve_job_status(task_id)
    if not job_details: 
        raise HTTPException(status_code=404, detail="Requested task not found in active records")
    return job_details

# 媒体库的两个来源（utils/library.py）。URL 前缀对应 entry_server.py 里的两个静态目录挂载。
LIBRARY_SOURCES = {
    "web": (DOWNLOADS_DIR, "/downloads"),
    "auto": (AUTOMATION_OUTPUT_DIR, "/outputs"),
}


def _library_source(source):
    if source not in LIBRARY_SOURCES:
        raise HTTPException(status_code=400, detail=f"Unknown library source: {source}")
    return LIBRARY_SOURCES[source]


@api_router.get("/library")
async def list_available_processed_videos():
    return collect_library(LIBRARY_SOURCES, ensure_thumbnail=ensure_thumbnail)

@api_router.delete("/library")
async def clear_complete_library(source: str = "web"):
    # 缺省只清 Web 成品；媒体库界面按当前的来源筛选传 web / auto / all。
    # 只删成品和它自己的封面、字幕，下载缓存留给 mover 的定期清理（RUNBOOK §4）。
    directories = list(LIBRARY_SOURCES.values()) if source == "all" else [_library_source(source)]
    deleted_count = 0
    try:
        for directory, _ in directories:
            for video_file in list(directory.glob("*_bilingual.mp4")):
                delete_library_video(video_file)
                deleted_count += 1
        return {"status": "cleared", "count": deleted_count}
    except OSError as error:
        raise HTTPException(status_code=500, detail=f"Failed to clear media library: {str(error)}")

@api_router.delete("/library/{name}")
async def remove_video_from_library(name: str, source: str = "web"):
    directory, _ = _library_source(source)
    target_video_file = resolve_library_video(directory, name)
    if target_video_file is None:
        raise HTTPException(status_code=404, detail="The specified file does not exist")
    try:
        delete_library_video(target_video_file)
        return {"status": "deleted"}
    except OSError as error:
        raise HTTPException(status_code=500, detail=f"Failed to delete media assets: {str(error)}")
