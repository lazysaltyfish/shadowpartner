#!/usr/bin/env python3
"""Test script to verify YouTube download functionality"""

import os
import sys
import tempfile
from pathlib import Path

# Add the backend directory to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.downloader import VideoDownloader


def test_download(tmp_path: Path):
    """Test downloading a short YouTube video."""
    # Use the first YouTube video ever uploaded (very short).
    test_url = "https://www.youtube.com/watch?v=jNQXAC9IVRw"
    downloader = VideoDownloader(download_dir=str(tmp_path))
    file_path = None

    try:
        file_path, info = downloader.download_audio(test_url)
        assert os.path.exists(file_path)
        assert info.get("title")
    finally:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_download(Path(tmp_dir))
    sys.exit(0)
