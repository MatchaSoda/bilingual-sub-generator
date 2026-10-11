import datetime
import re
from pathlib import Path
from config.settings import DEFAULT_STYLE
from utils.automation_store import STYLE_COLOR_FIELDS, normalize_color
from utils.subtitle_fonts import DEFAULT_FONTS, size_scale


# 播放器把成片转回 RGB 用的 YUV 矩阵 → (Kr, Kb)。ffmpeg 5.1 的 subtitles 滤镜不看视频标的矩阵，一律按 BT.601
# 把字幕颜色换成 YUV；YouTube 的高清源和成片都标 BT.709，播放器按 709 解，#FFFF00 就显示成 (255, 240, 0)。
YUV_MATRICES = {"bt601": (0.299, 0.114), "bt709": (0.2126, 0.0722), "bt2020": (0.2627, 0.0593)}


def _rgb_to_yuv(rgb, matrix):
    kr, kb = YUV_MATRICES[matrix]
    r, g, b = (channel / 255 for channel in rgb)
    y = kr * r + (1 - kr - kb) * g + kb * b
    return y, (b - y) / (2 * (1 - kb)), (r - y) / (2 * (1 - kr))


def _yuv_to_rgb(yuv, matrix):
    kr, kb = YUV_MATRICES[matrix]
    y, u, v = yuv
    r = y + 2 * (1 - kr) * v
    b = y + 2 * (1 - kb) * u
    g = (y - kr * r - kb * b) / (1 - kr - kb)
    return tuple(max(0, min(255, round(channel * 255))) for channel in (r, g, b))


def ass_color(rgb, alpha_hex, video_matrix=None):
    """'#RRGGBB' + 透明度 'AA' → ASS 的 &HAABBGGRR。

    video_matrix 是播放器解码成片用的矩阵。不是 BT.601 时先反算一遍，让 ffmpeg 按 601 换出来的 YUV 正好是想要的颜色在
    这个矩阵下的 YUV。纯黄、纯红这种超出范围的颜色只能补一部分。"""
    color = normalize_color(rgb)
    if not color:
        raise ValueError(f"Subtitle color must be #RRGGBB, got {rgb!r}")
    channels = tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
    if video_matrix in YUV_MATRICES and video_matrix != "bt601":
        channels = _yuv_to_rgb(_rgb_to_yuv(channels, video_matrix), "bt601")
    red, green, blue = channels
    return f"&H{alpha_hex}{blue:02X}{green:02X}{red:02X}"


def ass_font_size(size, family):
    """界面上的字号是字面大小，换成 libass 的字号（见 utils/subtitle_fonts.REFERENCE_WIN_RATIO）。思源黑体原样返回。"""
    scaled = size * size_scale(family)
    return int(scaled) if scaled == int(scaled) else round(scaled, 2)


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
                         video_width=1920, video_height=1080, furigana_annotator=None, video_matrix=None):
        from utils.furigana_generator import JapaneseFuriganaGenerator
        if not is_furigana_enabled:
            furigana_annotator = None
        elif furigana_annotator is None:
            furigana_annotator = JapaneseFuriganaGenerator()

        active_style = style_settings or DEFAULT_STYLE

        script_resolution_y = 1080
        script_resolution_x = int(script_resolution_y * (video_width / video_height))

        main_font_size = ass_font_size(active_style.get('font_size_main', DEFAULT_STYLE['font_size_main']),
                                       active_style.get('font_main') or DEFAULT_FONTS['ja'])
        main_vertical_margin = int((active_style.get('main_bottom', 12.0) / 100) * script_resolution_y)

        sub_font_size = ass_font_size(active_style.get('font_size_sub', DEFAULT_STYLE['font_size_sub']),
                                      active_style.get('font_sub') or DEFAULT_FONTS['zh'])
        sub_vertical_margin = int((active_style.get('sub_bottom', 5.0) / 100) * script_resolution_y)

        furigana_vertical_margin = main_vertical_margin + int(round(main_font_size))

        ass_header = self._build_ass_header(video_title, script_resolution_x, script_resolution_y,
                                           main_font_size, main_vertical_margin,
                                           sub_font_size, sub_vertical_margin,
                                           furigana_vertical_margin, active_style, video_matrix)

        output_path = Path(output_file_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, "w", encoding="utf-8") as ass_file:
            ass_file.write(ass_header)
            for segment in subtitle_segments:
                self._write_segment_to_ass(ass_file, segment, is_furigana_enabled, furigana_annotator, main_font_size)

        return str(output_path)

    def _build_ass_header(self, title, res_x, res_y, main_fs, main_vm, sub_fs, sub_vm, furi_vm, style, video_matrix=None):
        main_weight = 1 if style.get('font_weight', 700) > 500 else 0
        main_alpha = format(int((1 - style.get('font_alpha', 100)/100) * 255), '02X')
        main_outline_alpha = format(int((1 - style.get('outline_alpha', 100)/100) * 255), '02X')
        
        sub_weight = 1 if style.get('font_weight_sub', 400) > 500 else 0
        sub_alpha = format(int((1 - style.get('sub_alpha', 100)/100) * 255), '02X')
        sub_outline_alpha = format(int((1 - style.get('outline_sub_alpha', 100)/100) * 255), '02X')

        # 振假名跟着日文原文的字体和颜色
        main_font = style.get('font_main') or DEFAULT_FONTS['ja']
        sub_font = style.get('font_sub') or DEFAULT_FONTS['zh']
        colors = {key: style.get(key) or default for key, default in STYLE_COLOR_FIELDS.items()}
        main_primary = ass_color(colors['color_main'], main_alpha, video_matrix)
        main_outline = ass_color(colors['outline_color_main'], main_outline_alpha, video_matrix)
        sub_primary = ass_color(colors['color_sub'], sub_alpha, video_matrix)
        sub_outline = ass_color(colors['outline_color_sub'], sub_outline_alpha, video_matrix)

        return f"""[Script Info]
Title: {title}
Script Type: v4.00+
PlayResX: {res_x}
PlayResY: {res_y}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,{main_font},{main_fs},{main_primary},&H000000FF,{main_outline},&H90000000,{main_weight},0,0,0,100,100,0,0,1,{style.get('outline_main', 3.0)},{style.get('shadow_main', 1.5)},2,10,10,{main_vm},1
Style: Sub,{sub_font},{sub_fs},{sub_primary},&H000000FF,{sub_outline},&H90000000,{sub_weight},0,0,0,100,100,0,0,1,{style.get('outline_sub', 2.0)},{style.get('shadow_sub', 1.2)},2,10,10,{sub_vm},1
Style: Furigana,{main_font},{main_fs},{main_primary},&H000000FF,{main_outline},&H90000000,{main_weight},0,0,0,100,100,0,0,1,1.5,1,2,10,10,{furi_vm},1

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
