"""字幕可选字体表（utils/subtitle_fonts.py）。

在 Docker 镜像里（IN_DOCKER=1）还核对两件事：表里每个字体都装了；写死的 win_ratio 和字体文件里的一致
（字号换算靠它，Debian 换了字体版本、度量变了要跟着改，否则换字体时字面大小会对不上）。
"""
import io
import os
import struct
import subprocess
import sys
import unittest
from unittest import mock

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from utils import subtitle_fonts


def win_ratio_of(path, index):
    """(usWinAscent + usWinDescent) / unitsPerEm，直接读 OS/2 和 head 表（TTC 按 index 找到那个字体）。"""
    with open(path, "rb") as font_file:
        offset = 0
        if font_file.read(4) == b"ttcf":
            font_file.seek(12 + 4 * index)
            (offset,) = struct.unpack(">I", font_file.read(4))
        font_file.seek(offset + 4)
        (table_count,) = struct.unpack(">H", font_file.read(2))
        font_file.seek(offset + 12)
        tables = {}
        for _ in range(table_count):
            tag, _checksum, table_offset, _length = struct.unpack(">4sIII", font_file.read(16))
            tables[tag] = table_offset
        font_file.seek(tables[b"head"] + 18)
        (units_per_em,) = struct.unpack(">H", font_file.read(2))
        font_file.seek(tables[b"OS/2"] + 74)
        win_ascent, win_descent = struct.unpack(">HH", font_file.read(4))
    return (win_ascent + win_descent) / units_per_em


class CatalogTests(unittest.TestCase):
    def test_each_language_has_a_few_fonts_and_its_default(self):
        families = [font["family"] for font in subtitle_fonts.FONTS]
        self.assertEqual(len(families), len(set(families)))
        for lang, default in subtitle_fonts.DEFAULT_FONTS.items():
            self.assertTrue(subtitle_fonts.is_choice(default, lang))
            self.assertGreaterEqual(sum(font["lang"] == lang for font in subtitle_fonts.FONTS), 3)
        self.assertEqual({font["lang"] for font in subtitle_fonts.FONTS}, {"ja", "zh"})

    def test_language_decides_where_a_font_can_go(self):
        self.assertTrue(subtitle_fonts.is_choice("Klee One", "ja"))
        self.assertFalse(subtitle_fonts.is_choice("Klee One", "zh"))   # 日文字体，缺五百多个常用简体字
        self.assertFalse(subtitle_fonts.is_choice("Arial", "ja"))

    def test_default_fonts_keep_their_size(self):
        for family in subtitle_fonts.DEFAULT_FONTS.values():
            self.assertEqual(subtitle_fonts.size_scale(family), 1.0)
        self.assertAlmostEqual(subtitle_fonts.size_scale("BIZ UDGothic"), 1 / 1.448)
        self.assertEqual(subtitle_fonts.size_scale("Some Unknown Font"), 1.0)

    def test_family_names_fit_in_an_ass_style_line(self):
        for font in subtitle_fonts.FONTS:
            self.assertNotIn(",", font["family"])


class EntryCliFontCheckTests(unittest.TestCase):
    """字体没装时 libass 会悄悄换字体，entry_cli 要在下载之前就停下。"""

    def test_missing_font_stops_before_downloading(self):
        import entry_cli
        with mock.patch.object(entry_cli.subtitle_fonts, "is_installed", return_value=False), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as output:
            with self.assertRaises(SystemExit) as raised:
                entry_cli.check_subtitle_fonts(["Klee One"])
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("Klee One", output.getvalue())

    def test_unknown_fontconfig_only_warns(self):
        import entry_cli
        with mock.patch.object(entry_cli.subtitle_fonts, "is_installed", return_value=None), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as output:
            entry_cli.check_subtitle_fonts(["Klee One"])
        self.assertIn("cannot check", output.getvalue())


@unittest.skipUnless(os.environ.get("IN_DOCKER") == "1", "only the Docker image is guaranteed to have the fonts")
class InstalledFontsTests(unittest.TestCase):
    def test_every_font_is_installed(self):
        for font in subtitle_fonts.FONTS:
            self.assertTrue(subtitle_fonts.is_installed(font["family"]), font["family"])

    def test_win_ratio_matches_the_regular_and_bold_faces(self):
        # 字幕只用到常规和粗体（字重滑块过 500 就是粗体），对这两个字重各自选中的那个字体文件
        for font in subtitle_fonts.FONTS:
            for weight in ("regular", "bold"):
                match = subprocess.run(["fc-match", "--format", "%{family}|%{file}|%{index}",
                                        f"{font['family']}:weight={weight}"],
                                       capture_output=True, text=True, check=True).stdout
                families, path, index = match.rsplit("|", 2)
                self.assertIn(font["family"], families.split(","))
                self.assertAlmostEqual(win_ratio_of(path, int(index)), font["win_ratio"], places=3,
                                       msg=f"{font['family']} {weight}: {path}")


if __name__ == "__main__":
    unittest.main()
