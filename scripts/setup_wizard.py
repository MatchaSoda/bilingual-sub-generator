#!/usr/bin/env python3
"""首次部署向导：一步一步把代理、Gemini key、YouTube cookie、B 站登录、频道配置弄好。

每一步都「先解释为什么要这个 → 拿到输入 → 实际连一次验证 → 写进配置」，
不合格就当场告诉你哪里不对、怎么修。全部通过后写一个 .setup-done 标记，
docker-start.sh 看到标记就直接启动服务。

用法：
    python3 scripts/setup_wizard.py            # 交互向导（Docker 里由 ./docker-start.sh setup 调用）
    python3 scripts/setup_wizard.py --check    # 不交互，只体检现有配置并报告（退出码 0 = 全部合格）

路径约定（和 mover.py / settings.py 一致）：
    AUTOMATION_STATE_DIR 设了 → 一切用户数据都在那个目录（Docker：/app/userdata）
    没设                     → .env / cookies.txt 在仓库根，其余在 automation/
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "backend"))

from utils.setup_checks import (  # noqa: E402
    inspect_netscape_cookies, normalize_cookie_text, proxy_candidates,
    read_env_file, write_env_file, parse_api_keys,
)

IN_DOCKER = Path("/.dockerenv").exists() or os.getenv("IN_DOCKER") == "1"
_state_override = os.getenv("AUTOMATION_STATE_DIR")
STATE_DIR = Path(_state_override) if _state_override else BASE_DIR / "automation"
ENV_FILE = STATE_DIR / ".env" if _state_override else BASE_DIR / ".env"
COOKIES_FILE = Path(os.getenv("YT_COOKIES_FILE") or (BASE_DIR / "cookies.txt"))
BILI_COOKIES = STATE_DIR / "cookies.json"
CONFIG_FILE = STATE_DIR / "config.json"
CONFIG_EXAMPLE = BASE_DIR / "automation" / "config.json.example"
DONE_MARKER = STATE_DIR / ".setup-done"
VENV_BIN = BASE_DIR / "venv" / "bin"
DEFAULT_PROXY_HOST = "host.docker.internal" if IN_DOCKER else "127.0.0.1"

YOUTUBE_PROBE = "https://www.youtube.com/generate_204"
GEMINI_PROBE = "https://generativelanguage.googleapis.com/v1beta/models"
YT_TEST_VIDEO = "https://www.youtube.com/watch?v=aqz-KE-bpKQ"  # 公开视频，有 1080p 以上格式
NO_PROXY_DEFAULT = "localhost,127.0.0.1,.bilibili.com,.bilivideo.com,.biliapi.net,.hdslb.com,.acgvideo.com"


# ---------------------------------------------------------------- 输出与输入小工具
def hr(title):
    print("\n" + "=" * 64)
    print(f"  {title}")
    print("=" * 64)


def ok(msg):
    print(f"  ✅ {msg}")


def warn(msg):
    print(f"  ⚠️  {msg}")


def bad(msg):
    print(f"  ❌ {msg}")


def note(msg):
    for line in msg.strip("\n").splitlines():
        print(f"     {line}")


def display_path(p):
    """给用户看的路径：Docker 里把容器路径换成宿主机上的相对路径。"""
    p = Path(p)
    if IN_DOCKER and _state_override:
        try:
            return f"userdata/{p.relative_to(_state_override)}"
        except ValueError:
            pass
    return str(p)


def ask(prompt, default=None):
    suffix = f" [{default}]" if default not in (None, "") else ""
    try:
        answer = input(f"  ▶ {prompt}{suffix}: ").strip()
    except EOFError:
        print("\n  （没有交互终端，向导中止。Docker 下请用 ./docker-start.sh setup 运行。）")
        sys.exit(2)
    return answer or (default or "")


def ask_yes_no(prompt, default=True):
    hint = "Y/n" if default else "y/N"
    while True:
        answer = ask(f"{prompt} ({hint})").lower()
        if not answer:
            return default
        if answer in ("y", "yes", "是", "好"):
            return True
        if answer in ("n", "no", "否", "不"):
            return False


def ask_choice(prompt, choices, default=1):
    """choices: [(label, help), ...]，返回 1 起的序号。"""
    print(f"  ▶ {prompt}")
    for i, (label, help_text) in enumerate(choices, 1):
        print(f"       {i}. {label}" + (f"  —— {help_text}" if help_text else ""))
    while True:
        raw = ask("输入序号", str(default))
        if raw.isdigit() and 1 <= int(raw) <= len(choices):
            return int(raw)


def mask(secret):
    return secret if len(secret) <= 10 else f"{secret[:6]}…{secret[-4:]}"


# ---------------------------------------------------------------- 网络探测
def _requests():
    import requests  # 延迟导入，让 --help 不依赖它
    return requests


def probe(url, proxy, timeout=10, params=None):
    """返回 (status_code 或 None, 说明文字)。"""
    proxies = {"http": proxy, "https": proxy} if proxy else {"http": None, "https": None}
    try:
        r = _requests().get(url, proxies=proxies, timeout=timeout, params=params)
        return r.status_code, r.text[:400]
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"


def test_route(proxy):
    """一条出网路径能不能同时到 YouTube 和 Gemini。返回 (yt_ok, gemini_ok, detail)。"""
    yt_code, yt_detail = probe(YOUTUBE_PROBE, proxy)
    gm_code, gm_detail = probe(GEMINI_PROBE, proxy)
    yt_ok = yt_code in (200, 204)
    gemini_ok = gm_code in (200, 400, 401, 403, 404)  # 没带 key 会被拒，但能拒就说明网络通
    detail = f"YouTube={yt_code or yt_detail} Gemini={gm_code or gm_detail}"
    return yt_ok, gemini_ok, detail


def apply_proxy_env(proxy):
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        if proxy:
            os.environ[name] = proxy
        else:
            os.environ.pop(name, None)
    for name in ("ALL_PROXY", "all_proxy"):
        os.environ.pop(name, None)
    os.environ["NO_PROXY"] = NO_PROXY_DEFAULT


def validate_gemini_key(key, proxy):
    """返回 (状态, 说明)。状态：ok / invalid / region / unknown。"""
    code, body = probe(GEMINI_PROBE, proxy, timeout=15, params={"key": key, "pageSize": "1"})
    if code == 200:
        return "ok", "可用"
    if code is None:
        return "unknown", f"连不上：{body}"
    if "API_KEY_INVALID" in body or code in (401, 403):
        return "invalid", "key 无效（复制不完整？或者被删了）"
    if "location is not supported" in body:
        return "region", "Gemini 说「你所在地区不支持」—— 这是出口 IP 的问题，要换代理节点（或先开代理）"
    return "unknown", f"HTTP {code}: {body[:120]}"


# ---------------------------------------------------------------- 各步骤
def step_environment(report_only=False):
    hr("第 0 步 · 运行环境自检")
    all_good = True

    if shutil.which("ffmpeg"):
        ok("ffmpeg 已安装")
    else:
        bad("找不到 ffmpeg，无法压制视频")
        all_good = False

    try:
        fonts = subprocess.run(["fc-list", ":family"], capture_output=True, text=True, timeout=20).stdout
    except Exception:  # noqa: BLE001
        fonts = ""
    if "Noto Sans CJK" in fonts:
        ok("字体 Noto Sans CJK 已安装（字幕用）")
    else:
        bad("没有 Noto Sans CJK 字体。ffmpeg 会静默换成别的字体，字幕出现方块或缺字。"
            + ("镜像构建有问题，请重新 build。" if IN_DOCKER else "请安装 fonts-noto-cjk。"))
        all_good = False

    chrome = None
    try:
        from nodriver.core.config import find_chrome_executable
        chrome = find_chrome_executable()
    except Exception:  # noqa: BLE001
        pass
    if chrome:
        ok(f"Chrome/Chromium 已找到：{chrome}（yt-dlp 取 PO Token 要用）")
    else:
        warn("找不到 Chrome/Chromium。下载仍会进行，但 YouTube 只给 360p 画质（RUNBOOK §5.3）。")
    if chrome and not os.getenv("DISPLAY"):
        warn("没有 DISPLAY 环境变量，Chrome 会起不来。Docker 镜像里由 entrypoint 启动 Xvfb 提供。")

    for tool in ("yt-dlp", "biliup"):
        path = VENV_BIN / tool
        if path.exists() or shutil.which(tool):
            ok(f"{tool} 可用")
        else:
            warn(f"{tool} 不在 venv 里" + ("，B 站投稿功能不可用" if tool == "biliup" else ""))
            if tool == "yt-dlp":
                all_good = False
    return all_good


def step_network(env, report_only=False):
    hr("第 1 步 · 网络与代理")
    note("""
这套流程要访问三个地方：YouTube（下载）、Google Gemini（翻译）、B 站（投稿）。
前两个在中国大陆网络需要代理；在海外通常可以直连。
    """)
    current = env.get("HTTPS_PROXY") or env.get("HTTP_PROXY") or ""

    if report_only:
        yt_ok, gm_ok, detail = test_route(current or None)
        (ok if yt_ok and gm_ok else bad)(f"当前设置 {current or '直连'} → {detail}")
        return yt_ok and gm_ok

    if IN_DOCKER:
        note(f"""
你现在在 Docker 容器里。代理软件跑在「宿主机」上时，容器里不能写 127.0.0.1，
要写 {DEFAULT_PROXY_HOST}（向导会自动替你加上）。
两个常见坑：
  · 代理软件要打开「允许局域网连接 / Allow LAN」，否则容器连不进去（Linux 上必现）。
  · 同一个端口可能是 HTTP 代理也可能是 SOCKS5，向导会两种都试，用能通的那种。
        """)

    choice = ask_choice("你的网络能直接访问 YouTube 和 Google 吗？", [
        ("能，直连", "海外网络 / 路由器上已经翻墙"),
        ("不能，用本机代理软件（Clash / v2rayN / sing-box…）", "只需要告诉我端口号"),
        ("用别的地址的代理", "填完整地址，如 socks5://192.168.1.5:1080"),
    ], default=2)

    while True:
        if choice == 1:
            candidates = [None]
        elif choice == 2:
            default_port = ""
            if current and ":" in current:
                default_port = current.rsplit(":", 1)[-1]
            port = ask("代理软件监听的端口（Clash 常见 7890，v2rayN 常见 10808）", default_port or "7890")
            candidates = proxy_candidates(port, DEFAULT_PROXY_HOST) or [None]
        else:
            raw = ask("代理完整地址", current)
            candidates = proxy_candidates(raw, DEFAULT_PROXY_HOST) or [None]

        chosen, found = None, False
        for candidate in candidates:
            label = candidate or "直连"
            print(f"  … 测试 {label}")
            yt_ok, gm_ok, detail = test_route(candidate)
            if yt_ok and gm_ok:
                ok(f"{label} 通：{detail}")
                chosen, found = candidate, True
                break
            warn(f"{label} 不通：{detail}")

        if found:
            break
        if candidates == [None]:
            # 直连失败
            bad("直连到不了 YouTube / Gemini。")
        else:
            bad("这个代理两种协议都试过了，都不通。")
            note(f"""
排查顺序：
  1. 代理软件确实在运行，且端口没写错
  2. 代理软件开了「允许局域网连接」（容器 / 别的机器访问必须开）
  3. 防火墙没拦这个端口
  4. 代理节点本身能访问 Google（在浏览器里开 https://aistudio.google.com 试试）
            """)
        again = ask_choice("怎么办？", [
            ("重新填", ""),
            ("先跳过，之后再改 .env", "跳过则后面的 Gemini / YouTube 检查大概率也会失败"),
        ])
        if again == 2:
            chosen = current or None
            break
        choice = ask_choice("选择方式", [("直连", ""), ("本机代理端口", ""), ("完整地址", "")], default=2)

    apply_proxy_env(chosen)
    env["HTTP_PROXY"] = chosen or ""
    env["HTTPS_PROXY"] = chosen or ""
    env["NO_PROXY"] = NO_PROXY_DEFAULT
    env.setdefault("GEMINI_PROXY", "")
    write_env_file(ENV_FILE, {
        "HTTP_PROXY": env["HTTP_PROXY"], "HTTPS_PROXY": env["HTTPS_PROXY"],
        "NO_PROXY": env["NO_PROXY"], "GEMINI_PROXY": env["GEMINI_PROXY"],
    })
    ok(f"已写入 {display_path(ENV_FILE)}：代理 = {chosen or '直连'}")
    return True


def step_gemini(env, report_only=False):
    hr("第 2 步 · Gemini API Key（翻译用）")
    proxy = env.get("HTTPS_PROXY") or None
    existing = parse_api_keys(env.get("GOOGLE_API_KEYS", ""))

    def check_all(keys):
        good = []
        for key in keys:
            status, detail = validate_gemini_key(key, proxy)
            (ok if status == "ok" else bad)(f"{mask(key)} → {detail}")
            if status == "ok":
                good.append(key)
            elif status == "region":
                note("换一个代理节点后再跑一次向导；或者到 .env 里改 HTTPS_PROXY。")
        return good

    if report_only:
        if not existing:
            bad("没有配置 GOOGLE_API_KEYS")
            return False
        return len(check_all(existing)) == len(existing)

    note("""
去 https://aistudio.google.com/apikey 用 Google 账号登录，点「Create API key」，
复制以 AIza 开头的一串字符。免费额度够个人使用；多个 key 用逗号隔开会轮流使用，
可以分摊速率限制。
    """)
    if existing:
        ok(f"已有 {len(existing)} 个 key：{', '.join(mask(k) for k in existing)}")
        if not ask_yes_no("要重新填吗？", default=False):
            return len(check_all(existing)) > 0

    while True:
        raw = ask("粘贴 API key（多个用逗号分开）")
        keys = parse_api_keys(raw)
        if not keys:
            warn("没读到任何 key")
            continue
        good = check_all(keys)
        if good:
            write_env_file(ENV_FILE, {"GOOGLE_API_KEYS": ",".join(good)})
            env["GOOGLE_API_KEYS"] = ",".join(good)
            os.environ["GOOGLE_API_KEYS"] = env["GOOGLE_API_KEYS"]
            ok(f"已保存 {len(good)} 个可用 key 到 {display_path(ENV_FILE)}")
            return True
        if not ask_yes_no("全部不可用。再试一次？"):
            return False


def _ytdlp_smoke_test(proxy):
    """用生产同款参数拉一次公开视频的格式列表，看能不能拿到 ≥720p。返回 (ok, 说明)。"""
    import yt_dlp
    cookies_tmp = None
    if COOKIES_FILE.is_file() and COOKIES_FILE.stat().st_size > 0:
        fd, cookies_tmp = tempfile.mkstemp(prefix="yt-cookies-", suffix=".txt")
        os.close(fd)
        shutil.copyfile(COOKIES_FILE, cookies_tmp)
    opts = {
        "quiet": True, "no_warnings": True, "skip_download": True,
        "proxy": proxy, "socket_timeout": 30,
        "extractor_args": {"youtube": {"player_client": ["mweb"]}},
    }
    if cookies_tmp:
        opts["cookiefile"] = cookies_tmp
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(YT_TEST_VIDEO, download=False)
        heights = [f.get("height") or 0 for f in info.get("formats", []) if f.get("vcodec") not in (None, "none")]
        best = max(heights) if heights else 0
        if best >= 720:
            return True, f"拿到最高 {best}p 的视频格式"
        if best:
            return False, f"只拿到 {best}p。通常是 PO Token 没取到（Chrome 没起来）或 cookie 半残，见 RUNBOOK §5.3"
        return False, "没有任何视频格式，只有图片。cookie 大概率是半残导出，见 RUNBOOK §5.3"
    except Exception as e:  # noqa: BLE001
        text = str(e)
        if "not a bot" in text or "Sign in" in text:
            return False, "YouTube 要求登录验证（风控）。需要一份完整的登录态 cookie"
        return False, f"{type(e).__name__}: {text[:200]}"
    finally:
        if cookies_tmp:
            try:
                os.unlink(cookies_tmp)
            except OSError:
                pass


def step_youtube_cookies(env, report_only=False):
    hr("第 3 步 · YouTube Cookie（防风控）")
    proxy = env.get("HTTPS_PROXY") or None

    def inspect_file():
        if not COOKIES_FILE.is_file() or COOKIES_FILE.stat().st_size == 0:
            return None
        text = COOKIES_FILE.read_text(encoding="utf-8", errors="replace")
        report = inspect_netscape_cookies(text)
        if report["had_crlf"] and not report_only:
            with open(COOKIES_FILE, "w", encoding="utf-8") as f:  # 原地写，保持 bind mount 的 inode
                f.write(normalize_cookie_text(text))
            ok("已去掉 Windows 换行符（CRLF）")
        return report

    def show(report):
        ok(f"文件解析：{report['total']} 条 cookie，其中 youtube.com {report['youtube']} 条，登录态标记 {report['login_cookies'] or '无'}")
        for p in report["problems"]:
            bad(p)

    if report_only:
        report = inspect_file()
        if report is None:
            warn(f"没有 {display_path(COOKIES_FILE)}，下载会裸奔（容易被风控）")
            return True
        show(report)
        passed, detail = _ytdlp_smoke_test(proxy)
        (ok if passed else bad)(f"yt-dlp 实测：{detail}")
        return passed

    note(f"""
没有登录 cookie 时 YouTube 很容易弹「Sign in to confirm you're not a bot」，服务器 IP 尤其严重。
导出步骤（要「完整」导出，半残的比没有更糟）：
  1. 浏览器开一个「无痕 / 隐身窗口」，登录 YouTube
  2. 安装扩展 “Get cookies.txt LOCALLY”，在 youtube.com 页面点它 → Export → 得到 cookies.txt
  3. 立刻关掉这个无痕窗口，不要再用它访问 YouTube（否则 token 会被轮换作废）
  4. 把文件放到：{display_path(COOKIES_FILE)}
    """)
    report = inspect_file()
    if report is not None:
        ok("已经有一份 cookie 文件")
        show(report)
        if not report["problems"] and not ask_yes_no("要换新的吗？", default=False):
            pass
        else:
            report = None
    if report is None:
        while True:
            if ask("放好文件后按回车继续（直接输入 skip 跳过这一步）").lower() == "skip":
                warn("跳过 cookie。下载成功率会明显下降，之后可用 setup 补上。")
                return None
            report = inspect_file()
            if report is None:
                bad(f"还是没找到 {display_path(COOKIES_FILE)}（或文件是空的）")
                if ask_yes_no("跳过 cookie？下载成功率会明显下降", default=False):
                    return None
                continue
            show(report)
            if not report["problems"]:
                break
            if ask_yes_no("有问题。还是先用这份继续？", default=False):
                break

    print("  … 用 yt-dlp 实测一个公开视频（会拉起 Chrome 取 PO Token，约 20–60 秒）")
    passed, detail = _ytdlp_smoke_test(proxy)
    (ok if passed else bad)(f"yt-dlp 实测：{detail}")
    if not passed:
        note("可以先继续；正式跑起来后如果下载失败，回来重跑 setup 换 cookie。")
    return passed


def step_automation(env, report_only=False):
    hr("第 4 步 · 自动搬运到 B 站（可选）")
    if report_only:
        enabled = env.get("ENABLE_AUTOMATION", "0") == "1"
        if not enabled:
            ok("自动搬运未启用（只用 Web 界面）")
            return True
        good = True
        if CONFIG_FILE.is_file():
            try:
                cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                ok(f"config.json：{len(cfg.get('channels', []))} 个频道，每 {cfg.get('check_interval_seconds', '?')}s 扫一轮")
                backfill = cfg.get("backfill") or {}
                if backfill.get("mode") == "since_first_start":
                    ok(f"补档范围：只处理首次启动前 {backfill.get('lookback_hours', 24)} 小时之后发布的视频（新账号模式）")
                else:
                    warn("补档范围：history 之外的全补（老账号模式）。新账号 / 新部署请在 config.json 加 backfill.mode=since_first_start，否则会把频道存货全搬一遍")
            except Exception as e:  # noqa: BLE001
                bad(f"config.json 不是合法 JSON：{e}")
                good = False
        else:
            bad(f"缺少 {display_path(CONFIG_FILE)}")
            good = False
        if BILI_COOKIES.is_file() and BILI_COOKIES.stat().st_size > 0:
            ok("B 站登录信息存在")
        else:
            bad(f"缺少 {display_path(BILI_COOKIES)}，投稿会被跳过")
            good = False
        return good

    note("""
自动搬运 = 定期扫描指定 YouTube 频道 → 生成双语视频 → 自动投稿到你的 B 站账号。
不需要的话选「否」，只用 Web 界面手工处理单个视频。
    """)
    if not ask_yes_no("启用自动搬运？", default=env.get("ENABLE_AUTOMATION", "0") == "1"):
        write_env_file(ENV_FILE, {"ENABLE_AUTOMATION": "0"})
        env["ENABLE_AUTOMATION"] = "0"
        ok("已关闭自动搬运")
        return True

    # ---- B 站登录
    print("\n  —— 4a. B 站登录")
    if BILI_COOKIES.is_file() and BILI_COOKIES.stat().st_size > 0:
        ok(f"已有登录信息 {display_path(BILI_COOKIES)}")
        relogin = ask_yes_no("重新登录？", default=False)
    else:
        relogin = True
    if relogin:
        biliup = VENV_BIN / "biliup" if (VENV_BIN / "biliup").exists() else shutil.which("biliup")
        if not biliup:
            bad("没有 biliup，无法登录 / 投稿")
            return False
        note("接下来交给 biliup：按提示选「扫码登录」，用 B 站手机 App 扫终端里的二维码。")
        ask("按回车开始")
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        login_env = {k: v for k, v in os.environ.items() if k.lower() not in ("http_proxy", "https_proxy", "all_proxy")}
        subprocess.run([str(biliup), "login"], cwd=str(STATE_DIR), env=login_env)
        if BILI_COOKIES.is_file() and BILI_COOKIES.stat().st_size > 0:
            ok(f"登录成功，已保存到 {display_path(BILI_COOKIES)}")
        else:
            bad("没有生成 cookies.json，登录没成功。可以之后再跑一次 setup。")

    # ---- 频道配置
    print("\n  —— 4b. 要搬运哪些频道")
    if CONFIG_FILE.is_file():
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            bad(f"现有 config.json 解析失败：{e}，将用示例重建")
            cfg = json.loads(CONFIG_EXAMPLE.read_text(encoding="utf-8"))
        ok(f"已有配置：{len(cfg.get('channels', []))} 个频道")
        edit = ask_yes_no("重新设置频道列表？", default=False)
    else:
        cfg = json.loads(CONFIG_EXAMPLE.read_text(encoding="utf-8"))
        edit = True

    if edit:
        note("""
每个频道需要：
  · 频道视频页地址，形如 https://www.youtube.com/@频道名/videos
  · 关键词（可留空）：只处理标题或简介里含这个词的视频，用来只搬某个栏目
  · 排除词（可留空，逗号分开）：标题含任一词就跳过，比如 事故,火災
  · B 站分区 id（不清楚就用默认值）和投稿标签
        """)
        channels = []
        while True:
            name = ask("频道名字（随便写，只是给日志看）")
            url = ask("频道视频页地址")
            if not url.startswith("http"):
                warn("地址要以 http 开头")
                continue
            keyword = ask("关键词（可留空）", "")
            exclude = [w.strip() for w in ask("排除词（逗号分开，可留空）", "").split(",") if w.strip()]
            tid = ask("B 站分区 id", "208")
            tags = ask("投稿标签（逗号分开）", "日语学习,双语字幕,日本,日本新闻,日常")
            channels.append({
                "name": name or url, "url": url, "keyword": keyword, "exclude": exclude,
                "bili_tid": int(tid) if tid.isdigit() else 208, "tags": tags,
            })
            if not ask_yes_no("再加一个频道？", default=False):
                break
        cfg["channels"] = channels

        minutes = ask("每隔多少分钟扫一次频道", str(cfg.get("check_interval_seconds", 1800) // 60))
        cfg["check_interval_seconds"] = int(minutes) * 60 if minutes.isdigit() else 1800
        per_cycle = ask("每轮最多处理几个视频（防止首轮把整个频道都搬了）", str(cfg.get("max_uploads_per_cycle", 3)))
        cfg["max_uploads_per_cycle"] = int(per_cycle) if per_cycle.isdigit() else 3

        window = cfg.get("playlist_items", 100)
        note(f"""
每轮会扫频道最近 {window} 个视频（playlist_items）。这个窗口故意开得很大，是为了服务停机几天后能把
漏掉的都补上；但对一个新账号来说，第一次启动就会把这 {window} 个存货全搬上去。
        """)
        start_choice = ask_choice("这个 B 站账号之前搬过这些频道吗？", [
            ("没有，全新开始", "只处理从现在起发布的视频（往前多算几小时兜底），以后重启也不会推后这个起点"),
            ("有，带着旧的 history.json 继续", "history 之外的全补，等同一直以来的行为"),
        ], default=1 if (cfg.get("backfill") or {}).get("mode", "since_first_start") == "since_first_start" else 2)
        if start_choice == 1:
            hours = ask("起点往前多算几小时（覆盖启动前刚发布、还没来得及扫到的视频）",
                        str((cfg.get("backfill") or {}).get("lookback_hours", 24)))
            cfg["backfill"] = {"mode": "since_first_start",
                               "lookback_hours": int(hours) if hours.isdigit() else 24}
        else:
            cfg["backfill"] = {"mode": "all"}

        model_choice = ask_choice("语音识别模型", [
            ("large-v3-turbo", "质量最好，纯 CPU 处理 10 分钟视频约需 5–15 分钟"),
            ("small", "快 3–5 倍，识别错误明显变多，只适合弱机器试水"),
        ])
        cfg.setdefault("processing", {})["whisper_model"] = "large-v3-turbo" if model_choice == 1 else "small"

        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        ok(f"已写入 {display_path(CONFIG_FILE)}。以后想改直接编辑这个文件，下一轮扫描自动生效。")

    write_env_file(ENV_FILE, {"ENABLE_AUTOMATION": "1"})
    env["ENABLE_AUTOMATION"] = "1"
    return True


def whisper_model_cached(model):
    """快照目录里真的有 model.bin 才算缓存好了。

    只看 scan_cache_dir 有没有这个 repo 会误判：下载被打断时 repo 目录、config.json 都在，
    model.bin 却还是 blobs/*.incomplete，第一次任务会卡在「Loading Whisper model」重新下。
    """
    try:
        from huggingface_hub import scan_cache_dir
        for repo in scan_cache_dir().repos:
            if model.lower() not in repo.repo_id.lower():
                continue
            for revision in repo.revisions:
                if any(f.file_name == "model.bin" for f in revision.files):
                    return True
    except Exception:  # noqa: BLE001
        pass
    return False


def step_whisper_model(env, report_only=False):
    hr("第 5 步 · 预下载语音识别模型")
    model = "large-v3-turbo"
    if CONFIG_FILE.is_file():
        try:
            model = json.loads(CONFIG_FILE.read_text(encoding="utf-8")).get("processing", {}).get("whisper_model", model)
        except Exception:  # noqa: BLE001
            pass
    cached = whisper_model_cached(model)
    if cached:
        ok(f"模型 {model} 已在本地缓存")
        return True
    if report_only:
        warn(f"模型 {model} 还没下载，第一次处理视频时会自动下载（约 1.6 GB）")
        return True
    note(f"""
第一次转写要从 Hugging Face 下载模型 {model}（large-v3-turbo 约 1.6 GB），
走的是上面配置的代理。现在先下好，正式跑的时候就不用等。
    """)
    if not ask_yes_no("现在下载？"):
        return True
    try:
        from faster_whisper import download_model
        start = time.time()
        download_model(model)
        ok(f"下载完成，用时 {int(time.time() - start)} 秒")
    except Exception as e:  # noqa: BLE001
        bad(f"下载失败：{type(e).__name__}: {str(e)[:200]}")
        note("多半是代理到不了 huggingface.co。可以先继续，第一次处理视频时会再试。")
    return True


# ---------------------------------------------------------------- 主流程
def load_env():
    env = read_env_file(ENV_FILE)
    # 容器里 env_file 注入的值优先级低于文件本身（文件才是持久的），但文件没有的从环境补
    for key in ("GOOGLE_API_KEYS", "HTTP_PROXY", "HTTPS_PROXY", "GEMINI_PROXY", "ENABLE_AUTOMATION"):
        if key not in env and os.getenv(key):
            env[key] = os.getenv(key)
    return env


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="只体检，不交互")
    args = parser.parse_args()

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    env = load_env()
    apply_proxy_env(env.get("HTTPS_PROXY") or env.get("HTTP_PROXY") or None)

    if args.check:
        results = [
            step_environment(report_only=True),
            step_network(env, report_only=True),
            step_gemini(env, report_only=True),
            step_youtube_cookies(env, report_only=True),
            step_automation(env, report_only=True),
            step_whisper_model(env, report_only=True),
        ]
        hr("体检结果")
        (ok if all(results) else bad)(f"{sum(results)}/{len(results)} 项通过")
        sys.exit(0 if all(results) else 1)

    hr("双语字幕生成器 · 首次设置向导")
    note(f"""
接下来 5 步，每一步都会实际连一次网验证，随时 Ctrl+C 退出，下次从头再来即可（已填的会记住）。
配置文件位置：{display_path(ENV_FILE)}
    """)
    step_environment()
    step_network(env)
    gemini_ok = step_gemini(env)
    yt_ok = step_youtube_cookies(env)
    step_automation(env)
    step_whisper_model(env)

    hr("完成")
    if gemini_ok:
        ok("Gemini 可用")
    else:
        bad("Gemini 没配好，翻译会失败 —— 重跑 setup 或编辑 .env 的 GOOGLE_API_KEYS")
    if yt_ok:
        ok("YouTube 下载实测通过")
    elif yt_ok is None:
        warn("YouTube cookie 已跳过，遇到风控再回来补")
    else:
        warn("YouTube 下载实测没过，先试跑看看，失败就回来换 cookie")
    DONE_MARKER.write_text(time.strftime("%Y-%m-%d %H:%M:%S\n"))
    if IN_DOCKER:
        note("""
下一步（在宿主机项目目录里执行）：
    ./docker-start.sh              # 启动服务
    打开 http://localhost:8501      # Web 界面
    ./docker-start.sh logs         # 看日志
    ./docker-start.sh setup        # 以后要改配置，再跑一次向导
        """)
    else:
        note("下一步：bash start.sh 启动 Web 服务；自动搬运见 docs/RUNBOOK.md §1。")


if __name__ == "__main__":
    main()
