import os
import time
import json
import google.generativeai as genai
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

        maximum_api_retries = 6
        for attempt_number in range(maximum_api_retries):
            api_key = key_manager.get_next_available_api_key()
            try:
                raw_ai_response_text = self._call_gemini_api_with_retry(api_key, translation_prompt)
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
            "Keep any text enclosed in 【】 brackets unchanged in its original language; do not translate the content inside 【】, and preserve the 【】 brackets themselves.\n\n"
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
            f"6. CRITICAL: Also provide the corrected {source_lang} source text if you detect ASR errors. Return format: '[index] corrected_source | translated_text'."
            if fix_source else 
            "6. Return format: '[index] translated_text'."
        )

        return f"""You are a professional translator specializing in video subtitles. 
Your task is to translate the following {source_lang} subtitles into {self.target_language}.

Requirements:
1. Maintain the original meaning and tone.
2. Keep the format exactly as requested.
3. Do not combine or skip any lines.
4. If the content is for language learning, ensure the translation is natural and accurate.
5. Return ONLY the translated lines.
{instruction_for_fixing}

Subtitles:
{text_content}
"""

    def _call_gemini_api_with_retry(self, api_key, prompt):
        genai.configure(api_key=api_key, transport='rest')
        generative_model = genai.GenerativeModel(self.model_name)
        
        response = generative_model.generate_content(
            prompt,
            request_options={"timeout": 45, "retry": None}
        )
        return response.text.strip()

    def _parse_and_apply_translations(self, segments, raw_response_text, fix_source):
        lines_from_response = raw_response_text.split('\n')
        translation_results = {}
        source_correction_results = {}

        for line in lines_from_response:
            if ']' not in line:
                continue
                
            index_portion, content_portion = line.split(']', 1)
            segment_index = int(index_portion.replace('[', '').strip())
            
            if fix_source and '|' in content_portion:
                corrected_text, translated_text = content_portion.split('|', 1)
                source_correction_results[segment_index] = corrected_text.strip()
                translation_results[segment_index] = translated_text.strip()
            else:
                translation_results[segment_index] = content_portion.strip()
        
        for index, segment in enumerate(segments):
            segment['translated_text'] = translation_results.get(index, "")
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
