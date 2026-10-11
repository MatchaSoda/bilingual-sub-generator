import os
import re
import argparse
import time
import json
import shutil
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))

from engines.media_downloader import YouTubeMediaDownloader
from engines.transcription_engine import AudioTranscriptionEngine
from engines.subtitle_translator import GeminiSubtitleTranslator
from engines.source_corrector import AsrSourceCorrector, CORRECTION_MODEL
from engines.subtitle_generator import AdvancedSubtitleScriptGenerator
from engines.video_processor import FFmpegVideoProcessor
from engines.segment_optimizer import SubtitleSegmentOptimizer
from engines.llm_segmenter import LLMSubtitleSegmenter
from config.settings import DOWNLOADS_DIR
from utils.filenames import truncate_utf8
from utils import subtitle_fonts
from utils.automation_store import STYLE_DEFAULTS, normalize_color

def sanitize_for_filename(name):
    return re.sub(r'[\\/*?:"<>|]', "_", name).strip()

def subtitle_color(value):
    color = normalize_color(value)
    if not color:
        raise argparse.ArgumentTypeError(f"expected a #RRGGBB color, got {value!r}")
    return color

def check_subtitle_fonts(families):
    """A font fontconfig doesn't know is silently replaced by another one, and the video no longer
    matches the preview in 视觉实验室. Fail before downloading anything instead."""
    for family in families:
        installed = subtitle_fonts.is_installed(family)
        if "," in family or installed is False:
            print(f"❌ Subtitle font is not installed: {family!r} (fc-list doesn't know it)", flush=True)
            sys.exit(2)
        if installed is None:
            print(f"⚠️ fontconfig not found, cannot check that the subtitle font {family!r} is installed", flush=True)

def proofread_source_text(subtitle_segments, source_language, media_info, video_title, model_name):
    """--fix-source-text: fix mis-heard words before translating. Never fails the video;
    if Gemini is unreachable the recognized text is translated as it is."""
    try:
        report = AsrSourceCorrector(model_name=model_name).correct(
            subtitle_segments, source_language,
            title=media_info['original_title'], description=media_info.get('description', '')
        )
    except Exception as correction_error:
        print(f"⚠️ ASR correction failed, translating the recognized text as is: {correction_error}", flush=True)
        return
    if report is None:
        return
    # Every applied and rejected fix, for checking what the pass changed (RUNBOOK §5.12)
    try:
        with open(DOWNLOADS_DIR / f"{video_title}.corrections.json", 'w', encoding='utf-8') as report_file:
            json.dump(report.to_json(), report_file, ensure_ascii=False, indent=2)
    except OSError as write_error:
        print(f"⚠️ Could not save the correction report: {write_error}", flush=True)

def build_argument_parser():
    argument_parser = argparse.ArgumentParser(description="YouTube Bilingual Subtitle Generator")
    argument_parser.add_argument("video_url", help="YouTube video URL")
    argument_parser.add_argument("--target-language", default="zh-CN", help="Target language code")
    argument_parser.add_argument("--whisper-model", default="large-v3-turbo", help="Whisper model size")
    argument_parser.add_argument("--gemini-model", default="gemini-3.1-flash-lite", help="Gemini model identifier")
    argument_parser.add_argument("--enable-furigana", action="store_true", help="Enable Japanese furigana")
    argument_parser.add_argument("--fix-source-text", action="store_true", help="Before translating, fix mis-heard words in the Japanese ASR text (separate Gemini pass, checked against readings and the video's title / description)")
    argument_parser.add_argument("--correction-model", default=CORRECTION_MODEL, help="Gemini model for --fix-source-text (RUNBOOK §5.12 compares models on a replay)")
    argument_parser.add_argument("--translate-title", action="store_true", help="Translate the video title into the target language and use it for the default output filename")
    argument_parser.add_argument("--segment-mode", choices=["rule", "llm"], default="rule", help="Subtitle segmentation: 'rule' (offline, MeCab + punctuation + pause) or 'llm' (Gemini semantic)")
    argument_parser.add_argument("--translation-batch-size", type=int, default=100, help="How many subtitle segments to translate per Gemini call. Larger = better cross-line context. Output tokens are rarely the limit (model allows 64k); the real ceilings are the request timeout and the model occasionally dropping a line in very large batches.")
    argument_parser.add_argument("--output", "-o", help="Custom output video path (including filename and extension)")
    
    argument_parser.add_argument("--font-size-main", type=int, default=90)
    argument_parser.add_argument("--main-bottom", type=float, default=0.7)
    argument_parser.add_argument("--font-alpha", type=int, default=100)
    argument_parser.add_argument("--outline-alpha", type=int, default=100)
    argument_parser.add_argument("--font-weight", type=int, default=700)
    argument_parser.add_argument("--outline-main", type=float, default=3.0)
    argument_parser.add_argument("--shadow-main", type=float, default=1.5)
    
    argument_parser.add_argument("--font-size-sub", type=int, default=75)
    argument_parser.add_argument("--sub-bottom", type=float, default=92.1)
    argument_parser.add_argument("--sub-alpha", type=int, default=100)
    argument_parser.add_argument("--outline-sub-alpha", type=int, default=100)
    argument_parser.add_argument("--font-weight-sub", type=int, default=400)
    argument_parser.add_argument("--outline-sub", type=float, default=2.0)
    argument_parser.add_argument("--shadow-sub", type=float, default=1.5)

    # Fonts and colors from 视觉实验室. The main line is the Japanese original (furigana uses its font and colors),
    # the sub line is the Chinese translation. Defaults equal automation_store.STYLE_DEFAULTS (a test checks).
    argument_parser.add_argument("--font-main", default=STYLE_DEFAULTS["font_main"], help="Font family of the original line and its furigana")
    argument_parser.add_argument("--font-sub", default=STYLE_DEFAULTS["font_sub"], help="Font family of the translated line")
    argument_parser.add_argument("--color-main", type=subtitle_color, default=STYLE_DEFAULTS["color_main"])
    argument_parser.add_argument("--outline-color-main", type=subtitle_color, default=STYLE_DEFAULTS["outline_color_main"])
    argument_parser.add_argument("--color-sub", type=subtitle_color, default=STYLE_DEFAULTS["color_sub"])
    argument_parser.add_argument("--outline-color-sub", type=subtitle_color, default=STYLE_DEFAULTS["outline_color_sub"])
    return argument_parser

def run_subtitle_generation_pipeline():
    pipeline_arguments = build_argument_parser().parse_args()
    check_subtitle_fonts([pipeline_arguments.font_main, pipeline_arguments.font_sub])

    print(f"🚀 Starting process for: {pipeline_arguments.video_url}", flush=True)

    downloader = YouTubeMediaDownloader(target_directory=DOWNLOADS_DIR)
    downloaded_media_info = downloader.download_video_and_audio(pipeline_arguments.video_url)
    video_title = downloaded_media_info['title']
    print(f"✅ Downloaded: {video_title}", flush=True)

    transcription_cache_file = DOWNLOADS_DIR / f"{video_title}.asr.json"
    transcription_engine = AudioTranscriptionEngine(model_size=pipeline_arguments.whisper_model)
    transcription_results = transcription_engine.transcribe_audio_file(
        downloaded_media_info['audio_path'], 
        cached_results_path=str(transcription_cache_file)
    )
    detected_source_language = transcription_results['language']
    print(f"✅ Transcription complete. Detected language: {detected_source_language}", flush=True)

    if pipeline_arguments.segment_mode == "llm":
        subtitle_segmenter = LLMSubtitleSegmenter(maximum_characters_per_line=25)
        print(f"✂️ Segmentation mode: LLM (semantic, {subtitle_segmenter.model_name})", flush=True)
    else:
        print("✂️ Segmentation mode: rule (offline)", flush=True)
        subtitle_segmenter = SubtitleSegmentOptimizer(maximum_characters_per_line=25)
    refined_subtitle_segments = subtitle_segmenter.segment(
        transcription_results['segments'], source_language=detected_source_language
    )

    translation_cache_file = DOWNLOADS_DIR / f"{video_title}.translated.json"
    if translation_cache_file.exists():
        print(f"📦 Loading cached translations from: {translation_cache_file}", flush=True)
        with open(translation_cache_file, 'r', encoding='utf-8') as cache_file:
            final_subtitle_segments = json.load(cache_file)
    else:
        translator = GeminiSubtitleTranslator(
            target_language_code=pipeline_arguments.target_language, 
            ai_model_identifier=pipeline_arguments.gemini_model
        )
        final_subtitle_segments = refined_subtitle_segments
        if pipeline_arguments.fix_source_text:
            proofread_source_text(final_subtitle_segments, detected_source_language, downloaded_media_info, video_title,
                                  pipeline_arguments.correction_model)
        processing_batch_size = max(1, pipeline_arguments.translation_batch_size)
        for batch_start_index in range(0, len(final_subtitle_segments), processing_batch_size):
            current_batch = final_subtitle_segments[batch_start_index:batch_start_index + processing_batch_size]
            translator.translate_batch_of_subtitle_segments(current_batch, source_language=detected_source_language)
            processed_count = min(batch_start_index + processing_batch_size, len(final_subtitle_segments))
            print(f"Progress: {processed_count}/{len(final_subtitle_segments)}", flush=True)
        
        with open(translation_cache_file, 'w', encoding='utf-8') as cache_file:
            json.dump(final_subtitle_segments, cache_file, ensure_ascii=False, indent=2)

    script_generator = AdvancedSubtitleScriptGenerator()
    video_processor = FFmpegVideoProcessor()
    video_width, video_height = video_processor.extract_video_dimensions(downloaded_media_info['video_path'])

    generated_ass_path = DOWNLOADS_DIR / f"{video_title}.ass"
    script_generator.generate_ass_file(
        final_subtitle_segments, 
        str(generated_ass_path), 
        video_title=video_title, 
        is_furigana_enabled=pipeline_arguments.enable_furigana,
        style_settings=vars(pipeline_arguments),
        video_width=video_width,
        video_height=video_height
    )

    output_filename_base = video_title
    if pipeline_arguments.translate_title:
        try:
            title_translator = GeminiSubtitleTranslator(
                target_language_code=pipeline_arguments.target_language,
                ai_model_identifier=pipeline_arguments.gemini_model
            )
            translated_title = title_translator.translate_title(
                downloaded_media_info['original_title'], detected_source_language
            )
        except Exception as title_translation_error:
            print(f"⚠️ Title translation failed, keeping original: {title_translation_error}", flush=True)
            translated_title = downloaded_media_info['original_title']

        if not translated_title:
            translated_title = downloaded_media_info['original_title']
        # Emit a parseable line so downstream consumers (web UI, automation) can reuse the translated title.
        print(f"🌐 Translated title: {translated_title}", flush=True)
        output_filename_base = truncate_utf8(sanitize_for_filename(translated_title)) or video_title

    if pipeline_arguments.output:
        final_video_output_path = Path(pipeline_arguments.output)
        final_video_output_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        final_video_output_path = DOWNLOADS_DIR / f"{output_filename_base}_bilingual.mp4"

    video_processor.hardcode_subtitles_into_video(
        downloaded_media_info['video_path'], 
        str(generated_ass_path), 
        str(final_video_output_path)
    )

    # Handle YouTube thumbnail if exists
    original_thumbnail = DOWNLOADS_DIR / f"{video_title}.jpg"
    final_thumbnail = final_video_output_path.with_suffix(".jpg")
    if original_thumbnail.exists() and not final_thumbnail.exists():
        # shutil.move 而不是 rename：Docker 里 data/ 和 userdata/ 是两个挂载点，跨挂载点 rename 报 EXDEV（RUNBOOK §5.10）
        shutil.move(str(original_thumbnail), str(final_thumbnail))
        print(f"✅ Thumbnail synchronized: {final_thumbnail}", flush=True)

    print(f"🎉 All done! Final video: {final_video_output_path}", flush=True)

if __name__ == "__main__":
    run_subtitle_generation_pipeline()
