#!/usr/bin/env python3
"""把 B 站稿件唯一的分P换成新文件（换源）。BV 号、标题、简介、标签、封面、分区、播放、点赞、评论都保留；
分P 的 cid 会变，挂在旧 cid 上的弹幕会丢。

biliup 没有换源命令（1.1.29 只有 upload / append）。这里照它 append 的做法：取稿件 → 上传新文件 →
x/vu/web/edit 提交，只是把分P 换掉而不是追加。什么时候用、成品怎么重新生成、提交后会发生什么，见 docs/RUNBOOK.md §7。

用法（Docker 机要套进 mover 容器跑，命令见 RUNBOOK §7）:
    python3 scripts/replace_bili_video.py <BV> <新文件> --expect-filename <现在分P的 filename> --dry-run
    python3 scripts/replace_bili_video.py <BV> <新文件> --expect-filename <现在分P的 filename>
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))
from utils import automation_store as store  # noqa: E402

# 和 mover 一样：裸机是 automation/，Docker 由 AUTOMATION_STATE_DIR 指到 userdata/
STATE_DIR = Path(os.getenv("AUTOMATION_STATE_DIR") or REPO / "automation").absolute()
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/63.0.3239.108"
VIEW_URL = "https://member.bilibili.com/x/client/archive/view"
EDIT_URL = "https://member.bilibili.com/x/vu/web/edit"

# biliup 的 Studio 结构里有缺省值的字段：稿件数据里没有时，它发出去的就是这些（serde default / Option 为 None）。
# 其余字段它用 #[serde(flatten)] 原样带回，只去掉 limited_free。照抄这个形状，因为这是 append 实际在发的请求体。
STUDIO_DEFAULTS = {
    "copyright": 1, "source": "", "cover": "", "desc_format_id": 0, "desc": "", "desc_v2": None,
    "dynamic": "", "subtitle": {"open": 0, "lan": ""}, "tag": "", "videos": [], "dtime": None,
    "open_subtitle": False, "interactive": 0, "mission_id": None, "dolby": 0, "lossless_music": 0,
    "no_reprint": 0, "is_only_self": None, "charging_pay": 0, "aid": None,
    "up_selection_reply": False, "up_close_reply": False, "up_close_danmu": False,
}


def build_studio(archive, part):
    """编辑请求体：稿件原有字段 + biliup 的缺省值，分P 换成 part。"""
    studio = {key: value for key, value in archive.items() if key != "limited_free"}
    for key, value in STUDIO_DEFAULTS.items():
        studio.setdefault(key, value)
    studio["videos"] = [part]
    return studio


def check_parts(videos, expected_filename):
    """只换单P稿件，而且现在的分P必须是预期的那个：防止换错稿件，也防止重跑时把刚换好的再换一遍。
    有问题返回原因，没问题返回 None。"""
    if len(videos) != 1:
        return f"稿件有 {len(videos)} 个分P，这个脚本只处理单P稿件"
    if videos[0]["filename"] != expected_filename:
        return f"现在的分P 是 {videos[0]['filename']}，不是 --expect-filename 给的 {expected_filename}"
    return None


class CreativeCenter:
    """创作中心的取稿件、改稿件、上传。cookies.json 只读：biliup 的 BiliBili.login() 会改写它，所以不走那个入口。"""

    def __init__(self, cookies_path):
        self.login = json.loads(Path(cookies_path).read_text(encoding="utf-8"))
        self.cookies = {c["name"]: c["value"] for c in self.login["cookie_info"]["cookies"]}
        self.token = self.login["token_info"]["access_token"]
        self.session = requests.Session()
        self.session.headers.update({"user-agent": UA, "referer": "https://www.bilibili.com/"})
        requests.utils.add_dict_to_cookiejar(self.session.cookies, self.cookies)

    def view(self, bvid):
        r = self.session.get(VIEW_URL, params={"access_key": self.token, "bvid": bvid}, timeout=30).json()
        if r.get("code") != 0 or not r.get("data"):
            raise RuntimeError(f"取稿件失败: {r}")
        return r["data"]

    def edit(self, studio):
        params = {"t": int(time.time() * 1000), "csrf": self.cookies["bili_jct"]}
        return self.session.post(EDIT_URL, params=params, json=studio, timeout=60).json()

    def upload(self, path, line):
        # biliup 自带的纯 Python 上传器：只上传、不建稿件，返回 {"title", "filename", "desc"}
        from biliup.plugins.bili_webup import BiliBili
        bili = BiliBili(None)
        bili.login_by_cookies(self.login)
        return bili.upload_file(str(path), lines=line)


def local_duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def wait_probed(api, bvid, timeout, interval=30):
    """等 B 站读出新分P的时长（转码一开始就有，不等转码和审核结束），超时就返回最后一次看到的稿件数据。"""
    deadline = time.time() + timeout
    while True:
        data = api.view(bvid)
        part = data["videos"][0]
        print(f"  {time.strftime('%H:%M:%S')} 稿件{data['archive']['state_desc']}，分P 时长 {part['duration']}s"
              f"（xcode_state={part.get('xcode_state')}）", flush=True)
        if part["duration"] > 0 or part.get("fail_code") or time.time() >= deadline:
            return data
        time.sleep(interval)


def main():
    # 经 docker compose exec 跑时 stdout 不是终端，不按行刷新的话，退出时的报错（stderr）会排到前面的进度前头
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("bvid")
    parser.add_argument("video", help="新的成品文件")
    parser.add_argument("--expect-filename", required=True,
                        help="现在分P的 filename（biliup show 输出里 videos[0].filename）")
    parser.add_argument("--line", help="上传线路，缺省用 config.json 的 upload.line（RUNBOOK §5.4）")
    parser.add_argument("--wait", type=int, default=1800, help="提交后最多等几秒让 B 站读出新文件的时长，0 表示不等")
    parser.add_argument("--dry-run", action="store_true", help="只取稿件、检查分P，不上传不提交")
    args = parser.parse_args()

    video = Path(args.video)
    if not video.is_file():
        sys.exit(f"找不到新文件: {video}")
    raw, _ = store.load_config(store.Paths(STATE_DIR))
    line = args.line or store.effective_config(raw)["upload"]["line"] or "AUTO"
    api = CreativeCenter(STATE_DIR / "cookies.json")

    data = api.view(args.bvid)
    archive, videos = data["archive"], data["videos"]
    print(f"稿件 {archive['bvid']}（{archive['state_desc']}）: {archive['title']}")
    problem = check_parts(videos, args.expect_filename)
    if problem:
        sys.exit(f"❌ {problem}，不动")
    old = videos[0]
    duration = local_duration(video)
    print(f"现在的分P {old['filename']}（{old['duration']}s）→ 新文件 {video.name}（{duration:.1f}s），线路 {line}")
    if args.dry_run:
        return

    uploaded = api.upload(video, line)
    print()
    if not uploaded or not uploaded.get("filename"):
        sys.exit(f"❌ 上传失败: {uploaded}")
    new_part = {"title": old["title"], "filename": uploaded["filename"], "desc": old.get("desc") or ""}
    result = api.edit(build_studio(archive, new_part))
    if result.get("code") != 0:
        sys.exit(f"❌ 改稿件失败（新文件 {uploaded['filename']} 已上传，但没挂到稿件上）: {result}")
    print(f"✅ 已提交，新分P {uploaded['filename']}，等 B 站读出时长")
    if not args.wait:
        return

    data = wait_probed(api, args.bvid, args.wait)
    part = data["videos"][0]
    if part["filename"] != uploaded["filename"] or part["duration"] <= 0:
        sys.exit(f"⚠️ 等了 {args.wait}s B 站还没读出新文件的时长，过一会儿用 biliup show 再看")
    # bili_webup 的上传器某个分块重试 10 次都失败时会跳过它而不报错，文件缺块的话读出来的时长对不上
    if abs(part["duration"] - duration) > 2:
        sys.exit(f"❌ B 站读到 {part['duration']}s，本地 {duration:.1f}s，文件可能没传完整，重新换一次")
    print(f"✅ B 站读到的时长 {part['duration']}s 和本地一致。稿件现在「{data['archive']['state_desc']}」，"
          f"转码、审核完之后公开页面才换成新版本")


if __name__ == "__main__":
    main()
