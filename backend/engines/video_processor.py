import subprocess
import json
from pathlib import Path

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

    def hardcode_subtitles_into_video(self, source_video_path, subtitle_ass_path, target_output_path):
        absolute_subtitle_path = str(Path(subtitle_ass_path).absolute())
        
        ffmpeg_conversion_command = [
            "ffmpeg",
            "-y",
            "-i", str(source_video_path),
            "-vf", f"subtitles='{absolute_subtitle_path}'",
            "-c:a", "aac",
            str(target_output_path)
        ]
        
        print(f"🎬 Executing FFmpeg command: {' '.join(ffmpeg_conversion_command)}", flush=True)
        conversion_result = subprocess.run(ffmpeg_conversion_command, capture_output=True, text=True)
        
        if conversion_result.returncode != 0:
            print(f"❌ FFmpeg error output: {conversion_result.stderr}", flush=True)
            raise RuntimeError(f"Video processing failed with exit code {conversion_result.returncode}")
            
        return str(target_output_path)
