import yt_dlp
import os
import uuid
import shutil

# Helper to ensure ffmpeg is in path if we installed it locally
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCAL_BIN = os.path.join(BASE_DIR, "bin") 
if os.path.exists(LOCAL_BIN):
    os.environ["PATH"] += os.pathsep + LOCAL_BIN

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
        print(f"DEBUG: FFmpeg available: {has_ffmpeg}")
        
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': output_template,
            'quiet': True,
            'no_warnings': True,
        }
        
        if has_ffmpeg:
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                # If we converted, extension is mp3. If not, it's whatever source was (m4a, webm)
                ext = info['ext']
                if has_ffmpeg:
                    ext = 'mp3'
                
                final_path = os.path.join(self.download_dir, f"{session_id}.{ext}")
                
                # Double check file existence
                if not os.path.exists(final_path):
                    # Sometimes yt-dlp doesn't return the exact final extension in info['ext'] after post-processing
                    # We might need to look for it
                    for file in os.listdir(self.download_dir):
                        if file.startswith(session_id):
                            final_path = os.path.join(self.download_dir, file)
                            break

                return final_path, info
        except Exception as e:
            raise Exception(f"Download failed: {str(e)}")
