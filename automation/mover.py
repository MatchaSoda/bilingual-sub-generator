import os
import json
import time
import subprocess
import re
import shutil
import tempfile
import fcntl
from pathlib import Path

# 项目根路径配置
BASE_DIR = Path(__file__).parent.parent.absolute()
CLI_PATH = BASE_DIR / "backend" / "entry_cli.py"
PYTHON_PATH = BASE_DIR / "venv" / "bin" / "python3"
YTDLP_PATH = BASE_DIR / "venv" / "bin" / "yt-dlp"
BILIUP_PATH = BASE_DIR / "venv" / "bin" / "biliup"
DOWNLOADS_DIR = BASE_DIR / "data" / "downloads"
HISTORY_FILE = Path(__file__).parent / "history.json"
CONFIG_FILE = Path(__file__).parent / "config.json"
# 专门存放生成好的双语视频
OUTPUT_DIR = Path(__file__).parent / "data"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 哔哩哔哩登录凭据 (假设用户已通过 biliup login 生成或手动放置)
BILI_SESSION = Path(__file__).parent / "cookies.json"

# YouTube cookies (Netscape 格式，放在项目根目录) —— 用于规避 YouTube 机器人检测
YT_COOKIES = BASE_DIR / "cookies.txt"

def make_cookies_copy():
    """复制 master cookies 到临时文件返回路径。

    yt-dlp 每次运行会把 Set-Cookie 响应写回 cookies 文件；YouTube 在风控时返回的是匿名
    Set-Cookie，会把 master 文件里的认证 token 一点点冲掉。我们让 yt-dlp 只污染临时副本，
    master 永远是用户最近从浏览器导出的那一份。
    """
    if not YT_COOKIES.exists():
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
    """
    cookies_tmp = make_cookies_copy()
    try:
        cmd = [
            str(YTDLP_PATH), "--ignore-errors", "--flat-playlist",
            "--playlist-items", f"1-{playlist_items}",
            "--print", "%(id)s|%(title)s|%(webpage_url)s",
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
            parts = line.split('|', 2)
            if len(parts) >= 3:
                videos.append({
                    'id': parts[0].strip(),
                    'title': parts[1].strip(),
                    'url': parts[2].strip(),
                })

        if videos:
            print(f"📥 成功获取视频列表:")
            for v in videos:
                print(f"  - [{v['id']}] {v['title']}")
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
    """单独获取一个视频的描述（仅在 title 不匹配时调用）。

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
            return ""
        desc_str = result.stdout.strip()
        if not desc_str or desc_str == "NA":
            return ""
        try:
            return json.loads(desc_str)
        except Exception:
            return desc_str
    except Exception as e:
        print(f"⚠️ 描述异常: {e}")
        return ""
    finally:
        if cookies_tmp:
            try: os.unlink(cookies_tmp)
            except OSError: pass
        # 无论成功失败都休眠，保证两次描述请求之间至少间隔 throttle_seconds
        if throttle_seconds:
            time.sleep(throttle_seconds)

def upload_to_bilibili(video_path, cover_path, title, tid, description, tags):
    """使用 biliup 投稿到 B 站"""
    if not BILI_SESSION.exists():
        print(f"⚠️ 找不到 B 站登录凭据 {BILI_SESSION}, 跳过投稿")
        print(f"💡 请在 automation 目录下执行: ../venv/bin/biliup login")
        return False

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

    # 清除空参数 (例如没有封面时)
    cmd = [c for c in cmd if c]

    try:
        process = subprocess.run(
            cmd, 
            cwd=str(Path(__file__).parent), 
            check=True, 
            capture_output=True, 
            text=True
        )
        print(f"✅ B 站投稿成功!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ B 站投稿失败!")
        error_msg = e.stderr or e.stdout or str(e)
        print(f"  错误详情: {error_msg}")
        return False

def process_and_upload(video_id, video_url, video_title, config, processing=None):
    print(f"\n🚀 开始处理: {video_title} ({video_id})")

    # 将非法字符替换为下划线，保留标题长度和可识别性
    safe_title = re.sub(r'[\\/*?:"<>|]', "_", video_title)
    target_video_path = OUTPUT_DIR / f"{safe_title}_bilingual.mp4"

    # 处理参数来自 config.json 的 "processing" 段（缺省时沿用以下默认值，等同旧行为）。
    proc = processing or {}
    cli_cmd = [
        str(PYTHON_PATH), str(CLI_PATH), video_url,
        "--segment-mode", proc.get("segment_mode", "llm"),
        "--whisper-model", proc.get("whisper_model", "large-v3-turbo"),
        "--gemini-model", proc.get("gemini_model", "gemini-3.1-flash-lite"),
        "--translation-batch-size", str(proc.get("translation_batch_size", 100)),
        "--output", str(target_video_path),
    ]
    if proc.get("enable_furigana", True):
        cli_cmd.append("--enable-furigana")
    if proc.get("translate_title", True):
        cli_cmd.append("--translate-title")
    if proc.get("fix_source_text", False):
        cli_cmd.append("--fix-source-text")
    
    print(f"执行命令: {' '.join(cli_cmd)}")
    
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
    for line in process.stdout:
        stripped_line = line.strip()
        # 实时打印子进程输出
        print(f"  [CLI] {stripped_line}", flush=True)
        if "Translated title:" in stripped_line:
            translated_title = stripped_line.split("Translated title:", 1)[1].strip()

    process.wait()

    if process.returncode != 0:
        print(f"❌ CLI 失败 (Code {process.returncode})", flush=True)
        return False

    if not target_video_path.exists():
        print(f"❌ 找不到生成的文件: {target_video_path}", flush=True)
        return False

    # 用中文译名重命名输出文件与封面，使本地文件名和 B 站投稿名都为中文
    display_title = video_title
    if translated_title:
        display_title = translated_title
        safe_zh_title = re.sub(r'[\\/*?:"<>|]', "_", translated_title).strip()
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

    # 检查封面图是否已同步 (entry_cli.py 逻辑会将其放在视频同目录)
    target_cover_path = target_video_path.with_suffix(".jpg")
    if target_cover_path.exists():
        print(f"✅ 封面图已同步至: {target_cover_path}", flush=True)

    # B 站投稿逻辑
    bili_tid = config.get('bili_tid', 171) # 171 为默认分区
    # B 站标题带上双语前缀（使用翻译后的中文标题）
    bili_title = f"【双语字幕】{display_title}"
    bili_desc = f"原始视频: {video_url}\n使用 AI 自动生成双语字幕和假名标注。"
    
    bili_tags = config.get('tags', "日语学习,双语字幕,日本,日本新闻,日常")
    
    return upload_to_bilibili(target_video_path, target_cover_path, bili_title, bili_tid, bili_desc, bili_tags)


def main():
    print(f"🏁 自动化搬运程序启动 (BASE_DIR: {BASE_DIR})")
    print(f"📂 视频输出目录: {OUTPUT_DIR}")
    history = load_history()
    
    while True:
        try:
            config = load_config()
        except: pass

        # 三个反爬 / 限流开关，均可在 config.json 里调整（缺省沿用保守默认值）：
        #   playlist_items                   —— 每轮扫描频道最近多少个视频（窗口越大越能扛停机）
        #   description_fetch_interval_seconds —— 相邻两次“拉描述”重请求之间的最小间隔（秒）
        #   max_uploads_per_cycle            —— 每轮最多处理/投稿多少个视频（0 表示不限），
        #                                        用于抑制停机恢复 / 首轮时的上传突发
        playlist_items = config.get('playlist_items', 10)
        desc_interval = config.get('description_fetch_interval_seconds', 0)
        max_uploads = config.get('max_uploads_per_cycle', 0)
        uploads_this_cycle = 0

        for channel in config['channels']:
            # 本轮已达上限：后续频道一律不再扫描，避免无谓的列表 / 描述请求。
            if max_uploads and uploads_this_cycle >= max_uploads:
                print(f"⏸️ 本轮处理已达上限 ({max_uploads})，跳过剩余频道，等待下一轮")
                break
            fetch_url = channel['url']
            print(f"\n🔍 扫描频道: {channel['name']} ({fetch_url})")
            videos = get_video_list(fetch_url, playlist_items)
            print(f"📊 发现 {len(videos)} 个视频")

            for entry in videos:
                # 本轮已达上限：立刻停止遍历，剩余视频（含还没拉描述的）留到下一轮。
                # 关键：把上限检查提到“拉描述”之前，避免已经不处理了还去打 YouTube 描述
                # 接口——那是整条流程里最容易触发风控、且每个都要十几秒的重请求。
                if max_uploads and uploads_this_cycle >= max_uploads:
                    print(f"⏸️ 本轮处理已达上限 ({max_uploads})，停止扫描剩余视频，留到下一轮")
                    break
                if entry['id'] not in history:
                    keyword = channel.get('keyword', '').lower()
                    excludes = [e.lower() for e in channel.get('exclude', []) if e]
                    title = entry.get('title') or ""
                    title_lower = title.lower()

                    hit_exclude = next((ex for ex in excludes if ex in title_lower), None)
                    if hit_exclude:
                        print(f"⏭️ 跳过 (标题命中排除词 '{hit_exclude}'): {title}")
                        history.add(entry['id'])
                        save_history(history)
                        continue

                    if not keyword or keyword in title_lower:
                        is_match = True
                    else:
                        # title 没命中再去拿描述（每个 ~10s，所以放后面）
                        print(f"🔎 标题未命中，拉取描述: {title}")
                        description = fetch_video_description(entry['url'], desc_interval)
                        description_lower = description.lower()
                        hit_exclude = next((ex for ex in excludes if ex in description_lower), None)
                        if hit_exclude:
                            print(f"⏭️ 跳过 (描述命中排除词 '{hit_exclude}'): {title}")
                            is_match = False
                        else:
                            is_match = keyword in description_lower

                    if is_match:
                        print(f"should process: {entry['title']}")
                        # 计入本轮配额（无论成功失败，重下载/上传都已发生）
                        uploads_this_cycle += 1
                        if process_and_upload(entry['id'], entry['url'], entry['title'], channel, config.get('processing', {})):
                            history.add(entry['id'])
                            save_history(history)
                    else:
                        print(f"⏭️ 跳过 (关键字不匹配): {entry['title']}")
                        history.add(entry['id'])
                        save_history(history)
        
        interval = config.get('check_interval_seconds', 300)
        print(f"\n😴 等待 {interval}s 后重试...")
        time.sleep(interval)

if __name__ == "__main__":
    main()
