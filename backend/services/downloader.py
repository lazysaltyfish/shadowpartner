import os
import shutil
import uuid

import yt_dlp

from utils.logger import get_logger
from utils.path_setup import setup_local_bin_path

# Setup logger
logger = get_logger(__name__)

# Setup local bin path
setup_local_bin_path()

class VideoDownloader:
    def __init__(self, download_dir="temp"):
        self.download_dir = download_dir
        if not os.path.exists(download_dir):
            os.makedirs(download_dir)

    def download_audio(self, url: str) -> tuple[str, dict]:
        session_id = str(uuid.uuid4())
        output_template = os.path.join(self.download_dir, f"{session_id}.%(ext)s")

        # Check if we have ffmpeg
        has_ffmpeg = shutil.which("ffmpeg") is not None
        logger.info(f"FFmpeg available: {has_ffmpeg}")
        
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': output_template,
            'quiet': False,
            'no_warnings': False,
        }
        
        if has_ffmpeg:
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
        
        try:
            # Check for proxy environment variable
            proxy = os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY")
            if proxy:
                ydl_opts['proxy'] = proxy

            # Only use cookies if the file exists
            if os.path.exists('cookies.txt'):
                ydl_opts['cookiefile'] = 'cookies.txt'
                logger.info("Using cookies.txt for authentication")

            # Add user-agent to avoid being blocked
            ydl_opts['http_headers'] = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-us,en;q=0.5',
            }

            logger.info(f"Starting download from URL: {url}")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                ext = info['ext']
                if has_ffmpeg:
                    ext = 'mp3'

                final_path = os.path.join(self.download_dir, f"{session_id}.{ext}")

                # Double check file existence
                if not os.path.exists(final_path):
                    for file in os.listdir(self.download_dir):
                        if file.startswith(session_id):
                            final_path = os.path.join(self.download_dir, file)
                            break

                logger.info(f"Download completed: {final_path}")
                return final_path, info
        except Exception as e:
            logger.error(f"Download failed: {e}", exc_info=True)
            raise Exception(f"Download failed: {str(e)}")
