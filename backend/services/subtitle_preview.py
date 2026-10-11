"""视觉实验室的预览：用压制成片的那套代码渲染一帧，所见即成片。

- ASS 由流水线同一个生成器生成（engines/subtitle_generator.py），字号换算、颜色补偿、振假名排版都一样；
- 用压制时同一个 ffmpeg 滤镜（engines/video_processor.subtitles_filter）画到 1920x1080 的 yuv420p 画面上，
  字体是同一个镜像里的同一批文件；
- 再像播放器那样按 BT.709（成片的色彩标记）转回 RGB 输出 PNG：和 Chromium 放成片时解出来的颜色一致（10-11 用色块在
  浏览器里逐个比过，±1），PNG 标成 sRGB，浏览器不会再调亮度。

和成片的差别只剩 x264 的有损压缩。浏览器端不再自己渲染（以前的 libass-wasm 预览用的是另一个 libass 版本、另一套字体）。
scripts/check_subtitle_preview.py 核对这一点。
"""
import hashlib
import json
import subprocess
import threading
import tempfile
from collections import OrderedDict
from pathlib import Path

from config.settings import DOWNLOADS_DIR
from engines.subtitle_generator import AdvancedSubtitleScriptGenerator
from engines.video_processor import FFmpegVideoProcessor, subtitles_filter
from utils import automation_store as store
from utils import subtitle_fonts

WIDTH, HEIGHT = 1920, 1080
BACKGROUNDS = {"dark": "0x0a0c14", "light": "0xfdf6e3"}  # 视觉实验室原来的两种底色
SAMPLE_TEXT = {"main": "私の名前は抹茶です", "sub": "我的名字是抹茶"}
MAX_TEXT_LENGTH = 60
VIDEO_SUFFIXES = (".mp4", ".webm", ".mkv")

_render_lock = threading.Lock()   # 一次只渲染一帧：拖滑块时请求很密，排队比并发起一堆 ffmpeg 好
_cache = OrderedDict()
_CACHE_SIZE = 48
_annotator = None
_frame = {"key": None, "yuv": None, "matrix": None, "source": None}


class PreviewError(Exception):
    def __init__(self, message, errors=None, status=422):
        super().__init__(message)
        self.errors = errors or []
        self.status = status


def display_filter(matrix):
    """yuv420p 画面 → 浏览器放成片时显示的 RGB（ffmpeg 滤镜串）。"""
    return ",".join([
        # limited range 要显式扩成 full range：swscale 默认不扩，灰 128 会解成 126
        f"scale=in_color_matrix={matrix}:in_range=tv:out_range=pc:flags=accurate_rnd+full_chroma_int",
        "format=rgb24",
        # 标成 sRGB。否则 PNG 编码器按帧上的 BT.709 标记写 gAMA，浏览器据此再调一遍亮度（灰 126 显示成 137），
        # 而浏览器放视频时不做这一步
        "setparams=color_primaries=bt709:color_trc=iec61966-2-1:colorspace=gbr:range=pc",
    ])


def _clean_text(text, default):
    """预览文字进 ASS 的 Dialogue 行：去掉换行和 { } \\（会被当成换行 / 特效标签），限长。"""
    if text is None:
        return default
    text = "".join(" " if ch in "\r\n\t" else ch for ch in text if ch not in "{}\\")
    return text.strip()[:MAX_TEXT_LENGTH]


def _furigana_annotator():
    global _annotator
    if _annotator is None:
        from utils.furigana_generator import JapaneseFuriganaGenerator
        _annotator = JapaneseFuriganaGenerator()
    return _annotator


def _latest_source_frame():
    """最近下载的源视频的一帧（1/3 处），原样留成 yuv420p，不经过 RGB 来回转。没有可用的视频返回 None。"""
    candidates = sorted((p for p in DOWNLOADS_DIR.iterdir()
                         if p.suffix in VIDEO_SUFFIXES and not p.stem.endswith("_bilingual")),
                        key=lambda p: p.stat().st_mtime, reverse=True)
    for path in candidates[:6]:
        key = (str(path), path.stat().st_mtime)
        if _frame["key"] == key:
            return _frame
        try:
            probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                    "format=duration", "-of", "json", str(path)],
                                   capture_output=True, text=True, timeout=20)
            duration = float(json.loads(probe.stdout)["format"]["duration"])
            frame = subprocess.run(
                ["ffmpeg", "-v", "error", "-nostdin", "-ss", f"{duration / 3:.2f}", "-i", str(path), "-frames:v", "1",
                 "-vf", f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,"
                        f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
                 "-f", "rawvideo", "-"],
                capture_output=True, timeout=60)
        except (OSError, ValueError, KeyError, subprocess.SubprocessError):
            continue
        if frame.returncode == 0 and len(frame.stdout) == WIDTH * HEIGHT * 3 // 2:
            matrix = FFmpegVideoProcessor().extract_color_matrix(path)
            _frame.update(key=key, yuv=frame.stdout, matrix=matrix, source=path.name)
            return _frame
    return None


def render_preview(style=None, background="dark", furigana=True, main_text=None, sub_text=None):
    """返回 (PNG 字节, 用的背景说明)。style 和 config.json 的 processing.style 同一个格式，没写的项用缺省值。"""
    errors = []
    normalized = store.normalize_style(style or {}, errors, path="style")
    if errors:
        raise PreviewError("样式里有不合法的值", errors)
    full_style = {**store.STYLE_DEFAULTS, **normalized}
    for key in store.STYLE_FONT_FIELDS:
        if subtitle_fonts.is_installed(full_style[key]) is False:
            raise PreviewError(f"字体没装：{full_style[key]}（镜像里缺这个字体包，压制时也会被换成别的字体）")
    if background not in BACKGROUNDS and background != "video":
        raise PreviewError(f"不认识的背景：{background}")
    main_text = _clean_text(main_text, SAMPLE_TEXT["main"])
    sub_text = _clean_text(sub_text, SAMPLE_TEXT["sub"])

    with _render_lock:
        frame = None
        if background == "video":
            frame = _latest_source_frame()
            if frame is None:
                raise PreviewError("还没有下载过的源视频，先跑一个任务", status=404)
        cache_key = hashlib.sha1(json.dumps(
            [full_style, background, frame and frame["key"], bool(furigana), main_text, sub_text],
            sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if cache_key in _cache:
            _cache.move_to_end(cache_key)
            return _cache[cache_key]
        png = _render(full_style, background, frame, bool(furigana), main_text, sub_text)
        result = (png, frame["source"] if frame else background)
        _cache[cache_key] = result
        if len(_cache) > _CACHE_SIZE:
            _cache.popitem(last=False)
        return result


def _render(full_style, background, frame, furigana, main_text, sub_text):
    # 纯色背景当作 BT.709 的高清片（YouTube 源都是）；视频背景按那个视频自己的标记
    matrix = frame["matrix"] if frame else "bt709"
    with tempfile.TemporaryDirectory(prefix="subtitle-preview-") as tmp:
        ass_path = Path(tmp) / "preview.ass"
        AdvancedSubtitleScriptGenerator().generate_ass_file(
            [{"start": 0, "end": 10, "text": main_text, "translated_text": sub_text}], str(ass_path),
            video_title="Preview", is_furigana_enabled=furigana, style_settings=full_style,
            video_width=WIDTH, video_height=HEIGHT,
            furigana_annotator=_furigana_annotator() if furigana else None, video_matrix=matrix)
        if frame:
            frame_path = Path(tmp) / "frame.yuv"
            frame_path.write_bytes(frame["yuv"])
            source = ["-f", "rawvideo", "-pix_fmt", "yuv420p", "-s", f"{WIDTH}x{HEIGHT}", "-i", str(frame_path)]
        else:
            # 底色先按 BT.709 换成 yuv420p，播放器解回来就是这个颜色
            source = ["-f", "lavfi", "-i", f"color=c={BACKGROUNDS[background]}:s={WIDTH}x{HEIGHT}:d=1,format=rgb24,"
                                           f"scale=out_color_matrix={matrix}:out_range=tv:flags=accurate_rnd,format=yuv420p"]
        command = ["ffmpeg", "-v", "error", "-nostdin", *source,
                   "-vf", f"{subtitles_filter(ass_path)},{display_filter(matrix)}",
                   "-frames:v", "1", "-f", "image2pipe", "-c:v", "png", "-compression_level", "1", "-"]
        result = subprocess.run(command, capture_output=True, timeout=60)
    if result.returncode != 0 or not result.stdout:
        raise PreviewError(f"渲染失败：{result.stderr.decode(errors='replace')[-300:]}", status=500)
    return result.stdout
