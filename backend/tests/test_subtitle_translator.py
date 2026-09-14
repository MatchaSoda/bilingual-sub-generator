import unittest
import sys
import os

# Ensure the backend directory is in the path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from engines.subtitle_translator import GeminiSubtitleTranslator


class FakeGeminiTranslator(GeminiSubtitleTranslator):
    """Replaces the network call with a scripted list of responses."""

    def __init__(self, scripted_responses):
        super().__init__(target_language_code="zh-CN", ai_model_identifier="fake-model")
        self.scripted_responses = list(scripted_responses)
        self.prompts_seen = []

    def _call_gemini_api_with_retry(self, api_key, prompt, response_schema=None, sampling_temperature=0.0, attempt=0):
        self.prompts_seen.append(prompt)
        return self.scripted_responses.pop(0)

    def _perform_exponential_backoff(self, attempt, error):
        pass  # no sleeping in tests


class TestUntranslatedJapaneseDetection(unittest.TestCase):
    check = staticmethod(GeminiSubtitleTranslator._untranslated_japanese_in_title)

    def test_clean_chinese_title_passes(self):
        self.assertEqual(self.check("【中部电力】滨冈核电站重启申请撤回", "ja"), "")

    def test_generic_bracket_tag_left_in_japanese_is_flagged(self):
        leftover = self.check("【エネルギーの安定供給】与IEA确认合作", "ja")
        self.assertIn("【エネルギーの安定供給】", leftover)

    def test_loose_kana_outside_brackets_is_flagged(self):
        leftover = self.check("【西・东日本】明天部分地区仍有大雨 関東甲信では雷を伴う", "ja")
        self.assertIn("雷を伴う", leftover)

    def test_preserved_program_names_are_not_flagged(self):
        self.assertEqual(self.check("【きょうの1日】关东地区迎来罕见连绵阴雨", "ja"), "")
        self.assertEqual(self.check("【 #みんなのギモン 】千叶暴雨中出现的线状降水带是什么？", "ja"), "")
        self.assertEqual(self.check("【调查】隐藏进食更美味！？『気になる！』", "ja"), "")

    def test_kanji_only_is_not_treated_as_japanese(self):
        # Kanji are shared with Chinese; only kana proves untranslated source text.
        self.assertEqual(self.check("【高市首相】“人事”最后阶段调整", "ja"), "")

    def test_non_japanese_source_is_never_checked(self):
        self.assertEqual(self.check("【エネルギー】anything", "en"), "")
        self.assertEqual(self.check("【エネルギー】anything", None), "")


class TestTranslateTitleFixupRound(unittest.TestCase):
    def test_partially_translated_title_triggers_one_more_request(self):
        translator = FakeGeminiTranslator([
            "【エネルギーの安定供給】与IEA确认合作",
            "【能源稳定供应】与IEA确认合作",
        ])
        result = translator.translate_title("【エネルギーの安定供給】IEAと連携確認", "ja")
        self.assertEqual(result, "【能源稳定供应】与IEA确认合作")
        self.assertEqual(len(translator.prompts_seen), 2)
        self.assertIn("Your previous answer was: 【エネルギーの安定供給】与IEA确认合作", translator.prompts_seen[1])

    def test_fixup_round_is_bounded_and_last_answer_is_kept(self):
        translator = FakeGeminiTranslator([
            "【エネルギーの安定供給】与IEA确认合作",
            "【エネルギーの安定供給】与IEA确认合作",  # model insists
        ])
        result = translator.translate_title("【エネルギーの安定供給】IEAと連携確認", "ja")
        self.assertEqual(result, "【エネルギーの安定供給】与IEA确认合作")
        self.assertEqual(len(translator.prompts_seen), 2)

    def test_clean_translation_returns_after_single_request(self):
        translator = FakeGeminiTranslator(["【中部电力】滨冈核电站重启申请撤回"])
        result = translator.translate_title("【中部電力】浜岡原発の再稼働申請を取り下げ", "ja")
        self.assertEqual(result, "【中部电力】滨冈核电站重启申请撤回")
        self.assertEqual(len(translator.prompts_seen), 1)

    def test_preserved_program_name_does_not_trigger_fixup(self):
        translator = FakeGeminiTranslator(["【きょうの1日】关东地区迎来罕见连绵阴雨"])
        result = translator.translate_title("【きょうの1日】関東は珍しい長雨", "ja")
        self.assertEqual(result, "【きょうの1日】关东地区迎来罕见连绵阴雨")
        self.assertEqual(len(translator.prompts_seen), 1)

    def test_prompt_lists_closed_set_of_program_names(self):
        translator = FakeGeminiTranslator(["x"])
        translator.translate_title("テスト", "ja")
        prompt = translator.prompts_seen[0]
        self.assertIn("【きょうの1日】", prompt)
        self.assertIn("closed list", prompt)
        self.assertIn("Title: テスト", prompt)


if __name__ == "__main__":
    unittest.main()
