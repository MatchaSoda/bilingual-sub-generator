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

    def test_pause_inside_morpheme_does_not_split_word(self):
        # Whisper sometimes injects a spurious silent gap *inside* a single word
        # (its per-kana JP timestamps are unreliable). A pause that lands mid-word
        # must NOT force a hard break — 大量 must stay whole. Requires MeCab.
        if self.opt._tagger is None:
            self.skipTest("MeCab unavailable; morpheme protection is a no-op")
        tokens = ["大", "量", "の", "ゴミ"]
        # 1.2s of (spurious) silence before 量, i.e. between 大 and 量.
        seg = {"start": 0.0, "end": 5.0, "text": "".join(tokens),
               "words": make_words(tokens, gaps={1: 1.2})}
        cues = self.opt.segment([seg])
        self.assertTrue(any("大量" in c["text"] for c in cues),
                        f"大量 was split mid-word: {cues}")

    def test_whisper_segment_boundary_is_respected(self):
        # Two adjacent whisper segments with no pause and no punctuation between
        # them. Each is within the length limit. The optimizer must keep them as
        # separate cues instead of concatenating and reflowing to a fixed width
        # (which used to split phrases mid-word, e.g. 今すぐ|できる). Requires the
        # segment boundary to be a morpheme boundary, which "今すぐできる"|"備えに…"
        # is, so the test holds both with and without MeCab.
        words_a = make_words(["今", "すぐ", "できる"])
        words_b = make_words(["備え", "について"])
        offset = words_a[-1]["end"]
        words_b = [{"word": w["word"], "start": round(w["start"] + offset, 2),
                    "end": round(w["end"] + offset, 2)} for w in words_b]
        seg_a = {"start": words_a[0]["start"], "end": words_a[-1]["end"],
                 "text": "今すぐできる", "words": words_a}
        seg_b = {"start": words_b[0]["start"], "end": words_b[-1]["end"],
                 "text": "備えについて", "words": words_b}
        cues = self.opt.segment([seg_a, seg_b])
        self.assertEqual([c["text"] for c in cues], ["今すぐできる", "備えについて"], cues)

    def test_pause_at_word_boundary_still_breaks(self):
        # A pause that *does* fall on a real morpheme boundary must still break,
        # so the morpheme gate doesn't suppress legitimate sentence breaks.
        tokens = ["ゴミ", "数え", "切れ", "ない"]
        # 1.2s silence between ゴミ (noun) and 数え (verb) -> a real word boundary.
        seg = {"start": 0.0, "end": 5.0, "text": "".join(tokens),
               "words": make_words(tokens, gaps={1: 1.2})}
        cues = self.opt.segment([seg])
        self.assertGreaterEqual(len(cues), 2, cues)
        self.assertTrue(any(c["text"].endswith("ゴミ") for c in cues), cues)


class TestLLMFallbackSegmentation(unittest.TestCase):
    """The LLM segmenter falls back to rules when the model's response fails
    verbatim validation (common with punctuation-poor large-v3 output). That
    fallback must still honor pauses as hard breaks, not glue sentences together."""

    def test_failed_llm_response_still_breaks_at_pause(self):
        from engines.llm_segmenter import LLMSubtitleSegmenter
        seg = LLMSubtitleSegmenter(maximum_characters_per_line=10)
        # Force the validation-fail path: return text the model "altered" so
        # stripped != original -> None -> _rule_fallback_for_words.
        seg._request_markers = lambda hinted, source_language=None: hinted + "。"
        tokens = ["前半", "の", "話", "後半", "の", "話"]
        # 1.5s silence before 後半 (index 3) -> a long audible pause.
        whisper_seg = {"start": 0.0, "end": 6.0, "text": "".join(tokens),
                       "words": make_words(tokens, gaps={3: 1.5})}
        cues = seg.segment([whisper_seg])
        self.assertGreaterEqual(len(cues), 2, cues)
        # The two sentences must not be glued across the pause.
        self.assertFalse(any("前半" in c["text"] and "後半" in c["text"] for c in cues),
                         f"sentences glued across pause: {cues}")

    def test_llm_break_marker_inside_morpheme_is_rejected(self):
        # The model's own break marker can land mid-word once snapped to the
        # per-kana token grid (e.g. between 大 and 量). Such a cut must be dropped
        # so 大量 is never split. This is the LLM *success* path. Requires MeCab.
        from engines.llm_segmenter import LLMSubtitleSegmenter, BREAK_MARKER
        seg = LLMSubtitleSegmenter(maximum_characters_per_line=10)
        if seg.rule_fallback._tagger is None:
            self.skipTest("MeCab unavailable; morpheme gate is a no-op")
        # Model returns a valid (verbatim) response but inserts a break inside 大量.
        seg._request_markers = (
            lambda hinted, source_language=None: hinted.replace("大量", "大" + BREAK_MARKER + "量", 1)
        )
        tokens = ["大", "量", "の", "ゴミ"]
        whisper_seg = {"start": 0.0, "end": 4.0, "text": "".join(tokens),
                       "words": make_words(tokens)}
        cues = seg.segment([whisper_seg])
        self.assertTrue(any("大量" in c["text"] for c in cues),
                        f"大量 was split by an LLM marker: {cues}")


if __name__ == "__main__":
    unittest.main()
