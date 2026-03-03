import unittest
import sys
import os

# Ensure the backend directory is in the path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from engines.segment_optimizer import SubtitleSegmentOptimizer

class TestSubtitleSegmentOptimizer(unittest.TestCase):
    def setUp(self):
        self.optimizer = SubtitleSegmentOptimizer(maximum_characters_per_line=10)

    def test_japanese_splitting(self):
        # 模拟日语分段：每一条词元可能是一个或几个汉字/假名
        # "日本語を勉強しています" (11 chars)
        # Limit set to 5
        self.optimizer.character_limit = 5
        segment = {
            "text": "日本語を勉強しています",
            "words": [
                {"word": "日本語", "start": 0.0, "end": 0.5},
                {"word": "を", "start": 0.5, "end": 0.7},
                {"word": "勉強", "start": 0.7, "end": 1.2},
                {"word": "して", "start": 1.2, "end": 1.5},
                {"word": "います", "start": 1.5, "end": 2.0}
            ]
        }
        # 1. "日本語を" (4 chars)
        # 2. "勉強して" (4 chars) - "勉強しています" (7 chars > 5)
        # 3. "います" (3 chars)
        result = self.optimizer.split_long_segments_using_word_timestamps([segment])
        
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["text"], "日本語を")
        self.assertEqual(result[1]["text"], "勉強して")
        self.assertEqual(result[2]["text"], "います")

if __name__ == "__main__":
    unittest.main()
