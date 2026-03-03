import MeCab
import jaconv

tagger = MeCab.Tagger()
text = "日本語を勉強しています。昨日、学校に行きました。"
node = tagger.parseToNode(text)
while node:
    if node.surface:
        print(f"Surface: {node.surface}")
        print(f"Feature: {node.feature}")
        features = node.feature.split(',')
        for i, f in enumerate(features):
            print(f"  [{i}]: {f}")
        print("-" * 10)
    node = node.next
