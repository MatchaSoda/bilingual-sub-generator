#!/usr/bin/env python3
"""核对视觉实验室的预览图和压出来的成片是不是一样（RUNBOOK §6）。要在镜像里跑：

    docker compose run --rm -T setup bash -c 'cd /app && venv/bin/python3 scripts/check_subtitle_preview.py'
    ... check_subtitle_preview.py --video     # 再拿最近下载的源视频的一帧当背景比一次

每组样式：
1. 用预览服务（backend/services/subtitle_preview.py）出图；
2. 照流水线的做法真的压一段视频：样式经 entry_cli 的参数解析，同一个 ASS 生成器（按源视频的色彩标记补偿颜色），
   同一个 FFmpegVideoProcessor.hardcode_subtitles_into_video（libx264 默认参数）；另压一份无损的（-qp 0）；
3. 三项比较：
   - 渲染：无损成片用预览同一个解码滤镜解出来，必须和预览一个像素都不差（字幕渲染这一段完全相同）；
   - 解码：按 BT.709 公式直接从无损成片的 YUV 算颜色（浏览器放视频就是这么解的），平坦区域和预览最多差 2
     （抓预览解码出错，比如 limited range 没扩开）；
   - 有损成片（生产参数）：只差 x264 的压缩误差，报 PSNR。
任何一项不过退出码为 1。
"""
import argparse
import math
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from engines.subtitle_generator import YUV_MATRICES, AdvancedSubtitleScriptGenerator  # noqa: E402
from engines.video_processor import FFmpegVideoProcessor, subtitles_filter  # noqa: E402
from entry_cli import build_argument_parser  # noqa: E402
from services import subtitle_preview  # noqa: E402
from utils import automation_store as store  # noqa: E402

W, H = subtitle_preview.WIDTH, subtitle_preview.HEIGHT

CASES = [
    ("默认样式", {}),
    ("BIZ UDゴシック + 霞鹜文楷，浅黄字深蓝边", {
        "font_main": "BIZ UDGothic", "font_sub": "LXGW WenKai", "color_main": "#FFE16B",
        "outline_color_main": "#1F3A93", "color_sub": "#9CDCFE", "outline_color_sub": "#000000"}),
    ("クレー One 粗体 + 思源宋体，粉字白边，半透明", {
        "font_main": "Klee One", "font_sub": "Noto Serif CJK SC", "color_main": "#FFB6C8",
        "outline_color_main": "#FFFFFF", "color_sub": "#B6F2C1", "font_alpha": 80, "font_weight_sub": 700}),
    ("モトヤLマルベリ + 思源黑体，大字号", {
        "font_main": "MotoyaLMaru", "font_size_main": 110, "font_size_sub": 90, "outline_main": 5}),
]


def run(command):
    result = subprocess.run(command, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"{command[0]} failed: {result.stderr.decode(errors='replace')[-400:]}")
    return result.stdout


def rgb_of_png(png_bytes, tmp):
    path = Path(tmp) / "preview.png"
    path.write_bytes(png_bytes)
    raw = run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"])
    return np.frombuffer(raw, np.uint8).reshape(H, W, 3).astype(np.int16)


def rgb_of_first_frame(video, matrix):
    """和预览同一个解码滤镜。"""
    raw = run(["ffmpeg", "-v", "error", "-i", str(video), "-frames:v", "1",
               "-vf", subtitle_preview.display_filter(matrix), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"])
    return np.frombuffer(raw, np.uint8).reshape(H, W, 3).astype(np.int16)


def exact_rgb_of_first_frame(video, matrix):
    """按公式从 YUV 算 RGB（色度就近取样），再挑亮度 3x3、色度 5x5（swscale 的色度插值会用到两格外）都不变的平坦像素，
    避开各家色度插值方式不同带来的边缘差别。"""
    raw = np.frombuffer(run(["ffmpeg", "-v", "error", "-i", str(video), "-frames:v", "1",
                             "-f", "rawvideo", "-pix_fmt", "yuv420p", "-"]), np.uint8)
    y = raw[:W * H].reshape(H, W).astype(np.float64)
    u = raw[W * H:W * H * 5 // 4].reshape(H // 2, W // 2).astype(np.float64)
    v = raw[W * H * 5 // 4:].reshape(H // 2, W // 2).astype(np.float64)
    flat_chroma = np.ones(u.shape, bool)
    flat_luma = np.ones(y.shape, bool)
    for dy in range(-2, 3):
        for dx in range(-2, 3):
            flat_chroma &= (np.roll(u, (dy, dx), (0, 1)) == u) & (np.roll(v, (dy, dx), (0, 1)) == v)
            if abs(dy) <= 1 and abs(dx) <= 1:
                flat_luma &= np.roll(y, (dy, dx), (0, 1)) == y
    up = lambda plane: plane.repeat(2, 0).repeat(2, 1)  # noqa: E731
    kr, kb = YUV_MATRICES[matrix]
    luma, cb, cr = (y - 16) / 219, (up(u) - 128) / 224, (up(v) - 128) / 224
    red, blue = luma + 2 * (1 - kr) * cr, luma + 2 * (1 - kb) * cb
    green = (luma - kr * red - kb * blue) / (1 - kr - kb)
    rgb = np.clip(np.stack([red, green, blue], axis=2) * 255, 0, 255)
    return rgb, flat_luma & up(flat_chroma)


def make_source(tmp, background):
    """和预览同一张背景的 2 秒无损源视频，打上 BT.709 标记（YouTube 源都是这样）。"""
    source = Path(tmp) / "source.mp4"
    tags = ["-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709", "-color_range", "tv"]
    if background == "video":
        frame = subtitle_preview._frame
        (Path(tmp) / "frame.yuv").write_bytes(frame["yuv"])
        inputs = ["-f", "rawvideo", "-pix_fmt", "yuv420p", "-s", f"{W}x{H}", "-r", "25", "-i", str(Path(tmp) / "frame.yuv"),
                  "-vf", "tpad=stop_mode=clone:stop_duration=2"]
        if frame["matrix"] != "bt709":
            tags = []
    else:
        inputs = ["-f", "lavfi", "-i", f"color=c={subtitle_preview.BACKGROUNDS[background]}:s={W}x{H}:d=2:r=25,"
                                       f"format=rgb24,scale=out_color_matrix=bt709:out_range=tv:flags=accurate_rnd,"
                                       f"format=yuv420p"]
    run(["ffmpeg", "-v", "error", "-y", *inputs, "-c:v", "libx264", "-qp", "0", "-pix_fmt", "yuv420p", *tags, str(source)])
    return source


def encode_like_the_pipeline(tmp, source, style):
    """样式 → entry_cli 参数（mover 的写法）→ 生成 ASS → 压制。返回 (有损成片, 无损成片, 矩阵)。"""
    flags = []
    for key, value in store.normalize_style(style).items():
        flags += [f"--{key.replace('_', '-')}", str(value)]
    cli_style = vars(build_argument_parser().parse_args(["https://example.invalid", *flags]))
    processor = FFmpegVideoProcessor()
    matrix = processor.extract_color_matrix(source)
    ass = Path(tmp) / "video.ass"
    AdvancedSubtitleScriptGenerator().generate_ass_file(
        [{"start": 0, "end": 10, "text": subtitle_preview.SAMPLE_TEXT["main"],
          "translated_text": subtitle_preview.SAMPLE_TEXT["sub"]}],
        str(ass), video_title="check", is_furigana_enabled=True, style_settings=cli_style,
        video_width=W, video_height=H, video_matrix=matrix)
    lossy = Path(tmp) / "lossy.mp4"
    processor.hardcode_subtitles_into_video(str(source), str(ass), str(lossy))
    lossless = Path(tmp) / "lossless.mp4"
    run(["ffmpeg", "-v", "error", "-y", "-i", str(source), "-vf", subtitles_filter(ass),
         "-c:v", "libx264", "-qp", "0", str(lossless)])
    return lossy, lossless, matrix


def compare(a, b):
    diff = np.abs(a - b)
    mse = float(np.mean(diff.astype(np.float64) ** 2))
    psnr = math.inf if mse == 0 else 10 * math.log10(255 ** 2 / mse)
    return int(diff.max()), float(diff.mean()), float(np.mean(diff.max(axis=2) > 8) * 100), psnr


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--video", action="store_true", help="also compare on a frame of the latest downloaded video")
    args = parser.parse_args()
    backgrounds = ["dark", "light"] + (["video"] if args.video else [])
    ok = True
    for background in backgrounds:
        for name, style in CASES:
            with tempfile.TemporaryDirectory(prefix="check-preview-") as tmp:
                png, source_name = subtitle_preview.render_preview(style, background)
                preview = rgb_of_png(png, tmp)
                source = make_source(tmp, background)
                lossy, lossless, matrix = encode_like_the_pipeline(tmp, source, style)
                render = compare(preview, rgb_of_first_frame(lossless, matrix))
                exact, flat = exact_rgb_of_first_frame(lossless, matrix)
                decode = float(np.abs(preview - exact)[flat].max())
                lossy_diff = compare(preview, rgb_of_first_frame(lossy, matrix))
            passed = render[0] == 0 and decode <= 2
            ok &= passed
            print(f"{'✓' if passed else '✗'} [{source_name[:24]}] {name}")
            print(f"    渲染（无损成片 vs 预览）: 最大差 {render[0]}，平均差 {render[1]:.3f}")
            print(f"    解码（按 BT.709 公式解成片 vs 预览，平坦区域 {flat.mean() * 100:.0f}%）: 最大差 {decode:.2f}")
            print(f"    有损成片（生产参数）: 最大差 {lossy_diff[0]}，平均差 {lossy_diff[1]:.3f}，"
                  f"差 >8 的像素 {lossy_diff[2]:.3f}%，PSNR {lossy_diff[3]:.1f} dB")
    print("✅ 预览和成片一致" if ok else "❌ 预览和成片对不上，看上面打 ✗ 的那组")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
