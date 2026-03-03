import sys
import os

# 将 backend 目录添加到 path 以便导入 utils
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from utils.furigana_generator import JapaneseFuriganaGenerator

def test_furigana_generation():
    annotator = JapaneseFuriganaGenerator()
    if not annotator.tagger:
        print("MeCab Tagger not initialized!")
        return

    test_scenarios = [
        ("日本語を勉強しています。", "{#ruby#にっぽん|日本}{#ruby#ご|語}を{#ruby#べんきょう|勉強}しています。"),
        ("美味しいお寿司を食べたい。", "{#ruby#おい|美味}しいお{#ruby#すし|寿司}を{#ruby#たべる|食べ}たい。"),
        ("昨日、学校に行きました。", "{#ruby#きのう|昨日}、{#ruby#がっこう|学校}に{#ruby#いく|行き}ました。"),
        ("東京大学", "{#ruby#とうきょう|東京}{#ruby#だいがく|大学}"),
    ]

    for input_text, expected_output in test_scenarios:
        actual_result = annotator.annotate_text_with_furigana(input_text)
        print(f"Input: {input_text}")
        print(f"Result: {actual_result}")
        if actual_result == expected_output:
            print("Status: PASS")
        else:
            print(f"Status: DIFF (Expected: {expected_output})")
        print("-" * 20)

if __name__ == "__main__":
    test_furigana_generation()
