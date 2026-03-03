import datetime
import re
from pathlib import Path
from config.settings import DEFAULT_STYLE

class AdvancedSubtitleScriptGenerator:
    def __init__(self):
        pass

    def format_seconds_to_ass_timestamp(self, total_seconds: float) -> str:
        time_delta = datetime.timedelta(seconds=total_seconds)
        hours = int(time_delta.total_seconds()) // 3600
        minutes = (int(time_delta.total_seconds()) % 3600) // 60
        seconds = int(time_delta.total_seconds()) % 60
        centiseconds = int((total_seconds - int(total_seconds)) * 100)
        return f"{hours}:{minutes:02d}:{seconds:02d}.{centiseconds:02d}"

    def generate_ass_file(self, subtitle_segments, output_file_path, video_title="Bilingual Subtitles", 
                         is_furigana_enabled=False, style_settings=None, 
                         video_width=1920, video_height=1080):
        from utils.furigana_generator import JapaneseFuriganaGenerator
        furigana_annotator = JapaneseFuriganaGenerator() if is_furigana_enabled else None

        active_style = style_settings or DEFAULT_STYLE
        
        script_resolution_y = 1080
        script_resolution_x = int(script_resolution_y * (video_width / video_height))
        
        main_font_size = active_style.get('font_size_main', DEFAULT_STYLE['font_size_main'])
        main_vertical_margin = int((active_style.get('main_bottom', 12.0) / 100) * script_resolution_y)
        
        sub_font_size = active_style.get('font_size_sub', DEFAULT_STYLE['font_size_sub'])
        sub_vertical_margin = int((active_style.get('sub_bottom', 5.0) / 100) * script_resolution_y)
        
        furigana_vertical_margin = main_vertical_margin + main_font_size

        ass_header = self._build_ass_header(video_title, script_resolution_x, script_resolution_y, 
                                           main_font_size, main_vertical_margin, 
                                           sub_font_size, sub_vertical_margin, 
                                           furigana_vertical_margin, active_style)

        output_path = Path(output_file_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, "w", encoding="utf-8") as ass_file:
            ass_file.write(ass_header)
            for segment in subtitle_segments:
                self._write_segment_to_ass(ass_file, segment, is_furigana_enabled, furigana_annotator, main_font_size)

        return str(output_path)

    def _build_ass_header(self, title, res_x, res_y, main_fs, main_vm, sub_fs, sub_vm, furi_vm, style):
        main_weight = 1 if style.get('font_weight', 700) > 500 else 0
        main_alpha = format(int((1 - style.get('font_alpha', 100)/100) * 255), '02X')
        main_outline_alpha = format(int((1 - style.get('outline_alpha', 100)/100) * 255), '02X')
        
        sub_weight = 1 if style.get('font_weight_sub', 400) > 500 else 0
        sub_alpha = format(int((1 - style.get('sub_alpha', 100)/100) * 255), '02X')
        sub_outline_alpha = format(int((1 - style.get('outline_sub_alpha', 100)/100) * 255), '02X')

        return f"""[Script Info]
Title: {title}
Script Type: v4.00+
PlayResX: {res_x}
PlayResY: {res_y}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,Noto Sans CJK JP,{main_fs},&H{main_alpha}FFFFFF,&H000000FF,&H{main_outline_alpha}000000,&H90000000,{main_weight},0,0,0,100,100,0,0,1,{style.get('outline_main', 3.0)},{style.get('shadow_main', 1.5)},2,10,10,{main_vm},1
Style: Sub,Noto Sans CJK SC,{sub_fs},&H{sub_alpha}00FFFF,&H000000FF,&H{sub_outline_alpha}000000,&H90000000,{sub_weight},0,0,0,100,100,0,0,1,{style.get('outline_sub', 2.0)},{style.get('shadow_sub', 1.2)},2,10,10,{sub_vm},1
Style: Furigana,Noto Sans CJK JP,{main_fs},&H{main_alpha}FFFFFF,&H000000FF,&H{main_outline_alpha}000000,&H90000000,{main_weight},0,0,0,100,100,0,0,1,1.5,1,2,10,10,{furi_vm},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    def _write_segment_to_ass(self, ass_file, segment, enable_furigana, annotator, main_font_size):
        start_time = self.format_seconds_to_ass_timestamp(segment['start'])
        end_time = self.format_seconds_to_ass_timestamp(segment['end'])
        original_text = segment['text']
        translated_text = segment.get('translated_text', '')

        ass_file.write(f"Dialogue: 0,{start_time},{end_time},Main,,0,0,0,,{original_text}\n")
        if translated_text:
            ass_file.write(f"Dialogue: 1,{start_time},{end_time},Sub,,0,0,0,,{translated_text}\n")

        if enable_furigana and annotator:
            furigana_line = self._generate_furigana_line(original_text, annotator, main_font_size)
            if furigana_line.strip():
                ass_file.write(f"Dialogue: 0,{start_time},{end_time},Furigana,,0,0,0,,{furigana_line}\n")

    def _generate_furigana_line(self, text, annotator, main_font_size):
        # Only annotate if the text doesn't already contain ruby tags (for testing/flexibility)
        if "{#ruby#" not in text:
            annotated_text = annotator.annotate_text_with_furigana(text)
        else:
            annotated_text = text
        
        KANA_SCALE_PERCENT = 45
        KANA_SPACING_PIXELS = 1
        
        def calculate_visual_width(string):
            return sum(1 if ord(char) > 127 else 0.5 for char in string)

        furigana_elements = []
        parts = re.split(r'({#ruby#.*?\|.*?})', annotated_text)
        
        for part in parts:
            if not part: continue
            if part.startswith('{#ruby#'):
                match = re.match(r'{#ruby#(.*?)\|(.*?)}', part)
                if match:
                    kana, original = match.groups()
                    if not kana:
                        furigana_elements.append("　" * len(original))
                        continue
                        
                    original_width_in_pixels = calculate_visual_width(original) * main_font_size
                    base_kana_width = (calculate_visual_width(kana) * (KANA_SCALE_PERCENT / 100) * main_font_size) + (len(kana) - 1) * KANA_SPACING_PIXELS
                    
                    current_scale = KANA_SCALE_PERCENT
                    if base_kana_width > original_width_in_pixels:
                        current_scale = (original_width_in_pixels - (len(kana) - 1) * KANA_SPACING_PIXELS) / (calculate_visual_width(kana) * main_font_size) * 100
                        current_scale = max(25, current_scale)
                        base_kana_width = (calculate_visual_width(kana) * (current_scale / 100) * main_font_size) + (len(kana) - 1) * KANA_SPACING_PIXELS

                    horizontal_centering_margin = (original_width_in_pixels - base_kana_width) / 2
                    padding_tag = f"{{\\alpha&HFF&\\p1}}m 0 0 l {int(horizontal_centering_margin)} 0{{\\p0\\rFurigana}}" if horizontal_centering_margin > 0.5 else ""
                    
                    furigana_elements.append(f"{padding_tag}{{\\fscx{int(current_scale)}\\fscy{int(KANA_SCALE_PERCENT)}\\fsp{KANA_SPACING_PIXELS}}}{kana}{{\\fsp0\\fscx100\\fscy100}}{padding_tag}")
            else:
                for character in part:
                    furigana_elements.append("　" if ord(character) > 127 else " ")
        
        final_line = "".join(furigana_elements)
        return final_line.replace("{\\fscx100\\fscy100}{\\alpha&HFF&", "{\\alpha&HFF&")
