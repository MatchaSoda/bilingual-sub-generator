import os
import time
import json
import google.generativeai as genai
from google.generativeai import protos
from typing import List, Dict
from config.keys import key_manager
from config.settings import MODEL_NAME

class GeminiSubtitleTranslator:
    def __init__(self, target_language_code: str = "zh-CN", ai_model_identifier: str = None):
        self.target_language = target_language_code
        self.model_name = ai_model_identifier or MODEL_NAME
        
    def translate_batch_of_subtitle_segments(self, subtitle_segments: List[Dict], 
                                            source_language: str, 
                                            should_fix_source_errors: bool = False) -> List[Dict]:
        
        print(f"🤖 Requesting Gemini AI ({self.model_name}) for {len(subtitle_segments)} segments...", flush=True)
        
        numbered_text_to_translate = "\n".join([f"[{index}] {segment['text']}" for index, segment in enumerate(subtitle_segments)])
        translation_prompt = self._construct_translation_prompt(source_language, should_fix_source_errors, numbered_text_to_translate)
        response_schema = self._build_translation_response_schema(should_fix_source_errors)
        # Pure translation wants faithful, deterministic output (temp=0). ASR error
        # detection needs the model willing to alter the source, which temp=0 is too
        # conservative for — empirically ~0.3 maximizes error recall while staying in
        # the recommended low-temp translation range.
        sampling_temperature = 0.3 if should_fix_source_errors else 0.0

        maximum_api_retries = 6
        for attempt_number in range(maximum_api_retries):
            api_key = key_manager.get_next_available_api_key()
            try:
                raw_ai_response_text = self._call_gemini_api_with_retry(
                    api_key, translation_prompt, response_schema=response_schema,
                    sampling_temperature=sampling_temperature
                )
                self._parse_and_apply_translations(subtitle_segments, raw_ai_response_text, should_fix_source_errors)
                return subtitle_segments

            except Exception as api_error:
                if attempt_number == maximum_api_retries - 1:
                    self._handle_final_failure(api_error)
                    raise api_error
                
                self._perform_exponential_backoff(attempt_number, api_error)
        
        return subtitle_segments

    def translate_title(self, title: str, source_language: str) -> str:
        if not title or not title.strip():
            return title

        print(f"🌐 Translating video title via Gemini ({self.model_name})...", flush=True)
        prompt = (
            f"Translate the following video title from {source_language} into {self.target_language}.\n"
            "Return ONLY the translated title on a single line, with no quotes, labels, or explanation.\n"
            "Keep it concise and natural as a video title.\n"
            "If text enclosed in 【】 brackets is a fixed show name or program segment name (e.g. 【ゲーム実況】, 【雑談】, 【#みんなのギモン】, 【きょうの1日】, 【なるほどッ！】), keep it unchanged in its original language. If it is just a generic tag, category, or keyword, translate it normally. In either case, preserve the 【】 brackets themselves.\n\n"
            f"Title: {title}"
        )

        maximum_api_retries = 4
        for attempt_number in range(maximum_api_retries):
            api_key = key_manager.get_next_available_api_key()
            try:
                raw_ai_response_text = self._call_gemini_api_with_retry(api_key, prompt)
                return self._clean_translated_title(raw_ai_response_text)
            except Exception as api_error:
                if attempt_number == maximum_api_retries - 1:
                    raise api_error
                self._perform_exponential_backoff(attempt_number, api_error)

        return title

    def _clean_translated_title(self, raw_text: str) -> str:
        first_line = next((line.strip() for line in raw_text.splitlines() if line.strip()), "")
        return first_line.strip('"').strip("'").strip()

    def _construct_translation_prompt(self, source_lang, fix_source, text_content):
        instruction_for_fixing = (
            f'6. ASR correction: the {source_lang} text is speech-recognition output and may contain homophone mis-recognitions '
            '(a word replaced by a same-sounding wrong word, e.g. a name or katakana term written as unrelated kanji). '
            f'For any line with such an error, add a "corrected_source" field holding the corrected {source_lang} text, and base the translation on that corrected reading. '
            'IMPORTANT: apply corrections consistently — if a word is mis-recognized, correct it on EVERY line where it appears, not only the first. '
            'For lines that are already correct, OMIT the "corrected_source" field entirely (do not echo the source).'
            if fix_source else
            '6. Do not include any field other than "index" and "translation".'
        )

        return f"""You are a professional translator specializing in video subtitles.
Your task is to translate the following {source_lang} subtitles into {self.target_language}.

The input has one subtitle line per row, each prefixed with its index as [index].
Return a JSON array with EXACTLY one object per input line, in the same order.

Requirements:
1. Maintain the original meaning and tone.
2. Output exactly one object per input line: the array length MUST equal the number of input lines.
3. Do not combine, split, skip, reorder, or add lines. Each object's "index" MUST equal the [index] of the line it translates.
4. Translate each line independently even if a sentence spans multiple lines; never move content between lines.
5. If the content is for language learning, ensure the translation is natural and accurate.
{instruction_for_fixing}

Subtitles:
{text_content}
"""

    def _build_translation_response_schema(self, fix_source):
        object_properties = {
            "index": protos.Schema(type=protos.Type.INTEGER),
            "translation": protos.Schema(type=protos.Type.STRING),
        }
        required_fields = ["index", "translation"]
        if fix_source:
            # Optional (not required): the model omits it for correct lines,
            # so only genuinely mis-recognized lines cost extra output tokens.
            object_properties["corrected_source"] = protos.Schema(type=protos.Type.STRING)

        return protos.Schema(
            type=protos.Type.ARRAY,
            items=protos.Schema(
                type=protos.Type.OBJECT,
                properties=object_properties,
                required=required_fields,
            ),
        )

    def _call_gemini_api_with_retry(self, api_key, prompt, response_schema=None, sampling_temperature=0.0):
        genai.configure(api_key=api_key, transport='rest')
        generative_model = genai.GenerativeModel(self.model_name)

        generation_config = None
        if response_schema is not None:
            # Low temperature keeps translation faithful/stable and curbs the model's
            # tendency to merge or reword lines. Caller raises it slightly (~0.3) only
            # when ASR error-correction is on, where temp=0 detects too few errors.
            generation_config = genai.types.GenerationConfig(
                response_mime_type="application/json",
                response_schema=response_schema,
                temperature=sampling_temperature,
            )

        response = generative_model.generate_content(
            prompt,
            generation_config=generation_config,
            request_options={"timeout": 45, "retry": None}
        )
        return response.text.strip()

    def _parse_and_apply_translations(self, segments, raw_response_text, fix_source):
        try:
            parsed_response = json.loads(raw_response_text)
        except json.JSONDecodeError as decode_error:
            raise ValueError(f"Gemini returned non-JSON translation output: {decode_error}")

        if not isinstance(parsed_response, list):
            raise ValueError("Gemini translation output was not a JSON array.")

        translation_results = {}
        source_correction_results = {}
        for item in parsed_response:
            if not isinstance(item, dict) or "index" not in item or "translation" not in item:
                raise ValueError("Gemini translation item missing 'index' or 'translation'.")
            segment_index = int(item["index"])
            translation_results[segment_index] = str(item["translation"]).strip()
            if fix_source and item.get("corrected_source"):
                source_correction_results[segment_index] = str(item["corrected_source"]).strip()

        expected_indices = set(range(len(segments)))
        missing_indices = expected_indices - translation_results.keys()
        if missing_indices:
            raise ValueError(
                f"Translation count mismatch: expected {len(segments)} lines, "
                f"missing indices {sorted(missing_indices)[:10]}."
            )

        for index, segment in enumerate(segments):
            segment['translated_text'] = translation_results[index]
            if fix_source and index in source_correction_results:
                segment['text'] = source_correction_results[index]

    def _perform_exponential_backoff(self, attempt, error):
        seconds_to_wait = 2 ** (attempt + 1)
        print(f"⚠️ Attempt {attempt + 1} failed: {error}", flush=True)
        print(f"⏳ Waiting {seconds_to_wait} seconds before retrying...", flush=True)
        time.sleep(seconds_to_wait)

    def _handle_final_failure(self, error):
        print("❌ All retries failed. Gemini API is currently unavailable or overloaded.", flush=True)
        print("💡 Suggestion: Try using 'gemini-1.5-flash' in Settings for increased stability.", flush=True)
