import unittest

from utils.filenames import TITLE_MAX_BYTES, truncate_utf8


class TruncateUtf8Test(unittest.TestCase):
    def test_short_name_unchanged(self):
        self.assertEqual(truncate_utf8("短い標題"), "短い標題")

    def test_long_japanese_title_fits_with_longest_suffix(self):
        # 2026-10-03 线上实际卡住的标题（263 字节含后缀）
        title = ("【食レポ女王】横浜駅グルメ地下街を探検！超希少な“白カカオ”や”うま辛担々麵”が登場！⧸"
                 "東京駅グルメ地下街には、父の味を守る旭川ラーメンや、アメリカ発の食文化体験が！")
        trimmed = truncate_utf8(title)
        self.assertLessEqual(len(trimmed.encode("utf-8")), TITLE_MAX_BYTES)
        self.assertLessEqual(len((trimmed + ".translated.json").encode("utf-8")), 255)
        self.assertTrue(title.startswith(trimmed))

    def test_never_splits_a_multibyte_character(self):
        # 每字 3 字节，7 字节的预算只能放下 2 个字
        self.assertEqual(truncate_utf8("あいうえお", 7), "あい")


if __name__ == "__main__":
    unittest.main()
