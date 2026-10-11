import os
import sys
import unittest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from engines.source_corrector import (AsrSourceCorrector, JapaneseReader, Reference, as_pronounced,
                                      longest_changed_run, reading_similarity)

READER = JapaneseReader()


class ScriptedCorrector(AsrSourceCorrector):
    """Replaces the Gemini call with a fixed list of proposed fixes."""

    def __init__(self, proposals):
        super().__init__(model_name="fake-model", reader=READER)
        self.proposals = proposals
        self.prompts_seen = []

    def _request_fixes(self, prompt):
        self.prompts_seen.append(prompt)
        return list(self.proposals)


def lines(*texts):
    return [{"text": text} for text in texts]


def fix(index, wrong, right, reading=""):
    return {"index": index, "wrong": wrong, "right": right, "reading": reading}


def apply(segments, proposals, title="", description=""):
    corrector = AsrSourceCorrector(model_name="fake-model", reader=READER)
    return corrector.apply_fixes(segments, proposals, Reference.from_page(title, description))


class TestReadings(unittest.TestCase):
    def test_similarity_is_one_minus_normalized_edit_distance(self):
        self.assertEqual(reading_similarity("コーセー", "コーセー"), 1.0)
        self.assertAlmostEqual(reading_similarity("コーキョーラン", "コーキョラン"), 1 - 1 / 7)
        self.assertEqual(reading_similarity("オカモト", "サイトー"), 0.0)

    def test_model_readings_are_compared_as_pronounced(self):
        self.assertEqual(as_pronounced("コウセイ"), "コーセー")
        self.assertEqual(as_pronounced("そあい"), "ソアイ")
        self.assertEqual(as_pronounced("ナヴィ・ピレイ"), "ナヴィピレー")

    def test_changed_run_counts_neighboring_changes_together(self):
        self.assertEqual(longest_changed_run("コーセー", "コーセー"), 0)
        self.assertEqual(longest_changed_run("ヤナリ", "ヤナリョー"), 2)
        self.assertEqual(longest_changed_run("ゴレンチュー", "センシュー"), 3)
        self.assertEqual(longest_changed_run("ウチゲノソデガウラシ", "イチハラシノソデガウラシ"), 4)

    def test_rare_kanji_reading_is_among_the_candidates(self):
        # MeCab's first guess for 月代 is サカヤキ; Whisper wrote it for つきよ
        kana = [reading.kana for reading in READER.readings("月代竹")]
        self.assertEqual(kana[0], "サカヤキタケ")
        self.assertIn("ツキヨタケ", kana)

    def test_no_candidate_is_empty(self):
        # Walking N-best nodes once returned empty surfaces, and two empty readings
        # scored キンニク → セロリ as a perfect sound match.
        for text in ("キンニク", "セロリ", "斉藤", "公正 取引"):
            self.assertTrue(all(reading.kana for reading in READER.readings(text)), text)

    def test_unknown_characters_are_unreadable(self):
        self.assertTrue(READER.readings("国际")[0].unreadable)
        self.assertTrue(READER.readings("TOPIX")[0].unreadable)
        self.assertFalse(READER.readings("3票")[0].unreadable)

    def test_person_names_are_collected(self):
        self.assertEqual(READER.readings("斉藤代表")[0].person_names, ["斉藤"])
        self.assertEqual(READER.readings("公正取引委員")[0].person_names, [])


class TestApplyFixes(unittest.TestCase):
    def test_homophone_fix_is_applied_and_the_asr_text_kept(self):
        segments = lines("厚生取引委員会が強制調査に入りました")
        report = apply(segments, [fix(0, "厚生取引委員", "公正取引委員")])
        self.assertEqual(segments[0]["text"], "公正取引委員会が強制調査に入りました")
        self.assertEqual(segments[0]["asr_text"], "厚生取引委員会が強制調査に入りました")
        self.assertEqual([item["status"] for item in report.applied], ["applied"])

    def test_rare_kanji_reading_still_passes_the_sound_check(self):
        segments = lines("この月代竹よく見てください")
        apply(segments, [fix(0, "月代竹", "ツキヨタケ")])
        self.assertEqual(segments[0]["text"], "このツキヨタケよく見てください")

    def test_replacement_that_does_not_sound_alike_is_rejected(self):
        segments = lines("一番うまいキンニクがいい仕事してる")
        report = apply(segments, [fix(0, "キンニク", "セロリ")])
        self.assertEqual(segments[0]["text"], "一番うまいキンニクがいい仕事してる")
        self.assertEqual(report.rejected[0]["reason"], "sound_mismatch")

    def test_simplified_chinese_is_rejected(self):
        segments = lines("南アフリカの国際法学者")
        report = apply(segments, [fix(0, "国際", "国际")])
        self.assertEqual(segments[0]["text"], "南アフリカの国際法学者")
        self.assertEqual(report.rejected[0]["reason"], "unreadable")

    def test_name_without_a_dictionary_reading_is_checked_by_the_models_reading(self):
        title = "【ノーベル化学賞】硤合さんの“快挙”"
        segments = lines("ソワイさんの快挙とは", "これから宝塚を見に行くという双子は?")
        report = apply(segments, [fix(0, "ソワイ", "硤合", "ソアイ"), fix(1, "宝塚", "硤合", "ソアイ")], title=title)
        self.assertEqual(segments[0]["text"], "硤合さんの快挙とは")
        # The title's name must not land on an unrelated word
        self.assertEqual(segments[1]["text"], "これから宝塚を見に行くという双子は?")
        self.assertEqual(report.rejected[0]["reason"], "sound_mismatch")

    def test_name_without_any_reading_is_rejected(self):
        segments = lines("祖愛さんの快挙とは")
        report = apply(segments, [fix(0, "祖愛", "硤合")], title="硤合さんの“快挙”")
        self.assertEqual(segments[0]["text"], "祖愛さんの快挙とは")
        self.assertEqual(report.rejected[0]["reason"], "unreadable")

    def test_name_from_the_reference_does_not_replace_other_names(self):
        # Viewers who send in questions are not そらジロー, however close they sound
        segments = lines("タッカジローさんからのご質問です", "16歳の新次郎さんからの質問です", "続いてはねえねえ空次郎今日は")
        apply(segments, [fix(0, "タッカジロー", "そらジロー"), fix(1, "新次郎", "そらジロー"), fix(2, "空次郎", "そらジロー")],
              title="【ねぇねぇそらジロー】そらジローは文系、理系どっちですか？")
        self.assertEqual([segment["text"] for segment in segments],
                         ["タッカジローさんからのご質問です", "16歳の新次郎さんからの質問です", "続いてはねえねえそらジロー今日は"])

    def test_unreadable_part_only_needs_to_be_in_the_reference(self):
        # The model folded two fixes into one span; 硤合 is in the title, 硤合さん快挙 is not
        segments = lines("生命の起源祖愛さん解挙とは?")
        apply(segments, [fix(0, "祖愛さん解挙", "硤合さん快挙", "ソアイサンカイキョ")],
              title="生命の起源に迫る研究  硤合さんの“快挙”とは？")
        self.assertEqual(segments[0]["text"], "生命の起源硤合さん快挙とは?")

    def test_name_missing_from_the_reference_is_not_changed(self):
        segments = lines("曽藍健壮名誉教授", "玉城代表は")
        report = apply(segments, [fix(0, "曽藍", "曾根"), fix(1, "玉城", "玉木")])
        self.assertEqual(segments[0]["text"], "曽藍健壮名誉教授")
        self.assertEqual(segments[1]["text"], "玉城代表は")
        self.assertEqual([item["reason"] for item in report.rejected], ["name_not_in_reference"] * 2)

    def test_only_names_the_fix_brings_in_count(self):
        # 平山 is already there; ノーベル is in the title; 明 is one character
        segments = lines("その結果、平山市の得票数が", "昔から冗談でそのうちのメル賞というようなことは", "我々には勇気、先見の銘、")
        apply(segments, [fix(0, "平山市", "平山氏"), fix(1, "のメル賞", "ノーベル賞"), fix(2, "先見の銘", "先見の明")],
              title="【ノーベル化学賞】発表から一夜明け")
        self.assertEqual([segment["text"] for segment in segments],
                         ["その結果、平山氏の得票数が", "昔から冗談でそのうちノーベル賞というようなことは", "我々には勇気、先見の明、"])

    def test_name_in_the_reference_may_be_respelled(self):
        segments = lines("玉城代表は")
        apply(segments, [fix(0, "玉城", "玉木")], description="国民民主党の玉木代表が追及")
        self.assertEqual(segments[0]["text"], "玉木代表は")

    def test_fix_that_replaces_what_the_title_says_is_rejected(self):
        segments = lines("公明党の岡本代表は")
        report = apply(segments, [fix(0, "岡本", "斉藤")], title="公明･岡本代表から物価高対策への効果問われ")
        self.assertEqual(segments[0]["text"], "公明党の岡本代表は")
        self.assertEqual(report.rejected[0]["reason"], "reference_has_original")

    def test_added_or_dropped_words_are_rejected(self):
        segments = lines("取扱高のシェアが5%から18%に")
        report = apply(segments, [fix(0, "5%から", "5%旧マルハニチロが5%から")])
        self.assertEqual(segments[0]["text"], "取扱高のシェアが5%から18%に")
        self.assertEqual(report.rejected[0]["reason"], "insertion_or_deletion")

    def test_shared_context_does_not_hide_a_different_word(self):
        # Overall these look close; 内毛 → 市原市, 5連中 → 先週 and ウミオス → 水産 are not
        segments = lines("一方内毛の袖が浮らし", "5連中あたりがずっと雨だった", "旧マルハニチロウミオスが5%")
        report = apply(segments, [fix(0, "一方内毛の袖が浮らし", "一方市原市の袖ケ浦市"), fix(1, "5連中あたり", "先週あたり"),
                                  fix(2, "旧マルハニチロウミオス", "旧マルハニチロ水産")])
        self.assertEqual([segment["text"] for segment in segments],
                         ["一方内毛の袖が浮らし", "5連中あたりがずっと雨だった", "旧マルハニチロウミオスが5%"])
        self.assertEqual(len(report.rejected), 3)
        self.assertEqual(report.rejected[2]["reason"], "too_many_sounds_changed")

        segments = lines("一方内毛の袖が浮らし")
        apply(segments, [fix(0, "袖が浮らし", "袖ケ浦市")])
        self.assertEqual(segments[0]["text"], "一方内毛の袖ケ浦市")

    def test_place_from_the_models_own_knowledge_needs_a_close_match(self):
        segments = lines("熊本地震や千葉豪雨、台風25号などの災害の犠牲者に", "仙台市大白区の山中で")
        report = apply(segments, [fix(0, "千葉豪雨", "能登豪雨"), fix(1, "大白区", "太白区")])
        self.assertEqual(segments[0]["text"], "熊本地震や千葉豪雨、台風25号などの災害の犠牲者に")
        self.assertEqual(report.rejected[0]["reason"], "sound_mismatch")
        self.assertEqual(segments[1]["text"], "仙台市太白区の山中で")

    def test_numbers_do_not_change(self):
        segments = lines("熊本地震や千葉豪雨、台風25号などの災害の犠牲者に", "この三連携下ろそうかなとか思います")
        report = apply(segments, [fix(0, "台風25号", "台風15号"), fix(1, "三連携", "3連休")])
        self.assertEqual(segments[0]["text"], "熊本地震や千葉豪雨、台風25号などの災害の犠牲者に")
        self.assertEqual(report.rejected[0]["reason"], "number_changed")
        self.assertEqual(segments[1]["text"], "この3連休下ろそうかなとか思います")

    def test_meaning_flip_with_half_the_sound_is_rejected(self):
        segments = lines("一審は合憲と判断しました")
        report = apply(segments, [fix(0, "合憲", "違憲")])
        self.assertEqual(segments[0]["text"], "一審は合憲と判断しました")
        self.assertEqual(report.rejected[0]["reason"], "sound_mismatch")

    def test_parts_keep_their_reading_in_context(self):
        # 買 alone reads バイ; in 買ったり it is カッ, the same as 刈っ
        segments = lines("自分で買ったりとかしたいんですけども")
        apply(segments, [fix(0, "買ったり", "刈ったり")])
        self.assertEqual(segments[0]["text"], "自分で刈ったりとかしたいんですけども")

    def test_single_kanji_from_the_title_counts_as_reference(self):
        segments = lines("柳田大臣その上で", "きょうの柳田大臣")
        apply(segments, [fix(0, "柳田", "簗")], title="【簗農水相】｢減額求めていない｣")
        self.assertEqual(segments[0]["text"], "簗大臣その上で")
        # 柳田 is two characters, below the carry-over minimum: the other line stays
        self.assertEqual(segments[1]["text"], "きょうの柳田大臣")

    def test_neighbor_repeated_in_the_replacement_is_absorbed(self):
        segments = lines("シナドが食べ残したキノコを調べたところ")
        apply(segments, [fix(0, "シナド", "市などが")])
        self.assertEqual(segments[0]["text"], "市などが食べ残したキノコを調べたところ")

    def test_respelling_of_the_same_word_is_rejected(self):
        segments = lines("肛門癌などの予防効果", "痛い!")
        report = apply(segments, [fix(0, "肛門癌", "肛門がん"), fix(1, "痛い!", "痛い！")])
        self.assertEqual(segments[0]["text"], "肛門癌などの予防効果")
        self.assertEqual([item["reason"] for item in report.rejected], ["same_word", "same_word"])

    def test_different_kanji_under_one_lemma_is_a_fix(self):
        # unidic files 犯則 under 反則; they are different words that sound the same
        segments = lines("午前に反則調査権に基づく強制調査に入ったのは、")
        apply(segments, [fix(0, "反則調査権", "犯則調査権")])
        self.assertEqual(segments[0]["text"], "午前に犯則調査権に基づく強制調査に入ったのは、")

    def test_text_not_in_the_line_is_rejected(self):
        report = apply(lines("きょうはいい天気"), [fix(0, "厚生", "公正"), fix(5, "a", "b")])
        self.assertEqual([item["reason"] for item in report.rejected], ["not_in_line", "index_out_of_range"])

    def test_long_fix_is_carried_to_lines_the_model_missed(self):
        segments = lines("こちら公共ランでマナー違反", "ランナーが多い", "公共ランの実態調査", "公共の場所です")
        report = apply(segments, [fix(0, "公共ラン", "皇居ラン")])
        self.assertEqual(segments[2]["text"], "皇居ランの実態調査")
        self.assertEqual(segments[3]["text"], "公共の場所です")
        carried = [item for item in report.applied if item["status"] == "propagated"]
        self.assertEqual([(item["index"], item["from_index"]) for item in carried], [(2, 0)])

    def test_short_fix_is_not_carried(self):
        segments = lines("プルデンシャル声明に対し", "声明を発表しました")
        apply(segments, [fix(0, "声明", "生命")])
        self.assertEqual(segments[0]["text"], "プルデンシャル生命に対し")
        self.assertEqual(segments[1]["text"], "声明を発表しました")


class TestCorrect(unittest.TestCase):
    def test_whole_video_goes_into_one_request_with_the_reference(self):
        corrector = ScriptedCorrector([fix(1, "厚生取引委員", "公正取引委員")])
        segments = lines("きょう", "厚生取引委員会が")
        corrector.correct(segments, "ja", title="ビール大手に強制調査", description="#公正取引委員会")
        self.assertEqual(len(corrector.prompts_seen), 1)
        self.assertIn("<title>ビール大手に強制調査</title>", corrector.prompts_seen[0])
        self.assertIn("#公正取引委員会", corrector.prompts_seen[0])
        self.assertIn("[1] 厚生取引委員会が", corrector.prompts_seen[0])
        self.assertEqual(segments[1]["text"], "公正取引委員会が")

    def test_non_japanese_source_is_left_alone(self):
        corrector = ScriptedCorrector([fix(0, "their", "there")])
        segments = lines("their it is")
        self.assertIsNone(corrector.correct(segments, "en"))
        self.assertEqual(corrector.prompts_seen, [])
        self.assertEqual(segments[0]["text"], "their it is")

    def test_unparseable_model_output_raises_after_retries(self):
        class BrokenCorrector(AsrSourceCorrector):
            calls = 0

            def _call_gemini(self, api_key, prompt, attempt):
                BrokenCorrector.calls += 1
                return "not json"

            def _backoff(self, attempt, error):
                pass

        with self.assertRaises(ValueError):
            BrokenCorrector(model_name="fake-model", reader=READER).correct(lines("あ"), "ja")
        self.assertEqual(BrokenCorrector.calls, 4)


if __name__ == "__main__":
    unittest.main()
