"""「自动搬运」页面和「生成并投稿」的接口。

Web 进程自己不投稿，只读写 STATE_DIR 下和 mover 共享的文件（utils/automation_store.py）：
投稿任务写进 jobs/，mover 按提交顺序执行，和频道扫描排在同一条队列里，所以不会两边同时压视频，
也不会把同一个视频投两次。mover 没在跑时任务就一直排着，页面上会提示。
"""
import os
import time
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from config.settings import AUTOMATION_STATE_DIR
from utils import automation_store as store

# 接口都写成普通函数：FastAPI 把它们放进线程池跑，查 B 站登录状态、读一堆任务文件时不会卡住别的请求
automation_router = APIRouter()
PATHS = store.Paths(AUTOMATION_STATE_DIR)

SKIP_REASON_TEXT = {"keyword": "关键词不匹配", "exclude": "命中排除词", "cutoff": "早于起点", "description_failed": "拉简介失败"}

# 投稿任务的状态 → 前端任务面板沿用的那套状态名（和 Web 任务一致）
JOB_STATUS_FOR_UI = {"queued": "queued", "running": "processing", "done": "completed",
                     "failed": "failed", "cancelled": "cancelled"}


def _error(status_code, message, **extra):
    return JSONResponse(status_code=status_code, content=dict(detail=message, **extra))


def _read_config():
    """返回 (原始配置, 版本, 错误信息)。文件坏了不抛异常，页面要能把错误显示出来。"""
    try:
        config, version = store.load_config(PATHS)
        return config, version, None
    except (ValueError, OSError) as e:
        return None, store.config_version(PATHS.config), f"config.json 读不了: {e}"


def _queue_snapshot():
    jobs = store.list_jobs(PATHS)
    queued = [job for job in reversed(jobs) if job.get("status") == "queued"]
    running = next((job for job in jobs if job.get("status") == "running"), None)
    return queued, running


def _with_queue_position(job, queued):
    job = dict(job)
    ids = [j["id"] for j in queued]
    job["queue_position"] = ids.index(job["id"]) + 1 if job["id"] in ids else None
    return job


# ---------------------------------------------------------------- 状态与控制


@automation_router.get("/status")
def automation_status():
    now = time.time()
    config, _, config_error = _read_config()
    effective = store.effective_config(config or {})
    queued, running = _queue_snapshot()
    events = store.read_events(PATHS, limit=None, since=now - 86400)
    return {
        "server_time": now,
        "mover": store.read_status(PATHS, now),
        # 部署层面的开关：Docker 下 ENABLE_AUTOMATION=1 才会起 mover 容器（docker-start.sh）
        "automation_enabled": os.getenv("ENABLE_AUTOMATION") == "1" if os.getenv("ENABLE_AUTOMATION") else None,
        "config_exists": config is not None,
        "config_error": config_error,
        "paused": bool(effective.get("paused")),
        "channels": len(effective.get("channels") or []),
        "check_interval_seconds": effective.get("check_interval_seconds"),
        "queue": {"queued": len(queued), "running": running},
        "stats_24h": store.summarize_events(events),
    }


class PauseRequest(BaseModel):
    paused: bool


@automation_router.post("/pause")
def set_paused(request: PauseRequest):
    try:
        _, version = store.update_config(PATHS, lambda config: config.__setitem__("paused", request.paused))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"paused": request.paused, "version": version}


@automation_router.post("/scan")
def scan_now():
    store.request_scan(PATHS)
    return {"requested": True, "mover_online": store.read_status(PATHS)["online"]}


# ---------------------------------------------------------------- 配置


@automation_router.get("/config")
def get_config():
    config, version, error = _read_config()
    return {
        "exists": config is not None,
        "error": error,
        "version": version,
        "config": config or {},
        "effective": store.effective_config(config or {}),
        "channel_defaults": store.CHANNEL_DEFAULTS,
        "style_defaults": store.STYLE_DEFAULTS,
        "style_fields": {key: {"type": kind.__name__, "min": lo, "max": hi}
                         for key, (kind, lo, hi, _default) in store.STYLE_FIELDS.items()},
        "options": {
            "whisper_models": store.WHISPER_MODELS,
            "gemini_models": store.GEMINI_MODELS,
            "segment_modes": store.SEGMENT_MODES,
            "backfill_modes": store.BACKFILL_MODES,
            "upload_lines": store.UPLOAD_LINES,
        },
    }


class ConfigUpdate(BaseModel):
    config: dict
    version: str


@automation_router.put("/config")
def put_config(update: ConfigUpdate):
    config, errors = store.normalize_config(update.config)
    if errors:
        return _error(422, "配置里有不合法的值", errors=errors)
    try:
        version = store.save_config(PATHS, config, expected_version=update.version)
    except store.ConfigConflict as conflict:
        return _error(409, "config.json 在你打开页面之后被改过了（向导或手工编辑）。刷新后再改。",
                      current_version=conflict.current_version)
    return {"version": version, "config": config, "effective": store.effective_config(config)}


class StyleUpdate(BaseModel):
    style: Optional[dict] = None


@automation_router.put("/style")
def put_style(update: StyleUpdate):
    """视觉实验室「设为投稿样式」：只改 processing.style，不碰别的配置。style 为空 = 恢复默认样式。"""
    errors = []
    style = store.normalize_style(update.style or {}, errors)
    if errors:
        return _error(422, "样式里有不合法的值", errors=errors)

    def apply(config):
        config.setdefault("processing", {})["style"] = style

    try:
        _, version = store.update_config(PATHS, apply)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"style": style, "version": version}


# ---------------------------------------------------------------- 动态、记录、日志


@automation_router.get("/events")
def get_events(limit: int = 100):
    return {"server_time": time.time(), "events": store.read_events(PATHS, limit=max(1, min(limit, 1000)))}


@automation_router.get("/uploads")
def get_uploads(limit: int = 200):
    return {"uploads": store.read_uploads(PATHS, limit=max(1, min(limit, 5000)))}


@automation_router.get("/logs")
def get_logs(lines: int = 300):
    return {"exists": PATHS.log.is_file(), "lines": store.tail_text(PATHS.log, max_lines=max(1, min(lines, 2000)))}


# ---------------------------------------------------------------- 投稿任务


class JobRequest(BaseModel):
    url: str
    channel: Optional[int] = None
    tid: Optional[int] = None
    tags: Optional[str] = None
    title: Optional[str] = None
    force: bool = False


def _job_options(request):
    if request.channel is not None and request.channel < 0:
        raise HTTPException(status_code=400, detail="频道序号不对")
    if request.tid is not None and not 1 <= request.tid <= 100000:
        raise HTTPException(status_code=400, detail="分区 tid 不对")
    tags = ",".join(t.strip() for t in (request.tags or "").replace("，", ",").split(",") if t.strip())
    title = (request.title or "").strip()
    if len(title) > 80:
        raise HTTPException(status_code=400, detail="B 站标题最多 80 个字")
    return {"channel": request.channel, "tid": request.tid, "tags": tags or None, "title": title or None}


@automation_router.post("/jobs")
def create_job(request: JobRequest):
    url, video_id = store.parse_youtube_url(request.url)
    if not video_id:
        raise HTTPException(status_code=400, detail="投稿只支持 YouTube 单个视频的链接（watch?v=、youtu.be、shorts）")
    options = _job_options(request)
    existing = store.active_job_for(PATHS, video_id)
    if existing:
        return {"task_id": existing["id"], "job": existing, "duplicate": True}
    note = None
    if not request.force:
        upload = store.find_upload(PATHS, video_id)
        if upload:
            return _error(409, f"这个视频已经投过稿了（{upload.get('bvid') or 'BV 号未知'}）", reason="uploaded",
                          upload=upload)
        if store.history_contains(PATHS, video_id):
            # mover 把扫到的每个视频都记进 history（处理的和跳过的）。有跳过记录的就是没投过，直接放行
            skip = store.find_skip(PATHS, video_id)
            if skip is None:
                return _error(409, "这个视频在自动搬运的历史记录里：可能已经投过稿，也可能是被过滤规则跳过的",
                              reason="history")
            note = f"自动搬运之前跳过了这个视频（{SKIP_REASON_TEXT.get(skip.get('reason'), skip.get('reason'))}）"
    job = store.create_job(PATHS, url, video_id, options)
    return {"task_id": job["id"], "job": job, "note": note, "mover_online": store.read_status(PATHS)["online"]}


@automation_router.get("/jobs")
def list_jobs(limit: int = 50):
    queued, _ = _queue_snapshot()
    jobs = store.list_jobs(PATHS)[:max(1, min(limit, store.MAX_JOBS))]
    return {"server_time": time.time(), "jobs": [_with_queue_position(job, queued) for job in jobs]}


def job_status_payload(job_id, log_lines=500):
    """单个投稿任务给任务面板的样子：字段和 Web 任务（/api/status）对齐，前端用同一套轮询。"""
    job = store.load_job(PATHS, job_id)
    if job is None:
        return None
    queued, running = _queue_snapshot()
    mover = store.read_status(PATHS)
    return {
        "kind": "publish",
        "status": JOB_STATUS_FOR_UI.get(job.get("status"), job.get("status")),
        "stage": job.get("stage"),
        "logs": store.tail_text(store.job_log_path(PATHS, job_id), max_lines=log_lines),
        "result": job.get("result"),
        "error": job.get("error"),
        "job": _with_queue_position(job, queued),
        "mover_online": mover["online"],
        # 排队时告诉用户 mover 正在忙什么
        "mover_current": mover.get("current") if job.get("status") == "queued" else None,
        "running_job": running["id"] if running else None,
    }


@automation_router.get("/jobs/{job_id}")
def get_job(job_id: str, lines: int = 500):
    payload = job_status_payload(job_id, log_lines=max(1, min(lines, 5000)))
    if payload is None:
        raise HTTPException(status_code=404, detail="没有这个投稿任务")
    return payload


@automation_router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    if store.load_job(PATHS, job_id) is None:
        raise HTTPException(status_code=404, detail="没有这个投稿任务")
    job = store.cancel_job(PATHS, job_id)
    if job is None:
        raise HTTPException(status_code=409, detail="任务已经开始了，只能取消还在排队的任务")
    return {"job": job}


@automation_router.post("/jobs/{job_id}/retry")
def retry_job(job_id: str):
    old = store.load_job(PATHS, job_id)
    if old is None:
        raise HTTPException(status_code=404, detail="没有这个投稿任务")
    if old.get("status") in store.ACTIVE_STATUSES:
        raise HTTPException(status_code=409, detail="任务还在进行中")
    existing = store.active_job_for(PATHS, old["video_id"])
    if existing:
        return {"task_id": existing["id"], "job": existing, "duplicate": True}
    job = store.create_job(PATHS, old["url"], old["video_id"], dict(old.get("options") or {}, retry_of=job_id))
    return {"task_id": job["id"], "job": job, "mover_online": store.read_status(PATHS)["online"]}
