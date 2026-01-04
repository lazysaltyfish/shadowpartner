import sys
import os
try:
    from main import app
    print("Successfully imported app")
    
    # Also check other critical imports
    import yt_dlp
    import whisper
    import MeCab
    print("All critical libraries imported successfully")
    
except Exception as e:
    print(f"Error: {e}")
    sys.exit(1)
