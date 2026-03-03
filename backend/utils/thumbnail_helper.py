import subprocess
from pathlib import Path

def ensure_thumbnail(video_path: Path):
    """
    为视频文件生成 16:9 的缩略图。
    如果已存在则跳过。
    """
    thumbnail_path = video_path.with_suffix(".jpg")
    if not thumbnail_path.exists():
        try:
            # 从视频第 2 秒截取一帧，防止第 1 秒是纯黑
            # 使用 scale=640:-1 保持比例并调整宽度
            subprocess.run([
                "ffmpeg", "-y", "-i", str(video_path), 
                "-ss", "00:00:02", "-vframes", "1", 
                "-q:v", "2", "-vf", "scale=640:-1", 
                str(thumbnail_path)
            ], capture_output=True, check=True)
        except Exception as e:
            print(f"Failed to generate thumbnail for {video_path}: {e}")
    return thumbnail_path
