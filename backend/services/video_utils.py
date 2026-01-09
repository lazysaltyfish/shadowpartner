import hashlib
import os


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
        raise FileNotFoundError(f"File not found: {file_path}")

    hash_sha256 = hashlib.sha256()

    with open(file_path, "rb") as f:
        # 读取文件的前 10MB
        chunk = f.read(10 * 1024 * 1024)
        hash_sha256.update(chunk)

    # 使用前 16 个字符的哈希值
    hash_hex = hash_sha256.hexdigest()[:16]

    return f"upload_{hash_hex}"


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
    if video_id.startswith('upload_'):
        return 'upload'
    else:
        return 'youtube'
