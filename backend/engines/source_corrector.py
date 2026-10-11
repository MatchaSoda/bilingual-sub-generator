"""Proofread Japanese ASR text before it is translated (--fix-source-text).

This is its own Gemini request, separate from translation. When the fix rode along
with the translation request, the model rewrote whole lines while writing Chinese:
simplified characters leaked into the Japanese (国際 → 国际), names were swapped for
people it knew of, and words moved between lines. Here the model only proposes
`wrong → right` replacements for the whole video at once, with the title and the
description as reference, and every replacement is checked before it is applied:

- `wrong` must be in the line, and the fix must swap words, not add, drop or respell them;
- `right` must sound like `wrong` (MeCab readings), with no more than two sounds changed
  in a row, and must not change a number;
- the title / description win: a fix that replaces what they say is dropped, and a fix
  to a spelling they use may sound less alike or have no reading at all (硤合);
- a person's name the fix brings in must be in the title / description, and a place or
  organization they don't mention needs a close match.

Measured on 54 cached videos: docs/RUNBOOK.md §5.12.
"""
import difflib
import json
import re
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import google.generativeai as genai
from google.generativeai import protos

from config.keys import key_manager
from utils.gemini_transport import gemini_network_route, last_route

try:
    import MeCab
except Exception:  # pragma: no cover - mecab-python3 is in requirements.txt
    MeCab = None

# Finding a mis-heard name needs knowledge and attention more than speed; the output is
# a short list of fixes, so a stronger model than the translation default costs little.
CORRECTION_MODEL = "gemini-3.5-flash"
# Whole video in one request so the model sees every mention of a name; very long
# videos are split, and fixes found anywhere still reach every line (propagation).
MAXIMUM_LINES_PER_REQUEST = 400
DESCRIPTION_CHARACTER_LIMIT = 2000
# Reading similarity is 1 - edit distance / longer length, over katakana pronunciations.
# 0.5 still lets meaning flips through (合憲 → 違憲 is ゴーケン / イケン).
MINIMUM_READING_SIMILARITY = 0.55
# Lower-ranked parses recover readings Whisper meant (月代竹 → ツキヨタケ) but also invent
# some (合憲 as アイケン), so a fix resting on one of them must match almost exactly.
ALTERNATIVE_READING_SIMILARITY = 0.85
# A place or organization the model brings in from its own knowledge: 千葉豪雨 → 能登豪雨
# (0.6) put a 2024 disaster in place of this year's.
MINIMUM_PROPER_NOUN_SIMILARITY = 0.75
# A mis-hearing changes a sound or two in a row (ヤナリ → ヤナリョー). Shared context hides
# longer runs in the overall score: 一方内毛の袖が浮らし → 一方市原市の袖ケ浦市 is 0.67,
# 旧マルハニチロウミオス → 旧マルハニチロ水産 0.69, yet ウチゲ → イチハラシ and ウミオス →
# スイサン are different words.
MAXIMUM_CHANGED_RUN = 2
# A fix to a spelling the title / description use may sound less alike (柳田 → 簗 is 0.5),
# but still changes no more than two sounds in a row: the reference vouches for the
# spelling, not for where the model puts it (中学 → 千代田区)...
MINIMUM_GROUNDED_SIMILARITY = 0.34
# ...and names need more: the title's name attracts other names that sound a bit like it
# (a viewer, 新次郎 → そらジロー, is 0.6).
MINIMUM_GROUNDED_NAME_SIMILARITY = 0.65
# A fix whose `wrong` is at least this long is also applied to lines the model missed.
# Shorter strings (声明, 公共) are often correct elsewhere in the same video.
MINIMUM_PROPAGATION_CHARACTERS = 3
READING_CANDIDATES = 16
MAXIMUM_API_ATTEMPTS = 4
REQUEST_TIMEOUT_SECONDS = 120

_SYMBOL_POS = ("補助記号", "空白")
_KANA_ONLY = re.compile(r"^[\u3040-\u30ffー]+$")
_KATAKANA_ONLY = re.compile(r"^[\u30a1-\u30faー]+$")
_KANJI = re.compile(r"^[\u3400-\u9fff]$")
_VOWEL_O_OR_U = set("オコゴソゾトドノホボポモヨョロヲォウクグスズツヅヌフブプムユュルゥヴ")
_VOWEL_E = set("エケゲセゼテデネヘベペメレェ")
_KANJI_DIGITS = str.maketrans("〇一二三四五六七八九", "0123456789")
_DIGIT_KANA = dict(zip("0123456789", ("ゼロ", "イチ", "ニ", "サン", "ヨン", "ゴ", "ロク", "ナナ", "ハチ", "キュー")))


@dataclass
class Reading:
    """One parse of a span: its katakana pronunciation, token by token."""
    tokens: List[Tuple[str, str]] = field(default_factory=list)   # (surface, kana); symbols have ""
    # Tokens with no known reading (硤合, 际, TOPIX); their surface stands in for the kana
    unreadable_parts: List[str] = field(default_factory=list)
    # Dictionary forms: the same sequence on both sides means a respelling (癌 → がん), not a fix
    lemmas: List[str] = field(default_factory=list)
    # Proper-noun tokens. Only meaningful on the best parse: lower-ranked parses tag almost
    # any unknown word as a name.
    person_names: List[str] = field(default_factory=list)
    proper_nouns: List[str] = field(default_factory=list)   # places, organizations, ...

    @property
    def kana(self):
        return "".join(kana for _, kana in self.tokens)

    @property
    def unreadable(self):
        return bool(self.unreadable_parts)


class JapaneseReader:
    """Katakana pronunciations of a short span, via MeCab + unidic-lite."""

    def __init__(self):
        self.tagger = MeCab.Tagger() if MeCab is not None else None

    def readings(self, text: str, limit: int = READING_CANDIDATES) -> List[Reading]:
        """The first `limit` parses' readings, best first, without duplicates.

        Whisper writes what it heard with kanji whose usual reading can be another
        word: 月代竹 for つきよたけ, where MeCab's first guess is サカヤキ.

        Uses the text output of parseNBest: walking nodes after parseNBestInit returns
        empty surfaces for some paths (the input buffer is gone by then), and an empty
        reading on both sides scores as a perfect match.
        """
        text = unicodedata.normalize("NFKC", text or "")
        expected_surface = re.sub(r"\s", "", text)
        found = []
        path, covered = Reading(), ""
        for line in self.tagger.parseNBest(limit, text).splitlines():
            if line == "EOS":
                if covered == expected_surface and all(path.kana != seen.kana for seen in found):
                    found.append(path)
                path, covered = Reading(), ""
                continue
            # surface, pronunciation, reading, lemma, part of speech, ...
            columns = line.split("\t")
            surface = columns[0]
            pron = columns[1] if len(columns) > 1 else ""
            lemma = columns[3] if len(columns) > 3 else surface
            part_of_speech = columns[4] if len(columns) > 4 else ""
            covered += surface
            if part_of_speech.startswith(_SYMBOL_POS):
                path.tokens.append((surface, ""))
                continue
            path.lemmas.append(lemma)
            if _KATAKANA_ONLY.match(pron):
                kana = pron
            elif _KANA_ONLY.match(surface):
                kana = _hiragana_to_katakana(surface)
            elif surface.isdigit():
                kana = "".join(_DIGIT_KANA[digit] for digit in surface)
            else:
                # Unknown words echo their surface as the pronunciation (硤合, 际, TOPIX)
                kana = surface
                path.unreadable_parts.append(surface)
            path.tokens.append((surface, kana))
            if part_of_speech.startswith("名詞-固有名詞-人名"):
                path.person_names.append(surface)
            elif part_of_speech.startswith("名詞-固有名詞"):
                path.proper_nouns.append(surface)
        return found or [Reading(tokens=[(text, text)], unreadable_parts=[text])]


def _hiragana_to_katakana(text):
    return "".join(chr(ord(c) + 0x60) if "\u3041" <= c <= "\u3096" else c for c in text)


def as_pronounced(kana: str) -> str:
    """Katakana with long vowels written the way MeCab's pronunciations write them.

    The model gives readings as spelled (コウセイ); MeCab gives pronunciations (コーセー).
    """
    kana = _hiragana_to_katakana(re.sub(r"[\s・、。]", "", unicodedata.normalize("NFKC", kana or "")))
    out = []
    for char in kana:
        lengthens = (char == "ウ" and out and out[-1] in _VOWEL_O_OR_U) or (char == "イ" and out and out[-1] in _VOWEL_E)
        out.append("ー" if lengthens else char)
    return "".join(out)


def numbers_in(text: str) -> List[str]:
    """The numbers a span states, kanji digits included (三連休 and 3連休 both say 3)."""
    return sorted(re.findall(r"\d+", unicodedata.normalize("NFKC", text).translate(_KANJI_DIGITS)))


def reading_similarity(first: str, second: str) -> float:
    if not first and not second:
        return 1.0
    previous = list(range(len(second) + 1))
    for i, a in enumerate(first, 1):
        current = [i]
        for j, b in enumerate(second, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (a != b)))
        previous = current
    return 1 - previous[-1] / max(len(first), len(second))


def longest_changed_run(first: str, second: str) -> int:
    """Kana changed in the longest stretch where two readings differ.

    Changes one matching kana apart count as one stretch: ゴレンチュー → センシュー is
    ゴレ → セ, ン, チ → シ, three changes in a row.
    """
    longest = current = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, first, second, autojunk=False).get_opcodes():
        if tag == "equal":
            if i2 - i1 > 1:
                current = 0
            continue
        current += max(i2 - i1, j2 - j1)
        longest = max(longest, current)
    return longest


def _only_kanji_differ(wrong: str, right: str) -> bool:
    """Every changed character is a kanji on both sides: a different word that unidic files
    under the same lemma (反則 → 犯則), not a change of script (癌 → がん, うぐい → ウグイ)."""
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, wrong, right, autojunk=False).get_opcodes():
        if tag != "equal" and not all(_KANJI.match(char) for char in wrong[i1:i2] + right[j1:j2]):
            return False
    return True


@dataclass
class Reference:
    """The video's title and description, the spellings a fix may lean on."""
    title: str = ""
    text: str = ""

    @classmethod
    def from_page(cls, title, description):
        title = unicodedata.normalize("NFKC", title or "")
        description = unicodedata.normalize("NFKC", (description or "")[:DESCRIPTION_CHARACTER_LIMIT])
        return cls(title=title, text=f"{title}\n{description}")

    def uses(self, spelling):
        """True when the title / description spell something this way.

        One character proves nothing (市 is in half of all titles), except a kanji in the
        title: 簗 in 【簗農水相】 is the minister ASR keeps writing as 柳田.
        """
        spelling = unicodedata.normalize("NFKC", spelling)
        if len(spelling) >= 2:
            return spelling in self.text
        return bool(_KANJI.match(spelling)) and spelling in self.title


@dataclass
class CorrectionReport:
    model: str
    applied: List[Dict] = field(default_factory=list)
    rejected: List[Dict] = field(default_factory=list)

    def to_json(self):
        return {"model": self.model, "applied": self.applied, "rejected": self.rejected}


class AsrSourceCorrector:
    def __init__(self, model_name: Optional[str] = None, reader: Optional[JapaneseReader] = None):
        self.model_name = model_name or CORRECTION_MODEL
        self.reader = reader

    def correct(self, segments: List[Dict], source_language: str, title: str = "",
                description: str = "") -> Optional[CorrectionReport]:
        """Fix `segments[i]['text']` in place; the original goes to `asr_text`.

        Returns None when the source language has no reading check (non-Japanese).
        Raises when Gemini cannot be reached; callers translate the text as is.
        """
        if not (source_language or "").lower().startswith("ja"):
            print(f"🩹 ASR correction only checks Japanese; skipped for '{source_language}'.", flush=True)
            return None
        if self.reader is None:
            self.reader = JapaneseReader()
        if self.reader.tagger is None:
            print("⚠️ MeCab is unavailable, so fixes cannot be checked; ASR correction skipped.", flush=True)
            return None

        print(f"🩹 Proofreading ASR text with Gemini ({self.model_name}), {len(segments)} lines...", flush=True)
        proposals = []
        for start in range(0, len(segments), MAXIMUM_LINES_PER_REQUEST):
            chunk = segments[start:start + MAXIMUM_LINES_PER_REQUEST]
            prompt = self._construct_prompt(chunk, start, title, description)
            proposals.extend(self._request_fixes(prompt))

        report = self.apply_fixes(segments, proposals, Reference.from_page(title, description))
        self._print_report(report)
        return report

    def apply_fixes(self, segments: List[Dict], proposals: List[Dict], reference: Reference) -> CorrectionReport:
        """Check each proposed fix, apply the ones that pass, then carry them to missed lines."""
        if self.reader is None:
            self.reader = JapaneseReader()
        report = CorrectionReport(model=self.model_name)
        accepted_pairs = []
        for proposal in sorted(proposals, key=lambda item: item["index"]):
            verdict = self._judge(proposal, segments, reference)
            if verdict["status"] != "applied":
                report.rejected.append(verdict)
                continue
            self._replace_in_line(segments[verdict["index"]], verdict["wrong"], verdict["right"])
            report.applied.append(verdict)
            accepted_pairs.append((verdict["wrong"], verdict["right"], verdict))

        self._propagate(segments, accepted_pairs, report)
        return report

    # ---- model request -------------------------------------------------------

    def _construct_prompt(self, chunk, first_index, title, description):
        numbered = "\n".join(f"[{first_index + offset}] {segment['text']}" for offset, segment in enumerate(chunk))
        description = (description or "").strip()[:DESCRIPTION_CHARACTER_LIMIT] or "(none)"
        return f"""You are proofreading the speech-recognition (ASR) transcript of a Japanese video before it is translated.
ASR sometimes writes a word as a different word that sounds the same or almost the same. Names of people, places and organizations, technical terms and katakana loanwords are the usual victims (for example 厚生取引委員会 written for 公正取引委員会).

Reference text from the video page, written by the publisher. Its spellings of names and terms are reliable:
<title>{title or "(none)"}</title>
<description>
{description}
</description>

Find every place where the transcript has such a sound-alike recognition error, and give the fix.

Rules:
1. Only fix words that were mis-heard as a sound-alike word. Do not fix grammar or style, do not add, remove or reorder words, do not rephrase, and leave fillers and casual speech alone.
2. "wrong" is copied character for character from the line. Keep it short (usually one word) but long enough that it occurs only once in that line. "right" is what the speaker actually said, and it must sound the same as, or very close to, "wrong". "reading" is how "right" is pronounced, in katakana.
3. Names and terms in the reference text: use its spelling, also where the transcript writes the same name in kana. A person's name that is not in the reference text stays as it is unless you are certain. Never turn one person into another: speakers also mention viewers, guests and other people.
4. Write "right" in Japanese, as it would appear in Japanese subtitles. Never use simplified Chinese characters.
5. If the same error occurs on several lines, give one fix for each line.
6. When unsure, leave the text as it is. If nothing needs fixing, return an empty array.

Transcript (one subtitle line per row, prefixed with its index):
{numbered}
"""

    def _response_schema(self):
        return protos.Schema(
            type=protos.Type.ARRAY,
            items=protos.Schema(
                type=protos.Type.OBJECT,
                properties={
                    "index": protos.Schema(type=protos.Type.INTEGER),
                    "wrong": protos.Schema(type=protos.Type.STRING),
                    "right": protos.Schema(type=protos.Type.STRING),
                    "reading": protos.Schema(type=protos.Type.STRING),
                },
                required=["index", "wrong", "right", "reading"],
            ),
        )

    def _request_fixes(self, prompt):
        for attempt_number in range(MAXIMUM_API_ATTEMPTS):
            api_key = key_manager.get_next_available_api_key()
            try:
                raw_text = self._call_gemini(api_key, prompt, attempt_number)
                return self._parse_fixes(raw_text)
            except Exception as api_error:
                if attempt_number == MAXIMUM_API_ATTEMPTS - 1:
                    raise
                self._backoff(attempt_number, api_error)
        return []

    def _call_gemini(self, api_key, prompt, attempt):
        genai.configure(api_key=api_key, transport='rest')
        model = genai.GenerativeModel(self.model_name)
        generation_config = genai.types.GenerationConfig(
            response_mime_type="application/json",
            response_schema=self._response_schema(),
            temperature=0.0,
        )
        with gemini_network_route(attempt):
            response = model.generate_content(
                prompt,
                generation_config=generation_config,
                request_options={"timeout": REQUEST_TIMEOUT_SECONDS, "retry": None},
            )
        return response.text.strip()

    @staticmethod
    def _parse_fixes(raw_text):
        parsed = json.loads(raw_text)
        if not isinstance(parsed, list):
            raise ValueError("ASR correction output was not a JSON array.")
        fixes = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            try:
                fixes.append({"index": int(item["index"]), "wrong": str(item["wrong"]), "right": str(item["right"]),
                              "reading": str(item.get("reading") or "")})
            except (KeyError, TypeError, ValueError):
                continue
        return fixes

    def _backoff(self, attempt, error):
        seconds_to_wait = 2 ** (attempt + 1)
        print(f"⚠️ ASR correction attempt {attempt + 1} failed (route={last_route()}): {error}", flush=True)
        time.sleep(seconds_to_wait)

    # ---- checks ----------------------------------------------------------------

    def _judge(self, proposal, segments, reference):
        index, wrong, right = proposal["index"], proposal["wrong"], proposal["right"]
        verdict = {"index": index, "wrong": wrong, "right": right}

        def reject(reason):
            verdict.update(status="rejected", reason=reason)
            return verdict

        if not 0 <= index < len(segments):
            return reject("index_out_of_range")
        line = segments[index]["text"]
        if not wrong or not right or wrong == right:
            return reject("empty_or_unchanged")
        if wrong not in line:
            return reject("not_in_line")
        wrong = verdict["wrong"] = self._absorb_repeated_neighbor(line, wrong, right)
        if wrong in right or right in wrong:
            return reject("insertion_or_deletion")
        if line.count(wrong) > 1 and len(wrong) < MINIMUM_PROPAGATION_CHARACTERS:
            return reject("ambiguous_in_line")

        grounded = verdict["grounded"] = reference.uses(right)
        if not grounded and len(wrong) >= 2 and reference.uses(wrong):
            return reject("reference_has_original")
        # A changed number is a changed fact, and one sound apart (台風25号 → 台風15号)
        if not grounded and numbers_in(wrong) != numbers_in(right):
            return reject("number_changed")

        wrong_readings = self.reader.readings(wrong)
        right_readings = self.reader.readings(right)
        verdict["readings"] = [wrong_readings[0].kana, right_readings[0].kana]
        # A person's name the fix brings in must be one the title or description uses: the
        # model's own knowledge of names is what put 斉藤 for 岡本. Single characters are
        # left out, MeCab tags 明 in 先見の明 as a given name.
        new_names = [name for name in right_readings[0].person_names if len(name) >= 2 and name not in wrong]
        if new_names and not all(map(reference.uses, new_names)):
            return reject("name_not_in_reference")
        is_name = bool(new_names)
        if is_name:
            grounded = verdict["grounded"] = True
        if wrong_readings[0].lemmas == right_readings[0].lemmas and not grounded and not _only_kanji_differ(wrong, right):
            return reject("same_word")
        if wrong_readings[0].unreadable:
            # ASR wrote something MeCab can't read (Latin letters): nothing to compare with
            if grounded:
                verdict["status"] = "applied"
                return verdict
            return reject("unreadable")
        if right_readings[0].unreadable:
            # A spelling MeCab has no reading for: only one the title or description uses
            # (硤合; not 国际 for 国際), compared by the reading the model gives (ソアイ), so the
            # title's name can't land on an unrelated word (宝塚 → 硤合).
            model_reading = as_pronounced(proposal.get("reading", ""))
            parts = right_readings[0].unreadable_parts
            if not model_reading or not _KATAKANA_ONLY.match(model_reading) or not all(map(reference.uses, parts)):
                return reject("unreadable")
            right_readings = [Reading(tokens=[(right, model_reading)])]
            grounded = verdict["grounded"] = True
            is_name = True

        if grounded:
            minimum = MINIMUM_GROUNDED_NAME_SIMILARITY if is_name else MINIMUM_GROUNDED_SIMILARITY
        elif any(noun not in wrong for noun in right_readings[0].proper_nouns):
            minimum = MINIMUM_PROPER_NOUN_SIMILARITY
        else:
            minimum = MINIMUM_READING_SIMILARITY
        # The best parses first, then the others by score; the first pair that holds up wins
        pairs = sorted(((reading_similarity(a.kana, b.kana), a, b) for a in wrong_readings for b in right_readings),
                       key=lambda pair: (pair[1] is wrong_readings[0] and pair[2] is right_readings[0], pair[0]),
                       reverse=True)
        first_failure = None
        for similarity, wrong_reading, right_reading in pairs:
            is_best = wrong_reading is wrong_readings[0] and right_reading is right_readings[0]
            changed_run = longest_changed_run(wrong_reading.kana, right_reading.kana)
            evidence = {"similarity": round(similarity, 2), "changed_run": changed_run,
                        "readings": [wrong_reading.kana, right_reading.kana]}
            if similarity < (minimum if is_best else max(minimum, ALTERNATIVE_READING_SIMILARITY)):
                failure = "sound_mismatch"
            elif changed_run > MAXIMUM_CHANGED_RUN:
                failure = "too_many_sounds_changed"
            else:
                verdict.update(evidence, status="applied")
                return verdict
            if first_failure is None:
                first_failure = (failure, evidence)
        verdict.update(first_failure[1])
        return reject(first_failure[0])

    @staticmethod
    def _absorb_repeated_neighbor(line, wrong, right):
        """Widen `wrong` when `right` repeats the text next to it.

        The model sometimes puts the following particle into `right` only (シナド → 市などが
        in シナドが食べ残した); applied as is, the line would read 市などがが.
        """
        position = line.find(wrong)
        before, after = line[:position], line[position + len(wrong):]
        for size in range(min(3, len(after)), 0, -1):
            if right.endswith(after[:size]) and not wrong.endswith(after[:size]):
                wrong += after[:size]
                break
        for size in range(min(3, len(before)), 0, -1):
            if right.startswith(before[-size:]) and not wrong.startswith(before[-size:]):
                wrong = before[-size:] + wrong
                break
        return wrong

    @staticmethod
    def _replace_in_line(segment, wrong, right):
        segment.setdefault("asr_text", segment["text"])
        segment["text"] = segment["text"].replace(wrong, right)

    def _propagate(self, segments, accepted_pairs, report):
        for wrong, right, source_verdict in accepted_pairs:
            if len(wrong) < MINIMUM_PROPAGATION_CHARACTERS:
                continue
            for index, segment in enumerate(segments):
                if wrong in segment["text"]:
                    self._replace_in_line(segment, wrong, right)
                    report.applied.append({
                        "index": index, "wrong": wrong, "right": right, "status": "propagated",
                        "from_index": source_verdict["index"],
                    })

    @staticmethod
    def _print_report(report):
        propagated = sum(1 for item in report.applied if item["status"] == "propagated")
        print(f"🩹 ASR correction: {len(report.applied)} fixes applied ({propagated} carried to lines the model missed), "
              f"{len(report.rejected)} rejected", flush=True)
        for item in report.applied:
            note = " (carried)" if item["status"] == "propagated" else ""
            print(f"   ✓ [{item['index']}] {item['wrong']} → {item['right']}{note}", flush=True)
        for item in report.rejected:
            print(f"   ✗ [{item['index']}] {item['wrong']} → {item['right']} ({item['reason']})", flush=True)
