class SubtitleSegmentOptimizer:
    def __init__(self, maximum_characters_per_line=30):
        self.character_limit = maximum_characters_per_line

    def split_long_segments_using_word_timestamps(self, original_subtitle_segments):
        optimized_segments = []
        
        for segment in original_subtitle_segments:
            if self._is_segment_within_limit_or_lacks_word_data(segment):
                optimized_segments.append(segment)
                continue
            
            optimized_segments.extend(self._split_segment_by_word_limit(segment))
                
        return optimized_segments

    def _is_segment_within_limit_or_lacks_word_data(self, segment):
        has_word_data = "words" in segment and segment["words"]
        is_short_enough = len(segment["text"]) <= self.character_limit
        return not has_word_data or is_short_enough

    def _split_segment_by_word_limit(self, segment):
        split_results = []
        accumulated_text = ""
        segment_start_time = segment["words"][0]["start"]
        
        for index, word_info in enumerate(segment["words"]):
            word_text = word_info["word"]
            
            if len(accumulated_text + word_text) > self.character_limit and accumulated_text:
                previous_word_info = segment["words"][index - 1]
                split_results.append({
                    "start": segment_start_time,
                    "end": previous_word_info["end"],
                    "text": accumulated_text.strip()
                })
                accumulated_text = word_text
                segment_start_time = word_info["start"]
            else:
                accumulated_text += word_text
        
        if accumulated_text:
            last_word_info = segment["words"][-1]
            split_results.append({
                "start": segment_start_time,
                "end": last_word_info["end"],
                "text": accumulated_text.strip()
            })
            
        return split_results
