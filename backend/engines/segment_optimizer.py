"""Subtitle re-segmentation (mode B: offline, rule-based).

Replaces the old greedy "cut at N characters" splitter. Goal: cues that break at
natural boundaries (sentence-final / clause punctuation, particle boundaries via
MeCab, silent pauses) with balanced lengths instead of orphan tails.

Pipeline per video:
  flatten all word tokens -> split into BLOCKS at long pauses / sentence-final
  punctuation -> within each block, score every inter-word boundary and run a DP
  that minimises (length imbalance + break-point badness) subject to a hard max
  length. Timestamps are preserved because we only ever break between whisper word
  tokens.

MeCab is optional: if it can't load, scoring falls back to punctuation + pause
only, so this module still works without a Japanese dictionary.
"""

try:
    import MeCab
except Exception:  # pragma: no cover - MeCab is optional
    MeCab = None

# Characters that end a sentence -> always a block boundary (hard break).
SENTENCE_FINAL = "。．！？!?…"
# Soft clause punctuation -> strong (but not forced) break candidate.
CLAUSE_PUNCT = "、，,；;：:）)」』】"
# A silence longer than this between two words forces a block boundary.
PAUSE_HARD_BREAK_SECONDS = 0.7

# MeCab part-of-speech tags (ipadic and unidic spellings) used for scoring.
_POS_PUNCT = {"記号", "補助記号"}
_POS_PARTICLE = {"助詞"}
_POS_AUX = {"助動詞"}
_POS_CONNECTIVE = {"接続詞"}


def flatten_words(whisper_segments):
    """Collect every word token (with timing) into one ordered list.

    A segment that lacks word-level timestamps is kept as a single token spanning
    the whole segment, so non-speech / word-less segments are never dropped.
    """
    words = []
    for segment in whisper_segments:
        segment_words = segment.get("words") or []
        emitted = False
        for word in segment_words:
            text = (word.get("word") or "").strip()
            if not text:
                continue
            words.append({"word": text, "start": word["start"], "end": word["end"]})
            emitted = True
        if not emitted:
            text = (segment.get("text") or "").strip()
            if text:
                words.append({"word": text, "start": segment["start"], "end": segment["end"]})
    return words


class SubtitleSegmentOptimizer:
    def __init__(self, maximum_characters_per_line=25):
        self.max_chars = maximum_characters_per_line
        # Aim for fairly full lines (~80% of the cap) so cues read as coherent
        # phrases rather than getting chopped into tiny fragments.
        self.target_chars = max(8, round(maximum_characters_per_line * 0.8))
        self._tagger = None
        if MeCab is not None:
            try:
                self._tagger = MeCab.Tagger()
            except Exception:
                self._tagger = None

    def segment(self, whisper_segments, source_language=None):
        """Public entry point. Returns a list of {start, end, text} cues."""
        words = flatten_words(whisper_segments)
        if not words:
            # No word-level data: fall back to the raw segments as-is.
            return [
                {"start": s["start"], "end": s["end"], "text": s["text"]}
                for s in whisper_segments
            ]

        cues = []
        for block in self._build_blocks(words):
            cues.extend(self._segment_word_block(block))
        return cues

    def _build_blocks(self, words):
        """Split the flat word stream into independent blocks.

        Boundaries are placed after sentence-final punctuation or after a long
        silent gap. Each block is segmented independently, which both bounds the
        DP size and guarantees we always break at these strong boundaries.

        A pause break is only honored when it lands on a MeCab morpheme boundary.
        Whisper's per-kana Japanese timestamps routinely inject a spurious gap
        *inside* a word (e.g. 大|量, 時|計, 粗|大); forcing a hard block break there
        would split a single word across two cues. When the pause falls mid-word we
        keep both words in the same block and let the DP (which forbids mid-morpheme
        cuts) decide. Sentence-final punctuation is always a valid boundary.
        """
        morpheme_boundaries = self.morpheme_boundary_offsets(words)

        blocks = []
        current = []
        char_offset = 0
        for index, word in enumerate(words):
            current.append(word)
            char_offset += len(word["word"])
            is_last = index == len(words) - 1
            if is_last:
                break
            ends_sentence = word["word"][-1] in SENTENCE_FINAL
            gap = words[index + 1]["start"] - word["end"]
            pause_at_word_boundary = (
                gap >= PAUSE_HARD_BREAK_SECONDS
                and (morpheme_boundaries is None or char_offset in morpheme_boundaries)
            )
            if ends_sentence or pause_at_word_boundary:
                blocks.append(current)
                current = []
        if current:
            blocks.append(current)
        return blocks

    def morpheme_boundary_offsets(self, words):
        """Character offsets (over the concatenated word text) that fall on a MeCab
        morpheme boundary, as a set. Returns None when MeCab is unavailable, in
        which case callers treat every position as a valid boundary (legacy
        behaviour). Offset 0 and the total length are always boundaries.
        """
        spans = self._mecab_morpheme_spans("".join(w["word"] for w in words))
        if not spans:
            return None
        offsets = {0}
        for _start, end, _pos in spans:
            offsets.add(end)
        return offsets

    def _segment_word_block(self, words):
        """DP segmentation of a single block of word tokens into cues."""
        count = len(words)
        if count == 0:
            return []

        lengths = [len(w["word"]) for w in words]
        # prefix[k] = char length of words[0:k]
        prefix = [0] * (count + 1)
        for i in range(count):
            prefix[i + 1] = prefix[i] + lengths[i]

        boundary_score = self._compute_boundary_scores(words, prefix)

        INF = float("inf")
        # dp[i] = min cost to segment words[i:], best_j[i] = chosen cut end.
        dp = [INF] * (count + 1)
        best_j = [count] * (count + 1)
        dp[count] = 0.0

        for i in range(count - 1, -1, -1):
            for j in range(i + 1, count + 1):
                cue_len = prefix[j] - prefix[i]
                is_single_word = j - i == 1
                if cue_len > self.max_chars and not is_single_word:
                    break  # longer j only makes it worse; cut here
                cost = self._length_badness(cue_len)
                if j < count:
                    cost += self._break_penalty(boundary_score[j])
                cost += dp[j]
                if cost < dp[i]:
                    dp[i] = cost
                    best_j[i] = j

        cues = []
        i = 0
        while i < count:
            j = best_j[i]
            cues.append({
                "start": words[i]["start"],
                "end": words[j - 1]["end"],
                "text": "".join(w["word"] for w in words[i:j]).strip(),
            })
            i = j
        return cues

    def _length_badness(self, length):
        if length > self.max_chars:
            # Only reached by an unavoidable single over-long token; keep it
            # but make it costly so the DP never prefers it otherwise.
            return (length - self.target_chars) ** 2 + 500
        return (length - self.target_chars) ** 2

    def _break_penalty(self, score):
        # A perfect boundary (>=100) is free; worse boundaries cost more, and
        # breaking inside a word (negative score) is effectively forbidden.
        return max(0.0, 100.0 - score)

    def _compute_boundary_scores(self, words, prefix):
        """Score the boundary *before* word j (j in 1..count-1)."""
        count = len(words)
        scores = [0.0] * (count + 1)

        morpheme_spans = self._mecab_morpheme_spans("".join(w["word"] for w in words))

        for j in range(1, count):
            score = 0.0
            left_word = words[j - 1]["word"]

            if left_word and left_word[-1] in SENTENCE_FINAL:
                score += 120.0
            elif left_word and left_word[-1] in CLAUSE_PUNCT:
                score += 70.0

            gap = words[j]["start"] - words[j - 1]["end"]
            if gap > 0:
                score += min(gap * 50.0, 30.0)

            score += self._mecab_boundary_score(morpheme_spans, prefix[j])
            scores[j] = score
        return scores

    def _mecab_morpheme_spans(self, text):
        """Return [(start_char, end_char, pos)] for each morpheme, or None."""
        if not self._tagger or not text:
            return None
        try:
            node = self._tagger.parseToNode(text)
        except Exception:
            return None

        spans = []
        offset = 0
        while node:
            surface = node.surface
            if surface:
                pos = node.feature.split(",")[0]
                spans.append((offset, offset + len(surface), pos))
                offset += len(surface)
            node = node.next
        return spans

    def _mecab_boundary_score(self, spans, char_offset):
        if not spans:
            return 0.0
        for start, end, pos in spans:
            if start < char_offset < end:
                return -1000.0  # breaking inside a morpheme: forbidden
            if end == char_offset:
                if pos in _POS_PUNCT:
                    return 60.0
                if pos in _POS_PARTICLE:
                    return 40.0
                if pos in _POS_AUX:
                    return 20.0
                if pos in _POS_CONNECTIVE:
                    return 30.0
                return 5.0  # clean morpheme boundary, neutral content
        return 0.0


def hard_split_overlong_cues(cues, max_chars):
    """Safety net: greedily split any cue whose text exceeds max_chars.

    Used by the LLM segmenter, which has no length guarantee. Timing is
    interpolated proportionally to character position since LLM cues carry no
    per-word timestamps.
    """
    result = []
    for cue in cues:
        text = cue["text"]
        if len(text) <= max_chars:
            result.append(cue)
            continue
        total = len(text)
        span = cue["end"] - cue["start"]
        position = 0
        while position < total:
            chunk = text[position:position + max_chars]
            chunk_start = cue["start"] + span * (position / total)
            chunk_end = cue["start"] + span * (min(position + max_chars, total) / total)
            result.append({"start": chunk_start, "end": chunk_end, "text": chunk})
            position += max_chars
    return result
