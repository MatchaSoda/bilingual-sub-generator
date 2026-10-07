"""自动搬运的共享状态。Web 进程和 mover 进程（Docker 里是两个容器）只通过 STATE_DIR 下的文件协作：

  config.json            搬运配置。mover 每轮重读；Web「自动搬运」页面读写（带版本号，防止覆盖手工改动）
  uploads.jsonl          投稿记录：BV 号 ↔ YouTube ID ↔ 成品文件名。长期保存，迁移时带走
  jobs/<id>.json         Web 提交的投稿任务，mover 按提交顺序逐个执行；<id>.log 是这个任务的日志
  runtime/status.json    mover 的心跳和当前在做什么，Web 据此判断服务在不在线
  runtime/events.jsonl   最近的判定和结果（跳过原因、失败、投稿成功），Web 的「最近动态」和统计
  runtime/mover.log      mover 的输出（带时间戳），Web 的日志页
  runtime/wake           「立即扫描」的触发文件，mover 休眠时每几秒看一眼

STATE_DIR 裸机是 automation/，Docker 是 userdata/。长期保存的放根目录，运行期的放 runtime/：
userdata/data/ 会被定期清理整个扫掉（RUNBOOK §4），这里的东西都不能放进去。

只用标准库：mover.py 也 import 这个模块，不能牵出 config.settings 的副作用（建目录、读 .env）。
两个容器共用一个内核，fcntl.flock 在 bind mount 上跨容器互斥（OrbStack 10-07 实测）。
"""
import copy
import fcntl
import hashlib
import json
import os
import re
import secrets
import shutil
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

# ---------------------------------------------------------------- 路径


class Paths:
    def __init__(self, state_dir):
        self.state_dir = Path(state_dir)
        self.config = self.state_dir / "config.json"
        self.config_backup = self.state_dir / "config.json.bak-last"
        self.history = self.state_dir / "history.json"
        self.uploads = self.state_dir / "uploads.jsonl"
        self.jobs = self.state_dir / "jobs"
        self.runtime = self.state_dir / "runtime"
        self.status = self.runtime / "status.json"
        self.events = self.runtime / "events.jsonl"
        self.log = self.runtime / "mover.log"
        self.wake = self.runtime / "wake"
        self.config_lock = self.runtime / "config.lock"
        self.uploads_lock = self.runtime / "uploads.lock"
        self.jobs_lock = self.runtime / "jobs.lock"


# ---------------------------------------------------------------- 文件小工具


def write_json_atomic(path, data):
    """先写临时文件再 rename，读的一方永远看不到写了一半的文件。保留原文件的权限位。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        try:
            os.chmod(tmp_path, path.stat().st_mode & 0o777)
        except FileNotFoundError:
            pass
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def read_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


@contextmanager
def file_lock(lock_path):
    lock_path = Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


def append_jsonl(path, record):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_jsonl(path):
    """逐行解析，坏行（比如写到一半断电）直接跳过。"""
    records = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return records


def tail_text(path, max_lines=400, max_bytes=512 * 1024):
    """读文件末尾的若干行，日志可能很大，只读最后 max_bytes。"""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            data = f.read()
    except OSError:
        return []
    lines = data.decode("utf-8", "replace").splitlines()
    if size > max_bytes and lines:
        lines = lines[1:]  # 第一行多半被从中间截断
    return lines[-max_lines:] if max_lines else lines


# ---------------------------------------------------------------- 配置

# mover.py 里所有「没写就用这个值」的缺省都在这里，界面显示的「当前生效值」也按它算。
# 这些是代码缺省，不是推荐值：推荐值在 automation/config.json.example。
CHANNEL_DEFAULTS = {
    "name": "",
    "url": "",
    "keyword": "",
    "exclude": [],
    "bili_tid": 171,
    "tags": "日语学习,双语字幕,日本,日本新闻,日常",
}

DEFAULT_TITLE_TEMPLATE = "【双语字幕】{title}"
DEFAULT_DESCRIPTION_TEMPLATE = "原始视频: {url}\n使用 AI 自动生成双语字幕和假名标注。"

DEFAULTS = {
    "channels": [],
    "paused": False,
    "check_interval_seconds": 300,
    "playlist_items": 10,
    "description_fetch_interval_seconds": 0,
    "max_uploads_per_cycle": 0,
    "backfill": {"mode": "all", "lookback_hours": 24},
    "processing": {
        "whisper_model": "large-v3-turbo",
        "segment_mode": "rule",
        "gemini_model": "gemini-3.1-flash-lite",
        "translation_batch_size": 100,
        "enable_furigana": True,
        "translate_title": True,
        "fix_source_text": False,
        "style": {},
    },
    "upload": {
        "line": None,
        "retries": 3,
        "retry_delay_seconds": 60,
        "title_template": DEFAULT_TITLE_TEMPLATE,
        "description_template": DEFAULT_DESCRIPTION_TEMPLATE,
    },
    "cleanup": {"keep_days": 7},
}

# 字幕样式 → entry_cli.py 的参数（--font-size-main 之类，下划线换成连字符）。
# 类型要和 entry_cli 的 argparse 一致：int 参数传 "90.0" 会直接报错退出。范围和视觉实验室的滑块一致。
STYLE_FIELDS = {
    "font_size_main": (int, 10, 150, 90),
    "main_bottom": (float, 0, 100, 0.7),
    "font_alpha": (int, 0, 100, 100),
    "outline_alpha": (int, 0, 100, 100),
    "font_weight": (int, 100, 900, 700),
    "outline_main": (float, 0, 15, 3.0),
    "shadow_main": (float, 0, 15, 1.5),
    "font_size_sub": (int, 10, 150, 75),
    "sub_bottom": (float, 0, 100, 92.1),
    "sub_alpha": (int, 0, 100, 100),
    "outline_sub_alpha": (int, 0, 100, 100),
    "font_weight_sub": (int, 100, 900, 400),
    "outline_sub": (float, 0, 15, 2.0),
    "shadow_sub": (float, 0, 15, 1.5),
}
STYLE_DEFAULTS = {key: spec[3] for key, spec in STYLE_FIELDS.items()}

WHISPER_MODELS = ["large-v3-turbo", "large-v3", "medium", "small", "base", "tiny"]
GEMINI_MODELS = ["gemini-3.1-flash-lite", "gemini-3-flash-preview", "gemini-3.1-pro-preview", "gemini-2.5-flash"]
SEGMENT_MODES = ["rule", "llm"]
BACKFILL_MODES = ["all", "since_first_start"]
# biliup upload --line 的可选值（biliup 1.1.29 --help）
UPLOAD_LINES = ["tx", "bda2", "bldsa", "cnbldsa", "andsa", "atdsa", "cnbd", "anbd", "atbd",
                "cntx", "antx", "attx", "bda", "txa", "alia"]


def _deep_merge(base, override):
    merged = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def effective_config(raw):
    """把文件里没写的项按代码缺省补齐，得到 mover 实际在用的值（界面显示用）。"""
    merged = _deep_merge(DEFAULTS, raw if isinstance(raw, dict) else {})
    merged["channels"] = [_deep_merge(CHANNEL_DEFAULTS, ch) for ch in merged.get("channels") or []
                          if isinstance(ch, dict)]
    return merged


def config_version(path):
    """文件内容的指纹。界面保存时带上读到的版本，期间有人手改过文件就拒绝覆盖。"""
    try:
        return hashlib.sha1(Path(path).read_bytes()).hexdigest()[:16]
    except FileNotFoundError:
        return "missing"


class ConfigConflict(Exception):
    def __init__(self, current_version):
        super().__init__("config.json 在你打开页面之后被改过了")
        self.current_version = current_version


def _as_number(value, kind, errors, path, lo=None, hi=None):
    if isinstance(value, bool):
        errors.append({"path": path, "message": "要填数字"})
        return None
    try:
        number = kind(value) if kind is float else int(float(value))
    except (TypeError, ValueError):
        errors.append({"path": path, "message": "要填数字"})
        return None
    if kind is int and float(value) != number:
        errors.append({"path": path, "message": "要填整数"})
        return None
    if (lo is not None and number < lo) or (hi is not None and number > hi):
        errors.append({"path": path, "message": f"范围 {lo}–{hi}"})
        return None
    if kind is float and number == int(number):
        return int(number)  # 4.0 写回文件还是 4，别让手写的配置因为过了一遍界面就变样
    return number


def _as_bool(value, errors, path):
    if isinstance(value, bool):
        return value
    errors.append({"path": path, "message": "要填 true / false"})
    return None


def _as_text(value, errors, path, required=False):
    if value is None:
        value = ""
    if not isinstance(value, str):
        errors.append({"path": path, "message": "要填文字"})
        return None
    value = value.strip()
    if required and not value:
        errors.append({"path": path, "message": "不能为空"})
        return None
    return value


def _word_list(value, errors, path):
    """排除词：接受列表或逗号分隔的字符串，去空去重，保留原顺序。"""
    if isinstance(value, str):
        value = re.split(r"[,，\n]", value)
    if not isinstance(value, list):
        errors.append({"path": path, "message": "要填词语列表"})
        return None
    words = []
    for word in value:
        if not isinstance(word, str):
            errors.append({"path": path, "message": "每个词都要是文字"})
            return None
        word = word.strip()
        if word and word not in words:
            words.append(word)
    return words


def normalize_style(style, errors=None, path="processing.style"):
    """校验字幕样式并转成 entry_cli 要的类型；不认识的键丢掉（只传 entry_cli 认识的参数）。"""
    errors = [] if errors is None else errors
    if style in (None, {}):
        return {}
    if not isinstance(style, dict):
        errors.append({"path": path, "message": "格式不对"})
        return {}
    normalized = {}
    for key, (kind, lo, hi, _default) in STYLE_FIELDS.items():
        if key in style and style[key] is not None:
            value = _as_number(style[key], kind, errors, f"{path}.{key}", lo, hi)
            if value is not None:
                normalized[key] = value
    return normalized


def normalize_config(raw):
    """校验界面提交的配置，返回 (规范化后的配置, 错误列表)。

    只校验和规范化认识的字段，不认识的键原样保留（手工加的、以后版本加的都不丢）。
    错误的 path 用 channels[0].url 这种写法，界面据此标红对应的输入框。
    """
    errors = []
    if not isinstance(raw, dict):
        return {}, [{"path": "", "message": "配置必须是一个 JSON 对象"}]
    config = copy.deepcopy(raw)

    channels = raw.get("channels", [])
    if not isinstance(channels, list):
        errors.append({"path": "channels", "message": "要是列表"})
        channels = []
    normalized_channels = []
    for i, channel in enumerate(channels):
        path = f"channels[{i}]"
        if not isinstance(channel, dict):
            errors.append({"path": path, "message": "格式不对"})
            continue
        ch = copy.deepcopy(channel)
        url = _as_text(channel.get("url"), errors, f"{path}.url", required=True)
        if url is not None:
            if not re.match(r"^https?://", url):
                errors.append({"path": f"{path}.url", "message": "要以 http:// 或 https:// 开头"})
            ch["url"] = url
        name = _as_text(channel.get("name"), errors, f"{path}.name")
        if name is not None:
            ch["name"] = name or url or ""
        keyword = _as_text(channel.get("keyword"), errors, f"{path}.keyword")
        if keyword is not None:
            ch["keyword"] = keyword
        exclude = _word_list(channel.get("exclude", []), errors, f"{path}.exclude")
        if exclude is not None:
            ch["exclude"] = exclude
        if "bili_tid" in channel:
            tid = _as_number(channel.get("bili_tid"), int, errors, f"{path}.bili_tid", 1, 100000)
            if tid is not None:
                ch["bili_tid"] = tid
        if "tags" in channel:
            tags = _as_text(channel.get("tags"), errors, f"{path}.tags")
            if tags is not None:
                ch["tags"] = ",".join(t.strip() for t in re.split(r"[,，]", tags) if t.strip())
        normalized_channels.append(ch)
    config["channels"] = normalized_channels

    if "paused" in raw:
        value = _as_bool(raw["paused"], errors, "paused")
        if value is not None:
            config["paused"] = value

    for key, kind, lo, hi in (
        ("check_interval_seconds", int, 60, 86400),
        ("playlist_items", int, 1, 1000),
        ("description_fetch_interval_seconds", float, 0, 120),
        ("max_uploads_per_cycle", int, 0, 100),
    ):
        if key in raw:
            value = _as_number(raw[key], kind, errors, key, lo, hi)
            if value is not None:
                config[key] = value

    sections = {}
    for name in ("backfill", "processing", "upload", "cleanup"):
        section = raw.get(name, {})
        if section is None:
            section = {}
        if not isinstance(section, dict):
            errors.append({"path": name, "message": "格式不对"})
            section = {}
        sections[name] = section
        if name in raw:  # 没写的段不补空对象，文件保持原样
            config[name] = copy.deepcopy(section)

    backfill = sections["backfill"]
    if "mode" in backfill:
        if backfill["mode"] not in BACKFILL_MODES:
            errors.append({"path": "backfill.mode", "message": "只能是 all 或 since_first_start"})
    if "lookback_hours" in backfill:
        value = _as_number(backfill["lookback_hours"], float, errors, "backfill.lookback_hours", 0, 24 * 365)
        if value is not None:
            config["backfill"]["lookback_hours"] = value

    processing = sections["processing"]
    if "whisper_model" in processing and processing["whisper_model"] not in WHISPER_MODELS:
        errors.append({"path": "processing.whisper_model", "message": "不认识的模型"})
    if "segment_mode" in processing and processing["segment_mode"] not in SEGMENT_MODES:
        errors.append({"path": "processing.segment_mode", "message": "只能是 rule 或 llm"})
    if "gemini_model" in processing:
        value = _as_text(processing["gemini_model"], errors, "processing.gemini_model", required=True)
        if value is not None:
            config["processing"]["gemini_model"] = value
    if "translation_batch_size" in processing:
        value = _as_number(processing["translation_batch_size"], int, errors,
                           "processing.translation_batch_size", 10, 500)
        if value is not None:
            config["processing"]["translation_batch_size"] = value
    for key in ("enable_furigana", "translate_title", "fix_source_text"):
        if key in processing:
            _as_bool(processing[key], errors, f"processing.{key}")
    if "style" in processing:
        config["processing"]["style"] = normalize_style(processing["style"], errors)

    upload = sections["upload"]
    if "line" in upload:
        line = upload["line"] or None
        if line is not None and line not in UPLOAD_LINES:
            errors.append({"path": "upload.line", "message": "不认识的上传线路"})
        config["upload"]["line"] = line
    if "retries" in upload:
        value = _as_number(upload["retries"], int, errors, "upload.retries", 1, 10)
        if value is not None:
            config["upload"]["retries"] = value
    if "retry_delay_seconds" in upload:
        value = _as_number(upload["retry_delay_seconds"], int, errors, "upload.retry_delay_seconds", 0, 3600)
        if value is not None:
            config["upload"]["retry_delay_seconds"] = value
    for key in ("title_template", "description_template"):
        if key in upload:
            value = _as_text(upload[key], errors, f"upload.{key}", required=True)
            if value is not None:
                config["upload"][key] = value
    if "title_template" in upload and isinstance(upload["title_template"], str) \
            and "{title}" not in upload["title_template"]:
        errors.append({"path": "upload.title_template", "message": "要包含 {title}，否则每个稿件标题都一样"})

    cleanup = sections["cleanup"]
    if "keep_days" in cleanup:
        value = _as_number(cleanup["keep_days"], float, errors, "cleanup.keep_days", 0, 3650)
        if value is not None:
            config["cleanup"]["keep_days"] = value

    return config, errors


def load_config(paths):
    """返回 (原始配置 或 None, 版本)。文件不存在时配置是 None。坏 JSON 抛 ValueError。"""
    if not paths.config.is_file():
        return None, "missing"
    data = paths.config.read_bytes()
    config = json.loads(data.decode("utf-8"))
    return config, hashlib.sha1(data).hexdigest()[:16]


def save_config(paths, config, expected_version=None):
    """原子写 config.json，上一版留在 config.json.bak-last。返回新版本号。

    expected_version 不为 None 时，文件当前版本必须和它一致（界面打开之后没人改过），
    否则抛 ConfigConflict，避免把向导或手工改的内容静默覆盖。
    """
    with file_lock(paths.config_lock):
        current = config_version(paths.config)
        if expected_version is not None and current != expected_version:
            raise ConfigConflict(current)
        if paths.config.is_file():
            shutil.copy2(paths.config, paths.config_backup)
        write_json_atomic(paths.config, config)
        return config_version(paths.config)


def update_config(paths, mutate):
    """带锁的读-改-写，给「暂停」「设为投稿样式」这种只动一两个键的操作用。返回 (新配置, 新版本)。"""
    with file_lock(paths.config_lock):
        config = read_json(paths.config, None)
        if config is None and paths.config.is_file():
            raise ValueError("config.json 不是合法的 JSON，先修好文件再操作")
        config = config or {}
        mutate(config)
        if paths.config.is_file():
            shutil.copy2(paths.config, paths.config_backup)
        write_json_atomic(paths.config, config)
        return config, config_version(paths.config)


# ---------------------------------------------------------------- 投稿模板


def render_template(template, **values):
    """只替换认识的 {title} {original_title} {url} {video_id}，别的花括号原样保留，不会因为用户写了 {} 就报错。"""
    def replace(match):
        key = match.group(1)
        return str(values[key]) if key in values and values[key] is not None else match.group(0)
    return re.sub(r"\{(\w+)\}", replace, template or "")


# ---------------------------------------------------------------- YouTube 链接

_YT_ID = r"([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])"
_YT_PATTERNS = (
    re.compile(r"^https?://(?:www\.|m\.|music\.)?youtube\.com/watch\?(?:.*&)?v=" + _YT_ID),
    re.compile(r"^https?://(?:www\.|m\.)?youtube\.com/(?:shorts|live|embed)/" + _YT_ID),
    re.compile(r"^https?://youtu\.be/" + _YT_ID),
)


def parse_youtube_url(url):
    """投稿任务只收 YouTube 单个视频链接（history 存的是 YouTube ID）。返回 (规范化链接, 视频 ID) 或 (None, None)。"""
    url = (url or "").strip()
    if url and not re.match(r"^https?://", url):
        url = "https://" + url
    for pattern in _YT_PATTERNS:
        match = pattern.match(url)
        if match:
            video_id = match.group(1)
            return f"https://www.youtube.com/watch?v={video_id}", video_id
    return None, None


# ---------------------------------------------------------------- history（只读）


def history_contains(paths, video_id):
    """history.json 是 mover 进程内存集合的落盘，Web 只读不写（写入语义见 RUNBOOK §3）。"""
    data = read_json(paths.history, [])
    return isinstance(data, list) and video_id in data


# ---------------------------------------------------------------- 投稿任务

JOB_ID_RE = re.compile(r"^pub-\d{8}-\d{6}-[0-9a-f]{6}$")
MAX_JOBS = 200
ACTIVE_STATUSES = ("queued", "running")


def new_job_id(now=None):
    now = time.time() if now is None else now
    return time.strftime("pub-%Y%m%d-%H%M%S", time.localtime(now)) + "-" + secrets.token_hex(3)


def is_job_id(value):
    return bool(JOB_ID_RE.match(value or ""))


def job_path(paths, job_id):
    if not is_job_id(job_id):
        raise ValueError(f"非法任务 id: {job_id!r}")
    return paths.jobs / f"{job_id}.json"


def job_log_path(paths, job_id):
    return job_path(paths, job_id).with_suffix(".log")


def load_job(paths, job_id):
    if not is_job_id(job_id):
        return None
    return read_json(job_path(paths, job_id), None)


def list_jobs(paths):
    """全部任务，新的在前。"""
    jobs = []
    if paths.jobs.is_dir():
        for path in paths.jobs.glob("pub-*.json"):
            job = read_json(path, None)
            if isinstance(job, dict) and is_job_id(job.get("id")):
                jobs.append(job)
    jobs.sort(key=lambda job: (job.get("created_at") or 0, job["id"]), reverse=True)
    return jobs


def queued_jobs(paths):
    """排队中的任务，按提交顺序（先提交的在前）。"""
    jobs = [job for job in list_jobs(paths) if job.get("status") == "queued"]
    jobs.reverse()
    return jobs


def active_job_for(paths, video_id):
    for job in list_jobs(paths):
        if job.get("video_id") == video_id and job.get("status") in ACTIVE_STATUSES:
            return job
    return None


def create_job(paths, url, video_id, options=None, origin="web", now=None):
    now = time.time() if now is None else now
    job = {
        "id": new_job_id(now),
        "kind": "publish",
        "status": "queued",
        "stage": "queued",
        "url": url,
        "video_id": video_id,
        "title": None,
        "options": options or {},
        "origin": origin,
        "created_at": now,
        "started_at": None,
        "finished_at": None,
        "result": None,
        "error": None,
    }
    with file_lock(paths.jobs_lock):
        write_json_atomic(job_path(paths, job["id"]), job)
    prune_jobs(paths)
    return job


def update_job(paths, job_id, **fields):
    with file_lock(paths.jobs_lock):
        job = load_job(paths, job_id)
        if job is None:
            return None
        job.update(fields)
        write_json_atomic(job_path(paths, job_id), job)
        return job


def claim_next_job(paths, worker, now=None):
    """把最早排队的任务改成 running 并返回；没有就返回 None。在锁里做，取消和认领不会撞车。"""
    with file_lock(paths.jobs_lock):
        pending = queued_jobs(paths)
        if not pending:
            return None
        job = pending[0]
        job.update(status="running", stage="download", worker=worker,
                   started_at=time.time() if now is None else now)
        write_json_atomic(job_path(paths, job["id"]), job)
        return job


def cancel_job(paths, job_id, now=None):
    """只能取消还在排队的任务；已经开始的返回 None（流水线跑到一半不好收拾）。"""
    with file_lock(paths.jobs_lock):
        job = load_job(paths, job_id)
        if job is None or job.get("status") != "queued":
            return None
        job.update(status="cancelled", stage="cancelled", finished_at=time.time() if now is None else now)
        write_json_atomic(job_path(paths, job_id), job)
        return job


def fail_interrupted_jobs(paths, message, now=None):
    """mover 启动时调用：上次退出时还在 running 的任务标成失败。

    不自动重排：中断可能发生在投稿成功之后、记账之前，重跑就是重复投稿。让人看一眼 B 站再点重试。
    """
    count = 0
    with file_lock(paths.jobs_lock):
        for job in list_jobs(paths):
            if job.get("status") == "running":
                job.update(status="failed", error=message,
                           finished_at=time.time() if now is None else now)
                write_json_atomic(job_path(paths, job["id"]), job)
                count += 1
    return count


def prune_jobs(paths, keep=MAX_JOBS):
    """只留最近 keep 个任务（含日志），排队 / 进行中的不删。"""
    with file_lock(paths.jobs_lock):
        finished = [job for job in list_jobs(paths) if job.get("status") not in ACTIVE_STATUSES]
        active = sum(1 for job in list_jobs(paths) if job.get("status") in ACTIVE_STATUSES)
        for job in finished[max(0, keep - active):]:
            for path in (job_path(paths, job["id"]), job_log_path(paths, job["id"])):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass


# ---------------------------------------------------------------- mover 状态

ONLINE_GRACE_SECONDS = 45


def write_status(paths, status):
    write_json_atomic(paths.status, status)


def read_status(paths, now=None):
    """读 mover 的状态并判断在不在线（心跳超过 ONLINE_GRACE_SECONDS 秒没更新 = 不在线）。"""
    now = time.time() if now is None else now
    status = read_json(paths.status, None)
    if not isinstance(status, dict):
        return {"online": False, "heartbeat_at": None}
    heartbeat = status.get("heartbeat_at") or 0
    status["online"] = bool(heartbeat) and now - heartbeat < ONLINE_GRACE_SECONDS
    status["heartbeat_age"] = round(now - heartbeat, 1) if heartbeat else None
    return status


def request_scan(paths):
    paths.runtime.mkdir(parents=True, exist_ok=True)
    paths.wake.write_text(str(time.time()), encoding="utf-8")


def scan_requested(paths):
    return paths.wake.exists()


def consume_scan_request(paths):
    try:
        paths.wake.unlink()
        return True
    except FileNotFoundError:
        return False


# ---------------------------------------------------------------- 最近动态

EVENTS_MAX_BYTES = 2 * 1024 * 1024


def append_event(paths, event_type, now=None, **fields):
    record = {"ts": time.time() if now is None else now, "type": event_type}
    record.update(fields)
    append_jsonl(paths.events, record)
    return record


def read_events(paths, limit=200, since=None):
    events = read_jsonl(paths.events)
    if since is not None:
        events = [e for e in events if (e.get("ts") or 0) >= since]
    events.reverse()
    return events[:limit] if limit else events


def trim_events(paths, max_bytes=EVENTS_MAX_BYTES):
    """超过 max_bytes 就只留后一半。只有 mover 写这个文件，这里不用锁。"""
    try:
        if paths.events.stat().st_size <= max_bytes:
            return
    except FileNotFoundError:
        return
    lines = paths.events.read_text(encoding="utf-8", errors="replace").splitlines()
    keep = lines[len(lines) // 2:]
    fd, tmp_path = tempfile.mkstemp(dir=str(paths.runtime), prefix=".events-", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("\n".join(keep) + "\n")
    os.replace(tmp_path, paths.events)


SKIP_REASONS = ("keyword", "exclude", "cutoff", "description_failed")


def find_skip(paths, video_id):
    """mover 最近一次因为什么跳过这个视频（skip 动态），没有记录返回 None。

    history 里既有投过稿的也有被过滤掉的，光看 history 分不出来；有 skip 记录就说明它没投过。
    """
    for event in read_events(paths, limit=None):
        if event.get("video_id") == video_id and event.get("type") in ("skip", "uploaded"):
            return event if event["type"] == "skip" else None
    return None


def summarize_events(events, since=None):
    """按类型数一数：投稿成功、失败、各类跳过。界面「最近 24 小时」和 RUNBOOK §8 的判定分布是同一回事。"""
    summary = {"uploaded": 0, "failed": 0, "matched": 0, "skipped": {reason: 0 for reason in SKIP_REASONS},
               "cycles": 0}
    for event in events:
        if since is not None and (event.get("ts") or 0) < since:
            continue
        kind = event.get("type")
        if kind == "uploaded":
            summary["uploaded"] += 1
        elif kind == "failed":
            summary["failed"] += 1
        elif kind == "match":
            summary["matched"] += 1
        elif kind == "cycle":
            summary["cycles"] += 1
        elif kind == "skip":
            reason = event.get("reason") or "keyword"
            summary["skipped"][reason] = summary["skipped"].get(reason, 0) + 1
    return summary


# ---------------------------------------------------------------- 投稿记录


def append_upload(paths, record, now=None):
    record = dict(record)
    record.setdefault("uploaded_at", time.time() if now is None else now)
    with file_lock(paths.uploads_lock):
        append_jsonl(paths.uploads, record)
    return record


def read_uploads(paths, limit=None):
    uploads = read_jsonl(paths.uploads)
    uploads.reverse()
    return uploads[:limit] if limit else uploads


def find_upload(paths, video_id):
    for record in read_uploads(paths):
        if record.get("video_id") == video_id:
            return record
    return None
