#!/usr/bin/env python3
"""Test script to verify YouTube download functionality"""

import sys
import os

# Add the backend directory to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.downloader import VideoDownloader

def test_download():
    """Test downloading a short YouTube video"""
    # Use the first YouTube video ever uploaded (very short)
    test_url = "https://www.youtube.com/watch?v=jNQXAC9IVRw"

    print("Testing YouTube download functionality...")
    print(f"URL: {test_url}")
    print("-" * 50)

    try:
        downloader = VideoDownloader(download_dir="temp")
        print("Downloading...")
        file_path, info = downloader.download_audio(test_url)

        print("\n✓ Download successful!")
        print(f"File: {file_path}")
        print(f"Title: {info.get('title', 'Unknown')}")
        print(f"Duration: {info.get('duration', 'Unknown')} seconds")
        print(f"File exists: {os.path.exists(file_path)}")

        # Cleanup
        if os.path.exists(file_path):
            os.remove(file_path)
            print("\n✓ Cleanup completed")

    except Exception as e:
        print(f"\n✗ Download failed: {e}")
        return False

    return True

if __name__ == "__main__":
    success = test_download()
    sys.exit(0 if success else 1)
