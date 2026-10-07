"""B 站账号：看 cookies.json 里的登录状态，以及在 Web 上扫码登录（以前只能在终端里跑 biliup login）。

扫码用的是 biliup 自带的 stream_gears，和 `biliup login` 选「扫码登录」是同一套 TV 端接口：
get_qrcode 拿二维码链接，login_by_qrcode 一直轮询到手机上确认（或二维码过期），返回的 JSON
就是 biliup 投稿要读的 cookies.json，原样落盘。旧文件先备份成 cookies.json.bak-<时间>。
这两个调用放在独立进程里跑（services/bilibili_qr_login.py），原因见那个文件的说明。
"""
import json
import os
import queue
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from collections import deque
from pathlib import Path

QR_HELPER = Path(__file__).resolve().parent / "bilibili_qr_login.py"
# 拿二维码最多等这么久（helper 进程启动 + 一次 B 站请求，正常 1 秒内）
QR_START_TIMEOUT = 20

NAV_API = "https://api.bilibili.com/x/web-interface/nav"
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
# 二维码大约 3 分钟过期（login_by_qrcode 自己会在过期时报错退出）
QR_LIFETIME_SECONDS = 180
NAV_CACHE_SECONDS = 600


def parse_login_info(text):
    """校验 biliup 格式的登录信息，返回 (dict, 错误)。必须有 SESSDATA，否则投稿必失败。"""
    try:
        info = json.loads(text)
    except ValueError:
        return None, "不是合法的 JSON"
    if not isinstance(info, dict):
        return None, "格式不对"
    cookies = (info.get("cookie_info") or {}).get("cookies")
    if not isinstance(cookies, list):
        return None, f"缺少 cookie_info.cookies（有的键：{', '.join(sorted(info)) or '无'}）"
    if not any(isinstance(c, dict) and c.get("name") == "SESSDATA" and c.get("value") for c in cookies):
        return None, "缺少 SESSDATA"
    return info, None


def summarize_login_info(info):
    cookies = {c.get("name"): c for c in (info.get("cookie_info") or {}).get("cookies", []) if isinstance(c, dict)}
    token = info.get("token_info") or {}
    sessdata = cookies.get("SESSDATA") or {}
    mid = token.get("mid")
    if not mid and cookies.get("DedeUserID"):
        mid = cookies["DedeUserID"].get("value")
    return {
        "mid": str(mid) if mid else None,
        "expires_at": sessdata.get("expires"),
        "platform": info.get("platform"),
    }


class BilibiliAccount:
    def __init__(self, state_dir):
        self.cookie_file = Path(state_dir) / "cookies.json"
        self._lock = threading.Lock()
        self._nav_cache = None  # (文件 mtime, 检查时间, 结果)
        self._session = None    # 当前这张二维码
        self._process = None    # 等扫码的 helper 进程

    # ------------------------------------------------------------ 状态

    def status(self, check=True):
        if not self.cookie_file.is_file() or self.cookie_file.stat().st_size == 0:
            return {"exists": False, "logged_in": False}
        stat = self.cookie_file.stat()
        info, error = parse_login_info(self.cookie_file.read_text(encoding="utf-8", errors="replace"))
        if info is None:
            return {"exists": True, "logged_in": False, "error": f"cookies.json {error}", "updated_at": stat.st_mtime}
        result = dict(summarize_login_info(info), exists=True, logged_in=True, updated_at=stat.st_mtime)
        if check:
            result.update(self._check_online(info, stat.st_mtime))
        return result

    def _check_online(self, info, mtime):
        """用 SESSDATA 调一次 nav 接口：拿用户名，顺便确认会话还有效。结果按文件版本缓存 10 分钟。"""
        now = time.time()
        cached = self._nav_cache
        if cached and cached[0] == mtime and now - cached[1] < NAV_CACHE_SECONDS:
            return cached[2]
        cookies = {c["name"]: c.get("value", "") for c in info["cookie_info"]["cookies"]
                   if isinstance(c, dict) and c.get("name") in ("SESSDATA", "bili_jct", "DedeUserID")}
        try:
            import requests
            response = requests.get(NAV_API, cookies=cookies, headers={"User-Agent": USER_AGENT}, timeout=8)
            data = response.json()
            if data.get("code") == 0 and (data.get("data") or {}).get("isLogin"):
                result = {"valid": True, "uname": data["data"].get("uname"), "checked_at": now}
            elif data.get("code") == -101:
                result = {"valid": False, "uname": None, "checked_at": now,
                          "error": "B 站说这个登录已经失效了，需要重新扫码"}
            else:
                result = {"valid": None, "uname": None, "checked_at": now,
                          "error": f"B 站返回 {data.get('code')}: {data.get('message')}"}
        except Exception as e:  # noqa: BLE001 网络问题不算登录失效
            result = {"valid": None, "uname": None, "checked_at": now, "error": f"检查登录状态失败: {e}"}
        self._nav_cache = (mtime, now, result)
        return result

    # ------------------------------------------------------------ 扫码登录

    def _spawn_helper(self):
        return subprocess.Popen(
            [sys.executable, str(QR_HELPER)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            cwd=tempfile.gettempdir(),  # biliup 可能在工作目录写日志，别写进仓库或 userdata
        )

    @staticmethod
    def _pump(proc, messages):
        """把 helper 的结果行转成消息；最后总会放一条 exit，等消息的一方不会永远卡住。"""
        tail = deque(maxlen=5)
        for line in proc.stdout:
            line = line.strip()
            tag, _, payload = line.partition(" ")
            if tag in ("@@QR", "@@LOGIN", "@@ERROR"):
                try:
                    messages.put((tag[2:], json.loads(payload)))
                    continue
                except ValueError:
                    pass
            if line:
                tail.append(line)
        proc.wait()
        messages.put(("EXIT", {"code": proc.returncode, "tail": " | ".join(tail)}))

    def start_qr_login(self):
        self.cancel_qr_login()
        try:
            proc = self._spawn_helper()
        except OSError as e:
            raise RuntimeError(f"启动扫码登录进程失败: {e}") from e
        messages = queue.Queue()
        threading.Thread(target=self._pump, args=(proc, messages), daemon=True, name="bilibili-qr-pump").start()
        try:
            kind, payload = messages.get(timeout=QR_START_TIMEOUT)
        except queue.Empty:
            proc.kill()
            raise RuntimeError("B 站二维码接口没有响应") from None
        if kind != "QR":
            proc.kill()
            raise RuntimeError(payload.get("message") or f"扫码登录进程退出了: {payload.get('tail') or payload}")
        url = (payload.get("data") or {}).get("url")
        if payload.get("code") != 0 or not url:
            proc.kill()
            raise RuntimeError(f"B 站没给二维码: {payload.get('message') or payload}")
        now = time.time()
        session = {"id": secrets.token_hex(8), "url": url, "state": "waiting",
                   "created_at": now, "expires_at": now + QR_LIFETIME_SECONDS, "message": None}
        with self._lock:
            self._session = session  # 新二维码顶掉旧的；旧的那个扫上了也不会再落盘
            self._process = proc
        threading.Thread(target=self._wait_for_scan, args=(session["id"], messages), daemon=True,
                         name="bilibili-qr-login").start()
        return dict(session)

    def cancel_qr_login(self, session_id=None):
        """关掉还在等扫码的 helper 进程（关弹窗、重新生成二维码时）。"""
        with self._lock:
            if session_id and (not self._session or self._session["id"] != session_id):
                return False
            proc, self._process = self._process, None
            if self._session and self._session["state"] == "waiting":
                self._session.update(state="cancelled", message="已取消")
        if proc and proc.poll() is None:
            proc.kill()
        return True

    def qr_status(self, session_id):
        with self._lock:
            session = self._session
            if not session or session["id"] != session_id:
                return None
            if session["state"] == "waiting" and time.time() > session["expires_at"] + 15:
                session.update(state="expired", message="二维码过期了，重新生成一个")
            return dict(session)

    def _finish(self, session_id, **fields):
        with self._lock:
            if self._session and self._session["id"] == session_id and self._session["state"] == "waiting":
                self._session.update(fields)

    def _wait_for_scan(self, session_id, messages):
        kind, payload = messages.get()
        if kind == "ERROR":
            message = payload.get("message") or ""
            expired = "86038" in message or "过期" in message or "失效" in message or "expired" in message.lower()
            self._finish(session_id, state="expired" if expired else "failed",
                         message="二维码过期了，重新生成一个" if expired else f"登录失败: {message}")
            return
        if kind != "LOGIN":
            self._finish(session_id, state="failed", message=f"扫码登录进程退出了: {payload.get('tail') or payload}")
            return
        text = payload.get("info") or ""
        info, error = parse_login_info(text)
        if info is None:
            self._finish(session_id, state="failed", message=f"登录返回的数据不对（{error}），没有覆盖原来的登录信息")
            return
        with self._lock:
            superseded = not self._session or self._session["id"] != session_id or self._session["state"] != "waiting"
        if superseded:
            return
        try:
            backup = self.save_login_info(text)
        except OSError as e:
            self._finish(session_id, state="failed", message=f"写 cookies.json 失败: {e}")
            return
        self._nav_cache = None
        summary = summarize_login_info(info)
        self._finish(session_id, state="success", mid=summary["mid"], backup=backup,
                     message="登录成功，下一次投稿就会用新的登录信息")

    def save_login_info(self, text):
        """备份旧文件后原子替换 cookies.json（权限 600：里面是登录凭据）。返回备份文件名。"""
        backup = None
        if self.cookie_file.is_file():
            backup = self.cookie_file.with_name(f"cookies.json.bak-{time.strftime('%Y%m%d-%H%M%S')}")
            backup.write_bytes(self.cookie_file.read_bytes())
            os.chmod(backup, 0o600)
        self.cookie_file.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=str(self.cookie_file.parent), prefix=".cookies-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
            os.chmod(tmp_path, 0o600)
            os.replace(tmp_path, self.cookie_file)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        return backup.name if backup else None
