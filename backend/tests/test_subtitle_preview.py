"""视觉实验室的预览图（services/subtitle_preview.py）。"""
import os
import shutil
import struct
import sys
import unittest
from unittest import mock

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from services import subtitle_preview
from services.subtitle_preview import PreviewError, render_preview


class TextTests(unittest.TestCase):
    def test_text_cannot_break_the_dialogue_line_or_add_tags(self):
        self.assertEqual(subtitle_preview._clean_text("a{\\pos(0,0)}b\nc", "x"), "apos(0,0)b c")
        self.assertEqual(subtitle_preview._clean_text(None, "默认"), "默认")
        self.assertEqual(len(subtitle_preview._clean_text("あ" * 500, "")), subtitle_preview.MAX_TEXT_LENGTH)


class ValidationTests(unittest.TestCase):
    def test_bad_style_or_background_is_rejected_before_rendering(self):
        with self.assertRaises(PreviewError) as raised:
            render_preview({"font_main": "Arial", "color_sub": "yellow"})
        self.assertEqual(sorted(e["path"] for e in raised.exception.errors), ["style.color_sub", "style.font_main"])
        with self.assertRaises(PreviewError):
            render_preview({}, background="purple")

    def test_missing_font_is_an_error_not_a_silent_fallback(self):
        with mock.patch.object(subtitle_preview.subtitle_fonts, "is_installed", return_value=False):
            with self.assertRaises(PreviewError) as raised:
                render_preview({"font_main": "Klee One"})
        self.assertIn("Klee One", str(raised.exception))


def png_chunks(png):
    position, chunks = 8, {}
    while position < len(png):
        (length,) = struct.unpack(">I", png[position:position + 4])
        chunks.setdefault(png[position + 4:position + 8], png[position + 8:position + 8 + length])
        position += 12 + length
    return chunks


def pixel(png, x, y):
    import subprocess
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", "-", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         input=png, capture_output=True, check=True).stdout
    index = (y * 1920 + x) * 3
    return tuple(raw[index:index + 3])


@unittest.skipUnless(shutil.which("ffmpeg"), "rendering needs ffmpeg")
class RenderTests(unittest.TestCase):
    def test_full_hd_png(self):
        png, source = render_preview({}, "light")
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(struct.unpack(">II", png[16:24]), (1920, 1080))
        self.assertEqual(source, "light")

    def test_png_shows_colors_the_way_the_browser_plays_the_video(self):
        # 背景按 BT.709 进出 yuv420p，解回来要还是原来的颜色（swscale 不显式扩 range 时会暗 2~6 级）；
        # 要标成 sRGB：帧上带着 BT.709 标记时 PNG 会写 gAMA 1/1.961，浏览器据此把中间调提亮（126 → 137），放视频时却不会。
        # 有 sRGB 块时浏览器以它为准，同时写的 gAMA 是和 sRGB 一致的 1/2.2
        for background, color in (("dark", (10, 12, 20)), ("light", (253, 246, 227))):
            png, _ = render_preview({}, background)
            self.assertTrue(all(abs(a - b) <= 1 for a, b in zip(pixel(png, 100, 540), color)), background)
            chunks = png_chunks(png)
            self.assertIn(b"sRGB", chunks)
            if b"gAMA" in chunks:
                self.assertEqual(struct.unpack(">I", chunks[b"gAMA"])[0], 45455)

    def test_style_changes_the_picture_and_repeats_come_from_the_cache(self):
        green, _ = render_preview({"color_sub": "#00FF00"}, "dark")
        self.assertIs(render_preview({"color_sub": "#00ff00"}, "dark")[0], green)
        magenta, _ = render_preview({"color_sub": "#FF00FF"}, "dark")
        self.assertNotEqual(green, magenta)


if __name__ == "__main__":
    unittest.main()
