import os
import uuid
from typing import Any, Dict, cast

import yt_dlp

from settings import get_settings
from utils.logger import get_logger
from utils.resilience import retry_on_ytdlp_errors

# Setup logger
logger = get_logger(__name__)

DEFAULT_DOWNLOAD_RETRIES = 3
DEFAULT_DOWNLOAD_SOCKET_TIMEOUT_SECONDS = 20


class VideoDownloader:
    def __init__(self, download_dir="temp"):
        self.download_dir = download_dir
        self.settings = get_settings()
        if not os.path.exists(download_dir):
            os.makedirs(download_dir)

    def download_audio(self, url: str) -> tuple[str, Dict[str, Any]]:
        session_id = str(uuid.uuid4())
        output_template = os.path.join(self.download_dir, f"{session_id}.%(ext)s")

        ydl_opts: Dict[str, Any] = {
            "format": "bestaudio/best",
            "outtmpl": output_template,
            "quiet": False,
            "no_warnings": False,
            "extractor_args": {"youtube": {"remote_components": ["ejs:github"]}},
        }

        try:
            # Check for proxy environment variable
            if self.settings.proxy:
                ydl_opts["proxy"] = self.settings.proxy

            # Only use cookies if the file exists
            if os.path.exists("cookies.txt"):
                ydl_opts["cookiefile"] = "cookies.txt"
                logger.info("Using cookies.txt for authentication")

            # Add user-agent to avoid being blocked
            ydl_opts["http_headers"] = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/91.0.4472.124 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-us,en;q=0.5",
            }
            ydl_opts["socket_timeout"] = DEFAULT_DOWNLOAD_SOCKET_TIMEOUT_SECONDS
            ydl_opts["retries"] = DEFAULT_DOWNLOAD_RETRIES
            ydl_opts["fragment_retries"] = DEFAULT_DOWNLOAD_RETRIES

            logger.info(f"Starting download from URL: {url}")
            return self._download_with_retry(url, ydl_opts, session_id)
        except Exception as e:
            logger.error(f"Download failed: {e}", exc_info=True)
            raise Exception(f"Download failed: {str(e)}")

    @retry_on_ytdlp_errors()
    def _download_with_retry(
        self,
        url: str,
        ydl_opts: Dict[str, Any],
        session_id: str,
    ) -> tuple[str, Dict[str, Any]]:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = cast(Dict[str, Any], ydl.extract_info(url, download=True))
            # info is a dict, but yt-dlp type stubs might be missing or incomplete
            ext = info.get("ext")  # type: ignore

            final_path = os.path.join(self.download_dir, f"{session_id}.{ext}")

            # Double check file existence
            if not os.path.exists(final_path):
                for file in os.listdir(self.download_dir):
                    if file.startswith(session_id):
                        final_path = os.path.join(self.download_dir, file)
                        break

            logger.info(f"Download completed: {final_path}")
            return final_path, info
