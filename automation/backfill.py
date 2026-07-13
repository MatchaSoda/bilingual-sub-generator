#!/usr/bin/env python3
"""单个视频补投脚本 —— 给一个 YouTube URL，对这一条视频做和 automation 完全相同的事：
entry_cli 生成双语视频（下载 → 转写 → 翻译 → 压制）→ biliup 投稿到 B 站，直到投稿成功。

直接复用 mover.py 的 load_config / process_and_upload，因此处理参数（segment/whisper/
gemini/furigana/标题翻译…）、B 站分区、标签、投稿流程都与自动搬运一致，不会出现两套逻辑漂移。

用法:
    ../venv/bin/python3 backfill.py <youtube_url>
    ../venv/bin/python3 backfill.py <url> --channel 0          # 用第 N 个频道的分区/标签（默认 0）
    ../venv/bin/python3 backfill.py <url> --tid 21 --tags a,b  # 手动覆盖分区/标签
    ../venv/bin/python3 backfill.py <url> --retries 5 --retry-delay 60

说明:
  * 投稿成功后会把视频 id 写入 automation/history.json（用 mover.save_history，带文件锁 +
    磁盘合并 + 原子替换），因此即便常驻的 bili-mover 服务同时在写，也不会互相覆盖。
    用 --no-history 可跳过写入。
"""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import mover


def fetch_id_and_title(video_url):
    """拿单个视频的 id 和标题（供文件名 / 日志用）。复用 mover 的 cookies 临时副本逻辑。"""
    cookies_tmp = mover.make_cookies_copy()
    try:
        cmd = [
            str(mover.YTDLP_PATH), "--skip-download", "--ignore-no-formats-error",
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


def main():
    parser = argparse.ArgumentParser(description="单个 YouTube 视频补投到 B 站（复用 automation 流程）")
    parser.add_argument("video_url", help="YouTube 视频 URL")
    parser.add_argument("--channel", type=int, default=0,
                        help="使用 config.json 里第几个频道的分区/标签（默认 0）")
    parser.add_argument("--tid", type=int, default=None, help="覆盖 B 站分区 tid")
    parser.add_argument("--tags", default=None, help="覆盖 B 站标签（逗号分隔）")
    parser.add_argument("--retries", type=int, default=5, help="投稿失败最多重试次数（默认 5）")
    parser.add_argument("--retry-delay", type=int, default=60, help="每次重试前等待秒数（默认 60）")
    parser.add_argument("--no-history", action="store_true", help="投稿成功后不写入 history.json")
    args = parser.parse_args()

    config = mover.load_config()
    channels = config.get("channels", [])

    # 取一个频道配置作为分区/标签来源；没有频道时给个空 dict，process_and_upload 会用内置默认值。
    if channels:
        idx = args.channel if 0 <= args.channel < len(channels) else 0
        channel_cfg = dict(channels[idx])
        print(f"📺 使用频道配置: [{idx}] {channel_cfg.get('name', '?')}")
    else:
        channel_cfg = {}
        print("⚠️ config.json 没有 channels，分区/标签使用内置默认值")

    if args.tid is not None:
        channel_cfg["bili_tid"] = args.tid
    if args.tags is not None:
        channel_cfg["tags"] = args.tags

    processing = config.get("processing", {})

    video_id, video_title = fetch_id_and_title(args.video_url)
    if not video_title:
        print("❌ 拿不到标题，终止。")
        sys.exit(1)
    print(f"🎯 目标视频: [{video_id}] {video_title}")

    attempt = 0
    while True:
        attempt += 1
        print(f"\n===== 第 {attempt}/{args.retries + 1} 次尝试 =====")
        ok = mover.process_and_upload(
            video_id or "manual",
            args.video_url,
            video_title,
            channel_cfg,
            processing,
        )
        if ok:
            print(f"\n✅ 投稿成功: {video_title}")
            if video_id and not args.no_history:
                try:
                    hist = mover.load_history()
                    hist.add(video_id)
                    mover.save_history(hist)  # 带锁 + 合并，服务在写也不会互相覆盖
                    print(f"📝 已写入 history: {video_id}")
                except Exception as e:
                    print(f"⚠️ 写 history 失败（不影响投稿结果）: {e}")
            sys.exit(0)
        if attempt > args.retries:
            print(f"\n❌ 已重试 {args.retries} 次仍失败，放弃: {video_title}")
            sys.exit(1)
        print(f"⏳ {args.retry_delay}s 后重试…")
        time.sleep(args.retry_delay)


if __name__ == "__main__":
    main()
