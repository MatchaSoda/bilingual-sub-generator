import unittest
import sys
import os

# Ensure the backend directory is in the path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from utils.furigana_generator import JapaneseFuriganaGenerator

class TestJapaneseFuriganaGenerator(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.generator = JapaneseFuriganaGenerator()

    def test_initialization(self):
        self.assertIsNotNone(self.generator)
        # Check if tagger is initialized (might fail if MeCab/dictionary is not installed)
        if self.generator.tagger is None:
            self.skipTest("MeCab tagger not initialized, check MeCab installation and dictionaries.")

    def test_is_kanji_character(self):
        self.assertTrue(self.generator.is_kanji_character('日'))
        self.assertTrue(self.generator.is_kanji_character('本'))
        self.assertTrue(self.generator.is_kanji_character('語'))
        self.assertFalse(self.generator.is_kanji_character('あ'))
        self.assertFalse(self.generator.is_kanji_character('ア'))
        self.assertFalse(self.generator.is_kanji_character('a'))
        self.assertFalse(self.generator.is_kanji_character('1'))
        self.assertFalse(self.generator.is_kanji_character('。'))

    def test_contains_kanji(self):
        self.assertTrue(self.generator.contains_kanji("日本語"))
        self.assertTrue(self.generator.contains_kanji("日本a"))
        self.assertFalse(self.generator.contains_kanji("ひらがな"))
        self.assertFalse(self.generator.contains_kanji("カタカナ"))
        self.assertFalse(self.generator.contains_kanji("ABC 123"))

    def test_annotate_empty_string(self):
        self.assertEqual(self.generator.annotate_text_with_furigana(""), "")
        self.assertEqual(self.generator.annotate_text_with_furigana(None), None)

    def test_annotate_no_kanji(self):
        text = "あいうえお、かきくけこ。"
        self.assertEqual(self.generator.annotate_text_with_furigana(text), text)

    def test_annotate_basic_kanji(self):
        # Basic case: Kanji only
        text = "日本"
        result = self.generator.annotate_text_with_furigana(text)
        # The expected output format is {#ruby#reading|surface}
        # Note: Depending on MeCab dictionary, 日本 might be one node or two.
        # Based on current implementation, it processes nodes.
        # If 日本 is one node: {#ruby#にっぽん|日本} or {#ruby#にほん|日本}
        # If 日本 is two nodes: {#ruby#に|日}{#ruby#ほん|本} (or にっぽん|日本)
        self.assertIn("{#ruby#", result)
        self.assertIn("日本", result)

    def test_annotate_sentence(self):
        text = "日本語を勉強しています。"
        result = self.generator.annotate_text_with_furigana(text)
        self.assertIn("{#ruby#", result)
        self.assertIn("日本", result)
        self.assertIn("勉強", result)
        # Verify it doesn't break non-kanji parts
        self.assertIn("を", result)
        self.assertIn("しています。", result)

    def test_okurigana_handling(self):
        # Test verbs with okurigana
        # Based on current MeCab (unidic-lite): "食べる" -> {#ruby#た|食}べる
        text = "食べる"
        result = self.generator.annotate_text_with_furigana(text)
        self.assertEqual(result, "{#ruby#た|食}べる")

    def test_mixed_text(self):
        # 测试在全角标点符号中的处理
        text = "学校（がっこう）に行きます。"
        result = self.generator.annotate_text_with_furigana(text)
        self.assertIn("{#ruby#がっこう|学校}", result)
        self.assertIn("（がっこう）", result)

    def test_multiline_text(self):
        text = "昨日、学校に行きました。\n今日は休みです。"
        result = self.generator.annotate_text_with_furigana(text)
        self.assertIn("\n", result)
        # Expected components (depending on MeCab nodes)
        self.assertIn("{#ruby#きのう|昨日}", result)
        self.assertIn("{#ruby#がっこう|学校}", result)
        self.assertIn("{#ruby#きょう|今日}", result)
        self.assertIn("{#ruby#やす|休}み", result)

if __name__ == "__main__":
    unittest.main()
