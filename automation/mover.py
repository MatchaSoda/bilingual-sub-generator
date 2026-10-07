import os
import sys
import json
import time
import subprocess
import re
import shutil
import tempfile
import fcntl
import threading
import traceback
from collections import deque
from pathlib import Path

# 项目根路径配置
BASE_DIR = Path(__file__).parent.parent.absolute()

# 和 Web 进程共用的状态文件约定（投稿队列、心跳、动态、投稿记录）；只用标准库，不牵出 config.settings
sys.path.insert(0, str(BASE_DIR / "backend"))
from utils import automation_store as store  # noqa: E402
from utils.pipeline_stages import detect_stage  # noqa: E402
CLI_PATH = BASE_DIR / "backend" / "entry_cli.py"
PYTHON_PATH = BASE_DIR / "venv" / "bin" / "python3"
YTDLP_PATH = BASE_DIR / "venv" / "bin" / "yt-dlp"
BILIUP_PATH = BASE_DIR / "venv" / "bin" / "biliup"
DOWNLOADS_DIR = BASE_DIR / "data" / "downloads"

# 运行期状态（config.json / history.json / cookies.json / 产出视频）所在目录。
# 默认就是本目录，和以前一样；Docker 部署把 AUTOMATION_STATE_DIR 指到挂载的 userdata/，
# 这样代码和用户数据分开，镜像重建不丢状态。见 docs/DOCKER.md。
STATE_DIR = Path(os.getenv("AUTOMATION_STATE_DIR") or Path(__file__).parent).absolute()
HISTORY_FILE = STATE_DIR / "history.json"
CONFIG_FILE = STATE_DIR / "config.json"
# 专门存放生成好的双语视频
OUTPUT_DIR = STATE_DIR / "data"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 哔哩哔哩登录凭据 (用户通过 biliup login 生成；biliup 默认读工作目录下的 cookies.json)
BILI_SESSION = STATE_DIR / "cookies.json"

# YouTube cookies (Netscape 格式，默认放在项目根目录) —— 用于规避 YouTube 机器人检测
YT_COOKIES = Path(os.getenv("YT_COOKIES_FILE") or (BASE_DIR / "cookies.txt"))

# 运行期标记（目前只有「起点水位」的首次启动时间）。删掉这个文件 = 重新计起点。
STATE_FILE = STATE_DIR / "state.json"

# Web 界面和 mover 共享的文件（jobs/、runtime/、uploads.jsonl），布局见 backend/utils/automation_store.py
PATHS = store.Paths(STATE_DIR)

# 所有「config.json 没写时」的缺省值都在 store.DEFAULTS，Web 界面显示的「当前生效值」按同一份算
DEFAULT_LOOKBACK_HOURS = store.DEFAULTS["backfill"]["lookback_hours"]
# 每个投稿的视频在本地留约 370 MB，一天 4–7 GB，不清理三四周就写满磁盘（docs/RUNBOOK.md §4「定期清理」）
DEFAULT_KEEP_DAYS = store.DEFAULTS["cleanup"]["keep_days"]
DEFAULT_PROCESSING = store.DEFAULTS["processing"]
DEFAULT_UPLOAD = store.DEFAULTS["upload"]

# 休眠时每隔几秒看一眼 Web 有没有提交投稿任务、有没有点「立即扫描」
WAIT_POLL_SECONDS = 3
HEARTBEAT_SECONDS = 5
LOG_MAX_BYTES = 5 * 1024 * 1024
INTERRUPTED_MESSAGE = "自动搬运服务重启，任务被中断。先到 B 站稿件管理确认没有投上去，再点重试。"
BVID_RE = re.compile(r"BV1[0-9A-Za-z]{9}")
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


class LogTee:
    """print 的输出同时写三处：原 stdout（docker logs / journalctl 照旧）、runtime/mover.log（Web 日志页）、
    当前 Web 投稿任务的日志（jobs/<id>.log）。后两处每行加时间戳；写文件出错不影响主流程。"""

    def __init__(self, stream, log_path, max_bytes=LOG_MAX_BYTES):
        self.stream = stream
        self.log_path = Path(log_path)
        self.max_bytes = max_bytes
        self.job_file = None
        self._file = None
        self._at_line_start = True
        self._lock = threading.RLock()

    def write(self, text):
        self.stream.write(text)
        with self._lock:
            stamped = self._stamp(text)
            self._write_log(stamped)
            if self.job_file is not None:
                try:
                    self.job_file.write(stamped)
                    self.job_file.flush()
                except (OSError, ValueError):
                    pass
        return len(text)

    def flush(self):
        self.stream.flush()

    def __getattr__(self, name):
        return getattr(self.stream, name)

    def _stamp(self, text):
        parts = []
        for chunk in text.splitlines(keepends=True):
            if self._at_line_start:
                parts.append(time.strftime("%m-%d %H:%M:%S "))
            parts.append(chunk)
            self._at_line_start = chunk.endswith("\n")
        return "".join(parts)

    def _write_log(self, text):
        try:
            if self._file is None:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                self._file = open(self.log_path, "a", encoding="utf-8")
            self._file.write(text)
            self._file.flush()
            if self._file.tell() > self.max_bytes:
                self._file.close()
                self._file = None
                os.replace(self.log_path, self.log_path.with_name(self.log_path.name + ".1"))
        except OSError:
            self._file = None

    def close(self):
        with self._lock:
            if self._file is not None:
                self._file.close()
                self._file = None

    def attach_job(self, job_file):
        with self._lock:
            self.job_file = job_file

    def detach_job(self):
        with self._lock:
            self.job_file = None


class StatusReporter:
    """mover 在做什么，写到 runtime/status.json 给 Web 看。后台线程每 HEARTBEAT_SECONDS 秒刷一次心跳，
    所以压制一个视频十几分钟没有输出时，Web 也知道服务还活着。"""

    def __init__(self, paths):
        self.paths = paths
        self._lock = threading.Lock()
        self.state = {
            "pid": os.getpid(),
            "started_at": time.time(),
            "phase": "starting",
            "current": None,
            "next_scan_at": None,
            "last_cycle": None,
            "paused": False,
            "interval": None,
        }

    def update(self, **fields):
        with self._lock:
            self.state.update(fields)
            self._write()

    def set_stage(self, stage):
        with self._lock:
            current = self.state.get("current")
            if not current or current.get("stage") == stage:
                return
            self.state["current"] = dict(current, stage=stage)
            self._write()

    def start(self):
        threading.Thread(target=self._heartbeat, name="status-heartbeat", daemon=True).start()

    def _heartbeat(self):
        while True:
            time.sleep(HEARTBEAT_SECONDS)
            with self._lock:
                self._write()

    def _write(self):
        self.state["heartbeat_at"] = time.time()
        try:
            store.write_status(self.paths, self.state)
        except OSError:
            pass


# 只有常驻服务（main）才有这两个；backfill.py 直接调 publish_video 时它们是 None，相关调用都是空操作
TEE = None
REPORTER = None


def report(**fields):
    if REPORTER is not None:
        REPORTER.update(**fields)


def set_stage(stage, job_id=None):
    if REPORTER is not None:
        REPORTER.set_stage(stage)
    if job_id:
        store.update_job(PATHS, job_id, stage=stage)


def record_event(event_type, **fields):
    try:
        store.append_event(PATHS, event_type, **fields)
    except OSError as e:
        print(f"⚠️ 写动态记录失败: {e}")


def strip_ansi(text):
    return ANSI_RE.sub("", text or "")


def parse_bvid(text):
    """biliup 投稿成功时会打印接口返回（里面有 bvid），取最后一个 BV 号。拿不到返回 None，不影响投稿结果。"""
    found = BVID_RE.findall(strip_ansi(text))
    return found[-1] if found else None


def tail_message(text, limit=600):
    """报错只留最后几行给界面看：biliup 的真正原因总在最后一行（RUNBOOK §5.4）。"""
    lines = [line.strip() for line in strip_ansi(text).splitlines() if line.strip()]
    message = " | ".join(lines[-4:])
    return message[-limit:]


def load_state():
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ 读取运行期标记失败，按空处理: {e}")
    return {}


def save_state(state):
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=str(STATE_FILE.parent), prefix='.state-', suffix='.tmp')
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, STATE_FILE)
    except Exception as e:
        print(f"❌ 无法保存运行期标记: {e}")


def resolve_backfill_cutoff(config, state, now=None):
    """算出「早于这个时间点的视频一律不补」的水位，返回 (cutoff 时间戳 或 None, state 是否被改动)。

    config["backfill"]["mode"]:
      "all"（缺省）        —— 旧行为：history 里没有的全补。窗口（playlist_items）开得大是为了停机
                              恢复时把漏掉的都追回来，这对持续运行的老账号是对的。
      "since_first_start"  —— 新账号 / 全新部署用：以本部署**第一次**启动的时间为起点，往前多算
                              lookback_hours 小时，更早发布的视频直接记入 history 跳过。起点写在
                              state.json 里，之后服务重启不会推后起点，所以「从第一次启动到现在」
                              之间漏掉的照样会补，只是不会把频道几年的存货一股脑搬上去。

    lookback_hours 改了会立刻按新值重算（起点不变，只是往前多算或少算），不需要重置。
    要真正重置起点：停服务，删 state.json，再启动。
    """
    backfill = config.get('backfill') or {}
    if backfill.get('mode', store.DEFAULTS['backfill']['mode']) != 'since_first_start':
        return None, False
    now = time.time() if now is None else now
    changed = False
    first_start = state.get('first_start_at')
    if not isinstance(first_start, (int, float)) or isinstance(first_start, bool):
        first_start = int(now)
        state['first_start_at'] = first_start
        changed = True
    try:
        lookback_hours = float(backfill.get('lookback_hours', DEFAULT_LOOKBACK_HOURS))
    except (TypeError, ValueError):
        lookback_hours = float(DEFAULT_LOOKBACK_HOURS)
    return first_start - lookback_hours * 3600, changed


def is_before_cutoff(entry, cutoff):
    """发布时间已知且早于水位才算「太老」；拿不到发布时间的视频放行给后面的正常过滤。"""
    ts = entry.get('timestamp')
    return cutoff is not None and ts is not None and ts < cutoff


def fmt_ts(ts):
    return time.strftime('%Y-%m-%d %H:%M', time.localtime(ts)) if ts else '?'


def resolve_keep_days(config):
    """config.json 的 cleanup.keep_days：媒体文件保留几天，缺省 7；0 或负数 = 不清理。"""
    cleanup = config.get('cleanup') or {}
    try:
        return float(cleanup.get('keep_days', DEFAULT_KEEP_DAYS))
    except (TypeError, ValueError):
        return float(DEFAULT_KEEP_DAYS)


def cleanup_old_media(keep_days, now=None, targets=None):
    """删掉超过 keep_days 天没动过的文件，返回 (删除个数, 释放字节数)。

    targets 是 [(目录, 是否保留 *_bilingual 成品), ...]。缺省两个目录：
      data/downloads —— 下载缓存和中间产物；保留 Web 界面做的成品（媒体库里显示的就是它们）
      产出目录（OUTPUT_DIR）—— 搬运的成品，已经投到 B 站，到期一起删
    只看目录下一层的普通文件，不递归、不碰子目录。

    「没动过」取 mtime 和 ctime 里较新的那个：yt-dlp 抽音频时把 .wav 的 mtime 设成源视频的 mtime，
    重跑时 .wav 是新写的、mtime 却还是旧的；只看 mtime 可能把正在处理的文件当成旧文件删掉。
    """
    if keep_days <= 0:
        return 0, 0
    now = time.time() if now is None else now
    cutoff = now - keep_days * 86400
    if targets is None:
        targets = [(DOWNLOADS_DIR, True), (OUTPUT_DIR, False)]
    removed, freed = 0, 0
    for directory, keep_outputs in targets:
        if not directory.is_dir():
            continue
        for path in directory.iterdir():
            try:
                if path.is_symlink() or not path.is_file():
                    continue
                if keep_outputs and path.stem.endswith('_bilingual'):
                    continue
                st = path.stat()
                if max(st.st_mtime, st.st_ctime) >= cutoff:
                    continue
                path.unlink()
                removed += 1
                freed += st.st_size
            except OSError as e:
                print(f"⚠️ 清理 {path.name} 失败: {e}")
    return removed, freed


def parse_flat_playlist_line(line):
    """解析 get_video_list 的 --print 行：id|timestamp|url|title。

    title 放最后，因为它可能自带 '|'；timestamp 缺失时 yt-dlp 打印 NA。
    """
    parts = line.split('|', 3)
    if len(parts) < 4:
        return None
    vid, ts, url, title = (p.strip() for p in parts)
    try:
        timestamp = int(float(ts))
    except (TypeError, ValueError):
        timestamp = None
    return {'id': vid, 'timestamp': timestamp, 'url': url, 'title': title}

def make_cookies_copy():
    """复制 master cookies 到临时文件返回路径。

    yt-dlp 每次运行会把 Set-Cookie 响应写回 cookies 文件；YouTube 在风控时返回的是匿名
    Set-Cookie，会把 master 文件里的认证 token 一点点冲掉。我们让 yt-dlp 只污染临时副本，
    master 永远是用户最近从浏览器导出的那一份。
    """
    # 空文件视为没有 cookie：占位文件是向导 / 启动脚本 touch 出来的，喂给 yt-dlp 会报格式错误
    if not YT_COOKIES.is_file() or YT_COOKIES.stat().st_size == 0:
        return None
    fd, tmp_path = tempfile.mkstemp(prefix="yt-cookies-", suffix=".txt")
    os.close(fd)
    shutil.copyfile(YT_COOKIES, tmp_path)
    return tmp_path

def load_history():
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                print(f"📖 已加载历史记录: {len(data)} 条")
                return set(data)
        except Exception as e:
            print(f"⚠️ 加载历史记录失败: {e}")
            return set()
    return set()

def save_history(processed_ids):
    """并发安全地写 history.json。

    常驻服务和外部脚本（backfill.py）可能同时写这个文件，直接覆盖会丢条目。
    这里用文件锁串行化写入，并在锁内先把磁盘上已有条目并进来（避免覆盖对方新增的），
    最后原子替换落盘。processed_ids 会被就地更新为并集，保持内存与磁盘一致。

    注意这个并集语义的副作用：手工从磁盘删掉的 id 会被运行中的进程写回来。
    要删 history 必须先停服务，见 docs/RUNBOOK.md §3 和 scripts/prune_history.py。
    """
    try:
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        lock_path = HISTORY_FILE.with_suffix('.lock')
        with open(lock_path, 'w') as lock_f:
            fcntl.flock(lock_f, fcntl.LOCK_EX)
            # 锁内重新读盘并合并，吸收外部（如 backfill.py）追加的条目
            if HISTORY_FILE.exists():
                try:
                    with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                        processed_ids |= set(json.load(f))
                except Exception:
                    pass
            fd, tmp_path = tempfile.mkstemp(dir=str(HISTORY_FILE.parent),
                                            prefix='.history-', suffix='.tmp')
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(list(processed_ids), f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, HISTORY_FILE)
        print(f"💾 历史记录已更新: {HISTORY_FILE}")
    except Exception as e:
        print(f"❌ 无法保存历史记录: {e}")

def load_config():
    if not CONFIG_FILE.exists():
        print(f"❌ 找不到配置文件: {CONFIG_FILE}")
        print(f"💡 请参考 'config.json.example' 创建配置文件后再运行。")
        exit(1)

    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"❌ 加载配置文件失败: {e}")
        exit(1)

def get_video_list(channel_url, playlist_items=10):
    """通过 yt-dlp --flat-playlist 快速获取频道最近 playlist_items 个视频的 id/title/url。

    描述字段在频道页拿不到，按需通过 fetch_video_description 单独获取，
    这样可以避开 YouTube 的 PO token / JS challenge 慢路径。

    flat-playlist 只解析频道列表页（网页 + InnerTube API 分页，每页约 30 条），
    不触碰 player API / PO token，所以窗口开大只是多翻几页元数据，成本很低。

    youtubetab:approximate_date 让 yt-dlp 把列表页上的「3 時間前」这类相对时间换算成
    timestamp（精度到小时 / 天），不多打任何请求；起点水位（resolve_backfill_cutoff）靠它判断。
    """
    cookies_tmp = make_cookies_copy()
    try:
        cmd = [
            str(YTDLP_PATH), "--ignore-errors", "--flat-playlist",
            "--playlist-items", f"1-{playlist_items}",
            "--extractor-args", "youtubetab:approximate_date",
            "--print", "%(id)s|%(timestamp)s|%(webpage_url)s|%(title)s",
        ]
        if cookies_tmp:
            cmd[1:1] = ["--cookies", cookies_tmp]
            print(f"🍪 使用 cookies (临时副本): {cookies_tmp}")
        cmd.append(channel_url)
        env = os.environ.copy()
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, env=env)

        if result.returncode != 0:
            print(f"❌ yt-dlp 获取失败: {result.stderr[:200]}")
            return []

        videos = []
        for line in result.stdout.splitlines():
            if not line.strip(): continue
            entry = parse_flat_playlist_line(line)
            if entry:
                videos.append(entry)

        if videos:
            print(f"📥 成功获取视频列表:")
            for v in videos:
                print(f"  - [{v['id']}] {fmt_ts(v['timestamp'])} {v['title']}")
        else:
            print(f"⚠️ 未发现符合条件的视频内容")

        return videos
    except Exception as e:
        print(f"❌ 列表异常: {e}")
        return []
    finally:
        if cookies_tmp:
            try: os.unlink(cookies_tmp)
            except OSError: pass

def fetch_video_description(video_url, throttle_seconds=0):
    """单独获取一个视频的描述（仅在 title 不匹配时调用）。拉取失败返回 None，没有描述返回 ""。

    用 --ignore-no-formats-error：YouTube 频道视频的 player API 在无头环境下常常返回
    LOGIN_REQUIRED 而拿不到 formats，但 description 是从 webpage HTML 解析的，加这个
    flag 让 yt-dlp 不要因为 formats 缺失就抛错，从而能落到 webpage fallback 拿到描述。

    这是整条流程里最容易触发 YouTube 风控的重请求（每个视频单独打一次）。
    throttle_seconds > 0 时，每次抓取后强制休眠，把连续描述请求拉开间隔，避免突发。
    """
    cookies_tmp = make_cookies_copy()
    try:
        cmd = [
            str(YTDLP_PATH), "--skip-download", "--ignore-no-formats-error",
            "--print", "%(description)j",
        ]
        if cookies_tmp:
            cmd[1:1] = ["--cookies", cookies_tmp]
        cmd.append(video_url)
        env = os.environ.copy()
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, env=env)
        if result.returncode != 0:
            print(f"⚠️ 拉取描述失败: {result.stderr[:200]}")
            return None
        desc_str = result.stdout.strip()
        if not desc_str or desc_str == "NA":
            return ""
        try:
            return json.loads(desc_str)
        except Exception:
            return desc_str
    except Exception as e:
        print(f"⚠️ 描述异常: {e}")
        return None
    finally:
        if cookies_tmp:
            try: os.unlink(cookies_tmp)
            except OSError: pass
        # 无论成功失败都休眠，保证两次描述请求之间至少间隔 throttle_seconds
        if throttle_seconds:
            time.sleep(throttle_seconds)

def upload_to_bilibili(video_path, cover_path, title, tid, description, tags,
                       line=None, retries=3, retry_delay=60):
    """使用 biliup 投稿到 B 站，失败自动重试。返回 {"ok", "bvid", "error"}。

    重试是必要的：B 站上传 CDN 的连通性时好时坏，而 biliup 每次启动都会重新探测线路，
    所以「换个进程再试一次」经常就能成功。biliup 自身的 reqwest 重试只在同一条线路上
    退避，选错线的话重试多少次都是白搭。详见 docs/RUNBOOK.md §5.4。

    line: 指定上传线路（config.json 的 upload_line），None 表示交给 biliup 自动选。
    """
    if not BILI_SESSION.exists():
        print(f"⚠️ 找不到 B 站登录凭据 {BILI_SESSION}, 跳过投稿")
        print(f"💡 在 Web「自动搬运」页扫码登录，或在 {STATE_DIR} 目录下执行: biliup login（Docker 部署运行 ./docker-start.sh setup）")
        return {"ok": False, "bvid": None, "error": "没有 B 站登录信息（cookies.json），先在「自动搬运」页扫码登录"}

    print(f"🚀 开始投稿 B 站: {title} (分区: {tid})")

    cmd = [
        str(BILIUP_PATH), "upload",
        str(video_path),
        "--submit", "web",
        "--tid", str(tid),
        "--title", title[:80],
        "--desc", description[:250],
        "--cover", str(cover_path) if cover_path and cover_path.exists() else "",
        "--tag", tags,
    ]
    if line:
        cmd += ["--line", str(line)]

    # 清除空参数 (例如没有封面时)
    cmd = [c for c in cmd if c]

    total_attempts = max(1, retries)
    error_msg = ""
    for attempt in range(1, total_attempts + 1):
        try:
            completed = subprocess.run(
                cmd,
                cwd=str(STATE_DIR),  # biliup 从工作目录读 cookies.json
                check=True,
                capture_output=True,
                text=True
            )
            bvid = parse_bvid(f"{completed.stdout}\n{completed.stderr}")
            suffix = f" {bvid}" if bvid else ""
            if attempt > 1:
                print(f"✅ B 站投稿成功!{suffix} (第 {attempt}/{total_attempts} 次尝试)")
            else:
                print(f"✅ B 站投稿成功!{suffix}")
            return {"ok": True, "bvid": bvid, "error": None}
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr or e.stdout or str(e)
            if attempt < total_attempts:
                print(f"⚠️ B 站投稿失败 (第 {attempt}/{total_attempts} 次)，{retry_delay}s 后重试")
                print(f"  错误详情: {error_msg[-1500:]}")
                time.sleep(retry_delay)
            else:
                print(f"❌ B 站投稿失败! (已重试 {total_attempts} 次)")
                print(f"  错误详情: {error_msg}")
    return {"ok": False, "bvid": None, "error": f"B 站投稿失败（重试 {total_attempts} 次）: {tail_message(error_msg)}"}

def safe_filename_title(title):
    """替换非法字符并按字节截断。和 backend/utils/filenames.py 同一个 200 字节预算：
    文件名上限是 255 字节不是字符，长日文标题拼上 _bilingual.mp4 会 Errno 36。
    见 docs/RUNBOOK.md §5.7。"""
    cleaned = re.sub(r'[\\/*?:"<>|]', "_", title).strip()
    return cleaned.encode("utf-8")[:200].decode("utf-8", "ignore").rstrip()


def fetch_id_and_title(video_url):
    """拿单个视频的 id 和标题（输出文件名、日志、投稿记录用）。Web 投稿任务和 backfill.py 共用。"""
    cookies_tmp = make_cookies_copy()
    try:
        cmd = [
            str(YTDLP_PATH), "--skip-download", "--ignore-no-formats-error",
            "--print", "%(id)s|%(title)s",
        ]
        if cookies_tmp:
            cmd[1:1] = ["--cookies", cookies_tmp]
        cmd.append(video_url)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        line = ""
        for candidate in reversed(result.stdout.splitlines()):
            if "|" in candidate:
                line = candidate.strip()
                break
        if not line:
            print(f"❌ 无法获取视频信息: {result.stderr[:300]}")
            return None, None
        vid, _, title = line.partition("|")
        return vid.strip(), title.strip()
    except Exception as e:
        print(f"❌ 获取视频信息异常: {e}")
        return None, None
    finally:
        if cookies_tmp:
            try:
                os.unlink(cookies_tmp)
            except OSError:
                pass


def build_cli_command(video_url, target_video_path, processing=None):
    """config.json 的 processing 段 → entry_cli.py 的命令行。缺省值等同旧行为。"""
    proc = processing or {}
    cli_cmd = [
        str(PYTHON_PATH), str(CLI_PATH), video_url,
        "--segment-mode", proc.get("segment_mode", DEFAULT_PROCESSING["segment_mode"]),
        "--whisper-model", proc.get("whisper_model", DEFAULT_PROCESSING["whisper_model"]),
        "--gemini-model", proc.get("gemini_model", DEFAULT_PROCESSING["gemini_model"]),
        "--translation-batch-size", str(proc.get("translation_batch_size", DEFAULT_PROCESSING["translation_batch_size"])),
        "--output", str(target_video_path),
    ]
    if proc.get("enable_furigana", DEFAULT_PROCESSING["enable_furigana"]):
        cli_cmd.append("--enable-furigana")
    if proc.get("translate_title", DEFAULT_PROCESSING["translate_title"]):
        cli_cmd.append("--translate-title")
    if proc.get("fix_source_text", DEFAULT_PROCESSING["fix_source_text"]):
        cli_cmd.append("--fix-source-text")
    # 字幕样式（视觉实验室「设为投稿样式」写进来的）。没有就用 entry_cli 的缺省样式，和以前一样。
    style_errors = []
    style = store.normalize_style(proc.get("style"), style_errors)
    if style_errors:
        print(f"⚠️ processing.style 里有不合法的值，已忽略: {style_errors}")
    for key, value in style.items():
        cli_cmd += [f"--{key.replace('_', '-')}", str(value)]
    return cli_cmd


def publish_video(video_id, video_url, video_title, config, processing=None, full_config=None,
                  origin="auto", title_override=None, job_id=None):
    """生成双语视频并投稿 B 站。自动搬运、Web 投稿任务、backfill.py 都走这里。

    config 是频道配置（分区 / 标签）。返回 {"ok", "stage", "output", "title", "bili_title", "bvid", "error"}，
    stage 是失败发生在哪一步（cli / output / upload），成功时是 done。投稿成功会写一条投稿记录。
    """
    print(f"\n🚀 开始处理: {video_title} ({video_id})")
    result = {"ok": False, "stage": "cli", "output": None, "title": video_title,
              "bili_title": None, "bvid": None, "error": None}

    def fail(stage, error):
        result.update(stage=stage, error=error)
        record_event("failed", origin=origin, video_id=video_id, title=video_title, stage=stage,
                     error=error, job_id=job_id)
        return result

    safe_title = safe_filename_title(video_title)
    target_video_path = OUTPUT_DIR / f"{safe_title}_bilingual.mp4"

    # 处理参数来自 config.json 的 "processing" 段（缺省时沿用默认值，等同旧行为）。
    cli_cmd = build_cli_command(video_url, target_video_path, processing)

    print(f"执行命令: {' '.join(cli_cmd)}")
    set_stage("download", job_id)

    # 使用 Popen 来实时获取输出
    env = os.environ.copy()
    process = subprocess.Popen(
        cli_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
        bufsize=1,
        universal_newlines=True
    )

    translated_title = None
    recent_lines = deque(maxlen=20)
    current_stage = "download"
    for line in process.stdout:
        stripped_line = line.strip()
        # 实时打印子进程输出
        print(f"  [CLI] {stripped_line}", flush=True)
        if stripped_line:
            recent_lines.append(stripped_line)
        if "Translated title:" in stripped_line:
            translated_title = stripped_line.split("Translated title:", 1)[1].strip()
        stage = detect_stage(stripped_line)
        if stage and stage != current_stage:
            current_stage = stage
            set_stage(stage, job_id)

    process.stdout.close()
    process.wait()

    if process.returncode != 0:
        print(f"❌ CLI 失败 (Code {process.returncode})", flush=True)
        clues = [l for l in recent_lines if any(k in l for k in ("Error", "error", "❌", "Exception"))]
        detail = (clues or list(recent_lines) or [""])[-1]
        return fail("cli", f"CLI 失败 (Code {process.returncode}): {detail[-400:]}")

    if not target_video_path.exists():
        print(f"❌ 找不到生成的文件: {target_video_path}", flush=True)
        return fail("output", f"找不到生成的文件: {target_video_path.name}")

    # 用中文译名重命名输出文件与封面，使本地文件名和 B 站投稿名都为中文
    display_title = video_title
    if translated_title:
        display_title = translated_title
        safe_zh_title = safe_filename_title(translated_title)
        if safe_zh_title and safe_zh_title != safe_title:
            renamed_video_path = OUTPUT_DIR / f"{safe_zh_title}_bilingual.mp4"
            try:
                original_cover = target_video_path.with_suffix(".jpg")
                target_video_path.rename(renamed_video_path)
                if original_cover.exists():
                    original_cover.rename(renamed_video_path.with_suffix(".jpg"))
                target_video_path = renamed_video_path
                print(f"✅ 已重命名为中文标题: {target_video_path.name}", flush=True)
            except OSError as rename_error:
                print(f"⚠️ 重命名失败，沿用原文件名: {rename_error}", flush=True)

    print(f"✅ 处理完成: {target_video_path}", flush=True)
    result.update(output=target_video_path, title=display_title)

    # 检查封面图是否已同步 (entry_cli.py 逻辑会将其放在视频同目录)
    target_cover_path = target_video_path.with_suffix(".jpg")
    if target_cover_path.exists():
        print(f"✅ 封面图已同步至: {target_cover_path}", flush=True)

    # B 站投稿逻辑
    bili_tid = config.get('bili_tid', store.CHANNEL_DEFAULTS['bili_tid'])  # 171 是 biliup 的默认分区
    bili_tags = config.get('tags', store.CHANNEL_DEFAULTS['tags'])

    # 投稿参数在投稿这一刻重新读盘，而不是沿用循环开头那份。B 站会让某条上传线路的
    # 证书过期（见 docs/RUNBOOK.md §5.4），救火时改 upload.line 要立刻管用，不能等上
    # 一整轮——一轮最长 30 分钟，够失败好几个视频了。读盘失败就退回本轮的配置。
    try:
        upload_settings = (load_config() or {}).get('upload', {})
    except SystemExit:
        upload_settings = (full_config or {}).get('upload', {})
    except Exception:
        upload_settings = (full_config or {}).get('upload', {})

    # B 站标题和简介按模板生成（缺省「【双语字幕】+ 中文标题」、简介带原视频链接）；Web 投稿可以整个指定标题
    template_values = dict(title=display_title, original_title=video_title, url=video_url, video_id=video_id)
    bili_title = (title_override or "").strip() or store.render_template(
        upload_settings.get('title_template') or DEFAULT_UPLOAD['title_template'], **template_values)
    bili_desc = store.render_template(
        upload_settings.get('description_template') or DEFAULT_UPLOAD['description_template'], **template_values)
    result["bili_title"] = bili_title[:80]

    set_stage("upload", job_id)
    upload = upload_to_bilibili(
        target_video_path, target_cover_path, bili_title, bili_tid, bili_desc, bili_tags,
        line=upload_settings.get('line'),
        retries=upload_settings.get('retries', DEFAULT_UPLOAD['retries']),
        retry_delay=upload_settings.get('retry_delay_seconds', DEFAULT_UPLOAD['retry_delay_seconds']),
    )
    if not upload["ok"]:
        return fail("upload", upload["error"])

    result.update(ok=True, stage="done", bvid=upload["bvid"])
    try:
        # 媒体库靠「来源 + 成品文件名」认出哪个成品投过稿、BV 号是多少
        store.append_upload(PATHS, {
            "video_id": video_id, "url": video_url, "title": display_title,
            "original_title": video_title, "bili_title": result["bili_title"], "bvid": upload["bvid"],
            "tid": bili_tid, "output": target_video_path.name, "source": "auto",
            "origin": origin, "channel": config.get("name"), "job_id": job_id,
        })
    except OSError as e:
        print(f"⚠️ 写投稿记录失败（不影响投稿结果）: {e}")
    record_event("uploaded", origin=origin, video_id=video_id, title=display_title,
                 bvid=upload["bvid"], job_id=job_id)
    return result


def process_and_upload(video_id, video_url, video_title, config, processing=None, full_config=None):
    """旧接口：只关心成没成功。"""
    return publish_video(video_id, video_url, video_title, config, processing, full_config)["ok"]


def merge_disk_history(history):
    """把磁盘上 history.json 的 id 并进内存集合（Web 投稿、backfill.py 在别的进程里写进去的）。
    只增不减，和 save_history 的并集语义一致（RUNBOOK §3）。"""
    try:
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            history |= set(json.load(f))
    except (OSError, ValueError, TypeError):
        pass


def resolve_channel_profile(config, options):
    """Web 投稿任务用哪个频道的分区 / 标签：指定了第几个频道就用它，否则第一个；再用任务里填的覆盖。"""
    channels = config.get('channels') or []
    index = options.get('channel')
    if isinstance(index, int) and not isinstance(index, bool) and 0 <= index < len(channels):
        profile = dict(channels[index])
    elif channels:
        profile = dict(channels[0])
    else:
        profile = {}
    if options.get('tid'):
        profile['bili_tid'] = int(options['tid'])
    if options.get('tags'):
        profile['tags'] = options['tags']
    profile.setdefault('name', 'Web 投稿')
    return profile


def run_job(job, history):
    """执行一个 Web 提交的投稿任务：拿标题 → publish_video → 写 history。输出同时进 jobs/<id>.log。"""
    job_id = job['id']
    log_file = None
    try:
        log_file = open(store.job_log_path(PATHS, job_id), 'a', encoding='utf-8')
        if TEE is not None:
            TEE.attach_job(log_file)
    except OSError as e:
        print(f"⚠️ 打不开任务日志: {e}")
    started_at = time.time()
    try:
        print(f"\n📮 开始 Web 投稿任务 {job_id}: {job['url']}", flush=True)
        try:
            config = load_config()  # 每个任务用最新的处理参数和投稿设置
        except SystemExit:
            raise RuntimeError("config.json 读取失败，看 mover 日志")
        options = job.get('options') or {}
        profile = resolve_channel_profile(config, options)
        current = {"kind": "manual", "job_id": job_id, "video_id": job['video_id'], "title": None,
                   "channel": profile.get('name'), "stage": "download", "started_at": started_at}
        report(phase="processing", current=current)

        video_id, title = fetch_id_and_title(job['url'])
        if not title:
            raise RuntimeError("拿不到视频标题：视频不存在 / 不公开，或者被 YouTube 风控（看任务日志）")
        video_id = video_id or job['video_id']
        store.update_job(PATHS, job_id, title=title)
        report(current=dict(current, title=title))

        result = publish_video(video_id, job['url'], title, profile, config.get('processing', {}),
                               full_config=config, origin="manual",
                               title_override=options.get('title') or None, job_id=job_id)
        if result["ok"]:
            history.add(job['video_id'])
            save_history(history)
            store.update_job(PATHS, job_id, status="done", stage="done", finished_at=time.time(), result={
                "bvid": result["bvid"], "title": result["title"], "bili_title": result["bili_title"],
                "output": result["output"].name if result["output"] else None,
            })
            print(f"✅ Web 投稿任务完成: {result['bili_title']} {result['bvid'] or ''}", flush=True)
        else:
            store.update_job(PATHS, job_id, status="failed", failed_stage=result["stage"],
                             finished_at=time.time(), error=result["error"])
            print(f"❌ Web 投稿任务失败: {result['error']}", flush=True)
    except Exception as e:
        print(f"❌ Web 投稿任务出错: {e}", flush=True)
        traceback.print_exc(file=sys.stdout)
        store.update_job(PATHS, job_id, status="failed", finished_at=time.time(), error=str(e))
        record_event("failed", origin="manual", video_id=job.get('video_id'), title=job.get('title'),
                     stage="prepare", error=str(e), job_id=job_id)
    finally:
        if TEE is not None:
            TEE.detach_job()
        if log_file is not None:
            log_file.close()


def run_pending_jobs(history):
    """把排队的 Web 投稿任务按提交顺序跑完。在每轮开头、两个视频之间、休眠期间调用，所以最多等一个视频。"""
    while True:
        job = store.claim_next_job(PATHS, worker=f"mover:{os.getpid()}")
        if job is None:
            return
        run_job(job, history)
        report(phase="idle", current=None)


def scan_channels(config, history, cutoff):
    """扫一轮所有频道，命中的生成 + 投稿。返回本轮统计（Web 的「上一轮」）。"""
    stats = {"channels": 0, "found": 0, "new": 0, "matched": 0, "uploaded": 0, "failed": 0,
             "skipped": {reason: 0 for reason in store.SKIP_REASONS}}

    def skip(entry, reason, message, **extra):
        print(message)
        stats["skipped"][reason] = stats["skipped"].get(reason, 0) + 1
        record_event("skip", reason=reason, video_id=entry['id'], title=entry.get('title'),
                     channel=channel.get('name'), **extra)
        history.add(entry['id'])
        save_history(history)

    # 三个反爬 / 限流开关，均可在 config.json 里调整（缺省沿用保守默认值）：
    #   playlist_items                   —— 每轮扫描频道最近多少个视频（窗口越大越能扛停机）
    #   description_fetch_interval_seconds —— 相邻两次“拉描述”重请求之间的最小间隔（秒）
    #   max_uploads_per_cycle            —— 每轮最多处理/投稿多少个视频（0 表示不限），
    #                                        用于抑制停机恢复 / 首轮时的上传突发
    playlist_items = config.get('playlist_items', store.DEFAULTS['playlist_items'])
    desc_interval = config.get('description_fetch_interval_seconds', store.DEFAULTS['description_fetch_interval_seconds'])
    max_uploads = config.get('max_uploads_per_cycle', store.DEFAULTS['max_uploads_per_cycle'])
    uploads_this_cycle = 0

    for channel in config.get('channels') or []:
        # 本轮已达上限：后续频道一律不再扫描，避免无谓的列表 / 描述请求。
        if max_uploads and uploads_this_cycle >= max_uploads:
            print(f"⏸️ 本轮处理已达上限 ({max_uploads})，跳过剩余频道，等待下一轮")
            break
        fetch_url = channel['url']
        print(f"\n🔍 扫描频道: {channel['name']} ({fetch_url})")
        report(phase="scanning", current={"kind": "scan", "channel": channel.get('name'), "started_at": time.time()})
        videos = get_video_list(fetch_url, playlist_items)
        print(f"📊 发现 {len(videos)} 个视频")
        stats["channels"] += 1
        stats["found"] += len(videos)

        for entry in videos:
            # 本轮已达上限：立刻停止遍历，剩余视频（含还没拉描述的）留到下一轮。
            # 关键：把上限检查提到“拉描述”之前，避免已经不处理了还去打 YouTube 描述
            # 接口——那是整条流程里最容易触发风控、且每个都要十几秒的重请求。
            if max_uploads and uploads_this_cycle >= max_uploads:
                print(f"⏸️ 本轮处理已达上限 ({max_uploads})，停止扫描剩余视频，留到下一轮")
                break
            if entry['id'] in history:
                continue
            stats["new"] += 1
            # Web 投稿队列里已经有这个视频：交给那个任务，这里既不处理也不写 history，免得投两次
            active = store.active_job_for(PATHS, entry['id'])
            if active:
                print(f"⏭️ 跳过 (Web 投稿任务 {active['id']} 正在处理这个视频): {entry['title']}")
                continue
            if is_before_cutoff(entry, cutoff):
                skip(entry, "cutoff", f"⏭️ 跳过 (发布于 {fmt_ts(entry['timestamp'])}，早于起点 {fmt_ts(cutoff)}): {entry['title']}")
                continue
            keyword = channel.get('keyword', '').lower()
            excludes = [e.lower() for e in channel.get('exclude', []) if e]
            title = entry.get('title') or ""
            title_lower = title.lower()

            # exclude 只对标题生效；keyword 则标题 + 描述都查。
            # 不要把 exclude 也用到描述上——会和 keyword 形成子串死锁，
            # 匹配率静默变成 0。原委见 docs/RUNBOOK.md §4。
            hit_exclude = next((ex for ex in excludes if ex in title_lower), None)
            if hit_exclude:
                skip(entry, "exclude", f"⏭️ 跳过 (标题命中排除词 '{hit_exclude}'): {title}", word=hit_exclude)
                continue

            description_failed = False
            if not keyword or keyword in title_lower:
                is_match = True
            else:
                # title 没命中再去拿描述（每个 ~10s，所以放后面）
                print(f"🔎 标题未命中，拉取描述: {title}")
                report(current={"kind": "scan", "channel": channel.get('name'), "video_id": entry['id'],
                                "title": title, "stage": "description", "started_at": time.time()})
                description = fetch_video_description(entry['url'], desc_interval)
                # 拉描述失败照旧当成不匹配写进 history（RUNBOOK §8「静默陷阱」），只是动态里单独标出来
                description_failed = description is None
                is_match = keyword in (description or "").lower()

            if is_match:
                print(f"should process: {entry['title']}")
                # 计入本轮配额（无论成功失败，重下载/上传都已发生）
                uploads_this_cycle += 1
                stats["matched"] += 1
                record_event("match", video_id=entry['id'], title=entry['title'], channel=channel.get('name'))
                report(phase="processing", current={"kind": "auto", "video_id": entry['id'], "title": entry['title'],
                                                    "channel": channel.get('name'), "stage": "download",
                                                    "started_at": time.time()})
                result = publish_video(entry['id'], entry['url'], entry['title'], channel,
                                       config.get('processing', {}), full_config=config)
                if result["ok"]:
                    stats["uploaded"] += 1
                    history.add(entry['id'])
                    save_history(history)
                else:
                    stats["failed"] += 1
                # 两个视频之间插空处理 Web 提交的投稿，用户最多等一个视频
                run_pending_jobs(history)
                report(phase="scanning", current={"kind": "scan", "channel": channel.get('name'),
                                                  "started_at": time.time()})
            elif description_failed:
                skip(entry, "description_failed", f"⏭️ 跳过 (拉取描述失败，按不匹配处理): {entry['title']}")
            else:
                skip(entry, "keyword", f"⏭️ 跳过 (关键字不匹配): {entry['title']}")
    return stats


def wait_until(deadline, history):
    """休眠到下一轮；期间每 WAIT_POLL_SECONDS 秒看一眼投稿队列和「立即扫描」。"""
    last_seen = None
    last_full_check = 0.0
    while True:
        now = time.time()
        if now >= deadline:
            return
        if store.scan_requested(PATHS):
            print("⚡ 收到「立即扫描」请求，提前开始下一轮", flush=True)
            return
        try:
            jobs_mtime = PATHS.jobs.stat().st_mtime_ns
        except FileNotFoundError:
            jobs_mtime = None
        # 队列目录有变化（新任务、取消）才去读任务文件；另外每分钟兜底读一次
        if jobs_mtime != last_seen or now - last_full_check > 60:
            last_seen, last_full_check = jobs_mtime, now
            if store.queued_jobs(PATHS):
                run_pending_jobs(history)
                report(phase="idle", current=None, next_scan_at=deadline)
                if time.time() < deadline:
                    print(f"😴 投稿任务处理完，继续等待到 {fmt_ts(deadline)}", flush=True)
                continue
        time.sleep(max(0.0, min(WAIT_POLL_SECONDS, deadline - time.time())))


def main():
    global TEE, REPORTER
    TEE = LogTee(sys.stdout, PATHS.log)
    sys.stdout = TEE
    sys.stderr = TEE
    REPORTER = StatusReporter(PATHS)
    REPORTER.start()

    print(f"🏁 自动化搬运程序启动 (BASE_DIR: {BASE_DIR})")
    print(f"📂 视频输出目录: {OUTPUT_DIR}")
    interrupted = store.fail_interrupted_jobs(PATHS, INTERRUPTED_MESSAGE)
    if interrupted:
        print(f"⚠️ 上次退出时有 {interrupted} 个 Web 投稿任务没跑完，已标成失败（不自动重跑，避免重复投稿）")
    store.prune_jobs(PATHS)
    history = load_history()
    state = load_state()
    config = None

    while True:
        cycle_started = time.time()
        try:
            config = load_config()
        except SystemExit:
            if config is None:
                raise
            print("⚠️ config.json 读取失败，本轮沿用上一次读到的配置")

        # Web 投稿 / backfill.py 在别的进程里写进 history 的 id，先并进来，免得本轮再投一次
        merge_disk_history(history)
        forced = store.consume_scan_request(PATHS)
        paused = bool(config.get('paused', store.DEFAULTS['paused']))
        interval = config.get('check_interval_seconds', store.DEFAULTS['check_interval_seconds'])
        report(phase="cycle", current=None, paused=paused, interval=interval, next_scan_at=None)

        # Web 提交的投稿任务优先：用户在等着看结果
        run_pending_jobs(history)

        # 起点水位：config 每轮重读，所以 mode / lookback_hours 改了下一轮就生效；起点本身只在
        # 第一次算出来时落盘一次。语义见 resolve_backfill_cutoff 和 docs/RUNBOOK.md §4。
        cutoff, state_changed = resolve_backfill_cutoff(config, state)
        if state_changed:
            save_state(state)
            print(f"🧭 首次启动，起点已记录: {fmt_ts(state['first_start_at'])} → {STATE_FILE}")
        if cutoff is not None:
            print(f"🧭 起点水位: 只处理 {fmt_ts(cutoff)} 之后发布的视频（mode=since_first_start，"
                  f"起点 {fmt_ts(state.get('first_start_at'))} 往前 {config.get('backfill', {}).get('lookback_hours', DEFAULT_LOOKBACK_HOURS)}h）")

        # 定期清理：每轮开头删一次过期的下载缓存和成品，keep_days 改了下一轮生效（docs/RUNBOOK.md §4）
        keep_days = resolve_keep_days(config)
        removed, freed = cleanup_old_media(keep_days)
        if removed:
            print(f"🧹 已清理 {removed} 个超过 {keep_days:g} 天的文件，释放 {freed / 1e9:.2f} GB")
            record_event("cleanup", removed=removed, freed=freed, keep_days=keep_days)
        store.trim_events(PATHS)

        if paused and not forced:
            print("⏸️ 自动扫描已暂停（在 Web「自动搬运」页恢复），本轮只处理 Web 投稿任务")
            last_cycle = None
        else:
            if forced:
                print("⚡ 按「立即扫描」请求开始本轮扫描")
            stats = scan_channels(config, history, cutoff)
            last_cycle = dict(stats, started_at=cycle_started, finished_at=time.time(), forced=forced)
            record_event("cycle", **{k: v for k, v in last_cycle.items() if k not in ("started_at",)})

        next_scan_at = time.time() + interval
        fields = dict(phase="idle", current=None, next_scan_at=next_scan_at)
        if last_cycle is not None:
            fields["last_cycle"] = last_cycle
        report(**fields)
        print(f"\n😴 等待 {interval}s 后重试...")
        wait_until(next_scan_at, history)

if __name__ == "__main__":
    main()
