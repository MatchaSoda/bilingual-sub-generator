import yt_dlp
from pathlib import Path
from config.settings import DOWNLOADS_DIR, HTTP_PROXY, HTTPS_PROXY

class YouTubeMediaDownloader:
    def __init__(self, target_directory=None):
        self.download_path = Path(target_directory) if target_directory else DOWNLOADS_DIR
        self.download_path.mkdir(parents=True, exist_ok=True)

    def download_video_and_audio(self, video_url):
        ytdlp_configuration = {
            'format': 'bestvideo+bestaudio/best',
            'outtmpl': str(self.download_path / '%(title)s.%(ext)s'),
            'proxy': HTTP_PROXY,
            'writethumbnail': True,
            'postprocessors': [
                {
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'wav',
                    'preferredquality': '192',
                },
                {
                    'key': 'FFmpegThumbnailsConvertor',
                    'format': 'jpg',
                }
            ],
            'keepvideo': True,
            'socket_timeout': 30,
            'retries': 10,
            'nocheckcertificate': True,
        }

        with yt_dlp.YoutubeDL(ytdlp_configuration) as ytdlp_instance:
            extracted_metadata = ytdlp_instance.extract_info(video_url, download=True)
            
            video_title = extracted_metadata['title']
            original_extension = extracted_metadata['ext']
            
            video_file_full_path = self.download_path / f"{video_title}.{original_extension}"
            audio_file_full_path = video_file_full_path.with_suffix('.wav')
            
            return {
                "title": video_title,
                "video_path": str(video_file_full_path),
                "audio_path": str(audio_file_full_path)
            }
