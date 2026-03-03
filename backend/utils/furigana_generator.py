import MeCab
import jaconv
import re

class JapaneseFuriganaGenerator:
    def __init__(self):
        try:
            self.tagger = MeCab.Tagger()
        except Exception:
            self.tagger = None

    def is_kanji_character(self, character):
        # Kanji range in Unicode: 4E00-9FAF
        # This explicitly excludes numbers and symbols
        return '\u4e00' <= character <= '\u9faf'

    def contains_kanji(self, text):
        return any(self.is_kanji_character(char) for char in text)

    def annotate_text_with_furigana(self, text):
        if not self.tagger or not text:
            return text

        lines = text.splitlines()
        annotated_lines = [self._process_single_line(line) for line in lines]
        return "\n".join(annotated_lines)

    def _process_single_line(self, line):
        if not line.strip():
            return line
            
        node = self.tagger.parseToNode(line)
        annotated_line = ""
        current_pos = 0
        
        while node:
            if node.surface:
                start_index = line.find(node.surface, current_pos)
                if start_index != -1:
                    annotated_line += line[current_pos:start_index]
                    annotated_line += self._process_token(node.surface, node.feature)
                    current_pos = start_index + len(node.surface)
                else:
                    annotated_line += self._process_token(node.surface, node.feature)
            node = node.next
            
        return annotated_line + line[current_pos:]

    def _process_token(self, surface, feature):
        if not self.contains_kanji(surface):
            return surface

        features = feature.split(',')
        reading_in_hiragana = self._extract_reading_as_hiragana(surface, features)
        
        if not reading_in_hiragana or reading_in_hiragana == surface:
            return surface

        return self._format_with_ruby_tags_stripping_okurigana(surface, reading_in_hiragana)

    def _extract_reading_as_hiragana(self, surface, features):
        if len(features) <= 8:
            return ""

        root_canonical_reading = features[6]
        original_lexical_form = features[7]
        current_inflected_reading = features[8]

        if self.contains_kanji(original_lexical_form) and not self.contains_kanji(current_inflected_reading):
            return jaconv.kata2hira(current_inflected_reading)
        
        return jaconv.kata2hira(root_canonical_reading)

    def _format_with_ruby_tags_stripping_okurigana(self, surface, kana):
        okurigana_length = 0
        while (okurigana_length < len(surface) and 
               okurigana_length < len(kana) and 
               surface[-(okurigana_length+1)] == kana[-(okurigana_length+1)] and 
               not self.is_kanji_character(surface[-(okurigana_length+1)])):
            okurigana_length += 1
        
        if okurigana_length > 0:
            kanji_part = surface[:-okurigana_length]
            reading_part = kana[:-okurigana_length]
            suffix_part = surface[-okurigana_length:]
            
            if self.contains_kanji(kanji_part):
                return f"{{#ruby#{reading_part}|{kanji_part}}}{suffix_part}"
            return surface
            
        return f"{{#ruby#{kana}|{surface}}}"
