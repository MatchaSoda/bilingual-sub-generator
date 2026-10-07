"""媒体库：把 Web 界面的成品和自动搬运的成品放在一起列出、按来源删除。

两种成品在两个目录里（见 config/settings.py），文件名都以 _bilingual.mp4 结尾，封面是同名 .jpg：
  web  —— data/downloads，Web 界面提交的任务
  auto —— 自动搬运的产出目录（裸机 automation/data，Docker userdata/data），已经投到 B 站
"""
from datetime import datetime
from pathlib import Path

VIDEO_SUFFIX = "_bilingual.mp4"


def collect_library(sources, ensure_thumbnail=None):
    """sources: {来源: (目录, 对外 URL 前缀)}。返回按修改时间从新到旧排好的条目列表。

    size / time 是给界面直接显示的字符串；size_bytes / mtime 是原始数值，前端排序和筛选用。
    """
    items = []
    for source, (directory, url_prefix) in sources.items():
        if not directory.is_dir():
            continue
        for video in directory.glob(f"*{VIDEO_SUFFIX}"):
            try:
                st = video.stat()
            except OSError:
                continue  # 列目录和 stat 之间被删了（清理、别的请求）
            if ensure_thumbnail:
                ensure_thumbnail(video)
            items.append({
                "name": video.name,
                "source": source,
                "path": f"{url_prefix}/{video.name}",
                "thumbnail": f"{url_prefix}/{video.with_suffix('.jpg').name}",
                "size": f"{st.st_size / (1024 * 1024):.2f} MB",
                "size_bytes": st.st_size,
                "time": datetime.fromtimestamp(st.st_mtime).strftime('%Y-%m-%d %H:%M'),
                "mtime": st.st_mtime,
            })
    items.sort(key=lambda item: item["mtime"], reverse=True)
    return items


def resolve_library_video(directory, name):
    """把 URL 里的文件名解析成目录里的成品路径；不是本目录下的 *_bilingual.mp4 就返回 None。"""
    if not name.endswith(VIDEO_SUFFIX) or "/" in name or "\\" in name or name.startswith("."):
        return None
    candidate = directory / name
    if candidate.parent != directory or not candidate.is_file():
        return None
    return candidate


def delete_library_video(video):
    """删成品和它的封面；Web 成品可能还有同名 .ass。返回删掉的文件数。"""
    removed = 0
    for path in (video, video.with_suffix(".jpg"), video.with_suffix(".ass")):
        if path.is_file():
            path.unlink()
            removed += 1
    return removed
