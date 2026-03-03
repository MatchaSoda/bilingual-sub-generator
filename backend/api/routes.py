from fastapi import APIRouter, BackgroundTasks, HTTPException
import time
import os
from datetime import datetime
from pathlib import Path
from dotenv import set_key, load_dotenv
from api.schemas import SubtitleRequest
from services.job_manager import global_job_manager
from config.settings import DOWNLOADS_DIR, BASE_DIR
from utils.thumbnail_helper import ensure_thumbnail

api_router = APIRouter()
ENVIRONMENT_VARIABLES_FILE = BASE_DIR / ".env"

@api_router.get("/config")
async def fetch_current_configuration():
    load_dotenv(ENVIRONMENT_VARIABLES_FILE)
    raw_api_keys_string = os.getenv("GOOGLE_API_KEYS", "")
    
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
        set_key(str(ENVIRONMENT_VARIABLES_FILE), "GOOGLE_API_KEYS", new_api_keys_string)
        os.environ["GOOGLE_API_KEYS"] = new_api_keys_string
        
        from config.keys import key_manager
        key_manager.keys = [key.strip() for key in new_api_keys_string.split(",") if key.strip()]
        key_manager.current_index = 0
        
        return {"status": "updated", "count": len(key_manager.keys)}
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Failed to persist configuration: {str(error)}")

@api_router.post("/tasks")
async def submit_new_subtitle_generation_task(request: SubtitleRequest, background_worker: BackgroundTasks):
    new_job_id = global_job_manager.initialize_job_record()
    background_worker.add_task(global_job_manager.execute_subtitle_generation_job, new_job_id, request)
    return {"task_id": new_job_id}

@api_router.get("/status/{task_id}")
async def check_task_execution_status(task_id: str):
    job_details = global_job_manager.retrieve_job_status(task_id)
    if not job_details: 
        raise HTTPException(status_code=404, detail="Requested task not found in active records")
    return job_details

@api_router.get("/library")
async def list_available_processed_videos():
    if not DOWNLOADS_DIR.exists(): 
        return []
        
    discovered_video_files = []
    # Get all matching files and their stats
    video_files_with_stats = []
    for video_file in DOWNLOADS_DIR.glob("*_bilingual.mp4"):
        video_files_with_stats.append((video_file, video_file.stat()))
    
    # Sort by modification time descending (newest first)
    video_files_with_stats.sort(key=lambda x: x[1].st_mtime, reverse=True)

    for video_file, file_statistics in video_files_with_stats:
        ensure_thumbnail(video_file)
        thumb_name = video_file.with_suffix(".jpg").name
        
        discovered_video_files.append({
            "name": video_file.name, 
            "path": f"/downloads/{video_file.name}", 
            "thumbnail": f"/downloads/{thumb_name}",
            "size": f"{file_statistics.st_size / (1024*1024):.2f} MB", 
            "time": datetime.fromtimestamp(file_statistics.st_mtime).strftime('%Y-%m-%d %H:%M')
        })
    return discovered_video_files

@api_router.delete("/library")
async def clear_complete_library():
    if not DOWNLOADS_DIR.exists(): 
        return {"status": "cleared", "count": 0}
        
    deleted_count = 0
    try:
        # Delete both video, associated .ass and .jpg files
        for video_file in DOWNLOADS_DIR.glob("*_bilingual.mp4"):
            video_file.unlink()
            deleted_count += 1
            
        for subtitle_file in DOWNLOADS_DIR.glob("*.ass"):
            subtitle_file.unlink()

        for thumb_file in DOWNLOADS_DIR.glob("*.jpg"):
            thumb_file.unlink()
            
        return {"status": "cleared", "count": deleted_count}
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Failed to clear media library: {str(error)}")

@api_router.delete("/library/{name}")
async def remove_video_from_library(name: str):
    target_video_file = DOWNLOADS_DIR / name
    if not target_video_file.exists():
        raise HTTPException(status_code=404, detail="The specified file does not exist")
        
    try:
        target_video_file.unlink()
        associated_subtitle_file = target_video_file.with_suffix(".ass")
        if associated_subtitle_file.exists(): 
            associated_subtitle_file.unlink()
        associated_thumbnail = target_video_file.with_suffix(".jpg")
        if associated_thumbnail.exists():
            associated_thumbnail.unlink()
        return {"status": "deleted"}
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Failed to delete media assets: {str(error)}")
