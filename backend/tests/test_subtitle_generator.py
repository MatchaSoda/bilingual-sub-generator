import unittest
import sys
import os
import re

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

if __name__ == "__main__":
    unittest.main()
