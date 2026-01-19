import hashlib
import os
import shutil
import subprocess

from utils.logger import get_logger

# Setup logger
logger = get_logger(__name__)


def generate_video_id_from_file(file_path: str) -> str:
    """
    为上传的视频生成唯一 ID（基于文件前 10MB 的 SHA256 哈希）

    Args:
        file_path: 视频文件路径

    Returns:
        格式为 'upload_<hash>' 的 video_id

    Example:
        >>> generate_video_id_from_file('/path/to/video.mp4')
        'upload_a1b2c3d4e5f6g7h8'
    """
    if not os.path.exists(file_path):
        logger.error(f"File not found: {file_path}")
        raise FileNotFoundError(f"File not found: {file_path}")

    hash_sha256 = hashlib.sha256()

    with open(file_path, "rb") as f:
        chunk = f.read(10 * 1024 * 1024)
        hash_sha256.update(chunk)

    hash_hex = hash_sha256.hexdigest()[:16]
    video_id = f"upload_{hash_hex}"

    logger.debug(f"Generated video_id: {video_id} for file: {file_path}")
    return video_id


def get_video_source(video_id: str) -> str:
    """
    根据 video_id 判断视频来源

    Args:
        video_id: 视频 ID

    Returns:
        'youtube' 或 'upload'

    Example:
        >>> get_video_source('upload_a1b2c3d4e5f6g7h8')
        'upload'
        >>> get_video_source('dQw4w9WgXcQ')
        'youtube'
    """
    if video_id.startswith("upload_"):
        return "upload"
    else:
        return "youtube"


def build_thumbnail_storage_path(video_id: str) -> str:
    return f"{video_id}_thumb.jpg"


def generate_thumbnail(source_path: str, output_path: str, timestamp: float = 1.0) -> None:
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path is None:
        raise RuntimeError("ffmpeg not found in PATH")

    capture_time = max(0.0, timestamp)
    command = [
        ffmpeg_path,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        str(capture_time),
        "-i",
        source_path,
        "-frames:v",
        "1",
        "-q:v",
        "2",
        "-vf",
        "scale=640:-1",
        "-an",
        output_path,
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        error_text = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"ffmpeg thumbnail generation failed: {error_text}")
