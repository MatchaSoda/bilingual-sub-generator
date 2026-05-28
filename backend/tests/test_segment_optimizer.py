import unittest
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from engines.segment_optimizer import SubtitleSegmentOptimizer


def make_words(tokens, step=0.4, gaps=None):
    """Build whisper-style word dicts with contiguous timing.

    gaps: optional dict {index: extra_silence_before_this_word}.
    """
    gaps = gaps or {}
    words = []
    t = 0.0
    for i, tok in enumerate(tokens):
        t += gaps.get(i, 0.0)
        words.append({"word": tok, "start": round(t, 2), "end": round(t + step, 2)})
        t += step
    return words


class TestRuleSegmenter(unittest.TestCase):
    def setUp(self):
        self.opt = SubtitleSegmentOptimizer(maximum_characters_per_line=10)

    def test_short_segment_passes_through(self):
        seg = {"start": 0.0, "end": 1.0, "text": "短い文",
               "words": make_words(["短", "い", "文"])}
        cues = self.opt.segment([seg])
        self.assertEqual(len(cues), 1)
        self.assertEqual(cues[0]["text"], "短い文")

    def test_long_block_is_split_under_limit(self):
        tokens = ["今日", "は", "とても", "良い", "天気", "です", "ね", "本当に"]
        seg = {"start": 0.0, "end": 9.0, "text": "".join(tokens),
               "words": make_words(tokens)}
        cues = self.opt.segment([seg])
        self.assertGreater(len(cues), 1)
        for cue in cues:
            self.assertLessEqual(len(cue["text"]), 10)
        # Recombining cue text must reproduce the original transcript exactly.
        self.assertEqual("".join(c["text"] for c in cues), "".join(tokens))

    def test_sentence_final_punct_forces_block_boundary(self):
        tokens = ["はい", "。", "次", "の", "話"]
        seg = {"start": 0.0, "end": 5.0, "text": "".join(tokens),
               "words": make_words(tokens)}
        cues = self.opt.segment([seg])
        # The cue containing 。 must end with it (sentence boundary respected).
        first = cues[0]["text"]
        self.assertTrue(first.endswith("。"), cues)

    def test_long_pause_forces_break(self):
        tokens = ["前半", "の", "話", "後半", "の", "話"]
        # 1.2s silence before the 4th token (index 3) -> hard pause break.
        seg = {"start": 0.0, "end": 6.0, "text": "".join(tokens),
               "words": make_words(tokens, gaps={3: 1.2})}
        cues = self.opt.segment([seg])
        self.assertGreaterEqual(len(cues), 2)
        # The break should land at the pause: a cue ends right before 後半.
        joined_ends = ["前半の話" in c["text"] or c["text"] == "前半の話" for c in cues]
        self.assertTrue(any(joined_ends), cues)

    def test_balanced_no_orphan_tail(self):
        # 12 single-char tokens, limit 10 -> greedy would give 10 + 2 (orphan).
        tokens = list("あいうえおかきくけこさし")
        seg = {"start": 0.0, "end": 12.0, "text": "".join(tokens),
               "words": make_words(tokens)}
        cues = self.opt.segment([seg])
        lengths = [len(c["text"]) for c in cues]
        # DP should balance (e.g. 6/6) rather than leave a length-2 tail.
        self.assertTrue(min(lengths) >= 3, lengths)


if __name__ == "__main__":
    unittest.main()
