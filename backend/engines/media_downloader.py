import yt_dlp
from pathlib import Path
from config.settings import DOWNLOADS_DIR, HTTP_PROXY, HTTPS_PROXY, YT_DLP_COOKIES

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
            'extractor_args': {'youtube': {'player_client': ['default', 'mweb', 'tv']}},
        }

        if YT_DLP_COOKIES:
            ytdlp_configuration['cookiefile'] = YT_DLP_COOKIES
            print(f"🍪 Using cookies: {YT_DLP_COOKIES}", flush=True)

        with yt_dlp.YoutubeDL(ytdlp_configuration) as ytdlp_instance:
            extracted_metadata = ytdlp_instance.extract_info(video_url, download=True)
            
            # 使用 prepare_filename 获取 yt-dlp 实际保存（经过净化）的文件路径
            video_file_path = Path(ytdlp_instance.prepare_filename(extracted_metadata))
            
            # 获取净化后的标题（不含扩展名），确保后续生成的缓存文件名也是合法的
            video_title = video_file_path.stem
            
            # 音频文件路径根据视频路径生成（后缀改为 .wav）
            audio_file_path = video_file_path.with_suffix('.wav')
            
            return {
                "title": video_title,
                "video_path": str(video_file_path),
                "audio_path": str(audio_file_path)
            }
