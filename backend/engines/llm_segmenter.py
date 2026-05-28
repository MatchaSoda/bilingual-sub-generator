"""Subtitle re-segmentation (mode A: LLM-driven, semantic + timing-aware).

Gemini decides where subtitles should break based on meaning. To keep word-level
timestamps intact we never let the model rewrite text: it may only insert a single
break marker. We also inject pause hints (⏸) wherever the audio goes silent, so the
model can see the rhythm of speech — a short utterance bounded by pauses is its own
sentence and must not be glued to its neighbours. We then validate that the returned
text is byte-for-byte the original (markers + hints removed) and snap each break
marker back to the nearest whisper word boundary to recover timing.

Any failure (API error, validation mismatch) falls back to the offline rule-based
optimizer for that batch, so output is always produced.
"""

import time
import google.generativeai as genai
from config.keys import key_manager
from engines.segment_optimizer import (
    SubtitleSegmentOptimizer,
    flatten_words,
    hard_split_overlong_cues,
    SENTENCE_FINAL,
    CLAUSE_PUNCT,
    PAUSE_HARD_BREAK_SECONDS,
)

# Segmentation needs stronger instruction-following than translation, so it uses a
# more capable model than the (lighter) default translation model.
SEGMENT_MODEL = "gemini-3.5-flash"
BREAK_MARKER = "│"  # │ — where a subtitle should break (inserted by the model)
PAUSE_HINT = "⏸"    # ⏸ — an audible pause we inject to inform the model
# A silent gap at least this long is surfaced to the model as a pause hint and is
# also treated as a hard "do not merge across this" boundary in post-processing.
PAUSE_HINT_SECONDS = 0.4
# Punctuation that, on its own, should never form a standalone cue.
PUNCT_ONLY = set(SENTENCE_FINAL + CLAUSE_PUNCT)
# Group words into LLM batches no larger than this (keeps prompts small and
# bounds the damage of a single failed/invalid response).
BATCH_CHAR_BUDGET = 1200


class LLMSubtitleSegmenter:
    def __init__(self, model_name=None, maximum_characters_per_line=25):
        self.model_name = model_name or SEGMENT_MODEL
        self.max_chars = maximum_characters_per_line
        self.target_chars = max(8, round(maximum_characters_per_line * 0.8))
        # Cues shorter than this are merged into a neighbour (see _merge_short_cues).
        self.min_chars = max(6, round(maximum_characters_per_line * 0.32))
        self.rule_fallback = SubtitleSegmentOptimizer(maximum_characters_per_line)

    def segment(self, whisper_segments, source_language=None):
        words = flatten_words(whisper_segments)
        if not words:
            return self.rule_fallback.segment(whisper_segments, source_language)

        cues = []
        for batch in self._build_batches(words):
            cues.extend(self._segment_batch(batch, source_language))
        cues = hard_split_overlong_cues(cues, self.max_chars)
        return self._merge_short_cues(cues)

    def _merge_short_cues(self, cues):
        """Absorb tiny fragments (e.g. an isolated "専門家は、" or a lone "、") into a
        neighbour, while respecting timing.

        News subtitles read better without 5-7 char dangling cues, but a short
        utterance that is genuinely its own sentence — bounded by a pause or by
        sentence-final punctuation — must stay separate. So a merge is blocked when
        the two cues are separated by a real silent gap (>= PAUSE_HINT_SECONDS) or by
        sentence-final punctuation.
        """
        if not cues:
            return cues

        # Pass 1: punctuation-only cues always glue onto the preceding cue. A lone
        # "、" or "。" belongs to the clause it follows; it adds no visual width, so
        # this ignores the length cap.
        glued = []
        for cue in cues:
            if glued and self._is_punct_only(cue["text"]):
                prev = glued[-1]
                glued[-1] = {"start": prev["start"], "end": cue["end"],
                             "text": prev["text"] + cue["text"]}
            else:
                glued.append(cue)
        if len(glued) >= 2 and self._is_punct_only(glued[0]["text"]):
            head, nxt = glued[0], glued[1]
            glued[1] = {"start": head["start"], "end": nxt["end"],
                        "text": head["text"] + nxt["text"]}
            glued.pop(0)

        # Pass 2: merge a short text fragment into its neighbour (either direction),
        # but never across a pause or a sentence-final boundary.
        merged = [glued[0]]
        for cue in glued[1:]:
            prev = merged[-1]
            gap = cue["start"] - prev["end"]
            blocked = (gap >= PAUSE_HINT_SECONDS
                       or prev["text"][-1] in SENTENCE_FINAL
                       or len(prev["text"]) + len(cue["text"]) > self.max_chars)
            prev_short = len(prev["text"]) < self.min_chars
            cur_short = len(cue["text"]) < self.min_chars
            if (prev_short or cur_short) and not blocked:
                merged[-1] = {"start": prev["start"], "end": cue["end"],
                              "text": prev["text"] + cue["text"]}
            else:
                merged.append(cue)
        return merged

    def _is_punct_only(self, text):
        return bool(text) and all(character in PUNCT_ONLY for character in text)

    def _build_hinted_text(self, words):
        """Concatenate word tokens, inserting a ⏸ wherever the audio pauses."""
        parts = []
        for index, word in enumerate(words):
            parts.append(word["word"])
            if index < len(words) - 1:
                gap = words[index + 1]["start"] - word["end"]
                if gap >= PAUSE_HINT_SECONDS:
                    parts.append(PAUSE_HINT)
        return "".join(parts)

    def _build_batches(self, words):
        """Group words into batches, breaking only at natural points so a batch
        boundary is also a sensible cue boundary."""
        batches = []
        current = []
        current_chars = 0
        for index, word in enumerate(words):
            current.append(word)
            current_chars += len(word["word"])
            if index == len(words) - 1:
                break
            ends_sentence = word["word"][-1] in SENTENCE_FINAL
            gap = words[index + 1]["start"] - word["end"]
            at_natural_break = ends_sentence or gap >= PAUSE_HARD_BREAK_SECONDS
            if current_chars >= BATCH_CHAR_BUDGET and at_natural_break:
                batches.append(current)
                current = []
                current_chars = 0
        if current:
            batches.append(current)
        return batches

    def _segment_batch(self, words, source_language):
        batch_text = "".join(w["word"] for w in words)
        hinted_text = self._build_hinted_text(words)
        try:
            marked = self._request_markers(hinted_text, source_language)
            boundaries = self._marker_offsets_to_word_indices(marked, batch_text, words)
        except Exception as error:
            print(f"⚠️ LLM segmentation fell back to rules for one batch: {error}", flush=True)
            return self._rule_fallback_for_words(words)

        if boundaries is None:
            print("⚠️ LLM response failed validation; using rules for one batch.", flush=True)
            return self._rule_fallback_for_words(words)

        # Always break after sentence-final punctuation (。！？…), regardless of what
        # the model marked — two sentences should never share one cue.
        sentence_cuts = {index + 1 for index in range(len(words) - 1)
                         if words[index]["word"] and words[index]["word"][-1] in SENTENCE_FINAL}
        # Always break at audible pauses derived directly from word timestamps.
        # We can't trust the model to echo back the ⏸ hints — some models silently
        # strip them, which would otherwise lose the pause information entirely
        # (e.g. a 10-second silent gap winding up inside a single cue).
        pause_cuts = {index + 1 for index in range(len(words) - 1)
                      if words[index + 1]["start"] - words[index]["end"] >= PAUSE_HINT_SECONDS}
        boundaries = sorted(set(boundaries) | sentence_cuts | pause_cuts)

        cues = []
        previous = 0
        for cut in boundaries + [len(words)]:
            chunk = words[previous:cut]
            previous = cut
            if not chunk:
                continue
            text = "".join(w["word"] for w in chunk).strip()
            if len(text) > self.max_chars:
                # The model under-segmented this span (e.g. a long run with no
                # pause). Split it at word/MeCab boundaries via the rule engine
                # rather than chopping blindly at a character count.
                cues.extend(self.rule_fallback._segment_word_block(chunk))
            else:
                cues.append({
                    "start": chunk[0]["start"],
                    "end": chunk[-1]["end"],
                    "text": text,
                })
        return cues

    def _request_markers(self, text, source_language):
        language_hint = f" {source_language}" if source_language else ""
        prompt = (
            f"You are a subtitle segmentation engine for{language_hint} video subtitles.\n"
            f"Insert the marker character {BREAK_MARKER} at every position where the subtitle "
            "should break into a separate cue.\n"
            f"The text already contains {PAUSE_HINT} markers showing where the speaker pauses in "
            "the audio. They mark the rhythm of speech and almost always coincide with a cue "
            f"boundary. {PAUSE_HINT} is NOT spoken text.\n"
            "STRICT RULES:\n"
            f"1. Do NOT add, delete, translate, or change ANY character. You may only insert "
            f"{BREAK_MARKER}. Leave the existing {PAUSE_HINT} markers exactly where they are.\n"
            "2. Break at natural clause/semantic boundaries so each cue is a coherent unit, and "
            f"strongly prefer breaking at {PAUSE_HINT} pauses and after sentence-ending punctuation.\n"
            f"3. Aim for fairly full cues of about {self.target_chars}-{self.max_chars} characters; "
            f"never exceed {self.max_chars}. Keep cue lengths similar.\n"
            "4. Do NOT over-fragment: this is news narration, so prefer fuller, slightly longer "
            "coherent phrases over many short pieces. Do not break on every comma.\n"
            f"5. Never isolate a short fragment (under {self.min_chars} characters) as its own cue, "
            "and never leave punctuation alone — UNLESS that fragment is a complete short utterance "
            f"bounded by {PAUSE_HINT} pauses (e.g. はい⏸): such a standalone sentence must stay on "
            "its own. Do not split off a leading topic phrase (a noun + は/が + comma) when it is not "
            "followed by a pause; attach it to the clause that follows.\n"
            f"Return ONLY the text with {BREAK_MARKER} inserted, nothing else.\n\n"
            f"Text:\n{text}"
        )

        maximum_api_retries = 4
        for attempt_number in range(maximum_api_retries):
            api_key = key_manager.get_next_available_api_key()
            try:
                genai.configure(api_key=api_key, transport="rest")
                model = genai.GenerativeModel(self.model_name)
                response = model.generate_content(
                    prompt, request_options={"timeout": 45, "retry": None}
                )
                return response.text.strip()
            except Exception as api_error:
                if attempt_number == maximum_api_retries - 1:
                    raise api_error
                time.sleep(2 ** (attempt_number + 1))

    def _marker_offsets_to_word_indices(self, marked_text, original_text, words):
        """Validate verbatim match and map the model's break markers (│) to word
        boundaries. Pause cuts are computed deterministically from word timestamps in
        the caller, so we do not rely on the model echoing back the ⏸ hints (some
        models silently strip them). Returns a sorted list of word indices to cut
        before, or None if the model altered the text."""
        stripped = marked_text.replace(BREAK_MARKER, "").replace(PAUSE_HINT, "")
        # Tolerate a leading/trailing code fence or stray whitespace only.
        stripped = stripped.strip()
        if stripped != original_text:
            return None

        # Cumulative char length at each word boundary -> word index.
        cumulative_to_index = {}
        running = 0
        for index, word in enumerate(words):
            cumulative_to_index[running] = index
            running += len(word["word"])
        cumulative_to_index[running] = len(words)
        boundary_offsets = sorted(cumulative_to_index.keys())

        marker_offsets = []
        char_count = 0
        for character in marked_text.strip():
            if character == BREAK_MARKER:
                marker_offsets.append(char_count)
            elif character == PAUSE_HINT:
                continue  # injected hint, not a cut on its own (pauses are deterministic)
            else:
                char_count += 1

        cut_indices = []
        for offset in marker_offsets:
            snapped = min(boundary_offsets, key=lambda b: abs(b - offset))
            word_index = cumulative_to_index[snapped]
            if 0 < word_index < len(words) and word_index not in cut_indices:
                cut_indices.append(word_index)
        return sorted(cut_indices)

    def _rule_fallback_for_words(self, words):
        return self.rule_fallback._segment_word_block(words)
