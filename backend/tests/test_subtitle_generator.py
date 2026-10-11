import unittest
import sys
import os
import re
import tempfile

# Ensure the backend directory is in the path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from engines.subtitle_generator import AdvancedSubtitleScriptGenerator
from utils.furigana_generator import JapaneseFuriganaGenerator

class TestAdvancedSubtitleScriptGenerator(unittest.TestCase):
    def setUp(self):
        self.generator = AdvancedSubtitleScriptGenerator()
        self.annotator = JapaneseFuriganaGenerator()
        self.main_font_size = 40

    def test_space_replacement_for_non_kanji(self):
        # 验证非汉字部分是否被替换为等宽空格
        # "あいう" (3 full-width chars) -> "　　　"
        # "ABC" (3 half-width chars) -> "   "
        text = "あいう ABC"
        # 模拟标注结果（无汉字时不应有 ruby 标签）
        result = self.generator._generate_furigana_line(text, self.annotator, self.main_font_size)
        
        # 预期：3个全角空格 + 1个半角空格 + 3个半角空格
        self.assertEqual(result, "　　　    ")

    def test_furigana_layout_tags(self):
        # 验证 Ruby 标签是否转换为 ASS 渲染标签
        # 比如：{#ruby#にほん|日本}
        text = "日本"
        result = self.generator._generate_furigana_line(text, self.annotator, self.main_font_size)
        
        # 应该包含透明绘图标签 (padding/margin)
        self.assertIn("\\alpha&HFF&", result)
        self.assertIn("\\p1", result)
        # 应该包含缩放标签 (scaling)
        self.assertIn("\\fscx", result)
        self.assertIn("\\fscy", result)
        # 应该包含假名内容
        self.assertTrue("にほん" in result or "にっぽん" in result)

    def test_centering_logic(self):
        # 验证居中对齐的 margin 是否生成
        # 当假名长度显著小于汉字时，必须有 padding
        text = "{#ruby#し|市}"
        # 绕过 annotator 直接测试 layout 逻辑
        result = self.generator._generate_furigana_line(text, self.annotator, self.main_font_size)
        
        # 包含透明占位符标签以实现居中
        self.assertIn("\\alpha&HFF&\\p1", result)
        
    def test_numbers_replacement(self):
        # 半角数字应替换为半角空格
        text = "2024"
        result = self.generator._generate_furigana_line(text, self.annotator, self.main_font_size)
        self.assertEqual(result, "    ")

    def test_sokuon_and_special_kana(self):
        # 促音(っ)、小写假名(ゃ)、长音(ー)以及全角感叹号都应视为全角，替换为全角空格
        # "めっちゃ、ハッピー！" -> 10个全角字符
        text = "めっちゃ、ハッピー！"
        result = self.generator._generate_furigana_line(text, self.annotator, self.main_font_size)
        self.assertEqual(result, "　" * 10)

    def test_complex_furigana_width(self):
        # 验证包含促音的假名标注宽度计算
        # "学校" (width 2.0 * 40 = 80px)
        # "がっこう" (width 4.0 * 40 * 0.45 + 3px spacing = 75px)
        # 因为 75 < 80，不应触发缩小，且应有微小的居中 margin
        text = "{#ruby#がっこう|学校}"
        result = self.generator._generate_furigana_line(text, self.annotator, self.main_font_size)
        
        # 检查是否保留了默认缩放 45
        self.assertIn("\\fscx45", result)
        # 检查是否有居中对齐的透明 padding
        self.assertIn("\\alpha&HFF&\\p1", result)

    def test_scaling_adjustment(self):
        # 验证当假名太长时，缩放比例是否自动缩小
        # "愛" (1字) 对应长假名 "いとしすぎる"
        text = "{#ruby#いとしすぎる|愛}"
        result = self.generator._generate_furigana_line(text, self.annotator, self.main_font_size)
        print(f"\nDEBUG Result: {result}")
        
        # 查找 fscx 标签的值
        match = re.search(r'\\fscx(\d+)', result)
        if match:
            scale = int(match.group(1))
            # 默认 scale 是 45，由于假名太长，这里应该比 45 小
            self.assertLess(scale, 45)


def _displayed_color(ass):
    """ffmpeg 5.1 的 subtitles 滤镜把 ASS 颜色按 BT.601（limited range）换成 8 位 YUV，播放器按 BT.709 解回 RGB。"""
    bgr = ass[4:]
    r, g, b = (int(bgr[i:i + 2], 16) / 255 for i in (4, 2, 0))
    y = 0.299 * r + 0.587 * g + 0.114 * b
    yuv = [round(16 + 219 * y), round(128 + 224 * (b - y) / 1.772), round(128 + 224 * (r - y) / 1.402)]
    y, u, v = (yuv[0] - 16) / 219, (yuv[1] - 128) / 224, (yuv[2] - 128) / 224
    r, b = y + 1.5748 * v, y + 1.8556 * u
    g = (y - 0.2126 * r - 0.0722 * b) / 0.7152
    return tuple(max(0, min(255, round(c * 255))) for c in (r, g, b))


class TestAssStyles(unittest.TestCase):
    """样式头里的字体、颜色、字号。缺省样式必须和加字体 / 颜色之前逐字一致：线上视频的样子不能变。"""

    def styles(self, style=None, video_matrix=None):
        from utils.automation_store import STYLE_DEFAULTS
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "x.ass")
            AdvancedSubtitleScriptGenerator().generate_ass_file(
                [], path, style_settings={**STYLE_DEFAULTS, **(style or {})}, video_matrix=video_matrix)
            with open(path, encoding="utf-8") as ass_file:
                lines = ass_file.read().splitlines()
        return {line.split(",")[0][len("Style: "):]: line for line in lines if line.startswith("Style: ")}

    def test_default_style_is_byte_identical_to_before(self):
        # 改动前的镜像对同样的缺省参数生成的三行（10-11 从生产镜像里取的）
        self.assertEqual(self.styles(), {
            "Main": "Style: Main,Noto Sans CJK JP,90,&H00FFFFFF,&H000000FF,&H00000000,&H90000000,1,0,0,0,100,100,0,0,1,3.0,1.5,2,10,10,7,1",
            "Sub": "Style: Sub,Noto Sans CJK SC,75,&H0000FFFF,&H000000FF,&H00000000,&H90000000,0,0,0,0,100,100,0,0,1,2.0,1.5,2,10,10,994,1",
            "Furigana": "Style: Furigana,Noto Sans CJK JP,90,&H00FFFFFF,&H000000FF,&H00000000,&H90000000,1,0,0,0,100,100,0,0,1,1.5,1,2,10,10,97,1",
        })

    def test_fonts_colors_and_size_scaling(self):
        styles = self.styles({"font_main": "BIZ UDGothic", "font_sub": "LXGW WenKai", "font_alpha": 50,
                              "color_main": "#FFE16B", "outline_color_main": "#1F3A93", "color_sub": "#FFFFFF"})
        main = styles["Main"].split(",")
        # BIZ UDゴシック的 win ratio 是 1.0，同样字号 90 字面比思源黑体大 45%，所以 ASS 里写 90 / 1.448
        self.assertEqual(main[1:6], ["BIZ UDGothic", "62.15", "&H7F6BE1FF", "&H000000FF", "&H00933A1F"])
        furigana = styles["Furigana"].split(",")
        self.assertEqual(furigana[1:3], ["BIZ UDGothic", "62.15"])   # 振假名跟着日文的字体和颜色
        self.assertEqual(furigana[3], main[3])
        self.assertEqual(furigana[-2], str(7 + 62))                  # 振假名在日文行上方一个行高
        sub = styles["Sub"].split(",")
        self.assertEqual(sub[1:4], ["LXGW WenKai", "68.21", "&H00FFFFFF"])

    def test_bt709_compensation_shows_the_chosen_color(self):
        from engines.subtitle_generator import ass_color
        for rgb in [(255, 225, 107), (128, 208, 255), (255, 182, 200), (31, 58, 147), (182, 242, 193)]:
            wanted = "#%02X%02X%02X" % rgb
            shown = _displayed_color(ass_color(wanted, "00", "bt709"))
            self.assertTrue(all(abs(a - b) <= 1 for a, b in zip(shown, rgb)), f"{wanted} shown as {shown}")
            # 不补偿时明显偏
            self.assertTrue(any(abs(a - b) > 3 for a, b in zip(_displayed_color(ass_color(wanted, "00")), rgb)))
        # 黑白不用补；BT.601 的片子不补
        self.assertEqual(ass_color("#FFFFFF", "00", "bt709"), "&H00FFFFFF")
        self.assertEqual(ass_color("#000000", "80", "bt709"), "&H80000000")
        self.assertEqual(ass_color("#FFE16B", "00", "bt601"), ass_color("#FFE16B", "00"))
        with self.assertRaises(ValueError):
            ass_color("yellow", "00")

    def test_default_yellow_barely_moves_with_compensation(self):
        # 纯黄超出范围，补偿前后显示出来都是 (255, 240±1, 0)：线上中文字幕的颜色实际上不变
        plain = self.styles()["Sub"].split(",")[3]
        compensated = self.styles(video_matrix="bt709")["Sub"].split(",")[3]
        self.assertEqual(_displayed_color(plain), (255, 240, 0))
        self.assertEqual(_displayed_color(compensated), (255, 241, 1))

if __name__ == "__main__":
    unittest.main()
