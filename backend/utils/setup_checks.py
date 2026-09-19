"""首次部署向导（scripts/setup_wizard.py）用到的纯逻辑：cookie 体检、代理地址整理、.env 读写。

放在 backend/utils 而不是 scripts/ 里，是为了让 backend/tests 能直接 import 做单测。
这里不做任何网络请求，网络探测都在向导脚本里。
"""
import re
from pathlib import Path

# 判断 YouTube cookie 是否为「完整的登录态导出」的三个信号（docs/RUNBOOK.md §2）
_LOGIN_COOKIES = ("LOGIN_INFO", "SID", "__Secure-3PSID")


def normalize_cookie_text(text):
    """去掉 Windows 导出常见的 CRLF；yt-dlp 读到 \\r 会把值当成带回车的脏数据。"""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def inspect_netscape_cookies(text):
    """给 Netscape 格式 cookie 文本做体检，返回 dict：

    is_netscape   头部是否像 Netscape 格式（首行注释或存在 7 列 tab 分隔行）
    total         cookie 条数
    youtube       .youtube.com 域下的条数
    login_cookies 命中的登录态 cookie 名列表
    had_crlf      原文是否含 CRLF
    problems      人话描述的问题列表（空 = 合格）
    """
    had_crlf = "\r" in text
    text = normalize_cookie_text(text)
    rows = []
    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 7:
            rows.append(parts)

    youtube_rows = [r for r in rows if r[0].endswith("youtube.com")]
    names = {r[5] for r in youtube_rows}
    login_hits = [n for n in _LOGIN_COOKIES if n in names]
    is_netscape = bool(rows) and (text.lstrip().startswith("#") or len(rows) > 3)

    problems = []
    if not rows:
        problems.append("文件里没有任何 cookie 行。要用「Netscape / cookies.txt 格式」导出，不是 JSON。")
    elif not youtube_rows:
        problems.append("文件里没有 youtube.com 的 cookie。确认导出时打开的是 youtube.com 页面。")
    else:
        if "LOGIN_INFO" not in names:
            problems.append(
                "缺少 LOGIN_INFO，这不是登录态导出。半残 cookie 比没有更糟（会被判成未登录还丢掉高画质），"
                "请在无痕窗口登录后重新完整导出。"
            )
        if len(youtube_rows) < 20:
            problems.append(f"youtube.com 只有 {len(youtube_rows)} 条 cookie，完整导出通常有几十到几百条，疑似导出不全。")
    return {
        "is_netscape": is_netscape,
        "total": len(rows),
        "youtube": len(youtube_rows),
        "login_cookies": login_hits,
        "had_crlf": had_crlf,
        "problems": problems,
    }


def proxy_candidates(raw, default_host):
    """把用户随手输入的代理地址整理成一组候选完整 URL，按优先级排列。

    支持的输入：
      ""                        → []（不用代理）
      "7890"                    → http://<default_host>:7890, socks5h://<default_host>:7890
      "192.168.1.5:7890"        → http://192.168.1.5:7890,  socks5h://192.168.1.5:7890
      "socks5://127.0.0.1:1080" → 原样一个
      "http://x:1"              → 原样一个

    同一个端口既可能是 HTTP 也可能是 SOCKS5（10808 就踩过这个坑，见 CLAUDE.md 环境约束），
    所以没写协议时两种都给出来，由向导实际探测决定用哪个。
    """
    raw = (raw or "").strip()
    if not raw:
        return []
    if re.match(r"^[a-z0-9]+://", raw, re.I):
        return [raw]
    if re.fullmatch(r"\d{1,5}", raw):
        hostport = f"{default_host}:{raw}"
    else:
        hostport = raw
    if ":" not in hostport:
        hostport = f"{hostport}:7890"
    return [f"http://{hostport}", f"socks5h://{hostport}"]


def read_env_file(path):
    """读 KEY=VALUE 形式的 .env，返回 dict。忽略注释和空行，去掉值两侧的引号。"""
    values = {}
    path = Path(path)
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def write_env_file(path, updates):
    """把 updates 合并进 .env：已有的键原地改值（保留注释和顺序），新键追加到末尾。

    值为 None 表示删除该键。用 open(..., 'w') 原地写而不是先写临时文件再 os.replace：
    Docker 里这个文件可能是 bind mount 进来的单个文件，replace 会换掉 inode、宿主机看不到。
    """
    path = Path(path)
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    remaining = dict(updates)
    out = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.partition("=")[0].strip()
            if key in remaining:
                value = remaining.pop(key)
                if value is None:
                    continue
                out.append(f"{key}={value}")
                continue
        out.append(line)
    for key, value in remaining.items():
        if value is not None:
            out.append(f"{key}={value}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out).rstrip("\n") + "\n")


def parse_api_keys(raw):
    """把用户粘贴的 key 串（逗号 / 空格 / 换行分隔）整理成去重后的列表。"""
    keys = []
    for token in re.split(r"[,\s]+", raw or ""):
        token = token.strip().strip("\"'")
        if token and token not in keys:
            keys.append(token)
    return keys
