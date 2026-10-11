import subprocess
import json
from pathlib import Path


def subtitles_filter(subtitle_ass_path):
    """压制和视觉实验室的预览（services/subtitle_preview.py）用同一个滤镜，预览出来的才是成片的样子。"""
    return f"subtitles='{Path(subtitle_ass_path).absolute()}'"


class FFmpegVideoProcessor:
    def __init__(self):
        pass

    def extract_video_dimensions(self, video_file_path):
        ffprobe_command = [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "json", str(video_file_path)
        ]
        execution_result = subprocess.run(ffprobe_command, capture_output=True, text=True)
        probe_data = json.loads(execution_result.stdout)
        
        video_width = int(probe_data['streams'][0]['width'])
        video_height = int(probe_data['streams'][0]['height'])
        
        return video_width, video_height

    def extract_color_matrix(self, video_file_path):
        """播放器把这个视频（和用它压出来的成片，ffmpeg 会沿用色彩标记）转回 RGB 用的矩阵：bt709 / bt601 / bt2020。
        没标的按播放器的惯例，720p 及以上当 709。字幕颜色据此补偿（subtitle_generator.ass_color）。"""
        ffprobe_command = [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=height,color_space", "-of", "json", str(video_file_path)
        ]
        execution_result = subprocess.run(ffprobe_command, capture_output=True, text=True)
        stream = json.loads(execution_result.stdout)['streams'][0]
        color_space = stream.get('color_space', '')
        if color_space == 'bt709':
            return 'bt709'
        if color_space in ('bt470bg', 'smpte170m'):
            return 'bt601'
        if color_space.startswith('bt2020'):
            return 'bt2020'
        return 'bt709' if int(stream.get('height', 0)) >= 720 else 'bt601'

    def hardcode_subtitles_into_video(self, source_video_path, subtitle_ass_path, target_output_path):
        ffmpeg_conversion_command = [
            "ffmpeg",
            "-y",
            "-i", str(source_video_path),
            "-vf", subtitles_filter(subtitle_ass_path),
            "-c:a", "aac",
            str(target_output_path)
        ]
        
        print(f"🎬 Executing FFmpeg command: {' '.join(ffmpeg_conversion_command)}", flush=True)
        conversion_result = subprocess.run(ffmpeg_conversion_command, capture_output=True, text=True)
        
        if conversion_result.returncode != 0:
            print(f"❌ FFmpeg error output: {conversion_result.stderr}", flush=True)
            raise RuntimeError(f"Video processing failed with exit code {conversion_result.returncode}")
            
        return str(target_output_path)
